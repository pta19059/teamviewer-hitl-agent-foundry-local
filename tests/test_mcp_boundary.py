import ast
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
