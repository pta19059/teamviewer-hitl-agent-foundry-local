import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from agent_framework import (
    Agent,
    BaseChatClient,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
)

from teamviewer_hitl.agent import AgentRuntime, run_turn
from teamviewer_hitl.write_tools import create_mcp_write_tools


class _ScriptedChatClient(FunctionInvocationLayer, BaseChatClient):
    def __init__(self) -> None:
        super().__init__(
            function_invocation_configuration={
                "max_function_calls": 1,
                "terminate_on_unknown_calls": True,
            }
        )
        self.model_calls = 0

    async def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> ChatResponse:
        self.assert_not_streaming(stream)
        self.model_calls += 1
        if self.model_calls == 1:
            call = Content.from_function_call(
                "call-1",
                "tv_create_session",
                arguments={"description": "HITL-Test"},
            )
            return ChatResponse(messages=[Message(role="assistant", contents=[call])])
        return ChatResponse(messages=[Message(role="assistant", contents=["completed"])])

    @staticmethod
    def assert_not_streaming(stream: bool) -> None:
        if stream:
            raise AssertionError("The integration test does not use streaming")


class _RecordingMCP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, **arguments: Any) -> str:
        self.calls.append((name, arguments))
        return '{"code":"s123"}'


class AgentFrameworkApprovalIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.audit_path = Path(".tmp/test-framework-integration-audit.jsonl")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path.unlink(missing_ok=True)
        self.settings = SimpleNamespace(
            audit_path=self.audit_path,
            operator_id="operator@example.com",
        )
        self.prompt = (
            "Create a TeamViewer support session with description HITL-Test."
        )

    def tearDown(self) -> None:
        self.audit_path.unlink(missing_ok=True)

    async def _run_with_decision(self, decision: str):
        mcp = _RecordingMCP()
        create_tool = {
            item.name: item for item in create_mcp_write_tools(mcp)
        }["tv_create_session"]
        client = _ScriptedChatClient()

        async with Agent(client=client, instructions="test", tools=[]) as agent:
            runtime = AgentRuntime(agent=agent, tools={create_tool.name: create_tool})
            session = agent.create_session()

            def decide(_message: str) -> str:
                self.assertEqual(mcp.calls, [], "MCP write occurred before approval")
                return decision

            with patch("builtins.input", side_effect=decide):
                result = await run_turn(runtime, session, self.prompt, self.settings)
        return result, mcp, client

    async def test_real_framework_executes_exactly_once_after_approval(self) -> None:
        result, mcp, client = await self._run_with_decision("APPROVE")

        self.assertEqual(result, "completed")
        self.assertEqual(
            mcp.calls,
            [("tv_create_session", {"description": "HITL-Test"})],
        )
        self.assertEqual(client.model_calls, 2)

    async def test_real_framework_executes_zero_times_after_rejection(self) -> None:
        result, mcp, client = await self._run_with_decision("REJECT")

        self.assertEqual(result, "Rejected. No TeamViewer operation was executed.")
        self.assertEqual(mcp.calls, [])
        self.assertEqual(client.model_calls, 2)


if __name__ == "__main__":
    unittest.main()
