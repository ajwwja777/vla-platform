#!/usr/bin/env python3
"""Local XR-0 policy server with preprocessing moved off the ROS Python 3.8 client."""

from __future__ import annotations

import argparse
import pickle
import socket
import struct
import time
import traceback
from os.path import join as osp

import numpy as np
from PIL import Image
import torch
from mmengine import Config
from transformers import AutoProcessor

from mibot.models import MIMODEL
from mibot.server.deploy import strip_prefix
from mibot.utils.io import (
    ACTION_EPS,
    build_action_mask,
    compose_state,
    denormalize_action,
    resize_image,
    validate_stats,
)
from mibot.utils.paths import qwen3_vl_path
from mibot.utils.prefix import pad_action_prefix


def _recv_all(conn, length: int):
    data = b""
    while len(data) < length:
        packet = conn.recv(length - len(data))
        if not packet:
            return None
        data += packet
    return data


def _recv(conn):
    head = _recv_all(conn, 4)
    if not head:
        return None
    body = _recv_all(conn, struct.unpack(">I", head)[0])
    return None if body is None else pickle.loads(body)


def _send(conn, value) -> None:
    payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    conn.sendall(struct.pack(">I", len(payload)) + payload)


def _messages(instruction, ego, left, right):
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "The following observations are captured from multiple views.\n# Ego View\n"},
                {"type": "image", "image": ego},
                {"type": "text", "text": "\n# Left-Wrist View\n"},
                {"type": "image", "image": left},
                {"type": "text", "text": "\n# Right-Wrist View\n"},
                {"type": "image", "image": right},
                {"type": "text", "text": f"\nGenerate robot actions for the task:\n{instruction}"},
            ],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "<bot></bot>"}]},
    ]


class CobotPolicy:
    def __init__(self, model_dir: str, device: str = "cuda:0") -> None:
        self.device = device
        config = Config.fromfile(osp(model_dir, "config.py"))
        self.model = MIMODEL.build(config.model.params.model).to(torch.bfloat16)
        checkpoint = torch.load(
            osp(model_dir, "last.ckpt/checkpoint", "mp_rank_00_model_states.pt"),
            map_location="cpu",
        )["module"]
        result = self.model.load_state_dict(strip_prefix(checkpoint, "model."), assign=True)
        print(f"XR0_CHECKPOINT_LOADED {result}", flush=True)
        self.model = self.model.eval().to(device)

        data = config.data.params.train_datasets
        action_length = int(data.get("action_length", 30))
        mean, std = validate_stats(data.mean, data.std, action_length)
        self.mean = torch.tensor(mean, device=device)
        self.std = torch.tensor(std, device=device)
        self.action_mask = torch.from_numpy(build_action_mask(action_length)).to(device)
        self.processor = AutoProcessor.from_pretrained(qwen3_vl_path())
        self.processor.tokenizer.padding_side = "right"

    @staticmethod
    def _image(value) -> Image.Image:
        image = Image.fromarray(np.asarray(value, dtype=np.uint8), mode="RGB")
        return resize_image(image, factor=32, max_pixels=90000)

    def preprocess(self, request: dict) -> dict:
        state = np.asarray(request["state"], dtype=np.float32)
        images = request["images"]
        messages = _messages(
            request["instruction"],
            self._image(images["ego"]),
            self._image(images["left_wrist"]),
            self._image(images["right_wrist"]),
        )
        batch = self.processor.apply_chat_template(
            [[*messages]],
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            padding=True,
            images_kwargs={"do_resize": False},
        )
        batch["state"] = torch.from_numpy(
            compose_state(
                left_gripper=state[6:7],
                left_joint=state[:6],
                right_gripper=state[13:14],
                right_joint=state[7:13],
            )
        )[None]
        if "action_prefix" in request:
            prefix, length = pad_action_prefix(request["action_prefix"])
            batch["action"] = torch.from_numpy(prefix)[None]
            batch["prefix_length"] = length
        return batch

    @torch.inference_mode()
    def __call__(self, request: dict) -> np.ndarray:
        batch = {
            key: value.to(self.device) if isinstance(value, torch.Tensor) else value
            for key, value in self.preprocess(request).items()
        }
        mask = self.action_mask.unsqueeze(0).expand(batch["input_ids"].shape[0], -1, -1)
        if "action" in batch:
            batch["action"] = ((batch["action"] - self.mean) / (self.std + ACTION_EPS)) * mask
        else:
            batch["action"] = torch.zeros(
                (batch["input_ids"].shape[0], *self.mean.shape),
                device=self.device,
                dtype=torch.bfloat16,
            )
        batch["action_mask"] = mask
        action = self.model.generate(batch)
        action = denormalize_action(action * mask, self.mean, self.std) * mask
        return action.cpu().float().numpy()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8170)
    args = parser.parse_args()
    policy = CobotPolicy(args.model)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen(1)
        print(f"XR0_SERVER_READY {args.host}:{args.port}", flush=True)
        while True:
            conn, address = server.accept()
            print(f"XR0_CLIENT_CONNECTED {address}", flush=True)
            try:
                while True:
                    request = _recv(conn)
                    if request is None:
                        break
                    started = time.monotonic()
                    _send(conn, policy(request))
                    print(f"XR0_INFERENCE latency={time.monotonic() - started:.3f}s", flush=True)
            except Exception:
                traceback.print_exc()
            finally:
                conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

