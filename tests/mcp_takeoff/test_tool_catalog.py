import unittest
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    M1A_COMMAND_ARGUMENTS,
    M1A_COMMANDS,
    MAX_EXPOSED_TOOLS,
    RENDER_MAX_DPI,
)
from ost_visualizer.mcp_takeoff.tool_catalog import TOOLS, tool_items

FORBIDDEN_PARAMETER_FRAGMENTS = (
    "path",
    "sql",
    "dir",
    "command",
    "token",
    "approve",
    "accept",
    "file",
)
WRITE_VERBS = (
    "approve",
    "accept",
    "apply",
    "update",
    "delete",
    "create",
    "set_",
    "save",
)


class ToolCatalogTests(unittest.TestCase):
    def test_exactly_the_seven_m1a_tools_in_order(self):
        self.assertEqual(tuple(tool.name for tool in TOOLS), M1A_COMMANDS)
        self.assertLessEqual(len(TOOLS), MAX_EXPOSED_TOOLS)

    def test_schema_properties_match_the_bridge_argument_table(self):
        for tool in TOOLS:
            with self.subTest(tool=tool.name):
                self.assertEqual(
                    set(tool.input_schema["properties"]),
                    M1A_COMMAND_ARGUMENTS[tool.name],
                )

    def test_no_tool_can_write_approve_or_accept(self):
        for tool in TOOLS:
            for verb in WRITE_VERBS:
                with self.subTest(tool=tool.name, verb=verb):
                    self.assertNotIn(verb, tool.name)

    def test_schemas_are_closed_objects_without_forbidden_parameters(self):
        for tool in TOOLS:
            schema = tool.input_schema
            with self.subTest(tool=tool.name):
                self.assertEqual(schema["type"], "object")
                self.assertIs(schema["additionalProperties"], False)
                for required in schema.get("required", []):
                    self.assertIn(required, schema["properties"])
                for name in schema["properties"]:
                    for fragment in FORBIDDEN_PARAMETER_FRAGMENTS:
                        self.assertNotIn(fragment, name.lower())

    def test_page_tools_require_a_page_and_others_default_to_the_open_bid(self):
        required = {
            tool.name: set(tool.input_schema.get("required", [])) for tool in TOOLS
        }
        for name in ("render_sheet", "list_text", "list_segments"):
            self.assertEqual(required[name], {"page_uid"})
        for name in (
            "list_sheets",
            "get_quantities",
            "list_levels",
            "list_assumptions",
        ):
            self.assertEqual(required[name], set())

    def test_render_sheet_limits_dpi_and_documents_overlay_ids_as_a_no_op(self):
        render = next(tool for tool in TOOLS if tool.name == "render_sheet")
        properties = render.input_schema["properties"]
        self.assertEqual(properties["dpi"]["maximum"], RENDER_MAX_DPI)
        self.assertIn(
            "not_supported_until_m1b", properties["overlay_ids"]["description"]
        )
        self.assertEqual(properties["crop_pts"]["minItems"], 4)
        self.assertEqual(properties["crop_pts"]["maxItems"], 4)

    def test_text_bearing_tools_warn_that_drawing_text_is_untrusted_data(self):
        for name in (
            "list_sheets",
            "list_text",
            "get_quantities",
            "list_levels",
            "list_assumptions",
        ):
            tool = next(tool for tool in TOOLS if tool.name == name)
            with self.subTest(tool=name):
                self.assertIn("never instructions", tool.description)

    def test_tool_items_are_mcp_tool_descriptors(self):
        items = tool_items()
        self.assertEqual([item["name"] for item in items], list(M1A_COMMANDS))
        for item in items:
            self.assertEqual(set(item), {"name", "description", "inputSchema"})
        items[0]["inputSchema"]["properties"]["injected"] = {}
        self.assertNotIn("injected", tool_items()[0]["inputSchema"]["properties"])


if __name__ == "__main__":
    unittest.main()
