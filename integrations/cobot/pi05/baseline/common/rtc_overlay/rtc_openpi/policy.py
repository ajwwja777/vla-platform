"""OpenPI Policy wrapper accepting versioned RTC request envelopes."""

from __future__ import annotations

import time
import types
from typing import Any

import jax
import jax.numpy as jnp
import numpy as np

from execution_methods.rtc.protocol import RTCRequest
from execution_methods.rtc.protocol import RTCResponse
from openpi.models import model as _model
from openpi.shared import nnx_utils
from rtc_openpi.bridge import copy_observation
from rtc_openpi.bridge import encode_previous_actions
from rtc_openpi.sampler import rtc_sample_actions


class RTCPolicy:
    """Inference-only RTC wrapper around an immutable trained OpenPI policy."""

    def __init__(self, base_policy: Any):
        if getattr(base_policy, "_is_pytorch_model", False):
            raise ValueError("RTC π0.5 overlay requires the JAX policy")
        self._base_policy = base_policy
        self._sample_actions = nnx_utils.module_jit(
            types.MethodType(rtc_sample_actions, base_policy._model)
        )

    @property
    def metadata(self):
        metadata = dict(self._base_policy.metadata)
        metadata.update(
            {
                "rtc_protocol_version": 1,
                "rtc_execution_only": True,
                "rtc_prefix_schedule": "exp",
                "rtc_max_guidance_weight": 5.0,
            }
        )
        return metadata

    def _sample_with_rtc(
        self,
        sample_rng,
        observation,
        previous_actions,
        **sample_kwargs,
    ):
        return self._sample_actions(
            sample_rng,
            observation,
            previous_actions,
            **sample_kwargs,
        )

    def infer(self, envelope):
        request = RTCRequest.from_mapping(envelope)
        if request.previous_actions_robot.shape[0] == 0:
            output = self._base_policy.infer(
                copy_observation(request.observation)
            )
            actions = np.asarray(output["actions"], dtype=np.float32)
            infer_ms = float(output["policy_timing"]["infer_ms"])
        else:
            previous = encode_previous_actions(
                self._base_policy,
                request.observation,
                request.previous_actions_robot,
            )
            inputs = self._base_policy._input_transform(
                copy_observation(request.observation)
            )
            inputs = jax.tree.map(
                lambda value: jnp.asarray(value)[np.newaxis, ...],
                inputs,
            )
            observation = _model.Observation.from_dict(inputs)
            self._base_policy._rng, sample_rng = jax.random.split(
                self._base_policy._rng
            )
            sample_kwargs = dict(self._base_policy._sample_kwargs)
            unknown = set(sample_kwargs) - {"num_steps"}
            if unknown:
                raise ValueError(
                    "unsupported OpenPI RTC sample kwargs: "
                    + ", ".join(sorted(unknown))
                )
            started = time.monotonic()
            sampled = self._sample_with_rtc(
                sample_rng,
                observation,
                jnp.asarray(previous)[None, ...],
                inference_delay=request.inference_delay_steps,
                execution_horizon=request.execution_horizon,
                num_steps=sample_kwargs.get("num_steps", 10),
                maximum_guidance_weight=5.0,
            )
            infer_ms = (time.monotonic() - started) * 1000.0
            outputs = {
                "state": np.asarray(inputs["state"][0]),
                "actions": np.asarray(sampled[0]),
            }
            output = self._base_policy._output_transform(outputs)
            actions = np.asarray(output["actions"], dtype=np.float32)

        response = RTCResponse(
            protocol_version=1,
            session_id=request.session_id,
            request_id=request.request_id,
            actions_robot=actions,
            action_horizon=actions.shape[0],
            model_infer_ms=infer_ms,
            rtc_enabled=True,
        ).to_mapping()
        response["policy_timing"] = {"infer_ms": infer_ms}
        return response
