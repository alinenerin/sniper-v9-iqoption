import threading
import time
import unittest

from current_iq import _bounded_call


class TestIQSDKSingleFlight(unittest.TestCase):
    def test_timed_out_call_blocks_new_sdk_call_until_worker_finishes(self):
        started = []
        release = threading.Event()
        first_started = threading.Event()

        def slow_sdk_call():
            started.append('first')
            first_started.set()
            release.wait(timeout=2)
            return 'done'

        def second_sdk_call():
            started.append('second')
            return 'unexpected'

        try:
            first_result = _bounded_call(slow_sdk_call, timeout=0.05)
            self.assertTrue(first_started.wait(timeout=0.5))
            self.assertIsNone(first_result)
            second_result = _bounded_call(second_sdk_call, timeout=0.05)
            self.assertIsNone(second_result)
            self.assertEqual(started, ['first'])
        finally:
            release.set()

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            # The persistent worker must finish before a subsequent call can run.
            from current_iq import _sdk_active_future
            if _sdk_active_future is not None and _sdk_active_future.done():
                break
            time.sleep(0.01)
        self.assertEqual(started, ['first'])


if __name__ == '__main__':
    unittest.main()
