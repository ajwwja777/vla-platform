"""Wait for a valid observation without weakening the native freshness guard."""
import time

TRANSIENT = ('Camera/joint timestamp stale or in the future',
             'Camera/joint callback stale',
             'Camera/joint timestamps differ by more than 100 ms')


def fresh_snapshot(read, timeout=.2, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while True:
        try:
            return read()
        except ValueError as error:
            if not str(error).startswith(TRANSIENT) or clock() >= deadline:
                raise
            sleep(min(.01, max(0., deadline - clock())))
