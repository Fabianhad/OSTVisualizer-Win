import ast
import dataclasses
import sys
import unittest
from pathlib import Path
from ost_visualizer.application.dtos import ai_takeoff_dtos as dtos
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    M1A_COMMANDS,
    ResultMeta,
    UntrustedText,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    error_result,
    ok_result,
)


class UntrustedTextTests(unittest.TestCase):
    def test_short_text_is_kept_and_marked_untrusted(self):
        text = UntrustedText.of('SLAB 8" T.O.S. 100\'-0"')
        self.assertEqual(
            text.to_dict(),
            {"value": 'SLAB 8" T.O.S. 100\'-0"', "untrusted": True, "truncated": False},
        )

    def test_long_text_is_capped_and_flagged(self):
        text = UntrustedText.of("x" * (dtos.UNTRUSTED_TEXT_MAX_CHARS + 25))
        self.assertEqual(len(text.value), dtos.UNTRUSTED_TEXT_MAX_CHARS)
        self.assertTrue(text.truncated)

    def test_lone_surrogates_are_replaced_so_the_value_is_always_utf8(self):
        text = UntrustedText.of('SLAB \ud800 8" \udfff')
        self.assertEqual(text.value, 'SLAB \ufffd 8" \ufffd')
        text.value.encode("utf-8")
        paired = UntrustedText.of("\U0001f600 \u2265 \xd8")
        self.assertEqual(paired.value, "\U0001f600 \u2265 \xd8")

    def test_control_and_bidi_formatting_characters_are_stripped(self):
        raw = (
            'SLAB\x00 8\x07"\x1b[31m T.O.S.\x7f\x85\x9b '
            "\u202eGNIDLIUB\u202c \u2066x\u2069\u200e\u200f\u061c"
        )
        self.assertEqual(UntrustedText.of(raw).value, 'SLAB 8"[31m T.O.S. GNIDLIUB x')
        self.assertEqual(UntrustedText.of("A\tB\nC\r\nD").value, "A B C  D")
        kept = '\xd8 12" \u2265 \xbd \u5e73\u9762 \U0001f600 \u200d'
        self.assertEqual(UntrustedText.of(kept).value, kept)

    def test_every_bidi_formatting_character_is_stripped(self):
        bidi = (
            "\u061c",
            "\u200e",
            "\u200f",
            "\u202a",
            "\u202b",
            "\u202c",
            "\u202d",
            "\u202e",
            "\u2066",
            "\u2067",
            "\u2068",
            "\u2069",
        )
        for character in bidi:
            with self.subTest(code_point=f"U+{ord(character):04X}"):
                value = UntrustedText.of("A" + character + "B").value
                self.assertEqual(value.encode("unicode_escape"), b"AB")

    def test_whitespace_controls_become_spaces(self):
        for character in ("\t", "\n", "\r", "\x0b", "\x0c"):
            with self.subTest(code_point=f"U+{ord(character):04X}"):
                value = UntrustedText.of("A" + character + "B").value
                self.assertEqual(value.encode("unicode_escape"), b"A B")

    def test_c1_controls_are_stripped(self):
        for character in ("\x80", "\x85", "\x9b", "\x9f"):
            with self.subTest(code_point=f"U+{ord(character):04X}"):
                value = UntrustedText.of("A" + character + "B").value
                self.assertEqual(value.encode("unicode_escape"), b"AB")

    def test_stripping_happens_before_the_length_cap(self):
        text = UntrustedText.of("\u202e" * 600 + "visible")
        self.assertEqual((text.value, text.truncated), ("visible", False))

    def test_the_cap_is_five_hundred_characters(self):
        self.assertEqual(dtos.UNTRUSTED_TEXT_MAX_CHARS, 500)
        at_cap = UntrustedText.of("y" * 500)
        self.assertEqual((len(at_cap.value), at_cap.truncated), (500, False))
        over = UntrustedText.of("y" * 501)
        self.assertEqual((len(over.value), over.truncated), (500, True))

    def test_none_and_non_text_values_become_strings(self):
        self.assertEqual(UntrustedText.of(None).value, "")
        self.assertEqual(UntrustedText.of(12).value, "12")


