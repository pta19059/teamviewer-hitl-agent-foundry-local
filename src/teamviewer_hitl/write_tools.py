"""Strict application write tools whose TeamViewer I/O remains MCP-only."""

from __future__ import annotations

from typing import Annotated, Any

from agent_framework import tool
from pydantic import Field


def create_mcp_write_tools(teamviewer: Any) -> list[Any]:
    """Create typed, approval-required wrappers over official TeamViewer MCP calls."""

    @tool(approval_mode="always_require")
    async def tv_create_session(
        description: Annotated[
            str, Field(min_length=1, max_length=1000, description="Session description")
        ],
        groupid: Annotated[
            str,
            Field(
                min_length=2,
                max_length=255,
                pattern=r"^[gG][0-9]+$",
                description="Existing legacy Computers & Contacts group ID",
            ),
        ],
        tag: Annotated[
            str | None, Field(min_length=1, max_length=255, description="Optional session tag")
        ] = None,
        notes: Annotated[
            str | None, Field(min_length=1, max_length=1000, description="Optional internal notes")
        ] = None,
        supporter_name: Annotated[
            str | None, Field(min_length=1, max_length=255, description="Optional supporter name")
        ] = None,
        end_customer_name: Annotated[
            str | None, Field(min_length=1, max_length=255, description="Optional customer name")
        ] = None,
        end_customer_email: Annotated[
            str | None,
            Field(
                min_length=3,
                max_length=320,
                pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
                description="Optional customer email",
            ),
        ] = None,
    ) -> Any:
        """Create one TeamViewer service-case session after explicit human approval."""
        arguments: dict[str, Any] = {
            "description": description,
            "groupid": groupid,
        }
        for key, value in {
            "tag": tag,
            "notes": notes,
            "supporter_name": supporter_name,
        }.items():
            if value is not None:
                arguments[key] = value
        if end_customer_name is not None or end_customer_email is not None:
            arguments["end_customer"] = {
                key: value
                for key, value in {
                    "name": end_customer_name,
                    "email": end_customer_email,
                }.items()
                if value is not None
            }
        return await teamviewer.call_tool("tv_create_session", **arguments)

    @tool(approval_mode="always_require")
    async def tv_update_session(
        session_code: Annotated[
            str,
            Field(
                min_length=1,
                max_length=255,
                pattern=r"^[A-Za-z0-9_-]+$",
                description="Existing session code",
            ),
        ],
        description: Annotated[
            str | None, Field(min_length=1, max_length=1000, description="New session description")
        ] = None,
        tag: Annotated[
            str | None, Field(min_length=1, max_length=255, description="New session tag")
        ] = None,
        notes: Annotated[
            str | None, Field(min_length=1, max_length=1000, description="New internal notes")
        ] = None,
    ) -> Any:
        """Update one identified TeamViewer service-case session after approval."""
        arguments = {
            key: value
            for key, value in {
                "session_code": session_code,
                "description": description,
                "tag": tag,
                "notes": notes,
            }.items()
            if value is not None
        }
        return await teamviewer.call_tool("tv_update_session", **arguments)

    @tool(approval_mode="always_require")
    async def tv_delete_session(
        session_code: Annotated[
            str,
            Field(
                min_length=1,
                max_length=255,
                pattern=r"^[A-Za-z0-9_-]+$",
                description="Session code to close",
            ),
        ],
    ) -> Any:
        """Close one identified TeamViewer service-case session after approval."""
        return await teamviewer.call_tool("tv_delete_session", session_code=session_code)

    @tool(approval_mode="always_require")
    async def tv_update_managed_device_description(
        device_id: Annotated[
            str,
            Field(
                min_length=36,
                max_length=36,
                pattern=r"^[0-9a-fA-F-]{36}$",
                description="Managed-device UUID",
            ),
        ],
        description: Annotated[
            str, Field(min_length=1, max_length=1000, description="New device description")
        ],
    ) -> Any:
        """Change one managed device description after approval."""
        return await teamviewer.call_tool(
            "tv_update_managed_device_description",
            device_id=device_id,
            description=description,
        )

    @tool(approval_mode="always_require")
    async def tv_activate_monitoring(
        teamviewer_id: Annotated[int, Field(gt=0, description="Numeric TeamViewer device ID")],
        monitoring_policy_id: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=255,
                pattern=r"^[A-Za-z0-9_-]+$",
                description="Optional monitoring policy ID",
            ),
        ] = None,
        patch_management_policy_id: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=255,
                pattern=r"^[A-Za-z0-9_-]+$",
                description="Optional patch-management policy ID",
            ),
        ] = None,
    ) -> Any:
        """Activate monitoring and patch-management services on one device after approval."""
        arguments: dict[str, Any] = {"teamviewer_id": teamviewer_id}
        if monitoring_policy_id is not None:
            arguments["monitoring_policy_id"] = monitoring_policy_id
        if patch_management_policy_id is not None:
            arguments["patch_management_policy_id"] = patch_management_policy_id
        return await teamviewer.call_tool("tv_activate_monitoring", **arguments)

    @tool(approval_mode="always_require")
    async def tv_update_connection_report(
        connection_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=255,
                pattern=r"^[A-Za-z0-9_-]+$",
                description="Connection report ID",
            ),
        ],
        notes: Annotated[
            str, Field(min_length=1, max_length=1000, description="Replacement report notes")
        ],
    ) -> Any:
        """Update notes on one connection report after approval."""
        return await teamviewer.call_tool(
            "tv_update_connection_report", connection_id=connection_id, notes=notes
        )

    return [
        tv_create_session,
        tv_update_session,
        tv_delete_session,
        tv_update_managed_device_description,
        tv_activate_monitoring,
        tv_update_connection_report,
    ]
