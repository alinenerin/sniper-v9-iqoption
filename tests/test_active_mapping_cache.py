import time
import unittest
from unittest.mock import patch

import current_iq
from current_iq import IQOptionReadonly


class FakeProvider:
    def __init__(self):
        self.mapping_refreshes = 0
        self.candle_requests = 0

    def get_ALL_Binary_ACTIVES_OPCODE(self):
        self.mapping_refreshes += 1
        current_iq.OP_code.ACTIVES["EURUSD"] = 12345
        return True

    def get_candles(self, symbol, interval, count, cursor):
        self.candle_requests += 1
        last_open = int(time.time() // interval) * interval - interval
        return [
            {"from": last_open - interval * (count - index - 1),
             "open": 1.1000, "max": 1.1010, "min": 1.0990,
             "close": 1.1005, "volume": 1}
            for index in range(count)
        ]


class ActiveMappingCacheTests(unittest.TestCase):
    def test_official_active_map_is_refreshed_once_per_session(self):
        provider = FakeProvider()
        session = object.__new__(IQOptionReadonly)
        session.connected = True
        session.api = provider
        session._wait_for_connection = lambda timeout=35: True

        with patch.object(current_iq, "_session_id", "test-session"), \
             patch.object(current_iq, "_active_map_session_id", None), \
             patch.object(current_iq, "_state", {"status": "connected"}), \
             patch.dict(current_iq.OP_code.ACTIVES, {}, clear=True), \
             patch.object(current_iq, "_bounded_call",
                          side_effect=lambda fn, *args, timeout=8: fn(*args)):
            first = session.candles("EURUSD", 60, 1000, "REAL", allow_cache=False)
            second = session.candles("EURUSD", 60, 1000, "REAL", allow_cache=False)

        self.assertEqual(first["status"], "OK", first)
        self.assertEqual(second["status"], "OK", second)
        self.assertEqual(provider.mapping_refreshes, 1)
        self.assertEqual(provider.candle_requests, 2)
        self.assertFalse(first["mapping_cache_hit"])
        self.assertTrue(second["mapping_cache_hit"])
        self.assertEqual(second["mapping_source"], "IQ_OPTION_SESSION_MAPPING_CACHE")


if __name__ == "__main__":
    unittest.main()
