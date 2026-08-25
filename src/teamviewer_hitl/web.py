"""Local web console for the TeamViewer HITL agent."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .routing import IntentRoute, RouteOutcome, route_prompt


_MAX_REQUEST_BYTES = 16_384
_COMMAND_TIMEOUT_SECONDS = 600
_APPROVAL_TTL_SECONDS = 600
_UI_HEADER = "X-TeamViewer-UI"
_INDEX_PATH = Path(__file__).with_name("web_ui.html")
_RUN_LOCK = threading.Lock()
_PENDING_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class PendingApproval:
    prompt: str
    created_at: float


_PENDING: dict[str, PendingApproval] = {}


def _route_arguments(route: IntentRoute) -> dict[str, Any]:
    return dict(route.arguments)


def workflow_for_prompt(prompt: str) -> dict[str, Any]:
    """Return a UI-safe explanation of the actual deterministic workflow."""
    route = route_prompt(prompt)
    operation = (
        f"host_{route.intent}"
        if route.outcome == RouteOutcome.HOST
        else route.tool_name
        or route.outcome.value
    )
    steps = [
        {
            "id": "prompt",
            "label": "Operator prompt",
            "detail": "One requested operation",
            "state": "ready",
        },
        {
            "id": "qwen-plan",
            "label": "Qwen analysis",
            "detail": "Confirms the exact host-compatible operation",
            "state": "pending",
        },
        {
            "id": "host",
            "label": "Host validation",
            "detail": "Binds identifiers, filters, and arguments",
            "state": "pending",
        },
    ]
    if route.mutating:
        steps.append(
            {
                "id": "approval",
                "label": "Human approval",
                "detail": "Exact APPROVE required before execution",
                "state": "pending",
            }
        )
    if route.outcome in {RouteOutcome.TOOL, RouteOutcome.HOST}:
        steps.append(
            {
                "id": "mcp",
                "label": "Official MCP server",
                "detail": "Exclusive TeamViewer data and action boundary",
                "state": "pending",
            }
        )
    steps.append(
        {
            "id": "response",
            "label": "Grounded response",
            "detail": "Qwen presents verified MCP evidence",
            "state": "pending",
        }
    )
    return {
        "outcome": route.outcome.value,
        "intent": route.intent,
        "operation": operation,
        "mutating": route.mutating,
        "arguments": _route_arguments(route),
        "message": route.message,
        "steps": steps,
    }


def _cleanup_pending() -> None:
    cutoff = time.time() - _APPROVAL_TTL_SECONDS
    with _PENDING_LOCK:
        expired = [token for token, item in _PENDING.items() if item.created_at < cutoff]
        for token in expired:
            _PENDING.pop(token, None)


def _create_pending(prompt: str) -> str:
    _cleanup_pending()
    token = secrets.token_urlsafe(32)
    with _PENDING_LOCK:
        _PENDING[token] = PendingApproval(prompt=prompt, created_at=time.time())
    return token


def _take_pending(token: str) -> PendingApproval | None:
    _cleanup_pending()
    with _PENDING_LOCK:
        return _PENDING.pop(token, None)


def _run_cli(prompt: str, decision: str | None = None) -> dict[str, Any]:
    command = [sys.executable, "-m", "teamviewer_hitl.cli", prompt]
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with _RUN_LOCK:
            completed = subprocess.run(
                command,
                input=f"{decision}\n" if decision is not None else None,
                text=True,
                capture_output=True,
                timeout=_COMMAND_TIMEOUT_SECONDS,
                check=False,
                creationflags=creation_flags,
            )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": None,
            "output": "The command exceeded the 10-minute safety timeout.",
            "diagnostics": "",
        }
    if completed.stderr.strip() and completed.returncode != 0:
        sys.stderr.write(f"[command error] CLI exited with code {completed.returncode}.\n")
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "output": completed.stdout.strip(),
        "diagnostics": (
            ""
            if completed.returncode == 0
            else "The command process exited unexpectedly. Review the web-console host terminal."
        ),
    }


class TeamViewerWebHandler(BaseHTTPRequestHandler):
    server_version = "TeamViewerHITLWeb/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"[web] {self.address_string()} - {format % args}\n")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self) -> None:
        try:
            body = _INDEX_PATH.read_bytes()
        except OSError:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "The web UI asset is unavailable."},
            )
            return
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > _MAX_REQUEST_BYTES:
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _trusted_post(self) -> bool:
        if self.headers.get(_UI_HEADER) != "1":
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        parsed = urlparse(origin)
        return parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send_html()
            return
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_POST(self) -> None:  # noqa: N802
        if not self._trusted_post():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Untrusted request."})
            return
        payload = self._read_json()
        if payload is None:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON request."})
            return
        path = urlparse(self.path).path
        if path == "/api/analyze":
            self._handle_analyze(payload)
            return
        if path == "/api/run":
            self._handle_run(payload)
            return
        if path == "/api/decision":
            self._handle_decision(payload)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def _prompt(self, payload: dict[str, Any]) -> str | None:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return None
        prompt = prompt.strip()
        return prompt if 0 < len(prompt) <= 4_000 else None

    def _handle_analyze(self, payload: dict[str, Any]) -> None:
        prompt = self._prompt(payload)
        if prompt is None:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Supply a prompt."})
            return
        self._send_json(HTTPStatus.OK, {"workflow": workflow_for_prompt(prompt)})

    def _handle_run(self, payload: dict[str, Any]) -> None:
        prompt = self._prompt(payload)
        if prompt is None:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Supply a prompt."})
            return
        workflow = workflow_for_prompt(prompt)
        if workflow["mutating"]:
            token = _create_pending(prompt)
            self._send_json(
                HTTPStatus.ACCEPTED,
                {
                    "approval_required": True,
                    "approval_token": token,
                    "workflow": workflow,
                },
            )
            return
        result = _run_cli(prompt)
        self._send_json(
            HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_GATEWAY,
            {"approval_required": False, "workflow": workflow, "result": result},
        )

    def _handle_decision(self, payload: dict[str, Any]) -> None:
        token = payload.get("approval_token")
        decision = payload.get("decision")
        if not isinstance(token, str) or decision not in {"APPROVE", "REJECT"}:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid decision."})
            return
        pending = _take_pending(token)
        if pending is None:
            self._send_json(
                HTTPStatus.GONE,
                {"error": "The approval request expired or was already used."},
            )
            return
        workflow = workflow_for_prompt(pending.prompt)
        result = _run_cli(pending.prompt, decision)
        self._send_json(
            HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_GATEWAY,
            {"approval_required": False, "workflow": workflow, "result": result},
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the local page in a browser")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if not 1 <= args.port <= 65_535:
        raise SystemExit("Port must be between 1 and 65535.")
    server = ThreadingHTTPServer((args.host, args.port), TeamViewerWebHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"TeamViewer HITL web console: {url}")
    print("Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