class EnvelopeTests(unittest.TestCase):
    def test_ok_result_carries_status_data_and_meta(self):
        meta = ResultMeta(limit=2, returned_count=2, total_count=5, next_cursor="c:2")
        result = ok_result({"items": [1, 2]}, status=dtos.STATUS_TRUNCATED, meta=meta)
        self.assertEqual(
            result,
            {
                "success": True,
                "status": "truncated",
                "data": {"items": [1, 2]},
                "meta": {
                    "limit": 2,
                    "returned_count": 2,
                    "total_count": 5,
                    "truncated": True,
                    "has_more": True,
                    "next_cursor": "c:2",
                },
            },
        )
        self.assertNotIn("meta", ok_result({}))

    def test_meta_without_a_next_cursor_is_complete(self):
        meta = ResultMeta(limit=10, returned_count=3, total_count=3).to_dict()
        self.assertFalse(meta["truncated"])
        self.assertFalse(meta["has_more"])
        self.assertIsNone(meta["next_cursor"])

    def test_error_result_shape(self):
        self.assertEqual(
            error_result(dtos.ERROR_UNAUTHORIZED, "Session token rejected."),
            {
                "success": False,
                "status": "unauthorized",
                "error": {"code": "unauthorized", "message": "Session token rejected."},
            },
        )


class CursorAndLimitTests(unittest.TestCase):
    def test_cursor_round_trip_and_start(self):
        self.assertEqual(decode_cursor(None), 0)
        self.assertEqual(decode_cursor(""), 0)
        self.assertEqual(decode_cursor(encode_cursor(125)), 125)

    def test_invalid_cursors_are_rejected(self):
        for cursor in ("125", "c:-1", "c:abc", "x:3", 7):
            with self.subTest(cursor=cursor):
                with self.assertRaises(ValueError):
                    decode_cursor(cursor)

    def test_limits_are_clamped(self):
        self.assertEqual(clamp_limit(None), dtos.DEFAULT_LIMIT)
        self.assertEqual(clamp_limit(0), 1)
        self.assertEqual(clamp_limit(10**6), dtos.MAX_LIMIT)
        self.assertEqual(clamp_limit(25), 25)
        self.assertEqual(clamp_limit(None), 100)
        self.assertEqual(clamp_limit(500), 500)
        self.assertEqual(clamp_limit(501), 500)
        self.assertEqual(clamp_limit(1), 1)
        with self.assertRaises(ValueError):
            clamp_limit("many")
        with self.assertRaises(ValueError):
            clamp_limit(True)


