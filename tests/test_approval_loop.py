import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_framework import Content, Message

from teamviewer_hitl.agent import run_turn


class _FakeAgent:
    def __init__(self, request: Content) -> None:
        self.inputs = []
        self._results = [
            SimpleNamespace(user_input_requests=[request], text=""),
            SimpleNamespace(user_input_requests=[], text="completed"),
        ]

    async def run(self, value, *, session):
        self.inputs.append((value, session))
        return self._results.pop(0)


class ApprovalLoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.audit_path = Path(".tmp/test-approval-audit.jsonl")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path.unlink(missing_ok=True)

    def tearDown(self) -> None:
        self.audit_path.unlink(missing_ok=True)

    async def test_approved_call_is_returned_to_agent_and_audited(self) -> None:
        function_call = Content.from_function_call(
            "call-1", "tv_create_session", arguments={"name": "Help Alice"}
        )
        request = Content.from_function_approval_request("approval-1", function_call)
        fake_agent = _FakeAgent(request)

        settings = SimpleNamespace(
            audit_path=self.audit_path, operator_id="operator@example.com"
        )
        with patch("builtins.input", return_value="APPROVE"):
            result = await run_turn(fake_agent, object(), "Create a session", settings)

        self.assertEqual(result, "completed")
        continuation = fake_agent.inputs[1][0]
        self.assertIsInstance(continuation, Message)
        self.assertTrue(continuation.contents[0].approved)

        event = json.loads(self.audit_path.read_text(encoding="utf-8"))
        self.assertTrue(event["approved"])
        self.assertEqual(event["tool"], "tv_create_session")

    async def test_approval_is_exact_and_defaults_to_rejection(self) -> None:
        function_call = Content.from_function_call(
            "call-2", "tv_update_session", arguments={"code": "s123"}
        )
        request = Content.from_function_approval_request("approval-2", function_call)
        fake_agent = _FakeAgent(request)

        settings = SimpleNamespace(
            audit_path=self.audit_path, operator_id="operator@example.com"
        )
        with patch("builtins.input", return_value="yes"):
            await run_turn(fake_agent, object(), "Update the session", settings)

        continuation = fake_agent.inputs[1][0]
        self.assertFalse(continuation.contents[0].approved)


if __name__ == "__main__":
    unittest.main()
