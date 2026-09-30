"""Model-independent, opt-in execution choices. No model, ROS or NumPy imports."""
import json
import os

def normalize_options(options):
    if not isinstance(options, dict) or set(options) - {'enabled', 'publish_hz', 'rtc', 'smoothing'}:
        raise ValueError('invalid_execution_options')
    if type(options.get('enabled')) is not bool:
        raise ValueError('execution_options_enabled_must_be_boolean')
    if not options['enabled']:
        if set(options) != {'enabled'}:
            raise ValueError('disabled_execution_options_use_model_defaults')
        return {'enabled': False}
    if set(options) != {'enabled', 'publish_hz', 'rtc', 'smoothing'}:
        raise ValueError('execution_options_require_hz_rtc_smoothing')
    if type(options['publish_hz']) is not int or options['publish_hz'] not in (20,30,40,50) or type(options['rtc']) is not bool or type(options['smoothing']) is not bool:
        raise ValueError('invalid_execution_option_types')
    return dict(options)

def selected_options(environ=None):
    environ = os.environ if environ is None else environ
    raw = environ.get('COBOT_EXECUTION_OPTIONS')
    return normalize_options(json.loads(raw)) if raw else {'enabled': False}

def describe_execution(model):
    options = normalize_options(model.get('execution_options', {'enabled': False}))
    hz = model.get('control_hz') or 20
    defaults = dict(enabled=False, publish_hz=hz, logical_hz=hz,
                    rtc=model.get('kind') == 'pi05' or model.get('family') in ('FluxVLA π0.5', 'XR1', 'XR1 DAgger'),
                    smoothing=str(model.get('family', '')).startswith('XR1'))
    return {**defaults, **options} if options['enabled'] else defaults
