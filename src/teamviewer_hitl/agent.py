"""Microsoft Agent Framework and TeamViewer MCP composition."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Final
from urllib.parse import urlparse

from agent_framework import (
    Agent,
    FunctionInvocationContext,
    FunctionMiddleware,
    MCPStdioTool,
    MCPStreamableHTTPTool,
    Message,
)
from agent_framework.foundry import FoundryChatClient
from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity import AzureCliCredential

from .audit import record_decision
from .config import Settings
from .mcp_compositions import list_devices_across_namespaces, list_devices_in_group
from .policy import (
    ALLOWED_TOOLS,
    APPROVAL_REQUIRED_TOOLS,
    MCP_APPROVAL_MODE,
    READ_ONLY_TOOLS,
    validate_policy,
)
from .read_tools import create_mcp_read_tools
from .routing import IntentRoute, RouteOutcome, route_prompt
from .validation import arguments_to_dict, validate_invocation
from .write_tools import create_mcp_write_tools


logger = logging.getLogger(__name__)

AGENT_INSTRUCTIONS = """
You are a careful TeamViewer service-desk assistant.

Use TeamViewer tools to investigate devices, monitoring alarms, sessions, and reports. Start with
read-only evidence and clearly distinguish observed facts from suggestions. Never claim that an
action completed unless the tool returned success. Before a state-changing action, explain the
target and expected effect in one concise sentence; the host application will independently ask
the operator for approval. A rejection is final for that call: acknowledge it and offer a safe
alternative. Never ask for, display, or store passwords, API tokens, client secrets, or unattended
access credentials. Do not infer a device ID when more than one device matches a name.
The host supplies only the tool selected by its deterministic route. Do not substitute a different
operation. When no tool is available, do not claim to have read current TeamViewer data.

