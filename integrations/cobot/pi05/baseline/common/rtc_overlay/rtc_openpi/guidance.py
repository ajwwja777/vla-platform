"""JAX implementation of paper RTC's VJP inpainting correction."""

from __future__ import annotations

import jax
import jax.numpy as jnp


def prefix_weights_jax(start, end, total, schedule="exp"):
    indices = jnp.arange(total, dtype=jnp.float32)
    linear = jnp.clip(
        (start - 1 - indices) / (end - start + 1) + 1,
        0,
        1,
    )
    if schedule == "exp":
        weights = linear * jnp.expm1(linear) / jnp.expm1(
            jnp.float32(1.0)
        )
    elif schedule == "linear":
        weights = linear
    elif schedule == "ones":
        weights = jnp.ones(total, dtype=jnp.float32)
    elif schedule == "zeros":
        weights = (indices < start).astype(jnp.float32)
    else:
        raise ValueError("invalid RTC prefix schedule")
    return jnp.where(indices >= end, 0, weights)


def paper_guidance_weight_jax(tau, maximum=5.0):
    denominator = tau * (1.0 - tau)
    raw = (tau**2 + (1.0 - tau) ** 2) / denominator
    finite = jnp.nan_to_num(
        raw,
        nan=maximum,
        posinf=maximum,
        neginf=maximum,
    )
    return jnp.minimum(finite, maximum)


def corrected_velocity(
    denoiser,
    x_t,
    previous,
    weights,
    time,
    beta,
):
    """Correct OpenPI's noise-to-action velocity with RTC VJP guidance."""

    def clean_estimate(value):
        velocity = denoiser(value)
        x_clean = value - time * velocity
        return x_clean, velocity

    x_clean, vjp_fn, velocity = jax.vjp(
        clean_estimate,
        x_t,
        has_aux=True,
    )
    error = (previous - x_clean) * weights[None, :, None]
    correction = vjp_fn(error)[0]
    tau = 1.0 - time
    weight = paper_guidance_weight_jax(tau, beta)
    return velocity - weight * correction
