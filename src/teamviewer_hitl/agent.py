"""Microsoft Agent Framework and TeamViewer MCP composition."""

from __future__ import annotations

import json
import os
import re
import subprocess
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from agent_framework import Agent, MCPStdioTool, MCPStreamableHTTPTool, Message
from agent_framework.foundry import FoundryChatClient
from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity import AzureCliCredential

from .audit import record_decision
from .config import Settings
from .policy import ALLOWED_TOOLS, MCP_APPROVAL_MODE, validate_policy
from .mcp_compositions import list_devices_in_managed_group

AGENT_INSTRUCTIONS = """
You are a careful TeamViewer service-desk assistant.

Use TeamViewer tools to investigate devices, monitoring alarms, sessions, and reports. Start with
read-only evidence and clearly distinguish observed facts from suggestions. Never claim that an
action completed unless the tool returned success. Before a state-changing action, explain the
target and expected effect in one concise sentence; the host application will independently ask
the operator for approval. A rejection is final for that call: acknowledge it and offer a safe
alternative. Never ask for, display, or store passwords, API tokens, client secrets, or unattended
access credentials. Do not infer a device ID when more than one device matches a name.

TeamViewer has separate legacy "Computers & Contacts" groups and newer managed device groups.
When the user names a managed group, use tv_list_devices_in_managed_group and pass the exact group
name. Do not use tv_list_devices for a managed-group request. Never claim that a device belongs to
a group unless the tool result explicitly contains the verified group and device list.
For managed-group availability, reproduce the tool's availability text exactly: the API cannot
distinguish a Sleeping device from an Offline device when its isOnline value is false.
When tv_list_devices_in_managed_group returns status "ok", enumerate every device returned by the
tool with its name, TeamViewer ID, and availability. Do not omit entries, add recommendations, or
replace the list with a count unless the user explicitly requests a summary.
""".strip()

_TOOL_CALL_MARKER = re.compile(r"<\|tool_call\|>.*?<\|/tool_call\|>\s*", re.DOTALL)


def _create_managed_group_device_tool(teamviewer: Any):
    async def tv_list_devices_in_managed_group(group_name: str) -> dict[str, Any]:
        """List an exact managed group's devices using only official TeamViewer MCP tools."""
        return await list_devices_in_managed_group(teamviewer, group_name)

    return tv_list_devices_in_managed_group


def _clean_model_text(text: str) -> str:
    """Remove provider-specific raw tool-call markers from user-facing output."""
    return _TOOL_CALL_MARKER.sub("", text).strip()


