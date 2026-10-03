import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.mcp_server import output_artifacts as output_module
from ost_visualizer.mcp_server.output_artifacts import (
    JSON_OUTPUT_SUFFIX,
    MCP_OUTPUT_DIR_NAME,
    TEXT_OUTPUT_SUFFIX,
    McpOutputFormatter,
)

LONG_TEXT = "log line\n" * 40
LONG_JSON_VALUE = "x" * 200


class McpOutputArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output_dir = Path(self.tmp.name) / MCP_OUTPUT_DIR_NAME
        self.clock = lambda: datetime(2026, 7, 7, 12, 30, 45, 123456)
        self.nonce_factory = lambda: "fixed-id"

    def formatter(self, inline_max_chars=80, preview_max_chars=30):
        return McpOutputFormatter(
            self.output_dir,
            inline_max_chars=inline_max_chars,
            preview_max_chars=preview_max_chars,
            clock=self.clock,
            nonce_factory=self.nonce_factory,
        )

    def test_short_output_remains_inline_without_file(self):
        formatter = self.formatter(inline_max_chars=500)
        result = {"success": True, "data": {"message": "small"}}
        formatted = formatter.format_result("tool-list_databases", result)
        self.assertFalse(formatted.inline_truncated)
        self.assertEqual(json.loads(formatted.text), result)
        self.assertEqual(formatted.structured_content, result)
        self.assertFalse(self.output_dir.exists())

    def test_long_output_is_summarized_and_saved_to_json_file(self):
        formatter = self.formatter()
        result = {
            "success": True,
            "status": "truncated",
            "meta": {"truncated": True, "has_more": True},
            "data": {"stdout": LONG_JSON_VALUE},
        }
        formatted = formatter.format_result("tool-long_stdout", result)
        self.assertTrue(formatted.inline_truncated)
        self.assertIn("Full output saved to:", formatted.text)
        self.assertNotIn(LONG_JSON_VALUE, formatted.text)
        self.assertIsNotNone(formatted.artifact)
        output_path = Path(formatted.artifact.path)
        self.assertEqual(output_path.suffix, JSON_OUTPUT_SUFFIX)
        self.assertTrue(output_path.exists())
        self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), result)
        self.assertTrue(formatted.structured_content["full_output_saved"])
        self.assertEqual(formatted.structured_content["format"], "json")
        self.assertEqual(
            formatted.structured_content["meta"],
            {"truncated": True, "has_more": True},
        )
        self.assertEqual(
            formatted.structured_content["inline_char_count"],
            len(json.dumps(result, ensure_ascii=False)),
        )
        self.assertGreater(formatted.structured_content["inline_char_count"], 80)
        self.assertEqual(
            formatted.structured_content["full_output"]["path"],
            str(output_path),
        )
        self.assertEqual(formatted.structured_content["full_output"]["format"], "json")
        self.assertNotIn("data", formatted.structured_content)

    def test_long_stderr_failure_preserves_full_output(self):
        formatter = self.formatter()
        result = {
            "success": False,
            "status": "command_failed",
            "error": {"code": "failed", "message": "command failed"},
            "stderr": "error line\n" * 80,
            "exit_code": 1,
        }
        formatted = formatter.format_result("tool-command", result)
        output_path = Path(formatted.artifact.path)
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["stderr"], result["stderr"])
        self.assertEqual(formatted.structured_content["error"], result["error"])
        self.assertTrue(formatted.structured_content["inline_truncated"])

    def test_long_plain_text_output_is_saved_to_txt_file(self):
        formatter = self.formatter()
        formatted = formatter.format_result("tool-log", LONG_TEXT)
        output_path = Path(formatted.artifact.path)
        self.assertEqual(output_path.suffix, TEXT_OUTPUT_SUFFIX)
        self.assertEqual(output_path.read_text(encoding="utf-8"), LONG_TEXT)
        self.assertEqual(formatted.artifact.format, "text")
        self.assertEqual(formatted.artifact.mime_type, "text/plain")
        self.assertEqual(formatted.structured_content["format"], "text")

    def test_file_names_are_sanitized(self):
        formatter = self.formatter()
        formatted = formatter.format_result(
            "tool:bad/name with spaces",
            {"data": "x" * 200},
        )
        output_name = Path(formatted.artifact.path).name
        self.assertIn("tool-bad-name-with-spaces", output_name)
        self.assertNotIn(":", output_name)
        self.assertNotIn("/", output_name)

    def test_existing_files_are_not_overwritten(self):
        formatter = self.formatter()
        self.output_dir.mkdir(parents=True)
        existing = (
            self.output_dir
            / f"20260707_123045_123456_tool-long_fixed-id{JSON_OUTPUT_SUFFIX}"
        )
        existing.write_text("keep me", encoding="utf-8")
        formatted = formatter.format_result("tool-long", {"data": "x" * 200})
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep me")
        self.assertTrue(
            Path(formatted.artifact.path).name.endswith(f"_1{JSON_OUTPUT_SUFFIX}")
        )

    def test_file_write_failure_falls_back_to_inline_preview(self):
        blocking_path = self.output_dir
        blocking_path.write_text("not a directory", encoding="utf-8")
        formatter = self.formatter()
        formatted = formatter.format_result("tool-long", {"data": "x" * 200})
        self.assertTrue(formatted.inline_truncated)
        self.assertIsNone(formatted.artifact)
        self.assertIn("saving the full output failed", formatted.text)
        self.assertIn("output_save_error", formatted.structured_content)

    def test_preview_is_deterministic(self):
        formatter = self.formatter(preview_max_chars=25)
        result = {"data": "abcdefghijklmnopqrstuvwxyz" * 10}
        first = formatter.format_result("tool-preview", result)
        second = formatter.format_result("tool-preview", result)
        self.assertEqual(
            first.structured_content["preview"],
            second.structured_content["preview"],
        )
        self.assertEqual(
            first.structured_content["preview"], '{"data": "abcdefghijklmno'
        )
        self.assertLessEqual(len(first.structured_content["preview"]), 25)

    def test_inline_limit_is_inclusive_and_counts_characters(self):
        formatter = self.formatter(inline_max_chars=40)
        at_limit = {"data": "x" * 28}
        self.assertEqual(len(json.dumps(at_limit)), 40)
        inline = formatter.format_result("tool-edge", at_limit)
        self.assertFalse(inline.inline_truncated)
        self.assertIsNone(inline.artifact)
        over_limit = {"data": "x" * 29}
        spilled = formatter.format_result("tool-edge", over_limit)
        self.assertTrue(spilled.inline_truncated)
        self.assertEqual(spilled.structured_content["inline_char_count"], 41)
        # Non-ASCII text is measured and stored as characters, not JSON escapes.
        accents = formatter.format_result("tool-accents", {"data": "é" * 28})
        self.assertFalse(accents.inline_truncated)
        self.assertEqual(
            accents.text, json.dumps({"data": "é" * 28}, ensure_ascii=False)
        )

    def test_default_limits_keep_twelve_thousand_characters_inline(self):
        formatter = McpOutputFormatter(
            self.output_dir, clock=self.clock, nonce_factory=self.nonce_factory
        )
        self.assertEqual(formatter.inline_max_chars, 12000)
        self.assertEqual(formatter.output_dir, self.output_dir)
        self.assertFalse(
            formatter.format_result("tool-text", "x" * 12000).inline_truncated
        )
        spilled = formatter.format_result("tool-text", "x" * 12001)
        self.assertTrue(spilled.inline_truncated)
        self.assertEqual(len(spilled.structured_content["preview"]), 3000)

    def test_non_positive_limits_are_clamped_to_one(self):
        formatter = McpOutputFormatter(
            self.output_dir,
            inline_max_chars=0,
            preview_max_chars=-5,
            preview_max_lines=0,
            clock=self.clock,
            nonce_factory=self.nonce_factory,
        )
        self.assertEqual(formatter.inline_max_chars, 1)
        self.assertEqual(formatter.format_result("tool-one", "a").text, "a")
        formatted = formatter.format_result("tool-one", "abc\ndef")
        self.assertEqual(formatted.structured_content["preview"], "a")

    def test_saved_json_is_indented_utf8_and_size_matches_the_file(self):
        formatter = self.formatter()
        result = {"data": "é" * 100}
        formatted = formatter.format_result("tool-utf8", result)
        path = Path(formatted.artifact.path)
        raw = path.read_bytes()
        self.assertEqual(formatted.artifact.size_bytes, len(raw))
        self.assertEqual(formatted.artifact.mime_type, "application/json")
        self.assertEqual(formatted.artifact.format, "json")
        text = raw.decode("utf-8")
        self.assertEqual(text, '{\n  "data": "' + "é" * 100 + '"\n}')
        self.assertEqual(path.parent, self.output_dir)

    def test_artifact_name_has_timestamp_label_and_nonce(self):
        formatter = self.formatter()
        formatted = formatter.format_result("tool-long", {"data": "x" * 200})
        self.assertEqual(
            Path(formatted.artifact.path).name,
            f"20260707_123045_123456_tool-long_fixed-id{JSON_OUTPUT_SUFFIX}",
        )

    def test_nonce_is_sanitized_truncated_and_never_empty(self):
        cases = (
            ("../../evil nonce", "evil-nonce"),
            ("n" * 40, "n" * 16),
            ("///", "mcp-output"),
        )
        for nonce, expected in cases:
            with self.subTest(nonce=nonce):
                formatter = McpOutputFormatter(
                    self.output_dir,
                    inline_max_chars=10,
                    clock=self.clock,
                    nonce_factory=lambda nonce=nonce: nonce,
                )
                formatted = formatter.format_result("tool-x", "y" * 50)
                path = Path(formatted.artifact.path)
                self.assertEqual(path.parent, self.output_dir)
                self.assertEqual(
                    path.name,
                    f"20260707_123045_123456_tool-x_{expected}{TEXT_OUTPUT_SUFFIX}",
                )

    def test_label_that_sanitizes_to_nothing_uses_a_placeholder_and_stays_bounded(self):
        formatter = self.formatter()
        for label, expected in (("...", "mcp-output"), ("é" * 5, "mcp-output")):
            with self.subTest(label=label):
                name = Path(
                    formatter.format_result(label, "z" * 200).artifact.path
                ).name
                self.assertIn(f"_{expected}_fixed-id", name)
        long_name = Path(
            formatter.format_result("a" * 200, "z" * 200).artifact.path
        ).name
        self.assertIn("_" + "a" * 80 + "_fixed-id", long_name)
        self.assertNotIn("a" * 81, long_name)

    def test_unique_name_search_gives_up_and_falls_back_to_inline_preview(self):
        formatter = self.formatter()
        self.output_dir.mkdir(parents=True)
        base = "20260707_123045_123456_tool-busy_fixed-id"
        for suffix in ("", "_1", "_2"):
            (self.output_dir / f"{base}{suffix}{TEXT_OUTPUT_SUFFIX}").write_text(
                "keep", encoding="utf-8"
            )
        with patch.object(output_module, "MAX_UNIQUE_FILENAME_ATTEMPTS", 3):
            formatted = formatter.format_result("tool-busy", "y" * 200)
        self.assertIsNone(formatted.artifact)
        self.assertTrue(formatted.inline_truncated)
        self.assertEqual(
            formatted.save_error, "Could not create a unique MCP output file"
        )
        self.assertEqual(len(list(self.output_dir.iterdir())), 3)
        (self.output_dir / f"{base}_2{TEXT_OUTPUT_SUFFIX}").unlink()
        with patch.object(output_module, "MAX_UNIQUE_FILENAME_ATTEMPTS", 3):
            formatted = formatter.format_result("tool-busy", "y" * 200)
        self.assertEqual(
            Path(formatted.artifact.path).name, f"{base}_2{TEXT_OUTPUT_SUFFIX}"
        )

    def test_unencodable_text_falls_back_to_inline_preview(self):
        formatter = self.formatter()
        formatted = formatter.format_result("tool-surrogate", chr(0xD800) * 200)
        self.assertIsNone(formatted.artifact)
        self.assertTrue(formatted.inline_truncated)
        self.assertIn("surrogates not allowed", formatted.save_error)
        self.assertEqual(
            formatted.structured_content["output_save_error"], formatted.save_error
        )
        self.assertEqual(list(self.output_dir.glob("*.txt")), [])

    def test_missing_parent_directories_are_created_for_the_output_dir(self):
        nested = Path(self.tmp.name) / "deep" / "er" / MCP_OUTPUT_DIR_NAME
        formatter = McpOutputFormatter(
            nested,
            inline_max_chars=10,
            clock=self.clock,
            nonce_factory=self.nonce_factory,
        )
        formatted = formatter.format_result("tool-nested", "y" * 50)
        self.assertEqual(Path(formatted.artifact.path).parent, nested)
        self.assertEqual(Path(formatted.artifact.path).read_text("utf-8"), "y" * 50)

    def test_preview_is_limited_by_characters_and_lines(self):
        formatter = McpOutputFormatter(
            self.output_dir,
            inline_max_chars=10,
            preview_max_chars=100,
            preview_max_lines=3,
            clock=self.clock,
            nonce_factory=self.nonce_factory,
        )
        text = "".join(f"line {number}\n" for number in range(10))
        preview = formatter.format_result("tool-lines", text).structured_content[
            "preview"
        ]
        self.assertEqual(preview, "line 0\nline 1\nline 2")
        char_limited = self.formatter(inline_max_chars=10, preview_max_chars=10)
        preview = char_limited.format_result(
            "tool-chars", "abcdef\nghijklmnop\nqrs"
        ).structured_content["preview"]
        self.assertEqual(preview, "abcdef\nghi")

    def test_summary_copies_only_envelope_fields_of_dict_results(self):
        formatter = self.formatter()
        result = {
            "success": True,
            "status": "ok",
            "meta": {"has_more": False},
            "data": "x" * 200,
            "stderr": "secret " * 10,
        }
        summary = formatter.format_result("tool-envelope", result).structured_content
        self.assertEqual(summary["success"], True)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["meta"], {"has_more": False})
        self.assertNotIn("data", summary)
        self.assertNotIn("stderr", summary)
        self.assertNotIn("error", summary)
        listing = formatter.format_result(
            "tool-list", ["item"] * 100
        ).structured_content
        self.assertEqual(
            set(listing),
            {
                "inline_truncated",
                "inline_char_count",
                "preview",
                "format",
                "full_output_saved",
                "full_output",
            },
        )
        self.assertEqual(listing["format"], "json")
