import threading
import time
import unittest

from current_iq import (_bounded_call, _queue_candle_stream_subscription,
                        _candle_stream_ack)
from collections import defaultdict
from types import SimpleNamespace


class TestIQSDKSingleFlight(unittest.TestCase):
    def test_warm_subscription_queues_without_blocking_for_ack(self):
        calls = []
        class FakeAPI:
            real_time_candles_maxdict_table = defaultdict(lambda: defaultdict(int))
            candle_generated_check = defaultdict(lambda: defaultdict(dict))
            def subscribe(self, active_id, interval):
                calls.append((active_id, interval))
        class FakeClient:
            api = FakeAPI()
            subscribe_candle = []
        client = FakeClient()
        stable = client
        # Use a temporary official active-id mapping, restored immediately.
        import iqoptionapi.constants as codes
        previous = codes.ACTIVES.get('EURUSD')
        codes.ACTIVES['EURUSD'] = 1
        try:
            self.assertTrue(_queue_candle_stream_subscription(client, 'EURUSD', 60, 120))
            self.assertEqual(calls, [(1, 60)])
            self.assertEqual(stable.api.real_time_candles_maxdict_table['EURUSD'][60], 120)
            self.assertFalse(_candle_stream_ack(client, 'EURUSD', 60))
            stable.api.candle_generated_check['EURUSD'][60] = True
            self.assertTrue(_candle_stream_ack(client, 'EURUSD', 60))
        finally:
            if previous is None:
                codes.ACTIVES.pop('EURUSD', None)
            else:
                codes.ACTIVES['EURUSD'] = previous

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
