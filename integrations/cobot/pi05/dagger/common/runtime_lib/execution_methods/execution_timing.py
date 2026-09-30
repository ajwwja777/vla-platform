"""Reusable physical-time publication and causal joint filtering, no ROS/model imports."""
import math
import numpy as np


def publication_events(logical_step, logical_hz, publish_hz):
    """Regular publication ticks in one logical interval; handles 20->30/50."""
    if logical_step < 0 or not np.isfinite([logical_hz, publish_hz]).all() or not 0 < logical_hz <= publish_hz:
        raise ValueError('Invalid publication grid')
    lo = math.floor(logical_step * publish_hz / logical_hz + 1e-9) + 1
    hi = math.floor((logical_step + 1) * publish_hz / logical_hz + 1e-9)
    return [(tick / publish_hz, tick * logical_hz / publish_hz - logical_step)
            for tick in range(lo, hi + 1)]


class CausalJointFilter:
    def __init__(self, tau_sec=0.08, max_velocity=0.6, joint_dimensions=6):
        if not np.isfinite([tau_sec, max_velocity]).all() or tau_sec < 0 or max_velocity <= 0:
            raise ValueError('Invalid smoothing configuration')
        self.tau, self.velocity, self.joints = tau_sec, max_velocity, joint_dimensions
        self.previous = None

    def reset(self, measured=None):
        self.previous = None if measured is None else np.asarray(measured, np.float32).copy()

    def apply(self, target, measured, dt):
        target, measured = np.asarray(target, np.float32), np.asarray(measured, np.float32)
        if target.ndim != 1 or measured.shape != target.shape or not np.isfinite([dt]).all() or dt <= 0:
            raise ValueError('Invalid filter tick')
        if not np.isfinite(target).all() or not np.isfinite(measured).all():
            raise ValueError('Nonfinite command')
        if self.previous is None:
            self.reset(measured)
        alpha = 1. if self.tau == 0 else -math.expm1(-dt / self.tau)
        output = target.copy()
        delta = alpha * (target[:self.joints] - self.previous[:self.joints])
        output[:self.joints] = self.previous[:self.joints] + np.clip(delta, -self.velocity*dt, self.velocity*dt)
        self.previous = output.copy()
        return output
