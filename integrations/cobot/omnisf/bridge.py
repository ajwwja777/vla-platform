"""Apply reviewed lifecycle hooks to a SHA-pinned native client.

History, model input/output transforms, IK, units and limits stay in the original
v64_live.py. Exact anchors and SHA reject unreviewed native source revisions.
"""
import hashlib
import json
import os
from pathlib import Path


def patched_source(source):
    def change(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError('Native OmniSF lifecycle anchor changed: ' + old[:70])
        source = source.replace(old, new, 1)
    change('import argparse\n', 'import argparse\nimport os\nfrom gate import Gate\nfrom observations import fresh_snapshot\nfrom ik_worker import IKProcess\nimport pinocchio\n')
    change("    parser.add_argument('--prompt', default=COVER_BLOCKS)",
           "    parser.add_argument('--prompt', default=COVER_BLOCKS)\n"
           "    parser.add_argument('--shadow-predictions', type=int, default=0)")
    change('    if args.pilot and not args.execute:',
           "    if args.shadow_predictions and args.execute:\n"
           "        parser.error('Shadow qualification cannot construct robot publishers')\n"
           "    if args.pilot and not args.execute:")
    change('    def snapshot():', '    def snapshot_once():')
    change('    def ownership(data):',
           '    def snapshot():\n        return fresh_snapshot(snapshot_once)\n\n    def ownership(data):')
    change('                data, q = snapshot()\n                cmd =',
           '                data, q = snapshot_once()\n                cmd =')
    change('    arms = {s: Arm() for s in SIDES}',
           "    ik_pool = IKProcess()\n    arms = {s: ik_pool.arm(s) for s in SIDES}")
    change('from std_srvs.srv import SetBool, SetBoolResponse',
           'from std_srvs.srv import SetBool, SetBoolResponse, Trigger, TriggerResponse')
    change("out = ROOT / 'outputs' /", "out = Path(os.environ['OMNISF_OUTPUT_ROOT']) /")
    change('latest, lock, paused, history = {}, threading.RLock(), threading.Event(), History()',
           "latest, lock, paused, history = {}, threading.RLock(), threading.Event(), History()\n"
           "    gate = Gate(os.environ['COBOT_MODEL_GATE_STATE'], paused, int(os.environ['OMNISF_OWNER_PID']), os.environ['OMNISF_MODEL_ID'])\n"
           "    threading.Thread(target=gate.heartbeat, daemon=True).start()")
    change("    def set_paused(req):\n        paused.set() if req.data else paused.clear()\n        return SetBoolResponse(success=True, message='paused' if req.data else 'will re-plan from fresh observations')",
           "    def set_paused(req):\n"
           "        caller = getattr(req, '_connection_header', {}).get('callerid', '')\n"
           "        ok, message = gate.pause(req.data, 'cobot_deployment_command' in caller)\n"
           "        return SetBoolResponse(success=ok, message=message)\n\n"
           "    def arm_request(req):\n"
           "        nonlocal history\n"
           "        try:\n"
           "            def validate():\n"
           "                data, _ = snapshot()\n"
           "                ownership(data)\n"
           "            gate.arm(validate)\n"
           "            with lock:\n"
           "                history = History()\n"
           "                history.add(time.monotonic(), to_rgb(latest[CAMERAS['cam_high']][0]))\n"
           "            return TriggerResponse(success=True, message='armed; manually paused')\n"
           "        except Exception as exc:\n"
           "            return TriggerResponse(success=False, message=str(exc))")
    change("service = rospy.Service('/task2/policy/set_paused', SetBool, set_paused)",
           "service = rospy.Service('/task2/policy/set_paused', SetBool, set_paused)\n"
           "            arm_service = rospy.Service('/task2/policy/arm', Trigger, arm_request)")
    change('        stop_at = t_start + args.seconds',
           "        stop_at = t_start + args.seconds\n"
           "        if args.shadow_predictions:\n"
           "            gate.armed, gate.manual = True, False\n"
           "            paused.clear()\n            gate.save()")
    change('            if not args.execute:\n                time.sleep(.5)',
           "            if args.shadow_predictions and count >= args.shadow_predictions:\n"
           "                reason = 'no-publisher shadow complete'\n                break\n"
           "            if not args.execute:\n                time.sleep(.5)")
    warmup = """        warmup_start = time.monotonic()
        for warmup_index in range(2):
            warm_data, warm_q = snapshot()
            warm_now = time.monotonic()
            warm_images = {name: to_rgb(warm_data[t][0]) for name, t in CAMERAS.items()}
            with lock:
                warm_images['cam_high'] = history.stack(warm_now, warm_images['cam_high'])
            warm_state = np.asarray(sum((arm_state(warm_data[POSE[s]][0], warm_q[s][6], args.gripper_open) for s in SIDES), []), dtype=np.float32)
            warm_actions = np.asarray(client.infer({'images': warm_images, 'state': warm_state, 'prompt': args.prompt})['actions'])
            if warm_actions.shape != (50, 16) or not np.isfinite(warm_actions).all():
                raise ValueError('Invalid warmup model output: %s' % (warm_actions.shape,))
        print(json.dumps({'warmup_predictions': 2, 'warmup_seconds': time.monotonic() - warmup_start, 'commands_sent': 0}), flush=True)
"""
    change('        t_start = time.monotonic()',
           warmup + "        gate.ready = True\n        gate.save()\n"
           "        print('Model ready and PAUSED; explicit Web Start required.', flush=True)\n"
           "        last_epoch = None\n        t_start = time.monotonic()")
    change('            data, q = snapshot()\n            ownership(data)\n            if paused.is_set():\n                previous = {s: list(q[s]) for s in SIDES}\n                time.sleep(.03)\n                continue',
           "            gate.save(force=False)\n"
           "            if paused.is_set():\n"
           "                time.sleep(.03)\n                continue\n"
           "            epoch = gate.generation\n"
           "            data, q = snapshot()\n            ownership(data)\n"
           "            if epoch != last_epoch:\n"
           "                previous = {s: list(q[s]) for s in SIDES}\n"
           "                last_epoch = epoch")
    change('                stamp = rospy.Time.now()\n                for s in SIDES:\n                    msg = JointState()\n                    msg.header.stamp, msg.name, msg.position = stamp, [\'joint%d\' % j for j in range(7)], cmd[s]\n                    publishers[s].publish(msg)',
           "                with gate.lock:\n"
           "                    if paused.is_set() or epoch != gate.generation:\n"
           "                        break\n"
           "                    stamp = rospy.Time.now()\n"
           "                    for s in SIDES:\n"
           "                        msg = JointState()\n"
           "                        msg.header.stamp, msg.name, msg.position = stamp, ['joint%d' % j for j in range(7)], cmd[s]\n"
           "                        publishers[s].publish(msg)")
    change("    except Exception as exc:\n        reason = str(exc)\n        raise", "    except Exception as exc:\n        reason = str(exc)\n        gate.trip(exc)\n        raise")
    change('    finally:\n        for p in publishers.values():',
           "    finally:\n        gate.stopped.set()\n        ik_pool.close()\n        gate.ready = False\n        gate.manual = True\n        paused.set()\n        gate.save()\n        for p in publishers.values():")
    # Runtime guard failures cancel this plan and keep server/client paused.
    # Startup failures above this loop remain fatal and never report readiness.
    header = '        while not rospy.is_shutdown() and time.monotonic() < stop_at:\n'
    begin = source.index(header) + len(header)
    end = source.index('    except (KeyboardInterrupt, rospy.ROSInterruptException):', begin)
    body = source[begin:end]
    protected = '            try:\n' + ''.join('    ' + line if line.strip() else line for line in body.splitlines(True))
    protected += ("            except Exception as exc:\n"
                  "                gate.protect(exc)\n"
                  "                print(json.dumps({'protective_pause': str(exc), 'commands_sent': commands, 'prediction': count}), flush=True)\n"
                  "                continue\n")
    source = source[:begin] + protected + source[end:]
    compile(source, '<managed-omnisf>', 'exec')
    return source


def main():
    manifest = json.loads(Path(__file__).with_name('native_manifest.json').read_text())
    native = Path(manifest['root']) / 'scripts/v64_live.py'
    payload = native.read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest['files']['scripts/v64_live.py']:
        raise ValueError('Native OmniSF client SHA changed; review before deployment')
    source = patched_source(payload.decode('utf8'))
    namespace = {'__name__': '__main__', '__file__': str(native)}
    exec(compile(source, str(native), 'exec'), namespace)


if __name__ == '__main__':
    main()
