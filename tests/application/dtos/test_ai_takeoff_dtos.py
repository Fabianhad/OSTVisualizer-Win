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


if __name__ == "__main__":
    unittest.main()
