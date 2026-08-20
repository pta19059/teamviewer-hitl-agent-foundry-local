import unittest

from teamviewer_hitl.write_tools import create_mcp_write_tools


class _FakeMCP:
    def __init__(self) -> None:
        self.calls = []

    async def call_tool(self, name, **arguments):
        self.calls.append((name, arguments))
        return {"ok": True}


class WriteToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.mcp = _FakeMCP()
        self.tools = {tool.name: tool for tool in create_mcp_write_tools(self.mcp)}

    def test_every_wrapper_requires_fresh_approval(self) -> None:
        self.assertEqual(
            {name: tool.approval_mode for name, tool in self.tools.items()},
            {
                "tv_create_session": "always_require",
                "tv_update_session": "always_require",
                "tv_delete_session": "always_require",
                "tv_update_managed_device_description": "always_require",
                "tv_activate_monitoring": "always_require",
                "tv_update_connection_report": "always_require",
            },
        )

    async def test_session_creation_dispatches_only_through_exact_mcp_tool(self) -> None:
        await self.tools["tv_create_session"].func(
            description="Help Alice",
            tag="urgent",
            end_customer_name="Alice",
            end_customer_email="alice@example.com",
        )
        self.assertEqual(
            self.mcp.calls,
            [
                (
                    "tv_create_session",
                    {
                        "description": "Help Alice",
                        "tag": "urgent",
                        "end_customer": {
                            "name": "Alice",
                            "email": "alice@example.com",
                        },
                    },
                )
            ],
        )

    async def test_each_wrapper_dispatches_to_the_same_named_mcp_operation(self) -> None:
        cases = (
            ("tv_update_session", {"session_code": "s123", "notes": "Reviewed"}),
            ("tv_delete_session", {"session_code": "s123"}),
            (
                "tv_update_managed_device_description",
                {
                    "device_id": "550e8400-e29b-41d4-a716-446655440000",
                    "description": "Lobby kiosk",
                },
            ),
            ("tv_activate_monitoring", {"teamviewer_id": 987654321}),
            (
                "tv_update_connection_report",
                {"connection_id": "c123", "notes": "Reviewed"},
            ),
        )
        for name, arguments in cases:
            with self.subTest(name=name):
                self.mcp.calls.clear()
                await self.tools[name].func(**arguments)
                self.assertEqual(self.mcp.calls, [(name, arguments)])


if __name__ == "__main__":
    unittest.main()
