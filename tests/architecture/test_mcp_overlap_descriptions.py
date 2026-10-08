import logging
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    COORD_MODEL_UNITS,
    COORD_OST_INCHES,
    COORD_PAGE_PTS_Y_DOWN,
    COORD_PDF_PTS_Y_UP,
)
from ost_visualizer.mcp_server.registry import DatabaseRegistry
from ost_visualizer.mcp_server.server import build_mcp_server
from ost_visualizer.mcp_takeoff.tool_catalog import TOOLS
from ost_visualizer.presentation.utils.mcp_setup_config import (
    MCP_SERVER_NAME,
    TAKEOFF_MCP_SERVER_NAME,
)

READ_SERVER = "ost-visualizer"
TAKEOFF_SERVER = "ost-takeoff"
TAKEOFF_TO_READ = {
    "list_sheets": ("list_pages",),
    "list_text": ("get_page_pdf_text_summary", "search_page_pdf_text"),
    "list_segments": ("get_page_pdf_vectors_summary",),
    "get_quantities": (
        "summarize_quantities",
        "get_bid_quantity_summary",
        "get_summary",
    ),
}
READ_TO_TAKEOFF = {
    "list_pages": ("list_sheets",),
    "get_page_metadata": ("list_sheets",),
    "get_page_context": ("list_sheets",),
    "search_pages": ("list_sheets",),
    "get_page_pdf_text_summary": ("list_text",),
    "search_page_pdf_text": ("list_text",),
    "get_page_pdf_vectors_summary": ("list_segments",),
    "summarize_quantities": ("get_quantities",),
    "get_page_quantity_summary": ("get_quantities",),
    "get_bid_quantity_summary": ("get_quantities",),
    "get_summary": ("get_quantities",),
}
READ_QUANTITY_TOOLS = (
    "summarize_quantities",
    "get_page_quantity_summary",
    "get_bid_quantity_summary",
    "get_summary",
)
TAKEOFF_WRITE_TOOLS = ("apply_changeset", "undo_last_ai_changeset")
READ_SPACE_TOOLS = (
    "get_page_pdf_text_summary",
    "search_page_pdf_text",
    "get_page_pdf_vectors_summary",
)
TAKEOFF_SPACES = {
    "list_text": "page_pts_y_down",
    "list_segments": "page_pts_y_down",
    "find_regions": "ost_inches",
    "render_3d": "model_units",
}


def _read_descriptions():
    logger = logging.getLogger("test.mcp_overlap_descriptions")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    with tempfile.TemporaryDirectory() as directory:
        server = build_mcp_server(
            DatabaseRegistry(app_data_dir=Path(directory), logger=logger),
            logger=logger,
        )
        return {tool["name"]: tool["description"] for tool in server.list_tools()}


class McpOverlapDescriptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.read = _read_descriptions()
        cls.takeoff = {tool.name: tool.description for tool in TOOLS}

    def test_server_names_are_the_documented_prefixes(self):
        self.assertEqual(MCP_SERVER_NAME, READ_SERVER)
        self.assertEqual(TAKEOFF_MCP_SERVER_NAME, TAKEOFF_SERVER)

    def test_coordinate_space_ids_are_the_documented_strings(self):
        self.assertEqual(
            (
                COORD_PDF_PTS_Y_UP,
                COORD_PAGE_PTS_Y_DOWN,
                COORD_OST_INCHES,
                COORD_MODEL_UNITS,
            ),
            ("pdf_pts_y_up", "page_pts_y_down", "ost_inches", "model_units"),
        )

    def test_overlapping_takeoff_tools_name_their_role_and_point_at_the_read_server(
        self,
    ):
        for name, counterparts in TAKEOFF_TO_READ.items():
            with self.subTest(tool=name):
                description = self.takeoff[name]
                self.assertIn("Use when", description)
                self.assertIn(f"({TAKEOFF_SERVER} server)", description)
                self.assertIn(f"{READ_SERVER} server", description)
                for counterpart in counterparts:
                    self.assertIn(counterpart, description)
                    self.assertIn(counterpart, self.read)

    def test_overlapping_read_tools_name_their_role_and_point_at_the_takeoff_server(
        self,
    ):
        for name, counterparts in READ_TO_TAKEOFF.items():
            with self.subTest(tool=name):
                description = self.read[name]
                self.assertIn("Use when", description)
                self.assertIn(f"({READ_SERVER} server, read-only)", description)
                self.assertIn(f"{TAKEOFF_SERVER} server", description)
                for counterpart in counterparts:
                    self.assertIn(counterpart, description)
                    self.assertIn(counterpart, self.takeoff)

    def test_the_live_context_tool_links_the_two_servers_bid_identifiers(self):
        description = self.read["get_current_context"]
        self.assertIn(TAKEOFF_SERVER, description)
        self.assertIn("bid_uid", description)

    def test_tools_that_change_or_read_quantities_warn_about_the_read_lag(self):
        for name in TAKEOFF_WRITE_TOOLS:
            with self.subTest(tool=name):
                self.assertIn("few seconds", self.takeoff[name])
                self.assertIn(READ_SERVER, self.takeoff[name])
        for name in READ_QUANTITY_TOOLS:
            with self.subTest(tool=name):
                self.assertIn("few seconds", self.read[name])
                self.assertIn("get_quantities", self.read[name])

    def test_coordinate_tools_name_their_coordinate_space(self):
        for name in READ_SPACE_TOOLS:
            with self.subTest(tool=name):
                self.assertIn("pdf_pts_y_up", self.read[name])
        for name, space in TAKEOFF_SPACES.items():
            with self.subTest(tool=name):
                self.assertIn(space, self.takeoff[name])

    def test_coordinate_tools_state_how_page_rotation_is_treated(self):
        for name in READ_SPACE_TOOLS:
            with self.subTest(tool=name):
                self.assertIn("unrotated", self.read[name])
        for name in ("list_text", "list_segments"):
            with self.subTest(tool=name):
                self.assertIn("rotation applied", self.takeoff[name])

    def test_the_bid_comparison_says_it_compares_visible_quantities(self):
        description = self.read["compare_bids_by_ref_no"]
        self.assertIn("visible", description)
        self.assertIn("hidden", description)

    def test_descriptions_are_single_line_text(self):
        for descriptions in (self.read, self.takeoff):
            for name, description in descriptions.items():
                with self.subTest(tool=name):
                    self.assertEqual(description, " ".join(description.split()))


if __name__ == "__main__":
    unittest.main()
