import unittest

from gateway_health import connection_is_ready, liveness_payload, readiness_payload


class GatewayHealthContractTests(unittest.TestCase):
    def test_liveness_stays_ok_when_upstream_is_disconnected(self):
        connection = {"status": "disconnected", "reason": "upstream_unavailable"}
        payload = liveness_payload(connection)
        self.assertEqual(payload["liveness"], "ok")
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "disconnected")
        self.assertEqual(payload["connection"], connection)

    def test_readiness_requires_connected_upstream(self):
        self.assertTrue(connection_is_ready({"status": "connected"}))
        self.assertFalse(connection_is_ready({"status": "connecting"}))
        self.assertFalse(connection_is_ready({"status": "disconnected"}))
        self.assertFalse(connection_is_ready(None))

    def test_readiness_payload_reports_disconnected_state(self):
        payload = readiness_payload({"status": "disconnected"})
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "disconnected")

    def test_readiness_payload_reports_connected_state(self):
        payload = readiness_payload({"status": "connected"})
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "connected")


if __name__ == "__main__":
    unittest.main()
