"""Run the unchanged native IK in a child interpreter, leaving ROS callbacks free."""
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import signal
import threading


def _serve(connection, native_path, expected_sha):
    # Set only this CPU worker's library threads before importing NumPy/Pinocchio.
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[name] = '1'
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        path = Path(native_path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
            raise ValueError('Native IK source changed; review before deployment')
        spec = importlib.util.spec_from_file_location('omnisf_native_ik', str(path))
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        arms = {}
        while True:
            command, side, arguments = connection.recv()
            if command == 'stop':
                break
            try:
                if command == 'init':
                    arms[side] = native.Arm()
                    result = True
                elif command in ('fk', 'solve'):
                    result = getattr(arms[side], command)(*arguments)
                else:
                    raise ValueError('Unsupported IK worker command')
                connection.send((True, result))
            except Exception as error:
                connection.send((False, str(error)))
    except EOFError:
        pass
    except Exception as error:
        try:
            connection.send((False, str(error)))
        except (EOFError, OSError):
            pass
    finally:
        connection.close()


class RemoteArm:
    def __init__(self, owner, side):
        self.owner, self.side = owner, side

    def fk(self, q):
        return self.owner.request('fk', self.side, (q,))

    def solve(self, pose, seed):
        return self.owner.request('solve', self.side, (pose, seed))


class IKProcess:
    def __init__(self, native_path=None, expected_sha=None):
        if native_path is None:
            manifest = json.loads(Path(__file__).with_name('native_manifest.json').read_text())
            native_path = str(Path(manifest['root']) / 'scripts/v64_live.py')
            expected_sha = manifest['files']['scripts/v64_live.py']
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_serve, args=(child, str(native_path), expected_sha), daemon=True)
        self.lock = threading.RLock()
        self.failed = False
        self.closed = False
        self.process.start()
        child.close()

    def request(self, command, side, arguments=(), timeout=3):
        with self.lock:
            if self.closed or self.failed or not self.process.is_alive():
                raise RuntimeError('Native IK worker unavailable; release and reload')
            try:
                self.connection.send((command, side, arguments))
                if not self.connection.poll(timeout):
                    self.failed = True
                    raise RuntimeError('Native IK worker timed out; release and reload')
                ok, result = self.connection.recv()
            except (EOFError, OSError) as error:
                self.failed = True
                raise RuntimeError('Native IK worker disconnected; release and reload') from error
            if not ok:
                raise RuntimeError('Native IK worker: ' + str(result))
            return result

    def arm(self, side):
        self.request('init', side, timeout=30)
        return RemoteArm(self, side)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            try:
                if self.process.is_alive():
                    self.connection.send(('stop', '', ()))
            except (EOFError, OSError):
                pass
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1)
            self.connection.close()
