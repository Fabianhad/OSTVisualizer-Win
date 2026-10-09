import dataclasses
import unittest
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    AI_TAKEOFF_COMMAND_ARGUMENTS,
    AI_TAKEOFF_COMMANDS,
    M1A_COMMANDS,
    MAX_EXPOSED_TOOLS,
    MAX_LIMIT,
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
            "render_3d",
        ):
            self.assertEqual(required[name], set())
        self.assertEqual(required["propose_scale"], {"page_uid", "p1_pts", "p2_pts"})
        self.assertEqual(required["find_regions"], {"page_uid", "bbox_pts"})
        self.assertEqual(required["propose_element"], {"kind", "page_uid"})
        for name in ("apply_changeset", "discard_changeset", "undo_last_ai_changeset"):
            self.assertEqual(required[name], {"changeset_id"})
        self.assertEqual(required["update_assumption"], {"changeset_id", "op"})

    def test_tools_without_required_arguments_omit_the_required_list(self):
        for tool in TOOLS:
            with self.subTest(tool=tool.name):
                required = tool.input_schema.get("required")
                self.assertTrue(required is None or len(required) > 0)
        list_sheets = next(tool for tool in TOOLS if tool.name == "list_sheets")
        self.assertNotIn("required", list_sheets.input_schema)

    def test_shared_argument_schemas_bound_counts_and_lengths(self):
        schemas = {tool.name: tool.input_schema["properties"] for tool in TOOLS}
        self.assertEqual(
            schemas["list_sheets"]["limit"],
            {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
        )
        bbox = schemas["list_text"]["bbox_pts"]
        self.assertEqual((bbox["minItems"], bbox["maxItems"]), (4, 4))
        point = schemas["propose_scale"]["p1_pts"]
        self.assertEqual((point["minItems"], point["maxItems"]), (2, 2))
        polygon = schemas["propose_element"]["polygon_ost"]
        self.assertEqual(polygon["minItems"], 6)
        self.assertNotIn("maxItems", polygon)
        for name, argument in (
            ("propose_scale", "reason"),
            ("propose_element", "summary"),
            ("update_assumption", "value"),
        ):
            with self.subTest(tool=name, argument=argument):
                self.assertEqual(
                    schemas[name][argument], {"type": "string", "maxLength": 500}
                )

    def test_numeric_write_arguments_have_their_documented_ranges(self):
        schemas = {tool.name: tool.input_schema["properties"] for tool in TOOLS}
        self.assertEqual(schemas["render_sheet"]["dpi"]["minimum"], 1)
        self.assertEqual(schemas["propose_scale"]["real_in"]["exclusiveMinimum"], 0)
        self.assertEqual(
            schemas["find_regions"]["gap_close_in"],
            {"type": "number", "minimum": 0, "maximum": 48},
        )
        self.assertEqual(
            schemas["propose_element"]["thickness_in"],
            {"type": "number", "exclusiveMinimum": 0},
        )
        self.assertEqual(
            schemas["propose_element"]["name"], {"type": "string", "maxLength": 200}
        )
        self.assertEqual(
            schemas["update_assumption"]["length_in"], {"type": "number", "minimum": 0}
        )

    def test_list_segments_offers_line_attributes_and_a_kind_filter(self):
        tool = next(tool for tool in TOOLS if tool.name == "list_segments")
        self.assertEqual(
            tool.input_schema["properties"]["kinds"],
            {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["wall", "dashed", "thin", "symbol"],
                },
                "description": "Keep only these kind guesses.",
            },
        )
        for word in (
            "width_pts",
            "dash_pts",
            "color",
            "paint",
            "curve",
            "kind",
            "new_fields",
        ):
            with self.subTest(word=word):
                self.assertIn(word, tool.description)
        self.assertNotIn("not available yet", tool.description)

    def test_find_regions_filters_paging_and_workflow(self):
        tool = next(tool for tool in TOOLS if tool.name == "find_regions")
        properties = tool.input_schema["properties"]
        self.assertEqual(
            properties["max_gap_in"], {"type": "number", "minimum": 0, "maximum": 48}
        )
        self.assertEqual(properties["min_width"]["type"], "number")
        self.assertEqual(properties["min_width"]["minimum"], 0)
        self.assertEqual(properties["exclude_dashed"]["type"], "boolean")
        self.assertIs(properties["exclude_dashed"]["default"], True)
        self.assertEqual(
            properties["exclude_thin_curves"], {"type": "boolean", "default": True}
        )
        self.assertEqual(
            properties["colors"]["items"],
            {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
        )
        self.assertEqual(properties["min_area_sf"]["minimum"], 0)
        self.assertEqual(properties["symbol_max_pts"]["minimum"], 0)
        self.assertEqual(properties["symbol_max_pts"]["default"], 48)
        self.assertEqual(
            properties["limit"], {"type": "integer", "minimum": 1, "maximum": 50}
        )
        self.assertIn("cursor", properties)
        for phrase in (
            "largest first",
            "total_count",
            "next_cursor",
            "list_segments",
            "seed_pts",
            "closing-segment assumption",
            "12 in",
            "suppressed_symbol_count",
            "door swings",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, tool.description)

    def test_m2_1_fields_are_described(self):
        tools = {tool.name: tool for tool in TOOLS}
        hints = tools["list_sheets"].input_schema["properties"]["text_hints"]
        self.assertEqual(hints["type"], "boolean")
        self.assertIs(hints["default"], False)
        expected = {
            "list_sheets": (
                "text_hints",
                "text_extractable",
                "title_block_crop_pts",
                "scale_candidates",
                "plan_scale",
                "25",
                "render_sheet",
            ),
            "list_segments": ("suggested_min_width", "extraction_scope"),
            "find_regions": (
                "suggested_min_width",
                "min_width_source",
                "min_width 0",
                "extraction_scope",
                "truncated",
            ),
            "propose_scale": ("dimension_check", "2%"),
            "propose_element": ("geometry", "0.25 in", "0.1%", "holes_dropped"),
        }
        for name, phrases in expected.items():
            for phrase in phrases:
                with self.subTest(tool=name, phrase=phrase):
                    self.assertIn(phrase, tools[name].description)
        self.assertIn(
            "0 turns",
            tools["find_regions"].input_schema["properties"]["min_width"][
                "description"
            ],
        )

    def test_dashed_boundaries_and_leaks_are_described(self):
        tools = {tool.name: tool for tool in TOOLS}
        kinds = tools["find_regions"].input_schema["properties"]["boundary_kinds"]
        self.assertEqual(
            kinds,
            {
                "type": "array",
                "items": {"type": "string", "enum": ["wall", "dashed", "thin"]},
                "minItems": 1,
                "description": kinds["description"],
            },
        )
        self.assertIn('["dashed"]', kinds["description"])
        expected = {
            "find_regions": (
                "mat, footing or below-grade",
                "callouts",
                'boundary_kinds ["dashed"]',
                "dash_bridge_count",
                "at most 18 pt",
                "dashed_outline",
                "open_gaps",
                "leak_risk true",
                "72 in",
                "holes_ost",
                "dashed_analysis",
                "skipped_time_budget",
                "20 s",
            ),
            "propose_element": (
                "open_gaps",
                "dashed_outline",
                "high-impact",
                "mat, footing or below-grade",
                "callouts",
                "holes_ost",
            ),
        }
        for name, phrases in expected.items():
            for phrase in phrases:
                with self.subTest(tool=name, phrase=phrase):
                    self.assertIn(phrase, tools[name].description)
        self.assertEqual(len(TOOLS), 15)

    def test_tool_specs_are_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            TOOLS[0].name = "approve_changeset"

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
