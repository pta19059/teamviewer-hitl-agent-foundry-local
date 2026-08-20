import ast
import unittest
from pathlib import Path

from agent_framework import MCPStdioTool

from teamviewer_hitl.agent import _MCP_ADDITIONAL_TOOL_ARGUMENT_NAMES


class MCPBoundaryTests(unittest.TestCase):
    def test_python_host_has_no_direct_teamviewer_http_client(self) -> None:
        source_root = Path("src/teamviewer_hitl")
        forbidden_imports = {"requests", "httpx", "aiohttp", "urllib.request"}

        for path in source_root.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("webapi.teamviewer.com", source.casefold(), path)
            tree = ast.parse(source, filename=str(path))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertTrue(forbidden_imports.isdisjoint(imported), path)

    def test_host_only_arguments_survive_the_real_framework_mcp_filter(self) -> None:
        self.assertEqual(
            _MCP_ADDITIONAL_TOOL_ARGUMENT_NAMES,
            {
                "tv_create_session": ("groupid",),
                "tv_list_connection_reports": ("offset_id",),
                "tv_list_device_reports": ("offset_id",),
            },
        )
        tool = MCPStdioTool(
            name="filter-test",
            command="node",
            load_tools=False,
            additional_tool_argument_names=_MCP_ADDITIONAL_TOOL_ARGUMENT_NAMES,
        )
        tool._tool_param_names_by_name = {
            "tv_create_session": {"description"},
            "tv_update_session": {"session_code"},
            "tv_list_connection_reports": {"userid"},
            "tv_list_device_reports": {"from_date"},
        }

        create_arguments, _ = tool._prepare_call_kwargs(
            "tv_create_session",
            {
                "description": "HITL-Test",
                "groupid": "g12345678",
                "unexpected": "must-not-cross-mcp",
            },
        )
        update_arguments, _ = tool._prepare_call_kwargs(
            "tv_update_session",
            {"session_code": "s123", "groupid": "must-not-cross-mcp"},
        )
        report_arguments, _ = tool._prepare_call_kwargs(
            "tv_list_connection_reports",
            {
                "offset_id": "550e8400-e29b-41d4-a716-446655440000",
                "unexpected": "must-not-cross-mcp",
            },
        )
        device_report_arguments, _ = tool._prepare_call_kwargs(
            "tv_list_device_reports",
            {
                "offset_id": "550e8400-e29b-41d4-a716-446655440000",
                "unexpected": "must-not-cross-mcp",
            },
        )

        self.assertEqual(
            create_arguments,
            {"description": "HITL-Test", "groupid": "g12345678"},
        )
        self.assertEqual(update_arguments, {"session_code": "s123"})
        self.assertEqual(
            report_arguments,
            {"offset_id": "550e8400-e29b-41d4-a716-446655440000"},
        )
        self.assertEqual(
            device_report_arguments,
            {"offset_id": "550e8400-e29b-41d4-a716-446655440000"},
        )


if __name__ == "__main__":
    unittest.main()
