import importlib.util
import os
import pathlib
import unittest
from unittest import mock

import current_iq


class FakeAccountAPI:
    def __init__(self):
        self.balance_reads = 0
        self.mode_changes = 0

    def get_balance(self):
        self.balance_reads += 1
        return 123.45

    def get_currency(self):
        return "USD"

    def change_balance(self, mode):
        self.mode_changes += 1


class FakeSession:
    def __init__(self):
        self.calls = 0

    def account_balance_readonly(self):
        self.calls += 1
        return {"ok": True, "balance": 123.45, "currency": "USD",
                "balance_mode": "PRACTICE", "read_only": True,
                "execution_allowed": False}


class ReadOnlyBalanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = pathlib.Path(__file__).resolve().parents[1] / "market_gateway.py"
        spec = importlib.util.spec_from_file_location("balance_gateway_test", source)
        cls.gateway = importlib.util.module_from_spec(spec)
        cls.fake_session = FakeSession()
        with mock.patch.object(current_iq, "IQOptionReadonly", return_value=cls.fake_session):
            spec.loader.exec_module(cls.gateway)

    def setUp(self):
        self.fake_session.calls = 0

    def _handler(self, authorization):
        handler = object.__new__(self.gateway.Handler)
        handler.path = "/api/account/balance"
        handler.headers = {"Authorization": authorization}
        captured = {}
        handler._send = lambda payload, code=200: captured.update(payload=payload, code=code)
        return handler, captured

    def test_reads_selected_balance_without_switching_account_mode(self):
        session = object.__new__(current_iq.IQOptionReadonly)
        api = FakeAccountAPI()
        session.api = api
        session.connected = True
        session.balance_mode = "PRACTICE"
        with mock.patch.dict(current_iq._state, {"status": "connected"}), \
             mock.patch.object(current_iq, "_bounded_call", side_effect=lambda fn, *a, **k: fn()):
            payload = session.account_balance_readonly()
        self.assertEqual(payload["balance"], 123.45)
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(payload["balance_mode"], "PRACTICE")
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["execution_allowed"])
        self.assertEqual(api.balance_reads, 1)
        self.assertEqual(api.mode_changes, 0)

    def test_endpoint_rejects_missing_or_wrong_bearer_token(self):
        handler, captured = self._handler("Bearer wrong")
        with mock.patch.dict(os.environ, {"IQ_BALANCE_READ_TOKEN": "secret"}):
            handler.do_GET()
        self.assertEqual(captured["code"], 401)
        self.assertEqual(captured["payload"]["error"], "UNAUTHORIZED")
        self.assertEqual(self.fake_session.calls, 0)

    def test_endpoint_returns_balance_only_with_exact_bearer_token(self):
        handler, captured = self._handler("Bearer secret")
        with mock.patch.dict(os.environ, {"IQ_BALANCE_READ_TOKEN": "secret"}):
            handler.do_GET()
        self.assertEqual(captured["code"], 200)
        self.assertEqual(captured["payload"]["balance"], 123.45)
        self.assertTrue(captured["payload"]["read_only"])
        self.assertFalse(captured["payload"]["execution_allowed"])
        self.assertEqual(self.fake_session.calls, 1)

    def test_endpoint_is_disabled_when_no_token_is_configured(self):
        handler, captured = self._handler("Bearer secret")
        with mock.patch.dict(os.environ, {}, clear=True):
            handler.do_GET()
        self.assertEqual(captured["code"], 503)
        self.assertEqual(captured["payload"]["error"], "BALANCE_QUERY_DISABLED")
        self.assertEqual(self.fake_session.calls, 0)


if __name__ == "__main__":
    unittest.main()
