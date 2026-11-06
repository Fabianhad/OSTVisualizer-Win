import base64
import contextlib
import importlib
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.application.dtos.ai_takeoff_dtos import AI_TAKEOFF_COMMANDS
from ost_visualizer.mcp_takeoff import main as main_module
from ost_visualizer.mcp_takeoff.protocol import JsonRpcError
from ost_visualizer.mcp_takeoff.proxy import TakeoffProxy
from tests.paths import REPO_ROOT

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class FakeClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def call(self, command, arguments):
        self.calls.append((command, arguments))
        return self.result


def _render_result(png=PNG_BYTES):
    return {
        "success": True,
        "status": "ok",
        "data": {
            "page_uid": "p1",
            "image": {
                "png_base64": base64.b64encode(png).decode("ascii"),
                "width_px": 10,
                "height_px": 8,
            },
            "overlay_status": "not_supported_until_m1b",
        },
    }


class TakeoffProxyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output_dir = Path(directory.name) / "app_data" / "outputs"

    def proxy(self, result, inline_max_bytes=256 * 1024):
        client = FakeClient(result)
        proxy = TakeoffProxy(
            client,
            self.output_dir,
            inline_max_bytes=inline_max_bytes,
            clock=lambda: datetime(2026, 10, 7, 9, 30, 0),
            nonce_factory=lambda: "abc123",
        )
        return client, proxy

    def test_lists_the_catalog_tools(self):
        _client, proxy = self.proxy({})
        self.assertEqual(
            [tool["name"] for tool in proxy.list_tools()], list(AI_TAKEOFF_COMMANDS)
        )

    def test_unknown_tools_never_reach_the_app(self):
        client, proxy = self.proxy({})
        for name in ("approve_changeset", "accept_assumption", "get_context", ""):
            with self.subTest(name=name):
                with self.assertRaises(JsonRpcError):
                    proxy.call_tool(name, {})
        self.assertEqual(client.calls, [])

    def test_successful_results_become_text_and_structured_content(self):
        result = {"success": True, "status": "ok", "data": {"sheets": []}}
        client, proxy = self.proxy(result)
        response = proxy.call_tool("list_sheets", {"limit": 2})
        self.assertEqual(client.calls, [("list_sheets", {"limit": 2})])
        self.assertFalse(response["isError"])
        self.assertEqual(response["structuredContent"], result)
        self.assertEqual(json.loads(response["content"][0]["text"]), result)

    def test_errors_are_flagged(self):
        result = {
            "success": False,
            "status": "bid_not_open",
            "error": {"code": "bid_not_open", "message": "Open the bid first."},
        }
        _client, proxy = self.proxy(result)
        response = proxy.call_tool("list_sheets", {})
        self.assertTrue(response["isError"])
        self.assertEqual(response["structuredContent"]["status"], "bid_not_open")

    def test_small_png_is_returned_as_image_content_and_stripped_from_json(self):
        _client, proxy = self.proxy(_render_result())
        response = proxy.call_tool("render_sheet", {"page_uid": "p1"})
        image = response["content"][0]
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(image["data"]), PNG_BYTES)
        structured = response["structuredContent"]
        self.assertNotIn("png_base64", json.dumps(structured))
        self.assertEqual(structured["data"]["image"]["width_px"], 10)
        self.assertEqual(response["content"][1]["type"], "text")
        self.assertFalse(self.output_dir.exists())

    def test_large_png_is_saved_to_a_file_and_returned_by_path(self):
        big_png = PNG_BYTES + b"\x01" * 4000
        _client, proxy = self.proxy(_render_result(big_png), inline_max_bytes=2000)
        response = proxy.call_tool("render_sheet", {"page_uid": "p1"})
        self.assertEqual([item["type"] for item in response["content"]], ["text"])
        image = response["structuredContent"]["data"]["image"]
        saved = Path(image["file"]["path"])
        self.assertEqual(saved.parent, self.output_dir)
        self.assertEqual(saved.suffix, ".png")
        self.assertEqual(saved.name, "20261007_093000_000000_render_sheet_abc123.png")
        self.assertEqual(saved.read_bytes(), big_png)
        self.assertEqual(
            image["file"],
            {"path": str(saved), "size_bytes": len(big_png), "mime_type": "image/png"},
        )
        self.assertNotIn("png_base64", json.dumps(response["structuredContent"]))

    def test_large_json_is_saved_to_a_file_with_a_preview(self):
        result = {
            "success": True,
            "status": "ok",
            "data": {"segments": [{"id": f"s{index}"} for index in range(500)]},
            "meta": {"returned_count": 500},
        }
        _client, proxy = self.proxy(result, inline_max_bytes=1000)
        response = proxy.call_tool("list_segments", {"page_uid": "p1"})
        structured = response["structuredContent"]
        self.assertTrue(structured["inline_truncated"])
        self.assertEqual(structured["meta"], {"returned_count": 500})
        saved = Path(structured["full_output"]["path"])
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), result)
        self.assertLessEqual(len(response["content"][0]["text"].encode("utf-8")), 1000)

    def test_spilled_json_is_saved_indented_under_a_time_tool_and_nonce_name(self):
        result = {"success": True, "status": "ok", "data": {"x": "y" * 5000}}
        _client, proxy = self.proxy(result, inline_max_bytes=1000)
        response = proxy.call_tool("list_text", {"page_uid": "p1"})
        structured = response["structuredContent"]
        saved = self.output_dir / "20261007_093000_000000_list_text_abc123.json"
        self.assertTrue(structured["full_output_saved"])
        self.assertEqual(
            structured["full_output"], {"path": str(saved), "format": "json"}
        )
        self.assertEqual(
            saved.read_text(encoding="utf-8"), json.dumps(result, indent=2)
        )
        self.assertEqual(structured["preview"], json.dumps(result)[:3000])
        self.assertEqual(
            structured["inline_byte_count"], len(json.dumps(result).encode("utf-8"))
        )
        self.assertNotIn("image", structured)
        text = response["content"][0]["text"]
        self.assertTrue(
            text.startswith(
                "Output from list_text was too large to show inline. Full output "
                f"saved to: {saved}\nPreview:\n"
            )
        )
        self.assertEqual(len(text.encode("utf-8")), 1000 - 64)

    def test_name_collisions_get_a_numbered_suffix(self):
        result = {"success": True, "status": "ok", "data": {"x": "y" * 5000}}
        _client, proxy = self.proxy(result, inline_max_bytes=1000)
        paths = [
            proxy.call_tool("list_text", {})["structuredContent"]["full_output"]["path"]
            for _ in range(3)
        ]
        base = self.output_dir / "20261007_093000_000000_list_text_abc123"
        self.assertEqual(paths, [f"{base}.json", f"{base}_1.json", f"{base}_2.json"])

    def test_when_every_candidate_name_is_taken_nothing_is_saved(self):
        result = {"success": True, "status": "ok", "data": {"x": "y" * 5000}}
        _client, proxy = self.proxy(result, inline_max_bytes=1000)
        base = "20261007_093000_000000_list_text_abc123"
        self.output_dir.mkdir(parents=True)
        taken = [self.output_dir / f"{base}.json"] + [
            self.output_dir / f"{base}_{attempt}.json" for attempt in range(1, 1000)
        ]
        for path in taken:
            path.write_bytes(b"")
        response = proxy.call_tool("list_text", {})
        structured = response["structuredContent"]
        self.assertFalse(structured["full_output_saved"])
        self.assertEqual(
            structured["output_save_error"], "Could not create a unique output file"
        )
        self.assertEqual(len(list(self.output_dir.iterdir())), 1000)

    def test_output_names_use_a_short_safe_nonce(self):
        result = {"success": True, "status": "ok", "data": {"x": "y" * 5000}}
        cases = (
            (lambda: "n" * 30, "n" * 16),
            (lambda: "../..", "output"),
            (lambda: "a b/c", "a-b-c"),
            (lambda: "", "output"),
            (lambda: "._-ab-_.", "ab"),
            (lambda: "XaX", "XaX"),
        )
        for index, (nonce_factory, expected) in enumerate(cases):
            with self.subTest(expected=expected):
                proxy = TakeoffProxy(
                    FakeClient(result),
                    self.output_dir / str(index),
                    inline_max_bytes=1000,
                    clock=lambda: datetime(2026, 10, 7, 9, 30, 0, 12),
                    nonce_factory=nonce_factory,
                )
                path = proxy.call_tool("list_text", {})["structuredContent"][
                    "full_output"
                ]["path"]
                self.assertEqual(
                    Path(path).name,
                    f"20261007_093000_000012_list_text_{expected}.json",
                )

    def test_the_default_nonce_is_eight_hex_characters(self):
        result = {"success": True, "status": "ok", "data": {"x": "y" * 5000}}
        proxy = TakeoffProxy(
            FakeClient(result),
            self.output_dir,
            inline_max_bytes=1000,
            clock=lambda: datetime(2026, 10, 7, 9, 30, 0),
        )
        names = {
            Path(
                proxy.call_tool("get_quantities", {})["structuredContent"][
                    "full_output"
                ]["path"]
            ).name
            for _ in range(2)
        }
        self.assertEqual(len(names), 2)
        for name in names:
            self.assertRegex(
                name, r"^20261007_093000_000000_get_quantities_[0-9a-f]{8}\.json$"
            )

    def test_json_of_exactly_the_inline_cap_stays_inline(self):
        empty = json.dumps({"success": True, "status": "ok", "data": ""})
        for inline_max_bytes, cap in ((1000, 1000), (0, 256)):
            for size, spilled in ((cap, False), (cap + 1, True)):
                result = {
                    "success": True,
                    "status": "ok",
                    "data": "y" * (size - len(empty)),
                }
                with self.subTest(inline_max_bytes=inline_max_bytes, size=size):
                    self.assertEqual(len(json.dumps(result)), size)
                    _client, proxy = self.proxy(
                        result, inline_max_bytes=inline_max_bytes
                    )
                    structured = proxy.call_tool("list_text", {})["structuredContent"]
                    self.assertEqual("inline_truncated" in structured, spilled)

    def test_png_up_to_half_the_inline_cap_in_base64_stays_inline(self):
        for png_size, inline in ((750, True), (753, False)):
            png = PNG_BYTES + b"\x01" * (png_size - len(PNG_BYTES))
            with self.subTest(base64_length=len(base64.b64encode(png))):
                _client, proxy = self.proxy(_render_result(png), inline_max_bytes=2000)
                response = proxy.call_tool("render_sheet", {"page_uid": "p1"})
                types = [item["type"] for item in response["content"]]
                image = response["structuredContent"]["data"]["image"]
                if inline:
                    self.assertEqual(types, ["image", "text"])
                    self.assertNotIn("file", image)
                else:
                    self.assertEqual(types, ["text"])
                    self.assertEqual(Path(image["file"]["path"]).read_bytes(), png)

    def test_invalid_base64_png_data_is_dropped(self):
        for encoded in ("!!!!", "iVBO Rw==", 5):
            result = _render_result()
            result["data"]["image"]["png_base64"] = encoded
            with self.subTest(encoded=encoded):
                _client, proxy = self.proxy(result)
                response = proxy.call_tool("render_sheet", {"page_uid": "p1"})
                self.assertEqual(
                    [item["type"] for item in response["content"]], ["text"]
                )
                image = response["structuredContent"]["data"]["image"]
                self.assertEqual(image, {"width_px": 10, "height_px": 8})
        self.assertFalse(self.output_dir.exists())

    def test_save_failures_still_return_a_bounded_preview(self):
        result = {"success": True, "status": "ok", "data": {"x": "y" * 5000}}
        _client, proxy = self.proxy(result, inline_max_bytes=1000)
        with patch.object(Path, "open", side_effect=OSError("disk full")):
            response = proxy.call_tool("list_text", {"page_uid": "p1"})
        structured = response["structuredContent"]
        self.assertFalse(structured["full_output_saved"])
        self.assertIn("disk full", structured["output_save_error"])
        self.assertNotIn("full_output", structured)
        self.assertEqual(structured["preview"], json.dumps(result)[:3000])
        text = response["content"][0]["text"]
        self.assertTrue(
            text.startswith(
                "Output from list_text was too large to show inline and saving it "
                "failed: disk full. Preview:\n" + json.dumps(result)[:100]
            )
        )
        self.assertEqual(len(text.encode("utf-8")), 1000 - 64)

    def test_png_save_failures_still_return_the_result_without_the_image(self):
        big_png = PNG_BYTES + b"\x01" * 4000
        _client, proxy = self.proxy(_render_result(big_png), inline_max_bytes=2000)
        with patch.object(Path, "open", side_effect=OSError("disk full")):
            response = proxy.call_tool("render_sheet", {"page_uid": "p1"})
        image = response["structuredContent"]["data"]["image"]
        self.assertFalse(image["file_saved"])
        self.assertIn("disk full", image["file_save_error"])
        self.assertNotIn("file", image)
        self.assertNotIn("png_base64", json.dumps(response["structuredContent"]))
        self.assertEqual(response["structuredContent"]["data"]["page_uid"], "p1")
        self.assertFalse(response["isError"])

    def test_lone_surrogates_from_the_app_are_delivered(self):
        result = {"success": True, "status": "ok", "data": {"name": "a\ud800b"}}
        _client, proxy = self.proxy(result)
        response = proxy.call_tool("list_sheets", {})
        self.assertEqual(response["structuredContent"]["data"]["name"], "a\ud800b")
        text = response["content"][0]["text"]
        self.assertTrue(text.isascii())
        self.assertEqual(json.loads(text)["data"]["name"], "a\ud800b")

    def test_lone_surrogates_in_spilled_output_are_saved(self):
        result = {"success": True, "status": "ok", "data": {"x": "\udc00" * 400}}
        _client, proxy = self.proxy(result, inline_max_bytes=1000)
        response = proxy.call_tool("list_text", {"page_uid": "p1"})
        saved = Path(response["structuredContent"]["full_output"]["path"])
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), result)

    def test_the_inline_cap_counts_the_escaped_bytes_actually_written(self):
        result = {"success": True, "status": "ok", "data": {"x": "\u2265" * 300}}
        _client, proxy = self.proxy(result, inline_max_bytes=1000)
        response = proxy.call_tool("list_text", {"page_uid": "p1"})
        self.assertTrue(response["structuredContent"]["inline_truncated"])
        self.assertLessEqual(len(response["content"][0]["text"].encode("utf-8")), 1000)

    def test_json_spill_keeps_the_saved_png_reference(self):
        big_png = PNG_BYTES + b"\x01" * 4000
        result = _render_result(big_png)
        result["data"]["items"] = [{"id": f"s{index}"} for index in range(500)]
        _client, proxy = self.proxy(result, inline_max_bytes=2000)
        response = proxy.call_tool("render_sheet", {"page_uid": "p1"})
        structured = response["structuredContent"]
        self.assertTrue(structured["inline_truncated"])
        saved = Path(structured["image"]["file"]["path"])
        self.assertEqual(saved.read_bytes(), big_png)
        self.assertNotIn("png_base64", json.dumps(structured))


class OutputNamingAndSummaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output_dir = Path(directory.name) / "outputs"
        self.result = {"success": True, "status": "ok", "data": {"x": "y" * 5000}}

    def proxy(self, result, inline_max_bytes=1000):
        return TakeoffProxy(
            FakeClient(result),
            self.output_dir,
            inline_max_bytes=inline_max_bytes,
            clock=lambda: datetime(2026, 10, 7, 9, 30, 0),
            nonce_factory=lambda: "abc123",
        )

    def test_the_last_numbered_name_is_still_available(self):
        base = "20261007_093000_000000_list_text_abc123"
        self.output_dir.mkdir(parents=True)
        for attempt in range(999):
            name = f"{base}.json" if attempt == 0 else f"{base}_{attempt}.json"
            (self.output_dir / name).write_bytes(b"")
        structured = self.proxy(self.result).call_tool("list_text", {})[
            "structuredContent"
        ]
        self.assertTrue(structured["full_output_saved"])
        self.assertEqual(
            Path(structured["full_output"]["path"]).name, f"{base}_999.json"
        )
        self.assertEqual(len(list(self.output_dir.iterdir())), 1000)

    def test_a_spilled_summary_keeps_success_status_meta_and_error(self):
        result = {
            "success": False,
            "status": "invalid_argument",
            "data": {"x": "y" * 5000},
            "meta": {"returned_count": 0},
            "error": {"code": "invalid_argument", "message": "bad"},
        }
        response = self.proxy(result).call_tool("list_text", {})
        structured = response["structuredContent"]
        self.assertEqual(structured["success"], False)
        self.assertEqual(structured["status"], "invalid_argument")
        self.assertEqual(structured["meta"], {"returned_count": 0})
        self.assertEqual(
            structured["error"], {"code": "invalid_argument", "message": "bad"}
        )
        self.assertTrue(response["isError"])

    def test_the_failure_preview_is_cut_on_a_character_boundary(self):
        prefix = "Output from list_text was too large to show inline and saving it failed: "
        pad = "x" if (1000 - 64 - len(prefix)) % 2 == 0 else ""
        unicode_error = OSError(pad + "\u00e9" * 600)
        with patch.object(Path, "open", side_effect=unicode_error):
            response = self.proxy(self.result).call_tool("list_text", {})
        text = response["content"][0]["text"]
        self.assertTrue(text.startswith(prefix + pad + "\u00e9"))
        self.assertTrue(text.endswith("\u00e9"))
        encoded = text.encode("utf-8")
        self.assertEqual(len(encoded), 1000 - 64 - 1)

    def test_names_are_made_of_safe_characters_and_stop_at_eighty(self):
        from ost_visualizer.mcp_takeoff.proxy import _safe

        self.assertEqual(_safe("a" * 100), "a" * 80)
        self.assertEqual(_safe("a" * 80), "a" * 80)
        self.assertEqual(_safe("!!!"), "output")
        self.assertEqual(_safe(""), "output")
        self.assertEqual(_safe("-._x y.-"), "x-y")
        self.assertEqual(_safe("XhelloX"), "XhelloX")


