"""Strict application write tools whose TeamViewer I/O remains MCP-only."""

from __future__ import annotations

from typing import Annotated, Any

from agent_framework import tool
from pydantic import Field

_UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


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
    ) -> Any:
        """Create one TeamViewer service-case session after explicit human approval."""
        return await teamviewer.call_tool(
            "tv_create_session", description=description, groupid=groupid
        )

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
            str, Field(min_length=1, max_length=1000, description="New session description")
        ],
    ) -> Any:
        """Update one identified TeamViewer service-case session after approval."""
        return await teamviewer.call_tool(
            "tv_update_session",
            session_code=session_code,
            description=description,
        )

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
                pattern=_UUID_PATTERN,
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
        teamviewer_id: Annotated[
            int,
            Field(
                gt=0,
                le=9_007_199_254_740_991,
                description="Numeric TeamViewer device ID",
            ),
        ],
    ) -> Any:
        """Activate monitoring and patch-management services on one device after approval."""
        return await teamviewer.call_tool(
            "tv_activate_monitoring", teamviewer_id=teamviewer_id
        )

    @tool(approval_mode="always_require")
    async def tv_update_connection_report(
        connection_id: Annotated[
            str,
            Field(
                min_length=36,
                max_length=36,
                pattern=_UUID_PATTERN,
                description="Connection report UUID",
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
