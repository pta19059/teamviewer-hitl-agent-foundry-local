import re
import unittest
from pathlib import Path

from teamviewer_hitl.policy import (
    ALLOWED_TOOLS,
    APPROVAL_REQUIRED_TOOLS,
    MCP_APPROVAL_MODE,
    READ_ONLY_TOOLS,
    UNSAFE_DISABLED_TOOLS,
    validate_policy,
)


class PolicyTests(unittest.TestCase):
    def test_policy_is_valid_and_disjoint(self) -> None:
        validate_policy()
        self.assertFalse(READ_ONLY_TOOLS & APPROVAL_REQUIRED_TOOLS)

    def test_every_allowed_tool_has_an_explicit_approval_rule(self) -> None:
        governed = set(MCP_APPROVAL_MODE["always_require_approval"]) | set(
            MCP_APPROVAL_MODE["never_require_approval"]
        )
        self.assertEqual(set(ALLOWED_TOOLS), governed)

    def test_session_creation_requires_approval(self) -> None:
        self.assertIn("tv_create_session", APPROVAL_REQUIRED_TOOLS)
        self.assertNotIn("tv_create_session", READ_ONLY_TOOLS)

    def test_underspecified_policy_assignment_tools_are_disabled(self) -> None:
        self.assertEqual(
            UNSAFE_DISABLED_TOOLS,
            {
                "tv_assign_monitoring_policy",
                "tv_assign_patch_management_policy",
            },
        )
        self.assertTrue(UNSAFE_DISABLED_TOOLS.isdisjoint(ALLOWED_TOOLS))

    def test_every_model_visible_tool_is_published_by_official_mcp(self) -> None:
        tools_root = Path("external/TV_Remote_MCP/src/tools")
        published = set()
        for source in tools_root.glob("*.ts"):
            published.update(
                re.findall(r'name:\s*"(tv_[a-z0-9_]+)"', source.read_text(encoding="utf-8"))
            )
        self.assertTrue(published)
        self.assertTrue(set(ALLOWED_TOOLS).issubset(published))
        self.assertNotIn("tv_list_devices_in_group", ALLOWED_TOOLS)

    def test_high_risk_admin_tools_are_not_exposed(self) -> None:
        forbidden = {
            "tv_delete_user",
            "tv_deactivate_user_tfa",
            "tv_oauth_create_permanent_token",
            "tv_delete_managed_device",
            "tv_delete_teamviewer_policy",
        }
        self.assertTrue(forbidden.isdisjoint(ALLOWED_TOOLS))


if __name__ == "__main__":
    unittest.main()