class MainTests(unittest.TestCase):
    def test_only_the_log_level_argument_exists(self):
        with self.assertRaises(SystemExit):
            main_module.parse_args(["--database", "x.mdb"])
        with self.assertRaises(SystemExit):
            main_module.parse_args(["--app-data-dir", "c:/x"])
        self.assertEqual(main_module.parse_args([]).log_level, "WARNING")

    def test_real_stdio_is_utf8_whatever_the_windows_code_page(self):
        lines = [
            b"\xef\xbb\xbf"
            + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode(),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "\u2265 slab"}).encode(),
            '{"jsonrpc": "2.0", "id": 3, "method": "\u0141 \xd8 grid"}'.encode("utf-8"),
            json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping"}).encode(),
        ]
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONIOENCODING", "PYTHONUTF8", "PYTHONLEGACYWINDOWSSTDIO")
        }
        with tempfile.TemporaryDirectory() as home:
            environment["USERPROFILE"] = home
            environment["HOME"] = home
            completed = subprocess.run(
                [sys.executable, "-m", "ost_visualizer.mcp_takeoff.main"],
                input=b"\n".join(lines) + b"\n",
                capture_output=True,
                cwd=REPO_ROOT,
                env=environment,
                timeout=60,
            )
        self.assertEqual(
            completed.returncode, 0, completed.stderr.decode("utf-8", "replace")
        )
        responses = [
            json.loads(line) for line in completed.stdout.decode("utf-8").splitlines()
        ]
        self.assertEqual([response["id"] for response in responses], [1, 2, 3, 4])
        self.assertEqual(responses[0]["result"], {})
        self.assertEqual(
            responses[1]["error"]["message"], "Unsupported method: \u2265 slab"
        )
        self.assertEqual(
            responses[2]["error"]["message"], "Unsupported method: \u0141 \xd8 grid"
        )

    def test_main_switches_code_page_stdio_to_utf8(self):
        lines = [
            b"\xef\xbb\xbf"
            + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode(),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "\u2265"}).encode(),
            '{"jsonrpc": "2.0", "id": 3, "method": "\u0141"}'.encode("utf-8"),
        ]
        stdin = io.TextIOWrapper(
            io.BytesIO(b"\n".join(lines) + b"\n"), encoding="cp1252"
        )
        output = io.BytesIO()
        stdout = io.TextIOWrapper(output, encoding="cp1252")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            main_module, "app_data_dir", return_value=Path(directory)
        ), patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            self.assertEqual(main_module.main([]), 0)
            stdout.flush()
            main_module.LOGGER.handlers.clear()
        responses = [
            json.loads(line) for line in output.getvalue().decode("utf-8").splitlines()
        ]
        self.assertEqual([response["id"] for response in responses], [1, 2, 3])
        self.assertEqual(responses[0]["result"], {})
        self.assertEqual(responses[2]["error"]["message"], "Unsupported method: \u0141")

    def test_main_serves_stdio_with_the_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            stdin = io.StringIO(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
            )
            stdout = io.StringIO()
            with patch.object(
                main_module, "app_data_dir", return_value=Path(directory)
            ):
                self.assertEqual(main_module.main([], stdin=stdin, stdout=stdout), 0)
            response = json.loads(stdout.getvalue())
            self.assertEqual(
                [tool["name"] for tool in response["result"]["tools"]],
                list(AI_TAKEOFF_COMMANDS),
            )
            self.assertTrue((Path(directory) / "mcp_takeoff.log").exists())

    def test_main_announces_the_ost_takeoff_server_name(self):
        with tempfile.TemporaryDirectory() as directory:
            stdin = io.StringIO(
                json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
                )
                + "\n"
            )
            stdout = io.StringIO()
            with patch.object(
                main_module, "app_data_dir", return_value=Path(directory)
            ):
                self.assertEqual(main_module.main([], stdin=stdin, stdout=stdout), 0)
            result = json.loads(stdout.getvalue())["result"]
            self.assertEqual(result["serverInfo"]["name"], "ost-takeoff")

    def test_main_replaces_and_closes_handlers_left_on_its_logger(self):
        with tempfile.TemporaryDirectory() as directory:
            stale = logging.FileHandler(Path(directory) / "stale.log", encoding="utf-8")
            main_module.LOGGER.addHandler(stale)
            self.addCleanup(main_module.LOGGER.removeHandler, stale)
            self.addCleanup(stale.close)
            with patch.object(
                main_module, "app_data_dir", return_value=Path(directory)
            ):
                main_module.main([], stdin=io.StringIO(""), stdout=io.StringIO())
            self.assertNotIn(stale, main_module.LOGGER.handlers)
            self.assertIsNone(stale.stream)


class TakeoffMainLoggingContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name) / "nested" / "app_data"
        self.addCleanup(self.drop_handlers)

    @staticmethod
    def drop_handlers():
        for handler in list(main_module.LOGGER.handlers):
            main_module.LOGGER.removeHandler(handler)
            handler.close()

    def test_the_logger_is_the_takeoff_package_logger(self):
        self.assertEqual(main_module.LOGGER.name, "ost_visualizer.mcp_takeoff")
        self.assertEqual(
            main_module._LEVELS, ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        )

    def test_every_documented_level_is_accepted_and_applied_to_the_logger_and_both_handlers(
        self,
    ):
        for name, level in (
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
        ):
            with self.subTest(level=name):
                self.assertEqual(main_module.parse_args(["--log-level", name]).log_level, name)
                self.drop_handlers()
                with contextlib.redirect_stderr(io.StringIO()):
                    logger = main_module._configure_logging(self.directory, name)
                self.assertEqual(logger.level, level)
                self.assertEqual(len(logger.handlers), 2)
                self.assertEqual({handler.level for handler in logger.handlers}, {level})
                self.assertFalse(logger.propagate)

    def test_both_handlers_use_the_timestamped_format_and_the_folder_is_created(self):
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            logger = main_module._configure_logging(self.directory, "INFO")
        logger.warning("recorded")
        for handler in logger.handlers:
            handler.flush()
        pattern = (
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} "
            r"WARNING ost_visualizer\.mcp_takeoff: recorded$"
        )
        self.assertRegex(captured.getvalue().strip(), pattern)
        written = (self.directory / "mcp_takeoff.log").read_text(encoding="utf-8")
        self.assertRegex(written.strip(), pattern)

    def test_help_describes_the_proxy_and_its_only_option(self):
        stdout = io.StringIO()
        with patch.dict(os.environ, {"COLUMNS": "300"}), contextlib.redirect_stdout(
            stdout
        ), self.assertRaises(SystemExit):
            main_module.parse_args(["--help"])
        lines = [line.strip() for line in stdout.getvalue().splitlines()]
        self.assertIn("Run the OST Visualizer AI takeoff MCP stdio proxy.", lines)
        self.assertIn(
            "Logging level. Logs go to stderr and the app data log file.", lines
        )

    def test_stale_handlers_are_removed_and_closed_when_logging_is_configured(self):
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        stale = logging.FileHandler(self.directory.parent / "stale.log", encoding="utf-8")
        self.addCleanup(stale.close)
        main_module.LOGGER.addHandler(stale)
        with contextlib.redirect_stderr(io.StringIO()):
            logger = main_module._configure_logging(self.directory, "INFO")
        self.assertNotIn(stale, logger.handlers)
        self.assertIsNone(stale.stream)
        self.assertEqual(len(logger.handlers), 2)

    def test_the_handlers_of_a_finished_run_are_closed(self):
        recorded = []
        real = main_module._configure_logging

        def configure(directory, level):
            logger = real(directory, level)
            recorded.extend(logger.handlers)
            return logger

        with patch.object(main_module, "app_data_dir", return_value=self.directory):
            with patch.object(main_module, "_configure_logging", configure):
                with contextlib.redirect_stderr(io.StringIO()):
                    main_module.main([], stdin=io.StringIO(""), stdout=io.StringIO())
        file_handlers = [h for h in recorded if isinstance(h, logging.FileHandler)]
        self.assertEqual(len(file_handlers), 1)
        self.assertIsNone(file_handlers[0].stream)
        self.assertEqual(main_module.LOGGER.handlers, [])

    def test_a_run_logs_its_start_and_releases_its_handlers_when_it_ends(self):
        with patch.object(main_module, "app_data_dir", return_value=self.directory):
            with contextlib.redirect_stderr(io.StringIO()):
                main_module.main(
                    ["--log-level", "INFO"],
                    stdin=io.StringIO(""),
                    stdout=io.StringIO(),
                )
        self.assertEqual(main_module.LOGGER.handlers, [])
        written = (self.directory / "mcp_takeoff.log").read_text(encoding="utf-8")
        self.assertIn("INFO ost_visualizer.mcp_takeoff: AI takeoff MCP proxy started", written)

    def test_a_real_stdin_is_read_as_utf8_with_a_bom_and_bad_bytes_replaced(self):
        class FakeStdin(io.StringIO):
            calls = []

            def reconfigure(self, **options):
                FakeStdin.calls.append(options)

        with patch.object(main_module, "app_data_dir", return_value=self.directory):
            with patch.object(sys, "stdin", FakeStdin("")), contextlib.redirect_stderr(
                io.StringIO()
            ):
                main_module.main([], stdout=io.StringIO())
        self.assertEqual(
            FakeStdin.calls, [{"encoding": "utf-8-sig", "errors": "replace"}]
        )


