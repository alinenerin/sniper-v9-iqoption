from __future__ import annotations

import unittest
from tradingagents_committee import TradingAgentsShadowCommittee


class TradingAgentsCommitteeTest(unittest.TestCase):
    def test_committee_never_approves_and_preserves_vetoes(self):
        report = {
            "mode": "read_only",
            "forex": {"analyses": [{
                "symbol": "EURUSD",
                "market": "forex",
                "status": "completed",
                "approved": True,
                "direction": "CALL",
                "components": {
                    "darts": {"status": "inference_ok"},
                    "smc": {"status": "inference_ok"},
                    "finbert": {"status": "blocked"},
                },
            }]},
            "binary": {"analyses": []},
        }
        result = TradingAgentsShadowCommittee().evaluate_report(report)
        item = result["analyses"][0]
        self.assertEqual(item["verdict"], "WATCHLIST")
        self.assertFalse(item["execution_allowed"])
        self.assertTrue(item["read_only"])
        self.assertTrue(item["score_unchanged"])
        self.assertIn("finbert", item["blocked_components"])

    def test_otc_isolates_news_components(self):
        item = {
            "symbol": "EURUSD-OTC",
            "market": "otc",
            "status": "completed",
            "approved": False,
            "direction": "CALL",
            "components": {
                "darts": {"status": "inference_ok"},
                "finbert": {"status": "inference_ok"},
                "news_api": {"status": "inference_ok"},
            },
        }
        result = TradingAgentsShadowCommittee().evaluate(item)
        self.assertEqual(result["verdict"], "REJECTED")
        self.assertTrue(result["otc_news_isolated"])
        self.assertFalse(result["execution_allowed"])


if __name__ == "__main__":
    unittest.main()
