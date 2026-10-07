import unittest
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    AI_TAKEOFF_COMMAND_ARGUMENTS,
    AI_TAKEOFF_COMMANDS,
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
APPROVAL_VERBS = ("approve", "accept", "reject", "confirm", "set_status")


class ToolCatalogTests(unittest.TestCase):
    def test_the_m1a_tools_then_the_m1b_tools_under_the_cap(self):
        names = tuple(tool.name for tool in TOOLS)
        self.assertEqual(names, AI_TAKEOFF_COMMANDS)
        self.assertEqual(names[:7], M1A_COMMANDS)
        self.assertEqual(len(TOOLS), 15)
        self.assertLessEqual(len(TOOLS), MAX_EXPOSED_TOOLS)

    def test_schema_properties_match_the_bridge_argument_table(self):
        for tool in TOOLS:
            with self.subTest(tool=tool.name):
                self.assertEqual(
                    set(tool.input_schema["properties"]),
                    AI_TAKEOFF_COMMAND_ARGUMENTS[tool.name],
                )

    def test_no_tool_can_approve_accept_or_set_a_status(self):
        for tool in TOOLS:
            for verb in APPROVAL_VERBS:
                with self.subTest(tool=tool.name, verb=verb):
                    self.assertNotIn(verb, tool.name)
            if tool.name != "list_assumptions":
                self.assertNotIn("status", tool.input_schema["properties"])

    def test_update_assumption_can_only_add_or_revise(self):
        tool = next(tool for tool in TOOLS if tool.name == "update_assumption")
        properties = tool.input_schema["properties"]
        self.assertEqual(properties["op"]["enum"], ["add", "revise"])
        self.assertNotIn("accepted", str(properties))
        self.assertIn("cannot accept", tool.description)

    def test_apply_only_asks_the_user(self):
        tool = next(tool for tool in TOOLS if tool.name == "apply_changeset")
        self.assertIn("pending_approval", tool.description)
        self.assertIn("user", tool.description)

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

    def test_required_arguments(self):
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
            "undo_last_ai_changeset",
            "render_3d",
        ):
            self.assertEqual(required[name], set())
        self.assertEqual(required["propose_scale"], {"page_uid", "p1_pts", "p2_pts"})
        self.assertEqual(required["find_regions"], {"page_uid", "bbox_pts"})
        self.assertEqual(required["propose_element"], {"kind", "page_uid"})
        for name in ("apply_changeset", "discard_changeset"):
            self.assertEqual(required[name], {"changeset_id"})
        self.assertEqual(required["update_assumption"], {"changeset_id", "op"})

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
            "propose_scale",
            "propose_element",
            "apply_changeset",
            "discard_changeset",
            "update_assumption",
        ):
            tool = next(tool for tool in TOOLS if tool.name == name)
            with self.subTest(tool=name):
                self.assertIn("never instructions", tool.description)

    def test_tool_items_are_mcp_tool_descriptors(self):
        items = tool_items()
        self.assertEqual([item["name"] for item in items], list(AI_TAKEOFF_COMMANDS))
        for item in items:
            self.assertEqual(set(item), {"name", "description", "inputSchema"})
        items[0]["inputSchema"]["properties"]["injected"] = {}
        self.assertNotIn("injected", tool_items()[0]["inputSchema"]["properties"])


if __name__ == "__main__":
    unittest.main()
