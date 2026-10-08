"""Exercise the real web wrapper under its script-directory import precedence."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

VLA = Path(__file__).resolve().parents[3]
WEB_CLIENT = VLA.parent / 'cobot-web/app/backend/cobot_console/deployment_pi05_client.py'

@pytest.mark.parametrize('variant', ['baseline', 'dagger'])
@pytest.mark.parametrize('options', [None,
    dict(enabled=True, publish_hz=20, rtc=False, smoothing=False),
    dict(enabled=True, publish_hz=50, rtc=True, smoothing=True),
    dict(enabled=True, publish_hz=50, rtc=False, smoothing=True)])
def test_web_pi05_wrapper_ignores_same_named_web_module(variant, options, tmp_path):
    robot = VLA / 'integrations/cobot/pi05' / variant / 'common/robot'
    runtime = robot.parent / 'runtime_lib'
    code = '''import json,os,runpy,sys,types
from pathlib import Path
import numpy as np
web=Path(sys.argv[1]);robot=Path(sys.argv[2]);runtime=Path(sys.argv[3])
sys.path[:0]=[str(web.parent),str(robot),str(runtime)]
# Match an already cached colliding top-level module as well as sys.path order.
poison=types.ModuleType('execution_options')
def forbidden(*a,**kw):raise AssertionError('wrong execution options module')
poison.selected_options=forbidden;sys.modules['execution_options']=poison
ros=types.ModuleType('rospy');ros.Service=lambda *a,**k:object()
ros.Rate=lambda *a:types.SimpleNamespace(sleep=lambda:None)
ros.is_shutdown=lambda:True
sys.modules['rospy']=ros
srv=types.ModuleType('std_srvs.srv')
srv.SetBool=object
srv.SetBoolResponse=lambda **kw:types.SimpleNamespace(**kw)
sys.modules['std_srvs']=types.ModuleType('std_srvs');sys.modules['std_srvs.srv']=srv
policy_module=types.ModuleType('openpi_client')
class Policy:
 def __init__(self,**kw):self.calls=[]
 def get_server_metadata(self):return {'rtc_protocol_version':1}
 def infer(self,request):
  self.calls.append(request)
  return dict(protocol_version=1,session_id=request['session_id'],request_id=request['request_id'],actions_robot=np.zeros((30,14)),action_horizon=30,model_infer_ms=1,rtc_enabled=True)
policy_module.websocket_client_policy=types.SimpleNamespace(WebsocketClientPolicy=Policy)
sys.modules['openpi_client']=policy_module
# Hardware-only dependency is stubbed; RTC clients, queue, options, runtime and
# the web pause wrapper below are the actual files.
hardware=types.ModuleType('inference_pi05');hardware.RosInterface=object
hardware.apply_right_gripper=lambda a,*args,**kw:a
hardware.limit_action_step=lambda a,*args,**kw:a
hardware.parse_float_list=lambda value:[float(v) for v in value.split(',')]
hardware.str2bool=lambda value:value.lower()=='true'
sys.modules['inference_pi05']=hardware
wrapper=runpy.run_path(str(web),run_name='import_regression')
client=wrapper['client'];options=client.selected_options()
assert client.selected_options.__module__=='integrations.cobot.execution_options'
assert client.PublicationDriver.__module__=='integrations.cobot.execution_runtime'
assert sys.modules['execution_options'] is poison
expected=json.loads(os.environ['EXPECTED_OPTIONS']);assert options==expected
hardware_io=types.SimpleNamespace(wait_for_observation=lambda:{'state':np.zeros(14)},last_command=None)
client.rtc.create_ros_interface=lambda args:hardware_io
assert client.main(['--prompt','synthetic import regression','--use-init-pose','false'])==0
gate=json.loads(Path(os.environ['COBOT_PI05_GATE_STATE']).read_text())
assert gate['paused'] and gate['manual_pause'] and not gate['hil_active']
print(json.dumps({'options':options,'paused':gate['paused']}))
'''
    env = {**os.environ,
        'PYTHONPATH': str(VLA / 'integrations/cobot'),
        'COBOT_PI05_CLIENT_ROOT': str(robot),
        'COBOT_PI05_GATE_STATE': str(tmp_path / 'gate.json'),
        'EXPECTED_OPTIONS': json.dumps(options or {'enabled':False})}
    env.pop('COBOT_EXECUTION_OPTIONS', None)
    if options is not None:
        env['COBOT_EXECUTION_OPTIONS'] = json.dumps(options)
    result = subprocess.run([sys.executable, '-c', code, str(WEB_CLIENT), str(robot), str(runtime)],
        env=env,cwd=tmp_path,text=True,capture_output=True,timeout=15)
    assert result.returncode == 0, result.stdout+'\n'+result.stderr
    assert 'ready and PAUSED' in result.stdout
