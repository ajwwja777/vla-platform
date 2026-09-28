"""Standalone RTC sampler mirroring the pinned OpenPI π0.5 sampler."""

from __future__ import annotations

import einops
import jax
import jax.numpy as jnp

from openpi.models import model as _model
from openpi.models.pi0 import make_attn_mask
from rtc_openpi.guidance import corrected_velocity
from rtc_openpi.guidance import prefix_weights_jax


def rtc_sample_actions(
    model,
    rng,
    observation,
    previous_actions,
    *,
    inference_delay,
    execution_horizon,
    num_steps=10,
    maximum_guidance_weight=5.0,
):
    """Sample an action chunk while inpainting its pending old prefix."""

    observation = _model.preprocess_observation(
        None,
        observation,
        train=False,
    )
    dt = -1.0 / num_steps
    batch_size = observation.state.shape[0]
    noise = jax.random.normal(
        rng,
        (batch_size, model.action_horizon, model.action_dim),
    )
    previous_actions = jnp.asarray(previous_actions)
    if previous_actions.ndim == 2:
        previous_actions = previous_actions[None, ...]
    previous_actions = jnp.broadcast_to(
        previous_actions,
        (batch_size, model.action_horizon, model.action_dim),
    )
    weights = prefix_weights_jax(
        inference_delay,
        execution_horizon,
        model.action_horizon,
        "exp",
    )

    prefix_tokens, prefix_mask, prefix_ar_mask = model.embed_prefix(
        observation
    )
    prefix_attn_mask = make_attn_mask(prefix_mask, prefix_ar_mask)
    positions = jnp.cumsum(prefix_mask, axis=1) - 1
    _, kv_cache = model.PaliGemma.llm(
        [prefix_tokens, None],
        mask=prefix_attn_mask,
        positions=positions,
    )

    def model_velocity(x_t, time):
        suffix_tokens, suffix_mask, suffix_ar_mask, adarms_cond = (
            model.embed_suffix(
                observation,
                x_t,
                jnp.broadcast_to(time, (batch_size,)),
            )
        )
        suffix_attn_mask = make_attn_mask(
            suffix_mask,
            suffix_ar_mask,
        )
        prefix_to_suffix_mask = einops.repeat(
            prefix_mask,
            "b p -> b s p",
            s=suffix_tokens.shape[1],
        )
        full_attn_mask = jnp.concatenate(
            [prefix_to_suffix_mask, suffix_attn_mask],
            axis=-1,
        )
        suffix_positions = (
            jnp.sum(prefix_mask, axis=-1)[:, None]
            + jnp.cumsum(suffix_mask, axis=-1)
            - 1
        )
        (prefix_out, suffix_out), _ = model.PaliGemma.llm(
            [None, suffix_tokens],
            mask=full_attn_mask,
            positions=suffix_positions,
            kv_cache=kv_cache,
            adarms_cond=[None, adarms_cond],
        )
        if prefix_out is not None:
            raise ValueError("OpenPI prefix output must remain cached")
        return model.action_out_proj(
            suffix_out[:, -model.action_horizon :]
        )

    def step(carry):
        x_t, time = carry

        def denoiser(value):
            return model_velocity(value, time)

        velocity = corrected_velocity(
            denoiser,
            x_t,
            previous_actions,
            weights,
            time,
            maximum_guidance_weight,
        )
        return x_t + dt * velocity, time + dt

    def condition(carry):
        _, time = carry
        return time >= -dt / 2

    x_0, _ = jax.lax.while_loop(
        condition,
        step,
        (noise, jnp.float32(1.0)),
    )
    return x_0
