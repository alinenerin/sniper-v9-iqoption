from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime_agent_registry import evidence_manifest
from scripts.generate_scan_report import _agent_dashboard


class RuntimeAgentRegistryTest(unittest.TestCase):
    def test_manifest_distinguishes_fused_advisory_and_blocked_agents(self):
        manifest = evidence_manifest({
            "smc": {"status": "inference_ok", "role": "fused", "snapshot_id": "snap-a"},
            "news": {"status": "completed", "role": "advisory_only", "snapshot_id": "snap-a"},
            "lse": {"status": "blocked", "role": "advisory_only", "reason": "HTTP_502", "snapshot_id": "snap-a"},
        })
        agents = manifest["agents"]
        self.assertEqual(agents["smc"]["state"], "executed_and_fused")
        self.assertEqual(agents["news"]["state"], "executed_advisory_only")
        self.assertEqual(agents["lse"]["state"], "declared_or_blocked")
        self.assertEqual(agents["lse"]["reason"], "HTTP_502")
        self.assertEqual(manifest["market_snapshot_id"], "snap-a")
        self.assertTrue(manifest["snapshot_consistent"])
        self.assertFalse(manifest["execution_allowed"])
        self.assertFalse(manifest["executor_enabled"])

    def test_manifest_does_not_claim_one_snapshot_for_mixed_evidence(self):
        manifest = evidence_manifest({
            "smc": {"status": "inference_ok", "snapshot_id": "snap-a"},
            "vsa": {"status": "inference_ok", "snapshot_id": "snap-b"},
        })
        self.assertIsNone(manifest["market_snapshot_id"])
        self.assertFalse(manifest["snapshot_consistent"])

    def test_executed_evidence_without_snapshot_is_not_consistent(self):
        manifest = evidence_manifest({"smc": {"status": "inference_ok", "role": "fused"}})
        self.assertIsNone(manifest["market_snapshot_id"])
        self.assertFalse(manifest["snapshot_consistent"])

    def test_dashboard_is_derived_from_manifest_states(self):
        analysis = {
            "symbol": "EURUSD",
            "market": "forex",
            "score": 82,
            "approved": False,
            "vetoes": ["STALE_DATA"],
            "evidence_manifest": evidence_manifest({
                "smc": {"status": "inference_ok", "role": "fused"},
                "finbert": {"status": "blocked", "role": "advisory_only", "reason": "NO_NEWS"},
            }),
        }
        dashboard = _agent_dashboard([analysis], "forex")
        row = dashboard["analyses"][0]
        self.assertEqual(row["specialists_executed"], ["smc"])
        self.assertEqual(row["specialists_blocked"], ["finbert"])
        self.assertFalse(row["execution_allowed"])
        self.assertEqual(dashboard["specialist_names"], ["finbert", "smc"])


if __name__ == "__main__":
    unittest.main()