class EntryScriptTests(unittest.TestCase):
    def test_running_the_entry_script_serves_stdio_and_exits_cleanly(self):
        environment = dict(os.environ)
        with tempfile.TemporaryDirectory() as home:
            environment["USERPROFILE"] = home
            environment["HOME"] = home
            completed = subprocess.run(
                [sys.executable, str(REPO_ROOT / "McpTakeoffServer.py")],
                input=json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}).encode()
                + b"\n",
                capture_output=True,
                cwd=REPO_ROOT,
                env=environment,
                timeout=60,
            )
        self.assertEqual(
            completed.returncode, 0, completed.stderr.decode("utf-8", "replace")
        )
        self.assertEqual(
            json.loads(completed.stdout), {"jsonrpc": "2.0", "id": 9, "result": {}}
        )

    def test_importing_the_entry_script_does_not_start_the_proxy(self):
        calls = []
        sys.modules.pop("McpTakeoffServer", None)
        self.addCleanup(sys.modules.pop, "McpTakeoffServer", None)
        with patch.object(main_module, "main", lambda: calls.append("main") or 0):
            module = importlib.import_module("McpTakeoffServer")
        self.assertEqual(calls, [])
        self.assertEqual(module.__name__, "McpTakeoffServer")


if __name__ == "__main__":
    unittest.main()
