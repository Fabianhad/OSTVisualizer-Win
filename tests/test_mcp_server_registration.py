import logging
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.application.dtos.mcp_context_dtos import (
    MCP_SUMMARY_DEFAULT_GROUP_BY_AREA,
    MCP_SUMMARY_DEFAULT_GROUP_BY_PAGE,
    MCP_SUMMARY_DEFAULT_GROUP_BY_TYPE,
    MCP_SUMMARY_DEFAULT_LIMIT,
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

    def test_get_summary_schema_has_grouping_defaults(self):
        from ost_visualizer.mcp_server.registry import DatabaseRegistry
        from ost_visualizer.mcp_server.server import build_mcp_server

        with tempfile.TemporaryDirectory() as tmp:
            registry = DatabaseRegistry(app_data_dir=Path(tmp))
            server = build_mcp_server(registry)
            tool = next(
                tool for tool in server.list_tools() if tool["name"] == "get_summary"
            )
        properties = tool["inputSchema"]["properties"]
        self.assertEqual(tool["inputSchema"]["required"], ["database_id", "bid_uid"])
        self.assertEqual(
            properties["group_by_page"]["default"],
            MCP_SUMMARY_DEFAULT_GROUP_BY_PAGE,
        )
        self.assertEqual(
            properties["group_by_type"]["default"],
            MCP_SUMMARY_DEFAULT_GROUP_BY_TYPE,
        )
        self.assertEqual(
            properties["group_by_area"]["default"],
            MCP_SUMMARY_DEFAULT_GROUP_BY_AREA,
        )
        self.assertEqual(properties["limit"]["default"], MCP_SUMMARY_DEFAULT_LIMIT)


if __name__ == "__main__":
    unittest.main()
