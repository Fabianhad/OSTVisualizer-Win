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

    def test_expected_tools_are_registered_without_csv(self):
        from ost_visualizer.mcp_server.registry import DatabaseRegistry
        from ost_visualizer.mcp_server.server import build_mcp_server

        with tempfile.TemporaryDirectory() as tmp:
            registry = DatabaseRegistry(app_data_dir=Path(tmp))
            server = build_mcp_server(registry)
            tools = server.list_tools()
            tool_names = {tool["name"] for tool in tools}
        self.assertEqual(len(tool_names), 37)
        self.assertTrue(all(tool["description"] for tool in tools))
        self.assertIn("get_condition_summary", tool_names)
        self.assertIn("get_selected_pages_summary", tool_names)
        self.assertIn("get_selected_takeoffs_summary", tool_names)
        self.assertIn("get_page_metadata", tool_names)
        self.assertIn("get_page_pdf_text_summary", tool_names)
        self.assertIn("get_page_pdf_vectors_summary", tool_names)
        self.assertIn("get_page_markups_summary", tool_names)
        self.assertIn("get_page_overlay_summary", tool_names)
        self.assertIn("search_page_pdf_text", tool_names)
        self.assertIn("search_pages", tool_names)
        self.assertIn("list_layers", tool_names)
        self.assertIn("list_named_views", tool_names)
        self.assertIn("list_hotlinks", tool_names)
        self.assertIn("search_conditions", tool_names)
        self.assertIn("list_areas", tool_names)
        self.assertIn("get_area_summary", tool_names)
        self.assertIn("get_bid_quantity_summary", tool_names)
        self.assertIn("get_summary", tool_names)
        self.assertIn("review_scope_gaps", tool_names)
        self.assertIn("find_duplicate_conditions", tool_names)
        self.assertIn("find_zero_quantity_conditions", tool_names)
        self.assertIn("find_unplaced_takeoffs", tool_names)
        self.assertIn("get_page_context", tool_names)
        self.assertIn("find_pages_without_takeoffs", tool_names)
        self.assertIn("find_conditions_without_takeoffs", tool_names)
        self.assertFalse(any("csv" in name.lower() for name in tool_names))

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

    def test_expected_prompts_are_registered(self):
        from ost_visualizer.mcp_server.registry import DatabaseRegistry
        from ost_visualizer.mcp_server.server import build_mcp_server

        with tempfile.TemporaryDirectory() as tmp:
            registry = DatabaseRegistry(app_data_dir=Path(tmp))
            server = build_mcp_server(registry)
            prompt_names = {prompt["name"] for prompt in server.list_prompts()}
        self.assertEqual(len(prompt_names), 7)
        self.assertEqual(
            prompt_names,
            {
                "review_current_estimator_context",
                "review_takeoff_scope",
                "review_bid_scope",
                "review_page_qa",
                "review_markup_and_links",
                "review_overlay_and_pdf_context",
                "review_quantity_variance",
            },
        )


if __name__ == "__main__":
    unittest.main()
