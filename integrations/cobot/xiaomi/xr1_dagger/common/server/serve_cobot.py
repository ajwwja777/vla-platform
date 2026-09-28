#!/usr/bin/env python3
"""Loopback-only XR-1 policy server for the Cobot deployment package."""

from __future__ import annotations

import argparse
import os
import pickle
import socket
import struct
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image
import torch
from checkpoint_io import ensure_liger_dtensor_compat, load_checkpoint_module

ensure_liger_dtensor_compat()

from mmengine import Config
from transformers import AutoProcessor

from mibot.models import MIMODEL
from mibot.utils.io import (
    ACTION_EPS,
    build_action_mask,
    compose_state,
    denormalize_action,
    resize_image,
    validate_quantiles,
    validate_stats,
)
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


def _strip_prefix(state_dict, prefix):
    return {key[len(prefix) :]: value for key, value in state_dict.items() if key.startswith(prefix)}


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
                {"type": "text", "text": f"\nGenerate robot actions for the task:\n{instruction} /no_cot"},
            ],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "<cot></cot>"}]},
    ]


class CobotPolicy:
    def __init__(self, model_dir: str, processor_path: str, device: str = "cuda:0", max_pixels: int = 160000) -> None:
        self.device = device
        self.max_pixels = int(max_pixels)
        model_dir = Path(model_dir)
        config = Config.fromfile(str(model_dir / "config.py"))
        self.model = MIMODEL.build(config.model.params.model).to(torch.bfloat16)
        checkpoint_path = model_dir / "last.ckpt/checkpoint/mp_rank_00_model_states.pt"
        checkpoint = load_checkpoint_module(checkpoint_path)
        result = self.model.load_state_dict(_strip_prefix(checkpoint, "model."), strict=True)
        print(f"XR1_CHECKPOINT_LOADED path={checkpoint_path} result={result}", flush=True)
        self.model = self.model.eval().to(device)

        data = config.data.params.train_datasets
        action_length = int(data.get("action_length", config.data.params.get("action_length", 30)))
        mean, std = validate_stats(data.mean, data.std, action_length)
        q01, q99 = validate_quantiles(data.q01, data.q99)
        self.mean = torch.tensor(mean, device=device)
        self.std = torch.tensor(std, device=device)
        self.q01 = torch.tensor(q01, device=device)
        self.q99 = torch.tensor(q99, device=device)
        self.action_mask = torch.from_numpy(build_action_mask(action_length)).to(device)
        self.processor = AutoProcessor.from_pretrained(processor_path, local_files_only=True)
        self.processor.tokenizer.padding_side = "right"

    def _image(self, value) -> Image.Image:
        image = Image.fromarray(np.asarray(value, dtype=np.uint8), mode="RGB")
        return resize_image(image, factor=32, max_pixels=self.max_pixels)

    def preprocess(self, request: dict) -> dict:
        state = np.asarray(request["state"], dtype=np.float32)
        if state.shape != (14,) or not np.isfinite(state).all():
            raise ValueError("request state must be one finite 14D vector")
        images = request["images"]
        batch = self.processor.apply_chat_template(
            [[*_messages(request["instruction"], self._image(images["ego"]), self._image(images["left_wrist"]), self._image(images["right_wrist"]))]],
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
            prefix = np.asarray(request["action_prefix"], dtype=np.float32)
            if prefix.ndim != 2 or prefix.shape[1] != 60 or not 1 <= len(prefix) <= 30 or not np.isfinite(prefix).all():
                raise ValueError("action prefix must be finite with shape (1..30, 60)")
            padded = np.zeros((30, 60), dtype=np.float32)
            padded[: len(prefix)] = prefix
            batch["action"] = torch.from_numpy(padded)[None]
            batch["prefix_length"] = int(len(prefix))
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
        state = batch["state"]
        valid = self.q99 > self.q01
        normalized_state = torch.zeros_like(state)
        normalized_state[..., valid[0]] = (
            2.0 * (state[..., valid[0]] - self.q01[..., valid[0]])
            / (self.q99[..., valid[0]] - self.q01[..., valid[0]] + ACTION_EPS)
            - 1.0
        )
        batch["state"] = normalized_state.clamp(-1.0, 1.0)
        action = self.model.generate(batch)
        action = denormalize_action(action * mask, self.mean, self.std) * mask
        result = action.cpu().float().numpy()
        if result.shape != (1, 30, 60) or not np.isfinite(result).all():
            raise RuntimeError(f"XR-1 produced invalid action shape/content: {result.shape}")
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--processor", default=os.environ.get("XR1_QWEN3_VL_PATH"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8171)
    parser.add_argument("--max-pixels", type=int, default=160000)
    args = parser.parse_args()
    if not args.processor:
        parser.error("--processor or XR1_QWEN3_VL_PATH is required")
    policy = CobotPolicy(args.model, args.processor, max_pixels=args.max_pixels)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen(1)
        print(f"XR1_SERVER_READY {args.host}:{args.port}", flush=True)
        while True:
            conn, address = server.accept()
            print(f"XR1_CLIENT_CONNECTED {address}", flush=True)
            try:
                while True:
                    request = _recv(conn)
                    if request is None:
                        break
                    started = time.monotonic()
                    _send(conn, policy(request))
                    print(f"XR1_INFERENCE latency={time.monotonic() - started:.3f}s", flush=True)
            except Exception:
                traceback.print_exc()
            finally:
                conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
