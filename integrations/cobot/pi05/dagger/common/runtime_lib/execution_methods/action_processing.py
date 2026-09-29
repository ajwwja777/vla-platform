"""Time-preserving resampling and bounded exploratory perturbations.

Pure arrays and a caller-owned RNG. No ROS, no learner, no automatic activation.
Use trajectory interpolation at a higher publication rate, never reinterpret the
same actions at a faster model rate. Grippers can be excluded by dimension mask.
"""
import numpy as np

def resample_actions(actions, initial, logical_hz=20., publish_hz=40.):
    actions=np.asarray(actions,np.float32);initial=np.asarray(initial,np.float32)
    if actions.ndim!=2 or initial.shape!=(actions.shape[1],) or not len(actions):
        raise ValueError("Expected (steps, dimensions) actions and one initial state")
    if not np.isfinite(actions).all() or not np.isfinite(initial).all():
        raise ValueError("Actions must be finite")
    if not np.isfinite([logical_hz,publish_hz]).all() or logical_hz<=0 or publish_hz<logical_hz:
        raise ValueError("Invalid control rates")
    ratio=publish_hz/logical_hz
    if abs(ratio-round(ratio))>1e-8:raise ValueError("Publication rate must be an integer multiple")
    ratio=int(round(ratio))
    knots=np.concatenate([initial[None],actions])
    # Endpoints keep exact logical timestamps; interpolation delays the first
    # target until the end of its original logical period.
    times=np.arange(1,len(actions)*ratio+1)/publish_hz
    grid=np.arange(len(actions)+1)/logical_hz
    output=np.stack([np.interp(times,grid,knots[:,d]) for d in range(actions.shape[1])],axis=-1).astype(np.float32)
    return times,output

def bounded_noise(rng, shape, std, *, rho=0., active_dimensions=None, clip_sigma=3.):
    if len(shape)!=2 or min(shape)<=0:raise ValueError("Expected a chunk shape")
    if not np.isfinite([std,rho,clip_sigma]).all() or std<0 or not 0<=rho<1 or clip_sigma<=0:
        raise ValueError("Invalid noise configuration")
    if std==0:return np.zeros(shape,np.float32)
    noise=rng.normal(size=shape)
    for i in range(1,shape[0]):
        noise[i]=rho*noise[i-1]+np.sqrt(1-rho*rho)*noise[i]
    noise=np.clip(noise,-clip_sigma,clip_sigma)*std
    if active_dimensions is not None:
        mask=np.asarray(active_dimensions,bool)
        if mask.shape!=(shape[1],):raise ValueError("Wrong dimension mask")
        noise[:,~mask]=0
    return noise.astype(np.float32)
