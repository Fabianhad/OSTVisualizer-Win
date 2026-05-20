import importlib.util
import asyncio
import logging
import tempfile
import unittest
from pathlib import Path


@unittest.skipIf(
    importlib.util.find_spec("mcp") is None,
    "optional MCP SDK is not installed",
)
class McpServerRegistrationTests(unittest.TestCase):
    def test_server_builds_with_empty_registry(self):
        from ost_visualizer.mcp_server.registry import DatabaseRegistry
        from ost_visualizer.mcp_server.server import build_mcp_server

        with tempfile.TemporaryDirectory() as tmp:
            logger = logging.getLogger("test_mcp_server_registration")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            logger.propagate = False
            registry = DatabaseRegistry(app_data_dir=Path(tmp), logger=logger)
            server = build_mcp_server(registry, logger=logger)
            self.assertIsNotNone(server)

    def test_expected_phase_three_tools_are_registered_without_csv(self):
        from ost_visualizer.mcp_server.registry import DatabaseRegistry
        from ost_visualizer.mcp_server.server import build_mcp_server

        async def list_tool_names():
            with tempfile.TemporaryDirectory() as tmp:
                registry = DatabaseRegistry(app_data_dir=Path(tmp))
                server = build_mcp_server(registry)
                return {tool.name for tool in await server.list_tools()}

        tool_names = asyncio.run(list_tool_names())
        self.assertIn("get_condition_summary", tool_names)
        self.assertIn("get_selected_pages_summary", tool_names)
        self.assertIn("get_selected_takeoffs_summary", tool_names)
        self.assertIn("search_conditions", tool_names)
        self.assertIn("find_pages_without_takeoffs", tool_names)
        self.assertIn("find_conditions_without_takeoffs", tool_names)
        self.assertFalse(any("csv" in name.lower() for name in tool_names))

    def test_current_estimator_prompt_is_registered(self):
        from ost_visualizer.mcp_server.registry import DatabaseRegistry
        from ost_visualizer.mcp_server.server import build_mcp_server

        async def list_prompt_names():
            with tempfile.TemporaryDirectory() as tmp:
                registry = DatabaseRegistry(app_data_dir=Path(tmp))
                server = build_mcp_server(registry)
                return {prompt.name for prompt in await server.list_prompts()}

        prompt_names = asyncio.run(list_prompt_names())
        self.assertIn("review_current_estimator_context", prompt_names)


if __name__ == "__main__":
    unittest.main()
