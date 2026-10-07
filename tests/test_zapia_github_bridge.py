from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from zapia_github_bridge import GitHubScanBridge


class GitHubBridgeRunSelectionTest(unittest.TestCase):
    def test_run_after_uses_utc_and_matches_dispatched_branch(self):
        dispatched_at = datetime(2026, 10, 7, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "workflow_runs": [
                {
                    "id": 10,
                    "created_at": "2026-10-07T08:00:02Z",
                    "event": "workflow_dispatch",
                    "head_branch": "other-branch",
                },
                {
                    "id": 11,
                    "created_at": "2026-10-07T08:00:03Z",
                    "event": "workflow_dispatch",
                    "head_branch": "main",
                },
            ]
        }
        bridge = GitHubScanBridge(token="test-token")
        bridge.session.get = Mock(return_value=response)

        with patch("zapia_github_bridge.time.time", return_value=dispatched_at + 1), \
             patch("zapia_github_bridge.time.mktime", side_effect=AssertionError("local-time conversion used")):
            run = bridge.run_after(dispatched_at, timeout_seconds=30, ref="main")

        self.assertEqual(run["id"], 11)
        bridge.session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