def discover_foundry_local_endpoint(configured_endpoint: str | None = None) -> str:
    """Return the loopback OpenAI endpoint exposed by the current Foundry Local CLI."""
    endpoint = configured_endpoint
    if endpoint is None:
        try:
            completed = subprocess.run(
                ["foundry", "server", "status", "-o", "json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            status = json.loads(completed.stdout)
            urls = status.get("webUrls", [])
            if not status.get("running") or not urls:
                raise RuntimeError("Foundry Local server is not ready")
            endpoint = str(urls[0])
        except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError, RuntimeError) as exc:
            raise RuntimeError(
                "Could not discover Foundry Local. Run 'foundry server start', or set "
                "FOUNDRY_LOCAL_ENDPOINT to the loopback URL shown by 'foundry server status'."
            ) from exc

    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("FOUNDRY_LOCAL_ENDPOINT must be an HTTP loopback URL")

    endpoint = endpoint.rstrip("/")
    return endpoint if endpoint.endswith("/v1") else f"{endpoint}/v1"


@asynccontextmanager
async def open_teamviewer_mcp(settings: Settings) -> AsyncIterator[Any]:
    """Open the configured, capability-limited TeamViewer MCP connection."""
    validate_policy()
    common = {
        "name": "TeamViewer service desk",
        "description": "Approved TeamViewer investigation and remote-support operations",
        "allowed_tools": ALLOWED_TOOLS,
        "approval_mode": MCP_APPROVAL_MODE,
        "load_prompts": False,
    }

    if settings.transport == "local":
        assert settings.mcp_script is not None
        assert settings.mcp_command is not None
        assert settings.teamviewer_api_token is not None
        child_env = dict(os.environ)
        child_env["TEAMVIEWER_API_TOKEN"] = settings.teamviewer_api_token
        tool = MCPStdioTool(
            **common,
            command=settings.mcp_command,
            args=[str(settings.mcp_script)],
            env=child_env,
        )
    else:
        assert settings.mcp_url is not None
        if settings.mcp_bearer_token:
            bearer_token = settings.mcp_bearer_token

            def header_provider(_kwargs: dict[str, Any]) -> dict[str, str]:
                return {"Authorization": f"Bearer {bearer_token}"}

        else:
            header_provider = None
        tool = MCPStreamableHTTPTool(
            **common, url=settings.mcp_url, header_provider=header_provider
        )

    async with tool:
        yield tool


def _format_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
    return json.dumps(arguments, indent=2, ensure_ascii=False, default=str)


def _ask_for_approval(tool_name: str, arguments: Any) -> bool:
    print("\n--- HUMAN APPROVAL REQUIRED ---")
    print(f"Tool: {tool_name}")
    print("Arguments:")
    print(_format_arguments(arguments))
    print("Type APPROVE to execute this exact call. Any other response rejects it.")
    return input("Decision: ").strip() == "APPROVE"


async def run_turn(agent: Agent, session: Any, prompt: str, settings: Settings) -> str:
    """Run one conversational turn, pausing for every approval-required tool call."""
    result = await agent.run(prompt, session=session)

    while result.user_input_requests:
        responses = []
        for request in result.user_input_requests:
            function_call = request.function_call
            if function_call is None:
                raise RuntimeError("The agent requested unsupported non-tool human input")

            approved = _ask_for_approval(function_call.name, function_call.arguments)
            record_decision(
                settings.audit_path,
                operator_id=settings.operator_id,
                tool_name=function_call.name,
                arguments=function_call.arguments,
                approved=approved,
            )
            responses.append(request.to_function_approval_response(approved=approved))

        result = await agent.run(Message(role="user", contents=responses), session=session)

    return _clean_model_text(result.text)


@asynccontextmanager
async def open_agent(settings: Settings) -> AsyncIterator[Agent]:
    """Create the Foundry-backed agent and its TeamViewer MCP toolset."""
    credential = None
    try:
        async with open_teamviewer_mcp(settings) as teamviewer:
            if settings.model_provider == "foundry_local":
                assert settings.foundry_local_model is not None
                client = OpenAIChatCompletionClient(
                    model=settings.foundry_local_model,
                    base_url=discover_foundry_local_endpoint(settings.foundry_local_endpoint),
                    api_key="not-needed",
                )
            else:
                assert settings.foundry_project_endpoint is not None
                assert settings.foundry_model is not None
                credential = AzureCliCredential()
                client = FoundryChatClient(
                    project_endpoint=settings.foundry_project_endpoint,
                    model=settings.foundry_model,
                    credential=credential,
                )
            tools: list[Any] = [teamviewer, _create_managed_group_device_tool(teamviewer)]

            async with Agent(
                client=client,
                name="TeamViewerServiceDesk",
                instructions=AGENT_INSTRUCTIONS,
                tools=tools,
                # Phi-4-mini on Foundry Local can describe an available tool instead of
                # emitting a structured call when selection is left on "auto". Requiring
                # the first call keeps service-desk answers grounded in TeamViewer data.
                # Agent Framework resets "required" after that call so the model can
                # produce a normal final response.
                default_options=(
                    {"tool_choice": "required"}
                    if settings.model_provider == "foundry_local"
                    else None
                ),
            ) as agent:
                yield agent
    finally:
        if credential is not None:
            credential.close()
