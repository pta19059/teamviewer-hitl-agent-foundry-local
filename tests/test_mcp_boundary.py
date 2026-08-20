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

    def test_required_session_group_id_survives_real_framework_mcp_filter(self) -> None:
        self.assertEqual(
            _MCP_ADDITIONAL_TOOL_ARGUMENT_NAMES,
            {"tv_create_session": ("groupid",)},
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

        self.assertEqual(
            create_arguments,
            {"description": "HITL-Test", "groupid": "g12345678"},
        )
        self.assertEqual(update_arguments, {"session_code": "s123"})


if __name__ == "__main__":
    unittest.main()
