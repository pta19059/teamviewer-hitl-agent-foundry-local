import unittest

from teamviewer_hitl.policy import (
    ALLOWED_TOOLS,
    APPROVAL_REQUIRED_TOOLS,
    MCP_COMPOSITE_READ_ONLY_TOOLS,
    MCP_APPROVAL_MODE,
    READ_ONLY_TOOLS,
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

    def test_managed_group_composition_is_mcp_only_and_read_only(self) -> None:
        name = "tv_list_devices_in_managed_group"
        self.assertIn(name, MCP_COMPOSITE_READ_ONLY_TOOLS)
        self.assertIn(name, READ_ONLY_TOOLS)
        self.assertNotIn(name, ALLOWED_TOOLS)
        self.assertIn("tv_list_managed_groups", ALLOWED_TOOLS)
        self.assertIn("tv_list_company_managed_devices", ALLOWED_TOOLS)
        self.assertIn("tv_get_managed_device_groups", ALLOWED_TOOLS)

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
