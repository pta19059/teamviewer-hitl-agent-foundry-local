"""Environment-based application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when required configuration is absent or unsafe."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Set {name} in .env or the process environment")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    model_provider: str
    transport: str
    operator_id: str
    audit_path: Path
    foundry_project_endpoint: str | None = None
    foundry_model: str | None = None
    foundry_local_model: str | None = None
    foundry_local_endpoint: str | None = None
    mcp_command: str | None = None
    mcp_script: Path | None = None
    teamviewer_api_token: str | None = None
    mcp_url: str | None = None
    mcp_bearer_token: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        model_provider = os.getenv("MODEL_PROVIDER", "foundry_local").strip().lower()
        if model_provider not in {"foundry_local", "foundry_cloud"}:
            raise ConfigurationError(
                "MODEL_PROVIDER must be 'foundry_local' or 'foundry_cloud'"
            )

        transport = os.getenv("TEAMVIEWER_MCP_TRANSPORT", "local").strip().lower()
        if transport not in {"local", "http"}:
            raise ConfigurationError("TEAMVIEWER_MCP_TRANSPORT must be 'local' or 'http'")

        common = {
            "model_provider": model_provider,
            "transport": transport,
            "operator_id": os.getenv("OPERATOR_ID", "unknown-operator").strip()
            or "unknown-operator",
            "audit_path": Path(".audit/teamviewer-approvals.jsonl"),
        }

        if model_provider == "foundry_local":
            common["foundry_local_model"] = _required("FOUNDRY_LOCAL_MODEL")
            common["foundry_local_endpoint"] = (
                os.getenv("FOUNDRY_LOCAL_ENDPOINT", "").strip() or None
            )
        else:
            common["foundry_project_endpoint"] = _required("FOUNDRY_PROJECT_ENDPOINT")
            common["foundry_model"] = _required("FOUNDRY_MODEL")

        if transport == "local":
            script = Path(_required("TEAMVIEWER_MCP_SCRIPT")).expanduser().resolve()
            if not script.is_file():
                raise ConfigurationError(
                    f"TEAMVIEWER_MCP_SCRIPT does not exist: {script}. Build the TeamViewer MCP server first."
                )
            return cls(
                **common,
                mcp_command=os.getenv("TEAMVIEWER_MCP_COMMAND", "node").strip() or "node",
                mcp_script=script,
                teamviewer_api_token=_required("TEAMVIEWER_API_TOKEN"),
            )

        url = _required("TEAMVIEWER_MCP_URL")
        if not url.startswith(("http://", "https://")):
            raise ConfigurationError("TEAMVIEWER_MCP_URL must start with http:// or https://")
        return cls(
            **common,
            mcp_url=url,
            mcp_bearer_token=os.getenv("TEAMVIEWER_MCP_BEARER_TOKEN", "").strip() or None,
        )
