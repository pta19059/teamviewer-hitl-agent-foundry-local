import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from teamviewer_hitl.web import _create_pending, _run_cli, _take_pending, workflow_for_prompt


class WebConsoleTests(unittest.TestCase):
    def test_read_workflow_shows_qwen_host_and_official_mcp_boundary(self) -> None:
        workflow = workflow_for_prompt("List the online TeamViewer devices.")

        self.assertEqual(workflow["operation"], "host_all_devices")
        self.assertFalse(workflow["mutating"])
        self.assertEqual(workflow["arguments"], {"online_state": "Online"})
        self.assertEqual(
            [step["id"] for step in workflow["steps"]],
            ["prompt", "qwen-plan", "host", "mcp", "response"],
        )

    def test_write_workflow_displays_canonical_arguments_and_hitl_step(self) -> None:
        workflow = workflow_for_prompt(
            "Update TeamViewer session code 156827066 with description Customer confirmed."
        )

        self.assertEqual(workflow["operation"], "tv_update_session")
        self.assertTrue(workflow["mutating"])
        self.assertEqual(workflow["arguments"]["session_code"], "s156827066")
        self.assertIn("approval", [step["id"] for step in workflow["steps"]])

    def test_approval_tokens_are_single_use(self) -> None:
        token = _create_pending("Close TeamViewer session code s123.")

        self.assertIsNotNone(_take_pending(token))
        self.assertIsNone(_take_pending(token))

    def test_web_page_contains_command_workflow_and_approval_controls(self) -> None:
        page = Path("src/teamviewer_hitl/web_ui.html").read_text(encoding="utf-8")

        self.assertIn('id="prompt"', page)
        self.assertIn('id="flow"', page)
        self.assertIn('id="approval-dialog"', page)
        self.assertIn("Official MCP only", page)

    @patch("teamviewer_hitl.web.subprocess.run")
    def test_cli_failure_does_not_expose_traceback_to_the_browser(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=["python"],
            returncode=1,
            stdout="",
            stderr="Traceback (most recent call last):\nsecret local path",
        )

        result = _run_cli("Hello")

        self.assertFalse(result["ok"])
        self.assertNotIn("Traceback", result["diagnostics"])
        self.assertNotIn("secret local path", result["diagnostics"])


if __name__ == "__main__":
    unittest.main()
