import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_framework import Content, Message

from teamviewer_hitl.agent import (
    AgentRuntime,
    InvocationGuard,
    _clean_model_text,
    run_turn,
)
from teamviewer_hitl.routing import route_prompt


class _FakeAgent:
    def __init__(self, *results) -> None:
        self.calls = []
        self._results = list(results)

    async def run(
        self,
        value,
        *,
        session,
        tools=None,
        options=None,
        middleware=None,
    ):
        self.calls.append(
            {
                "value": value,
                "session": session,
                "tools": tools,
                "options": options,
                "middleware": middleware,
            }
        )
        result = self._results.pop(0)
        if getattr(result, "guard_attempted", False):
            for item in middleware or []:
                item.attempted = True
        return result


def _result(*, requests=(), text="", guard_attempted=False):
    return SimpleNamespace(
        user_input_requests=list(requests),
        text=text,
        guard_attempted=guard_attempted,
    )


def _runtime(tool_name: str, *results) -> tuple[AgentRuntime, _FakeAgent, object]:
    fake_agent = _FakeAgent(*results)
    selected = SimpleNamespace(name=tool_name)
    return AgentRuntime(fake_agent, {tool_name: selected}), fake_agent, selected


class ApprovalLoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.audit_path = Path(".tmp/test-approval-audit.jsonl")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path.unlink(missing_ok=True)
        self.settings = SimpleNamespace(
            audit_path=self.audit_path,
            operator_id="operator@example.com",
        )

    def tearDown(self) -> None:
        self.audit_path.unlink(missing_ok=True)

    async def test_approved_call_uses_only_the_routed_tool_and_is_audited(self) -> None:
        function_call = Content.from_function_call(
            "call-1",
            "tv_create_session",
            arguments={"description": "Help Alice", "groupid": "g12345678"},
        )
        request = Content.from_function_approval_request("approval-1", function_call)
        runtime, fake_agent, selected = _runtime(
            "tv_create_session",
            _result(requests=[request]),
            _result(text="completed", guard_attempted=True),
        )

        prompt = (
            "Create a TeamViewer support session with description Help Alice "
            "in group ID g12345678."
        )
        with patch("builtins.input", return_value="APPROVE"):
            result = await run_turn(runtime, object(), prompt, self.settings)

        self.assertEqual(result, "completed")
        self.assertEqual(fake_agent.calls[0]["tools"], [selected])
        self.assertEqual(
            fake_agent.calls[0]["options"],
            {
                "tool_choice": {
                    "mode": "required",
                    "required_function_name": "tv_create_session",
                },
                "allow_multiple_tool_calls": False,
            },
        )

        continuation = fake_agent.calls[1]
        self.assertIsInstance(continuation["value"], Message)
        self.assertTrue(continuation["value"].contents[0].approved)
        self.assertEqual(continuation["tools"], [selected])
        self.assertEqual(
            continuation["options"],
            {"tool_choice": "none", "allow_multiple_tool_calls": False},
        )

        event = json.loads(self.audit_path.read_text(encoding="utf-8"))
        self.assertTrue(event["approved"])
        self.assertEqual(event["tool"], "tv_create_session")

    async def test_any_response_other_than_exact_approve_rejects(self) -> None:
        function_call = Content.from_function_call(
            "call-2",
            "tv_update_session",
            arguments={"session_code": "s123", "description": "Escalated case"},
        )
        request = Content.from_function_approval_request("approval-2", function_call)
        runtime, fake_agent, _ = _runtime(
            "tv_update_session",
            _result(requests=[request]),
            _result(text="model text must be ignored"),
        )

        prompt = "Update TeamViewer session code s123 description to Escalated case."
        with patch("builtins.input", return_value="yes"):
            result = await run_turn(runtime, object(), prompt, self.settings)

        self.assertEqual(result, "Rejected. No TeamViewer operation was executed.")
        continuation = fake_agent.calls[1]["value"]
        self.assertFalse(continuation.contents[0].approved)
        event = json.loads(self.audit_path.read_text(encoding="utf-8"))
        self.assertFalse(event["approved"])

    async def test_wrong_write_tool_is_rejected_before_approval(self) -> None:
        function_call = Content.from_function_call(
            "call-3", "tv_activate_monitoring", arguments={"teamviewer_id": 987654321}
        )
        request = Content.from_function_approval_request("approval-3", function_call)
        runtime, fake_agent, _ = _runtime(
            "tv_delete_session",
            _result(requests=[request]),
            _result(text="ignored"),
        )

        with patch("builtins.input") as approval_input:
            result = await run_turn(
                runtime,
                object(),
                "Close TeamViewer session s123.",
                self.settings,
            )

        self.assertIn("does not match the deterministic route", result)
        self.assertIn("No TeamViewer operation was executed", result)
        approval_input.assert_not_called()
        self.assertFalse(fake_agent.calls[1]["value"].contents[0].approved)

    async def test_missing_write_arguments_are_rejected_before_approval(self) -> None:
        function_call = Content.from_function_call(
            "call-4", "tv_create_session", arguments={}
        )
        request = Content.from_function_approval_request("approval-4", function_call)
        runtime, _, _ = _runtime(
            "tv_create_session",
            _result(requests=[request]),
            _result(text="ignored"),
        )

        with patch("builtins.input") as approval_input:
            result = await run_turn(
                runtime,
                object(),
                "Create a TeamViewer support session with description Help Alice "
                "in group ID g12345678.",
                self.settings,
            )

        self.assertIn("Missing required argument(s): description", result)
        approval_input.assert_not_called()

    async def test_create_without_group_never_reaches_model_or_mcp(self) -> None:
        runtime, fake_agent, _ = _runtime("tv_create_session")

        result = await run_turn(
            runtime,
            object(),
            "Create a TeamViewer support session named HITL-Test.",
            self.settings,
        )

        self.assertIn("exactly one existing legacy", result)
        self.assertIn("No TeamViewer operation was executed", result)
        self.assertEqual(fake_agent.calls, [])

    async def test_approved_result_cannot_claim_execution_if_guard_never_ran(self) -> None:
        function_call = Content.from_function_call(
            "call-5",
            "tv_create_session",
            arguments={"description": "Help Alice", "groupid": "g12345678"},
        )
        request = Content.from_function_approval_request("approval-5", function_call)
        runtime, _, _ = _runtime(
            "tv_create_session",
            _result(requests=[request]),
            _result(text="invented success"),
        )

        with patch("builtins.input", return_value="APPROVE"):
            result = await run_turn(
                runtime,
                object(),
                "Create a TeamViewer support session with description Help Alice "
                "in group ID g12345678.",
                self.settings,
            )

        self.assertEqual(result, "The approved TeamViewer MCP operation was not executed.")

    async def test_second_operation_from_same_prompt_is_rejected(self) -> None:
        first_call = Content.from_function_call(
            "call-6",
            "tv_create_session",
            arguments={"description": "Help Alice", "groupid": "g12345678"},
        )
        first_request = Content.from_function_approval_request("approval-6", first_call)
        second_call = Content.from_function_call(
            "call-7",
            "tv_create_session",
            arguments={"description": "Help Alice", "groupid": "g12345678"},
        )
        second_request = Content.from_function_approval_request("approval-7", second_call)
        runtime, fake_agent, _ = _runtime(
            "tv_create_session",
            _result(requests=[first_request]),
            _result(requests=[second_request], guard_attempted=True),
            _result(text="settled"),
        )

        with patch("builtins.input", return_value="APPROVE") as approval_input:
            result = await run_turn(
                runtime,
                object(),
                "Create a TeamViewer support session with description Help Alice "
                "in group ID g12345678.",
                self.settings,
            )

        self.assertIn("additional operation was rejected", result)
        approval_input.assert_called_once()
        self.assertFalse(fake_agent.calls[2]["value"].contents[0].approved)

    async def test_write_middleware_cannot_execute_without_host_approval_binding(self) -> None:
        prompt = (
            "Create a TeamViewer support session with description Help Alice "
            "in group ID g12345678."
        )
        guard = InvocationGuard(route_prompt(prompt), prompt)
        context = SimpleNamespace(
            function=SimpleNamespace(name="tv_create_session"),
            arguments={"description": "Help Alice", "groupid": "g12345678"},
            result=None,
        )
        called = False

        async def call_next():
            nonlocal called
            called = True

        await guard.process(context, call_next)

        self.assertFalse(called)
        self.assertIn("No human-approved call", guard.blocked_message or "")

    async def test_call_changed_after_approval_is_blocked(self) -> None:
        prompt = (
            "Create a TeamViewer support session with description Help Alice "
            "in group ID g12345678."
        )
        guard = InvocationGuard(route_prompt(prompt), prompt)
        guard.bind_approved_call(
            "tv_create_session",
            {"description": "Help Alice", "groupid": "g12345678"},
        )
        context = SimpleNamespace(
            function=SimpleNamespace(name="tv_create_session"),
            arguments={"description": "Tampered value", "groupid": "g12345678"},
            result=None,
        )
        called = False

        async def call_next():
            nonlocal called
            called = True

        await guard.process(context, call_next)

        self.assertFalse(called)
        self.assertIn("changed after human approval", guard.blocked_message or "")

    async def test_mcp_exception_detail_is_not_retained_for_operator_output(self) -> None:
        prompt = "Show my TeamViewer account summary."
        guard = InvocationGuard(route_prompt(prompt), prompt)
        context = SimpleNamespace(
            function=SimpleNamespace(name="tv_get_account"),
            arguments={},
            result=None,
        )

        async def call_next():
            raise RuntimeError("TEAMVIEWER_API_TOKEN=do-not-display")

        await guard.process(context, call_next)

        self.assertEqual(guard.execution_error, "RuntimeError")
        self.assertNotIn("do-not-display", guard.execution_error)

    async def test_conversation_has_no_model_visible_tools(self) -> None:
        runtime, fake_agent, _ = _runtime("tv_get_account", _result(text="Hello!"))

        result = await run_turn(runtime, object(), "Hello", self.settings)

        self.assertEqual(result, "Hello!")
        self.assertEqual(fake_agent.calls[0]["tools"], [])
        self.assertEqual(
            fake_agent.calls[0]["options"],
            {"tool_choice": "none", "allow_multiple_tool_calls": False},
        )

    async def test_read_request_exposes_only_the_exact_routed_tool(self) -> None:
        runtime, fake_agent, selected = _runtime(
            "tv_get_account", _result(text="account evidence", guard_attempted=True)
        )

        result = await run_turn(
            runtime, object(), "Show my account summary.", self.settings
        )

        self.assertEqual(result, "account evidence")
        self.assertEqual(fake_agent.calls[0]["tools"], [selected])
        self.assertEqual(
            fake_agent.calls[0]["options"]["tool_choice"]["required_function_name"],
            "tv_get_account",
        )

    async def test_provider_cannot_return_ungrounded_read_text(self) -> None:
        runtime, _, _ = _runtime(
            "tv_get_account", _result(text="invented account evidence")
        )

        result = await run_turn(
            runtime, object(), "Show my account summary.", self.settings
        )

        self.assertIn("MCP read was not executed", result)
        self.assertNotIn("invented account evidence", result)

    async def test_ambiguous_multi_write_prompt_makes_no_agent_call(self) -> None:
        runtime, fake_agent, _ = _runtime("tv_create_session")

        result = await run_turn(
            runtime,
            object(),
            "Create a TeamViewer session and close TeamViewer session s123.",
            self.settings,
        )

        self.assertIn("one TeamViewer operation", result)
        self.assertIn("No TeamViewer operation was executed", result)
        self.assertEqual(fake_agent.calls, [])

    def test_raw_foundry_tool_call_marker_is_not_shown_to_the_operator(self) -> None:
        text = (
            '<|tool_call|>[{"name":"tv_get_account","parameters":{}}]'
            "<|/tool_call|>Observed facts"
        )
        self.assertEqual(_clean_model_text(text), "Observed facts")


if __name__ == "__main__":
    unittest.main()