TeamViewer has separate legacy "Computers & Contacts" groups and newer managed device groups.
Named-group device lookup is resolved deterministically by the host using only official TeamViewer
MCP operations. A request to create a TeamViewer support session is not a group request. Never
claim that a device belongs to a group unless an official MCP result explicitly contains the
verified group and device list.
Creating a support session requires exactly one explicit legacy Computers & Contacts group ID.
Never substitute a managed-device group, and never omit or invent the create-session group ID.
Session creation supports only description and group ID. Session updates support only description.
Hardware, system, and software inventory tools use the monitored device's numeric TeamViewer ID.
Connection-report IDs are UUIDs. Never substitute a short display ID or device ID.
For managed-group availability, reproduce the tool's availability text exactly: the API cannot
distinguish a Sleeping device from an Offline device when its isOnline value is false.
""".strip()

_TOOL_CALL_MARKER = re.compile(
    r"(?:<\|tool_call\|>.*?<\|/tool_call\|>|<tool_call>.*?</tool_call>)\s*",
    re.DOTALL,
)
_MCP_ADDITIONAL_TOOL_ARGUMENT_NAMES: Final[dict[str, tuple[str, ...]]] = {
    # The pinned official MCP handler forwards this required TeamViewer API field,
    # but its advertised inputSchema omits it. Scope the framework exception to
    # this one remote tool so no unrelated model argument can cross MCP.
    "tv_create_session": ("groupid",),
    # The report handlers forward arbitrary query arguments, but their schemas omit
    # the current API's UUID pagination cursor.
    "tv_list_connection_reports": ("offset_id",),
    "tv_list_device_reports": ("offset_id",),
}


@dataclass(slots=True)
class AgentRuntime:
    """Connected agent plus the exact per-run tool registry."""

    agent: Agent
    tools: dict[str, Any]
    teamviewer: Any | None = None


class InvocationGuard(FunctionMiddleware):
    """Block mismatched or untrusted arguments before an MCP call executes."""

    def __init__(self, route: IntentRoute, prompt: str) -> None:
        self.route = route
        self.prompt = prompt
        self.blocked_message: str | None = None
        self.execution_error: str | None = None
        self.attempted = False
        self.invocation_count = 0
        self.approved_call_fingerprint: str | None = None

    @staticmethod
    def _fingerprint(function_name: str, arguments: dict[str, Any]) -> str:
        return json.dumps(
            {"tool": function_name, "arguments": arguments},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )

    def bind_approved_call(self, function_name: str, arguments: dict[str, Any]) -> None:
        """Bind execution to the exact call the operator approved."""
        self.approved_call_fingerprint = self._fingerprint(function_name, arguments)

    async def process(self, context: FunctionInvocationContext, call_next) -> None:
        self.attempted = True
        self.invocation_count += 1
        if self.invocation_count > 1:
            self.blocked_message = "Only one TeamViewer operation is allowed per prompt."
            context.result = {"status": "blocked", "message": self.blocked_message}
            return
        arguments = arguments_to_dict(context.arguments)
        if self.route.mutating:
            if self.approved_call_fingerprint is None:
                self.blocked_message = "No human-approved call is bound for execution."
                context.result = {"status": "blocked", "message": self.blocked_message}
                return
            current_fingerprint = self._fingerprint(context.function.name, arguments)
            if current_fingerprint != self.approved_call_fingerprint:
                self.blocked_message = "The call changed after human approval."
                context.result = {"status": "blocked", "message": self.blocked_message}
                return
        error = validate_invocation(
            self.route,
            self.prompt,
            context.function.name,
            arguments,
        )
        if error:
            self.blocked_message = error
            context.result = {"status": "blocked", "message": error}
            return
        try:
            await call_next()
        except Exception as exc:
            self.execution_error = type(exc).__name__
            context.result = {
                "status": "error",
                "message": "The TeamViewer MCP operation failed in the host.",
            }


def _clean_model_text(text: str) -> str:
    """Remove provider-specific raw tool-call markers from user-facing output."""
    return _TOOL_CALL_MARKER.sub("", text).strip()


def _device_value(device: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = device.get(key)
        if value not in (None, ""):
            return value
    return None


def _format_group_devices(result: dict[str, Any]) -> str:
    """Render verified MCP group membership without model rewriting."""
    status = result.get("status")
    if status == "not_found":
        return "No TeamViewer group matched the requested name exactly."
    if status == "ambiguous":
        matches = result.get("matches", [])
        lines = ["More than one TeamViewer group matched that exact name:"]
        for match in matches if isinstance(matches, list) else []:
            if isinstance(match, dict):
                lines.append(
                    f"- {match.get('namespace', 'unknown')}: "
                    f"{match.get('name', 'Unnamed')} (ID: {match.get('id', 'unknown')})"
                )
        lines.append("Specify the legacy or managed group namespace.")
        return "\n".join(lines)
    if status not in {"ok", "partial"}:
        return "The official TeamViewer MCP group lookup returned no usable result."

    group = result.get("group") if isinstance(result.get("group"), dict) else {}
    devices = result.get("devices") if isinstance(result.get("devices"), list) else []
    namespace = result.get("groupNamespace", "unknown")
    lines = [
        f"Group: {group.get('name', 'Unnamed')} (ID: {group.get('id', 'unknown')}, "
        f"namespace: {namespace})",
        f"Devices: {len(devices)}",
    ]
    if status == "partial":
        failures = result.get("failedMembershipChecks")
        failure_count = len(failures) if isinstance(failures, list) else 0
        lines.append(
            "Warning: membership verification was incomplete for "
            f"{failure_count} company-managed device(s) after bounded retries. "
            "Only devices whose membership was verified through MCP are shown."
        )
    for device in devices:
        if not isinstance(device, dict):
            continue
        name = _device_value(device, "name", "alias") or "Unnamed"
        teamviewer_id = _device_value(
            device, "teamviewerId", "teamviewer_id", "remotecontrol_id"
        )
        local_id = _device_value(device, "id", "device_id")
        availability = _device_value(
            device, "availability", "online_state", "onlineState"
        )
        if availability is None and isinstance(device.get("isOnline"), bool):
            availability = "Online" if device["isOnline"] else "Offline"
        identifiers = []
        if teamviewer_id is not None:
            identifiers.append(f"TeamViewer ID: {teamviewer_id}")
        if local_id is not None:
            identifiers.append(f"device ID: {local_id}")
        identifiers.append(f"availability: {availability or 'Unknown'}")
        lines.append(f"- {name} ({', '.join(identifiers)})")
    return "\n".join(lines)


def _format_inventory_device(device: dict[str, Any]) -> str:
    name = _device_value(device, "name", "alias") or "Unnamed"
    teamviewer_id = _device_value(
        device, "teamviewerId", "teamviewer_id", "remotecontrol_id"
    )
    local_id = _device_value(device, "id", "device_id")
    availability = _device_value(
        device, "availability", "online_state", "onlineState"
    )
    if availability is None and isinstance(device.get("isOnline"), bool):
        availability = (
            "Online"
            if device["isOnline"]
            else "Not online (the API does not distinguish Sleeping from Offline)"
        )
    identifiers = []
    if teamviewer_id is not None:
        identifiers.append(f"TeamViewer ID: {teamviewer_id}")
    if local_id is not None:
        identifiers.append(f"device ID: {local_id}")
    identifiers.append(f"availability: {availability or 'Unknown'}")
    return f"- {name} ({', '.join(identifiers)})"


def _format_all_devices(result: dict[str, Any]) -> str:
    """Render the two official TeamViewer inventory namespaces separately."""
    legacy = result.get("legacyDevices")
    managed = result.get("managedDevices")
    legacy_devices = legacy if isinstance(legacy, list) else []
    managed_devices = managed if isinstance(managed, list) else []
    requested_state = result.get("onlineState") or "All"
    lines = [
        f"TeamViewer device inventory (availability filter: {requested_state})",
        f"Legacy Computers & Contacts devices: {len(legacy_devices)}",
    ]
    lines.extend(
        _format_inventory_device(device)
        for device in legacy_devices
        if isinstance(device, dict)
    )
    lines.append(f"Company-managed devices: {len(managed_devices)}")
    lines.extend(
        _format_inventory_device(device)
        for device in managed_devices
        if isinstance(device, dict)
    )
    return "\n".join(lines)


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
            # Some Foundry Local CLI versions report a stale ``running`` flag when an
            # existing per-user daemon still serves the advertised loopback URL.
            # The OpenAI client performs the definitive reachability check.
            if not urls:
                raise RuntimeError("Foundry Local did not advertise an endpoint")
            endpoint = str(urls[0])
        except (
            FileNotFoundError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
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
        "additional_tool_argument_names": _MCP_ADDITIONAL_TOOL_ARGUMENT_NAMES,
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


def _tool_options(tool_name: str) -> dict[str, Any]:
    return {
        "tool_choice": {"mode": "required", "required_function_name": tool_name},
        "allow_multiple_tool_calls": False,
    }


def _continuation_options() -> dict[str, Any]:
    return {"tool_choice": "none", "allow_multiple_tool_calls": False}


async def _settle_rejection(
    runtime: AgentRuntime,
    session: Any,
    requests: list[Any],
    selected_tools: list[Any],
    guard: InvocationGuard,
) -> None:
    responses = [request.to_function_approval_response(approved=False) for request in requests]
    await runtime.agent.run(
        Message(role="user", contents=responses),
        session=session,
        tools=selected_tools,
        options=_continuation_options(),
        middleware=[guard],
    )


async def run_turn(
    runtime: AgentRuntime,
    session: Any,
    prompt: str,
    settings: Settings,
) -> str:
    """Route one turn, exposing at most one validated TeamViewer operation."""
    route = route_prompt(prompt)
    if route.outcome == RouteOutcome.CLARIFY:
        return f"{route.message}\nNo TeamViewer operation was executed."

    if route.outcome == RouteOutcome.CONVERSATION:
        result = await runtime.agent.run(
            prompt,
            session=session,
            tools=[],
            options=_continuation_options(),
        )
        return _clean_model_text(result.text)

    if route.outcome == RouteOutcome.HOST:
        if runtime.teamviewer is None:
            return "The requested host workflow is unavailable. No TeamViewer operation ran."
        if route.intent == "all_devices":
            online_state = dict(route.arguments).get("online_state")
            try:
                result = await list_devices_across_namespaces(
                    runtime.teamviewer, online_state
                )
            except Exception as exc:
                logger.warning(
                    "TeamViewer MCP host workflow failed: workflow=all_devices "
                    "error_type=%s",
                    type(exc).__name__,
                )
                return "The TeamViewer MCP inventory lookup failed. No success was reported."
            return _format_all_devices(result)
        if route.intent != "group_devices":
            return "The requested host workflow is unavailable. No TeamViewer operation ran."
        group_name = dict(route.arguments).get("group_name")
        if not isinstance(group_name, str) or not group_name.strip():
            return "A non-empty group name is required. No TeamViewer operation ran."
        try:
            result = await list_devices_in_group(runtime.teamviewer, group_name)
        except Exception as exc:
            logger.warning(
                "TeamViewer MCP host workflow failed: workflow=group_devices "
                "error_type=%s",
                type(exc).__name__,
            )
            return "The TeamViewer MCP group lookup failed. No success was reported."
        return _format_group_devices(result)

    assert route.tool_name is not None
    selected = runtime.tools.get(route.tool_name)
    if selected is None:
        return (
            f"The routed tool {route.tool_name} is not available under the active MCP policy.\n"
            "No TeamViewer operation was executed."
        )

    selected_tools = [selected]
    guard = InvocationGuard(route, prompt)
    result = await runtime.agent.run(
        prompt,
        session=session,
        tools=selected_tools,
        options=_tool_options(route.tool_name),
        middleware=[guard],
    )

    if guard.blocked_message:
        return (
            f"Blocked before MCP execution: {guard.blocked_message}\n"
            "No TeamViewer operation was executed."
        )
    if guard.execution_error:
        return "The TeamViewer MCP operation failed. No success was reported."

    if not route.mutating:
        if result.user_input_requests:
            await _settle_rejection(
                runtime,
                session,
                list(result.user_input_requests),
                selected_tools,
                guard,
            )
            return (
                "An unexpected approval request was rejected. "
                "No TeamViewer operation was executed."
            )
        if not guard.attempted:
            return (
                "The required TeamViewer MCP read was not executed. "
                "No live TeamViewer data is available for this response."
            )
        return _clean_model_text(result.text)

    requests = list(result.user_input_requests)
    if len(requests) != 1:
        if requests:
            await _settle_rejection(runtime, session, requests, selected_tools, guard)
        return (
            "Could not prepare exactly one valid operation. "
            "No TeamViewer operation was executed."
        )

    while requests:
        request = requests[0]
        function_call = request.function_call
        if function_call is None:
            await _settle_rejection(runtime, session, requests, selected_tools, guard)
            return "Unsupported approval request rejected. No TeamViewer operation was executed."

        arguments = arguments_to_dict(function_call.arguments)
        error = validate_invocation(route, prompt, function_call.name, arguments)
        if error:
            await _settle_rejection(runtime, session, requests, selected_tools, guard)
            return f"Blocked before approval: {error}\nNo TeamViewer operation was executed."

        approved = _ask_for_approval(function_call.name, arguments)
        record_decision(
            settings.audit_path,
            operator_id=settings.operator_id,
            tool_name=function_call.name,
            arguments=arguments,
            approved=approved,
        )
        response = request.to_function_approval_response(approved=approved)
        if approved:
            guard.bind_approved_call(function_call.name, arguments)
        result = await runtime.agent.run(
            Message(role="user", contents=[response]),
            session=session,
            tools=selected_tools,
            options=_continuation_options(),
            middleware=[guard],
        )
        if not approved:
            return "Rejected. No TeamViewer operation was executed."
        if guard.blocked_message:
            return (
                f"Blocked before MCP execution: {guard.blocked_message}\n"
                "No TeamViewer operation was executed."
            )
        if guard.execution_error:
            return "The TeamViewer MCP operation failed. No success was reported."

        additional_requests = list(result.user_input_requests)
        if additional_requests:
            await _settle_rejection(
                runtime,
                session,
                additional_requests,
                selected_tools,
                guard,
            )
            return (
                "An additional operation was rejected. "
                "No additional TeamViewer operation was executed."
            )
        requests = []

    if not guard.attempted:
        return "The approved TeamViewer MCP operation was not executed."
    return _clean_model_text(result.text)


@asynccontextmanager
async def open_agent(settings: Settings) -> AsyncIterator[AgentRuntime]:
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
                    function_invocation_configuration={
                        "max_function_calls": 1,
                        "terminate_on_unknown_calls": True,
                    },
                )
            else:
                assert settings.foundry_project_endpoint is not None
                assert settings.foundry_model is not None
                credential = AzureCliCredential()
                client = FoundryChatClient(
                    project_endpoint=settings.foundry_project_endpoint,
                    model=settings.foundry_model,
                    credential=credential,
                    function_invocation_configuration={
                        "max_function_calls": 1,
                        "terminate_on_unknown_calls": True,
                    },
                )

            registry = {
                function.name: function
                for function in teamviewer.functions
                if function.name in READ_ONLY_TOOLS
            }
            for read_tool in create_mcp_read_tools(teamviewer):
                registry[read_tool.name] = read_tool
            for write_tool in create_mcp_write_tools(teamviewer):
                registry[write_tool.name] = write_tool
            expected_tools = READ_ONLY_TOOLS | APPROVAL_REQUIRED_TOOLS
            missing = expected_tools - set(registry)
            unexpected = set(registry) - expected_tools
            if missing or unexpected:
                raise RuntimeError(
                    "Routed tool registry does not match policy; "
                    f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
                )

            async with Agent(
                client=client,
                name="TeamViewerServiceDesk",
                instructions=AGENT_INSTRUCTIONS,
                tools=[],
            ) as agent:
                yield AgentRuntime(agent=agent, tools=registry, teamviewer=teamviewer)
    finally:
        if credential is not None:
            credential.close()
