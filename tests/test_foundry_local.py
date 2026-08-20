import json
import subprocess
import unittest
from unittest.mock import patch

from teamviewer_hitl.agent import discover_foundry_local_endpoint


class FoundryLocalEndpointTests(unittest.TestCase):
    def test_accepts_loopback_override_and_adds_v1(self) -> None:
        self.assertEqual(
            discover_foundry_local_endpoint("http://127.0.0.1:58893"),
            "http://127.0.0.1:58893/v1",
        )

    def test_rejects_non_loopback_override(self) -> None:
        with self.assertRaises(ValueError):
            discover_foundry_local_endpoint("https://example.com")

    @patch("teamviewer_hitl.agent.subprocess.run")
    def test_discovers_current_cli_server_url(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {"running": True, "state": "ready", "webUrls": ["http://127.0.0.1:60000"]}
            ),
            stderr="",
        )
        self.assertEqual(discover_foundry_local_endpoint(), "http://127.0.0.1:60000/v1")

    @patch("teamviewer_hitl.agent.subprocess.run")
    def test_accepts_advertised_url_when_cli_running_flag_is_stale(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "running": False,
                    "state": "not_running",
                    "webUrls": ["http://127.0.0.1:62911"],
                }
            ),
            stderr="",
        )
        self.assertEqual(discover_foundry_local_endpoint(), "http://127.0.0.1:62911/v1")


if __name__ == "__main__":
    unittest.main()