class ContractTests(unittest.TestCase):
    def test_m1a_commands_are_the_seven_read_only_tools(self):
        self.assertEqual(
            M1A_COMMANDS,
            (
                "list_sheets",
                "render_sheet",
                "list_text",
                "list_segments",
                "get_quantities",
                "list_levels",
                "list_assumptions",
            ),
        )
        self.assertLessEqual(len(M1A_COMMANDS), dtos.MAX_EXPOSED_TOOLS)

    def test_sidecar_statuses(self):
        self.assertEqual(
            dtos.SIDECAR_STATUSES,
            (
                "ok",
                "empty",
                "rebind_required",
                "fingerprint_mismatch",
                "corrupt",
                "unavailable_no_database_guid",
            ),
        )

    def test_limits_and_caps(self):
        self.assertEqual(dtos.MAX_EXPOSED_TOOLS, 20)
        self.assertEqual(dtos.INLINE_RESPONSE_MAX_BYTES, 256 * 1024)
        self.assertEqual(dtos.RENDER_MAX_DPI, 200.0)
        self.assertEqual(dtos.RENDER_MAX_LONG_SIDE_PX, 1600)

    def test_request_errors_carry_code_and_message(self):
        error = dtos.AiTakeoffRequestError(dtos.ERROR_NOT_FOUND, "Page not found.")
        self.assertIsInstance(error, ValueError)
        self.assertEqual(str(error), "Page not found.")
        self.assertEqual((error.code, error.message), ("not_found", "Page not found."))

    def test_value_objects_are_immutable(self):
        page = dtos.PageSnapshot("p1", "a.pdf", 0, 612.0, 792.0, None, True)
        plan = dtos.CropPlan("p1", "a.pdf", 0, (0, 0, 1, 1), 1.0, 1, 1, (), None)
        text = UntrustedText.of("x")
        meta = ResultMeta(limit=1, returned_count=1, total_count=1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            page.is_pdf = False
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.scale = 2.0
        with self.assertRaises(dataclasses.FrozenInstanceError):
            text.value = "y"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            meta.next_cursor = "c:1"

    def test_module_imports_only_stdlib(self):
        tree = ast.parse(Path(dtos.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                roots = [node.module.split(".")[0]]
            else:
                continue
            for root in roots:
                self.assertIn(root, sys.stdlib_module_names)


class WireContractLiteralsTests(unittest.TestCase):
    """The names a client and the app must agree on, written out literally."""

    def test_storage_and_pipe_names(self):
        from ost_visualizer.application.dtos import ai_takeoff_dtos as dtos

        self.assertEqual(
            (
                dtos.AI_TAKEOFF_BRIDGE_SERVER_NAME,
                dtos.APP_DATA_DIR_NAME,
                dtos.AI_TAKEOFF_DIR_NAME,
                dtos.AI_TAKEOFF_SESSION_TOKEN_FILE_NAME,
                dtos.AI_TAKEOFF_SIDECAR_DIR_NAME,
                dtos.AI_TAKEOFF_OUTPUT_DIR_NAME,
            ),
            (
                "OSTVisualizerTakeoffBridge.v1",
                ".ost_visualizer",
                "ai_takeoff",
                "session.token",
                "bids",
                "mcp_takeoff_outputs",
            ),
        )

    def test_render_and_timeout_limits(self):
        from ost_visualizer.application.dtos import ai_takeoff_dtos as dtos

        self.assertEqual(dtos.RENDER_DEFAULT_DPI, 100.0)
        self.assertEqual(dtos.RENDER_MAX_DPI, 200.0)
        self.assertEqual(dtos.RENDER_MAX_LONG_SIDE_PX, 1600)
        self.assertEqual(dtos.PIPE_READ_TIMEOUT_SECONDS, 120.0)
        self.assertEqual(dtos.INLINE_RESPONSE_MAX_BYTES, 262144)
        self.assertEqual((dtos.DEFAULT_LIMIT, dtos.MAX_LIMIT), (100, 500))

    def test_command_names_and_the_argument_each_command_accepts(self):
        from ost_visualizer.application.dtos import ai_takeoff_dtos as dtos

        expected = {
            "list_sheets": {"bid_uid", "cursor", "limit", "text_hints"},
            "render_sheet": {"page_uid", "crop_pts", "dpi", "overlay_ids"},
            "list_text": {"page_uid", "bbox_pts", "query", "cursor", "limit"},
            "list_segments": {"page_uid", "bbox_pts", "kinds", "cursor", "limit"},
            "get_quantities": {"bid_uid", "group_by"},
            "list_levels": {"bid_uid"},
            "list_assumptions": {"bid_uid", "status"},
            "propose_scale": {
                "page_uid",
                "p1_pts",
                "p2_pts",
                "real_in",
                "preset",
                "reason",
                "sheet_ref",
            },
            "find_regions": {
                "page_uid",
                "bbox_pts",
                "gap_close_in",
                "max_gap_in",
                "seed_pts",
                "min_width",
                "exclude_dashed",
                "exclude_thin_curves",
                "colors",
                "min_area_sf",
                "symbol_max_pts",
                "cursor",
                "limit",
                "boundary_kinds",
            },
            "propose_element": {
                "kind",
                "page_uid",
                "polygon_ost",
                "region_id",
                "holes_ost",
                "thickness_in",
                "top_elev_in",
                "level_id",
                "name",
                "summary",
                "condition_uid",
            },
            "apply_changeset": {"changeset_id"},
            "discard_changeset": {"changeset_id"},
            "undo_last_ai_changeset": {"bid_uid", "changeset_id"},
            "render_3d": {"bid_uid", "view"},
            "update_assumption": {
                "changeset_id",
                "op",
                "assumption_id",
                "subject",
                "target_key",
                "value",
                "reason",
                "sheet_ref",
                "length_in",
            },
        }
        self.assertEqual(dtos.AI_TAKEOFF_COMMANDS, tuple(expected))
        self.assertEqual(
            {
                name: set(args)
                for name, args in dtos.AI_TAKEOFF_COMMAND_ARGUMENTS.items()
            },
            expected,
        )
        self.assertEqual(dtos.M1A_COMMANDS, tuple(expected)[:7])
        self.assertEqual(dtos.M1B_COMMANDS, tuple(expected)[7:])
        self.assertEqual(dtos.LINE_KIND_NAMES, ("wall", "dashed", "thin", "symbol"))

    def test_status_error_and_sidecar_codes(self):
        from ost_visualizer.application.dtos import ai_takeoff_dtos as dtos

        self.assertEqual(
            (
                dtos.STATUS_OK,
                dtos.STATUS_EMPTY,
                dtos.STATUS_TRUNCATED,
                dtos.STATUS_NOT_PDF,
                dtos.OVERLAY_NOT_SUPPORTED_UNTIL_M1B,
            ),
            ("ok", "empty", "truncated", "not_pdf", "not_supported_until_m1b"),
        )
        self.assertEqual(
            (
                dtos.ERROR_APP_NOT_RUNNING,
                dtos.ERROR_UNAUTHORIZED,
                dtos.ERROR_FEATURE_DENIED,
                dtos.ERROR_UNKNOWN_COMMAND,
                dtos.ERROR_INVALID_ARGUMENT,
                dtos.ERROR_BID_NOT_OPEN,
                dtos.ERROR_NOT_FOUND,
                dtos.ERROR_MALFORMED_RESPONSE,
                dtos.ERROR_UNEXPECTED,
                dtos.ERROR_APP_TIMEOUT,
                dtos.ERROR_BUSY,
            ),
            (
                "app_not_running",
                "unauthorized",
                "feature_denied",
                "unknown_command",
                "invalid_argument",
                "bid_not_open",
                "not_found",
                "malformed_bridge_response",
                "unexpected_error",
                "app_timeout",
                "busy",
            ),
        )
        self.assertEqual(
            dtos.SIDECAR_STATUSES,
            (
                "ok",
                "empty",
                "rebind_required",
                "fingerprint_mismatch",
                "corrupt",
                "unavailable_no_database_guid",
            ),
        )
        self.assertEqual(
            (dtos.MAX_REGIONS_PER_PAGE, dtos.SYMBOL_MAX_PTS_DEFAULT), (50, 48)
        )

    def test_coordinate_space_declarations(self):
        from ost_visualizer.application.dtos import ai_takeoff_dtos as dtos

        down, up, inches = "page_pts_y_down", "pdf_pts_y_up", "ost_inches"
        self.assertEqual(dtos.COORDINATE_SPACE_KEY, "coordinate_space")
        self.assertEqual(
            (
                dtos.COORD_PDF_PTS_Y_UP,
                dtos.COORD_PAGE_PTS_Y_DOWN,
                dtos.COORD_OST_INCHES,
            ),
            (up, down, inches),
        )
        self.assertEqual(dtos.COORD_MODEL_UNITS, "model_units")
        self.assertEqual(
            dtos.list_text_coordinate_space(), {"bbox_pts": down, "bbox_ost": inches}
        )
        self.assertEqual(
            dtos.list_segments_coordinate_space(),
            {"p1_pts": down, "p2_pts": down, "p1_ost": inches, "p2_ost": inches},
        )
        self.assertEqual(
            dtos.sheet_hints_coordinate_space(),
            {
                "sheets[].text_hints.sheet_number_bbox_pts": down,
                "sheets[].text_hints.scale_candidates[].bbox_pts": down,
                "sheets[].text_hints.title_block_crop_pts": down,
            },
        )
        self.assertEqual(
            dtos.find_regions_coordinate_space(),
            {
                "regions[].polygon_ost": inches,
                "regions[].holes_ost": inches,
                "regions[].gaps[].p1_pts": down,
                "regions[].gaps[].p2_pts": down,
                "suppressed_symbols_pts": down,
            },
        )
        self.assertEqual(
            dtos.render_3d_coordinate_space(),
            {"bbox_model": "model_units", "px_to_model": "model_units"},
        )
        self.assertEqual(
            dtos.pdf_pts_coordinate_space("runs", ("bbox_pts", "origin")),
            {"runs[].bbox_pts": up, "runs[].origin": up},
        )

    def test_cursor_and_limit_text(self):
        from ost_visualizer.application.dtos import ai_takeoff_dtos as dtos

        self.assertEqual(dtos.encode_cursor(25), "c:25")
        self.assertEqual(dtos.decode_cursor("c:25"), 25)
        for bad in ("25", "x:25", "c:", "c:-1", "c:2.5", 7):
            with self.subTest(cursor=bad):
                with self.assertRaises(ValueError) as raised:
                    dtos.decode_cursor(bad)
                self.assertEqual(str(raised.exception), "Invalid cursor")
        with self.assertRaises(ValueError) as raised:
            dtos.clamp_limit("5")
        self.assertEqual(str(raised.exception), "limit must be an integer")

    def test_invisible_formatting_characters_are_removed_and_whitespace_controls_spaced(
        self,
    ):
        from ost_visualizer.application.dtos.ai_takeoff_dtos import UntrustedText

        bidi = (
            "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
        )
        self.assertEqual(UntrustedText.of("a" + bidi + "b").value, "ab")
        self.assertEqual(UntrustedText.of("a\tb\nc\rd\x0be\x0cf").value, "a b c d e f")
        self.assertEqual(UntrustedText.of("AXB X").value, "AXB X")


if __name__ == "__main__":
    unittest.main()
