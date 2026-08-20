"""The intentionally small TeamViewer MCP capability and approval boundary."""

from typing import Final

# Discovery and investigation may run without an approval interruption. These tools
# should not change TeamViewer state.
READ_ONLY_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "tv_get_account",
        "tv_get_company",
        "tv_get_company_license",
        "tv_list_device_groups",
        "tv_get_device_group",
        "tv_list_devices",
        "tv_get_device",
        "tv_get_event_logs",
        "tv_list_managed_devices",
        "tv_list_company_managed_devices",
        "tv_get_managed_device",
        "tv_get_managed_device_groups",
        "tv_list_monitoring_alarms",
        "tv_list_monitoring_devices",
        "tv_get_device_hardware_info",
        "tv_get_device_system_info",
        "tv_get_device_software_info",
        "tv_list_connection_reports",
        "tv_get_connection_report",
        "tv_get_connection_ai_summary",
        "tv_list_device_reports",
        "tv_list_sessions",
        "tv_get_session",
    }
)

# Each call to one of these state-changing tools is intercepted by Microsoft Agent
# Framework and must receive a fresh, explicit human decision.
APPROVAL_REQUIRED_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "tv_create_session",
        "tv_update_session",
        "tv_delete_session",
        "tv_update_managed_device_description",
        "tv_activate_monitoring",
        "tv_assign_monitoring_policy",
        "tv_assign_patch_management_policy",
        "tv_update_connection_report",
    }
)

ALLOWED_TOOLS: Final[tuple[str, ...]] = tuple(
    sorted(READ_ONLY_TOOLS | APPROVAL_REQUIRED_TOOLS)
)

MCP_APPROVAL_MODE: Final[dict[str, tuple[str, ...]]] = {
    "always_require_approval": tuple(sorted(APPROVAL_REQUIRED_TOOLS)),
    "never_require_approval": tuple(sorted(READ_ONLY_TOOLS)),
}


def validate_policy() -> None:
    """Fail fast if a tool is accidentally assigned contradictory approval rules."""
    overlap = READ_ONLY_TOOLS & APPROVAL_REQUIRED_TOOLS
    if overlap:
        names = ", ".join(sorted(overlap))
        raise ValueError(f"Tools cannot be both read-only and approval-required: {names}")
    if set(ALLOWED_TOOLS) != READ_ONLY_TOOLS | APPROVAL_REQUIRED_TOOLS:
        raise ValueError("The TeamViewer allow-list does not match the approval policy")
