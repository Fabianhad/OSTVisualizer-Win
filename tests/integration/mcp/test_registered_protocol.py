import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.mcp_server.registry import DatabaseRegistry
from ost_visualizer.mcp_server.server import build_mcp_server

EXPECTED_TOOLS = {
    "list_databases",
    "get_current_context",
    "list_projects",
    "list_bids",
    "get_bid_summary",
    "compare_bids_by_ref_no",
    "list_pages",
    "get_current_page",
    "get_page_metadata",
    "get_page_pdf_text_summary",
    "get_page_pdf_vectors_summary",
    "get_page_markups_summary",
    "get_page_overlay_summary",
    "search_page_pdf_text",
    "list_conditions",
    "list_areas",
    "get_area_summary",
    "search_conditions",
    "get_condition_summary",
    "list_takeoffs",
    "get_selected_takeoffs_summary",
    "get_selected_pages_summary",
    "summarize_quantities",
    "search_pages",
    "list_layers",
    "list_named_views",
    "list_hotlinks",
    "get_page_quantity_summary",
    "search_takeoffs",
    "get_bid_quantity_summary",
    "get_summary",
    "review_scope_gaps",
    "find_duplicate_conditions",
    "find_zero_quantity_conditions",
    "find_unplaced_takeoffs",
    "get_page_context",
    "find_pages_without_takeoffs",
    "find_conditions_without_takeoffs",
}
EXPECTED_PROMPTS = {
    "review_current_estimator_context",
    "review_takeoff_scope",
    "review_bid_scope",
    "review_page_qa",
    "review_markup_and_links",
    "review_overlay_and_pdf_context",
    "review_quantity_variance",
}
PROMPT_ARGUMENTS = {
    "review_current_estimator_context": {},
    "review_takeoff_scope": {"database_id": "db", "bid_uid": "bid"},
    "review_bid_scope": {"database_id": "db", "bid_uid": "bid"},
    "review_page_qa": {
        "database_id": "db",
        "bid_uid": "bid",
        "page_uid": "page",
    },
    "review_markup_and_links": {"database_id": "db", "bid_uid": "bid"},
    "review_overlay_and_pdf_context": {
        "database_id": "db",
        "bid_uid": "bid",
        "page_uid": "page",
    },
    "review_quantity_variance": {"database_id": "db", "bid_uid": "bid"},
}
FORBIDDEN_PROMPT_TERMS = (
    "write",
    "writes",
    "database mutation",
    "exports",
    "arbitrary sql",
    "ocr",
    "arbitrary path",
    "arbitrary paths",
    "file path",
    "full text",
    "full raw text",
    "raw table",
    "raw tables",
    "unbounded",
    "ui control",
)
ALLOWED_PROMPT_IDENTIFIERS = (
    EXPECTED_TOOLS
    | EXPECTED_PROMPTS
    | {
        "database_id",
        "bid_uid",
        "page_uid",
        "condition_uid",
        "has_more",
    }
)


class McpRegisteredProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        registry = DatabaseRegistry(app_data_dir=Path(self.tmp.name))
        self.server = build_mcp_server(registry)

    def request(self, method, params=None, request_id=1):
        return self.server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )

    def test_tools_list_and_call_shape(self):
        tools = self.request("tools/list")["result"]["tools"]
        tool_names = {tool["name"] for tool in tools}
        self.assertEqual(tool_names, EXPECTED_TOOLS)
        self.assertEqual(len(tool_names), 38)
        self.assertFalse(any("csv" in name.lower() for name in tool_names))
        self.assertTrue(all(tool["description"] for tool in tools))
        # Read-only scope: no tool accepts a database/file path, an app-data
        # override or SQL; databases are addressed only by registry database_id.
        argument_names = {
            name for tool in tools for name in tool["inputSchema"].get("properties", {})
        }
        self.assertIn("database_id", argument_names)
        self.assertEqual(
            argument_names
            & {
                "database",
                "database_path",
                "db_path",
                "path",
                "file_path",
                "app_data_dir",
                "sql",
                "statement",
                "command",
            },
            set(),
        )
        response = self.request(
            "tools/call",
            {"name": "list_databases", "arguments": {}},
        )["result"]
        self.assertEqual(response["content"][0]["type"], "text")
        self.assertFalse(response["isError"])
        self.assertTrue(response["structuredContent"]["success"])
        self.assertEqual(response["structuredContent"]["status"], "no_checked_database")
        self.assertIn("has_more", response["structuredContent"]["meta"])

    def test_resources_and_templates(self):
        resources = self.request("resources/list")["result"]["resources"]
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["uri"], "ost://databases")
        read = self.request(
            "resources/read",
            {"uri": "ost://databases"},
        )[
            "result"
        ]["contents"]
        self.assertEqual(read[0]["mimeType"], "application/json")
        payload = json.loads(read[0]["text"])
        self.assertTrue(payload["success"])
        templates = self.request("resources/templates/list")["result"][
            "resourceTemplates"
        ]
        self.assertEqual(
            {template["uriTemplate"] for template in templates},
            {
                "ost://database/{database_id}/hierarchy",
                "ost://database/{database_id}/bid/{bid_uid}/pages",
                "ost://database/{database_id}/bid/{bid_uid}/conditions",
                "ost://database/{database_id}/bid/{bid_uid}/quantities",
            },
        )

    def test_unknown_requests_are_rejected_instead_of_executed(self):
        for method, params, message in (
            (
                "tools/call",
                {"name": "run_sql", "arguments": {}},
                "Unknown tool: run_sql",
            ),
            ("resources/read", {"uri": "file:///C:/Windows/win.ini"}, None),
            ("prompts/get", {"name": "nope", "arguments": {}}, "Unknown prompt: nope"),
            ("database/open", {}, "Unsupported method: database/open"),
        ):
            with self.subTest(method=method):
                error = self.request(method, params)["error"]
                self.assertEqual(error["code"], -32601)
                self.assertEqual(
                    error["message"],
                    message or "Unknown resource: file:///C:/Windows/win.ini",
                )

    def test_database_ids_come_only_from_checked_registry_entries(self):
        root = Path(self.tmp.name)
        for name in ("demo.mdb", "unchecked.mdb", "notes.txt"):
            (root / name).write_text("", encoding="utf-8")
        entries = [
            {"file_path": str(root / "demo.mdb"), "is_checked": True},
            {"file_path": str(root / "demo.mdb"), "is_checked": True},
            {"file_path": str(root / "unchecked.mdb"), "is_checked": False},
            {"file_path": str(root / "missing.mdb"), "is_checked": True},
            {"file_path": str(root / "notes.txt"), "is_checked": True},
        ]
        (root / "file_state.json").write_text(
            json.dumps({"file_entries": entries}), encoding="utf-8"
        )
        self.server = build_mcp_server(DatabaseRegistry(app_data_dir=root))
        with self.assertLogs(level="WARNING"):
            response = self.request(
                "tools/call", {"name": "list_databases", "arguments": {}}
            )["result"]
        self.assertFalse(response["isError"])
        data = response["structuredContent"]["data"]
        # Only the checked, existing, MDB, de-duplicated entry is exposed, as a
        # safe id and basename, never as a path.
        self.assertEqual(
            [(item["basename"], item["path_status"], item["exists"]) for item in data],
            [("demo.mdb", "checked", True)],
        )
        self.assertNotIn(str(root), json.dumps(response))
        # A raw filesystem path is not a database id and is rejected by the
        # registry before any database is opened.
        by_path = self.request(
            "tools/call",
            {
                "name": "list_projects",
                "arguments": {"database_id": str(root / "demo.mdb")},
            },
        )["result"]
        self.assertTrue(by_path["isError"])
        self.assertEqual(by_path["structuredContent"]["status"], "invalid_database_id")

    def test_saved_context_redacts_file_paths(self):
        class BridgeUnavailable:
            last_status = "bridge_unavailable"

            def get_context(self):
                return None

        root = Path(self.tmp.name)
        db_path = root / "private" / "demo.mdb"
        db_path.parent.mkdir()
        db_path.write_text("", encoding="utf-8")
        (root / "file_state.json").write_text(
            json.dumps(
                {"file_entries": [{"file_path": str(db_path), "is_checked": True}]}
            ),
            encoding="utf-8",
        )
        (root / "workspace_state.json").write_text(
            json.dumps(
                {
                    "project_workspace": {
                        "selected_node": {
                            "kind": "database",
                            "file_path": str(db_path),
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        with patch(
            "ost_visualizer.mcp_server.server.McpBridgeClient",
            return_value=BridgeUnavailable(),
        ):
            self.server = build_mcp_server(DatabaseRegistry(app_data_dir=root))
            response = self.request(
                "tools/call",
                {"name": "get_current_context", "arguments": {}},
            )["result"]["structuredContent"]
        encoded = json.dumps(response)
        self.assertNotIn(str(db_path), encoded)
        self.assertNotIn("file_path", encoded)
        self.assertEqual(response["data"]["file_basename"], "demo.mdb")

    def test_live_context_redacts_file_paths_and_resolves_database_id(self):
        root = Path(self.tmp.name)
        db_path = root / "private" / "live.mdb"
        db_path.parent.mkdir()
        db_path.write_text("", encoding="utf-8")
        (root / "file_state.json").write_text(
            json.dumps(
                {"file_entries": [{"file_path": str(db_path), "is_checked": True}]}
            ),
            encoding="utf-8",
        )

        class LiveBridge:
            last_status = "ok"

            def get_context(self):
                return {
                    "selected_file_path": str(db_path),
                    "selected_bid_ref": {
                        "file_path": str(db_path),
                        "bid_uid": "bid-7",
                    },
                    "active_page_uid": "page-3",
                    "selected_area_uid": "0",
                }

        with patch(
            "ost_visualizer.mcp_server.server.McpBridgeClient",
            return_value=LiveBridge(),
        ):
            self.server = build_mcp_server(DatabaseRegistry(app_data_dir=root))
            response = self.request(
                "tools/call",
                {"name": "get_current_context", "arguments": {}},
            )["result"]
        self.assertFalse(response["isError"])
        context = response["structuredContent"]
        self.assertEqual(context["status"], "live_context")
        self.assertNotIn(str(db_path), json.dumps(response))
        self.assertNotIn("file_path", json.dumps(response))
        data = context["data"]
        listed_id = self.request(
            "tools/call", {"name": "list_databases", "arguments": {}}
        )["result"]["structuredContent"]["data"][0]["database_id"]
        self.assertEqual(data["database_id"], listed_id)
        self.assertEqual(data["bid_uid"], "bid-7")
        self.assertEqual(data["selected_page_uid"], "page-3")
        self.assertEqual(data["selected_file_basename"], "live.mdb")
        self.assertEqual(data["selected_bid_ref"]["file_basename"], "live.mdb")
        self.assertIsNone(data["selected_area_name"])

    def test_prompts_list_and_get(self):
        prompts = self.request("prompts/list")["result"]["prompts"]
        prompt_names = {prompt["name"] for prompt in prompts}
        self.assertEqual(prompt_names, EXPECTED_PROMPTS)
        self.assertTrue(all(prompt["description"] for prompt in prompts))
        for name, arguments in PROMPT_ARGUMENTS.items():
            response = self.request(
                "prompts/get",
                {"name": name, "arguments": arguments},
            )["result"]
            self.assertEqual(response["messages"][0]["role"], "user")
            text = response["messages"][0]["content"]["text"]
            self.assertIn("read-only", text.lower())
            self.assertIn("truncated", text.lower())
            self.assertIn("has_more", text.lower())
            for key, value in arguments.items():
                self.assertIn(f"{key}={value}", text, name)
        scoped = self.request(
            "prompts/get",
            {
                "name": "review_markup_and_links",
                "arguments": {"database_id": "db", "bid_uid": "bid", "page_uid": "p9"},
            },
        )["result"]["messages"][0]["content"]["text"]
        self.assertIn("scope=page_uid=p9", scoped)
        unscoped = self.request(
            "prompts/get",
            {
                "name": "review_markup_and_links",
                "arguments": {"database_id": "db", "bid_uid": "bid"},
            },
        )["result"]["messages"][0]["content"]["text"]
        self.assertIn("scope=all pages in the bid", unscoped)

    def test_prompt_text_references_existing_tools_only(self):
        identifier_pattern = r"\b[a-z]+(?:_[a-z]+)+\b"
        for name, arguments in PROMPT_ARGUMENTS.items():
            response = self.request(
                "prompts/get",
                {"name": name, "arguments": arguments},
            )["result"]
            text = response["messages"][0]["content"]["text"]
            identifiers = set(re.findall(identifier_pattern, text))
            unknown = identifiers - ALLOWED_PROMPT_IDENTIFIERS
            self.assertEqual(unknown, set(), f"{name} references unknown identifiers")
            # Non-vacuity: every prompt actually names tools.
            self.assertTrue(identifiers & EXPECTED_TOOLS, name)

    def test_prompt_text_stays_within_read_only_safety_limits(self):
        for name, arguments in PROMPT_ARGUMENTS.items():
            response = self.request(
                "prompts/get",
                {"name": name, "arguments": arguments},
            )["result"]
            lower_text = response["messages"][0]["content"]["text"].lower()
            self.assertIn("read-only", lower_text, name)
            for term in FORBIDDEN_PROMPT_TERMS:
                self.assertNotIn(term, lower_text, name)
