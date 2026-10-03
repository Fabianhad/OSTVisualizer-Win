import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import create_autospec, patch
from ost_visualizer.application.dtos.mcp_context_dtos import (
    MCP_BID_COMPARISON_DEFAULT_LIMIT,
    MCP_SUMMARY_DEFAULT_GROUP_BY_AREA,
    MCP_SUMMARY_DEFAULT_GROUP_BY_PAGE,
    MCP_SUMMARY_DEFAULT_GROUP_BY_TYPE,
    MCP_SUMMARY_DEFAULT_LIMIT,
    McpBidDto,
    McpResultMetaDto,
    McpSelectedPagesSummaryDto,
    McpSelectedTakeoffsSummaryDto,
    McpSummaryDto,
)
from ost_visualizer.application.services.bid_comparison_service import (
    BidComparisonResult,
)
from ost_visualizer.application.services.mcp_read_service import (
    McpLimitedList,
    McpReadError,
    McpReadService,
)
from ost_visualizer.domain.entities.area import UNASSIGNED_AREA_UID
from ost_visualizer.mcp_server import server as server_module
from ost_visualizer.mcp_server.internal_server import OstMcpServer
from ost_visualizer.mcp_server.registry import DatabaseRegistry
from ost_visualizer.mcp_server.server import build_mcp_server


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
            self.assertIsInstance(server, OstMcpServer)
            self.assertEqual(server.name, "ost-visualizer")
            # Public surface from AGENTS.md "MCP Guardrails".
            self.assertEqual(len(server.list_tools()), 38)
            self.assertEqual(len(server.list_prompts()), 7)
            self.assertEqual(len(server.list_resources()), 1)
            self.assertEqual(len(server.list_resource_templates()), 4)
            self.assertEqual(
                server._output_formatter.output_dir, registry.output_artifacts_dir
            )

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
        # Literal contract values, independent of the production constants.
        self.assertEqual(
            {
                name: spec["default"]
                for name, spec in properties.items()
                if "default" in spec
            },
            {
                "group_by_page": False,
                "group_by_type": True,
                "group_by_area": True,
                "limit": 500,
            },
        )

    def test_compare_bids_schema_is_minimal_and_bounded(self):
        from ost_visualizer.mcp_server.registry import DatabaseRegistry
        from ost_visualizer.mcp_server.server import build_mcp_server

        with tempfile.TemporaryDirectory() as tmp:
            registry = DatabaseRegistry(app_data_dir=Path(tmp))
            server = build_mcp_server(registry)
            tool = next(
                tool
                for tool in server.list_tools()
                if tool["name"] == "compare_bids_by_ref_no"
            )
        schema = tool["inputSchema"]
        self.assertEqual(
            schema["required"], ["database_id", "old_bid_uid", "new_bid_uid"]
        )
        self.assertEqual(
            set(schema["properties"]),
            {
                "database_id",
                "old_bid_uid",
                "new_bid_uid",
                "include_details",
                "limit",
            },
        )
        self.assertFalse(schema["properties"]["include_details"]["default"])
        self.assertEqual(
            schema["properties"]["limit"]["default"],
            MCP_BID_COMPARISON_DEFAULT_LIMIT,
        )
        self.assertEqual(schema["properties"]["limit"]["default"], 250)

    def test_collection_tool_schemas_expose_default_limits(self):
        from ost_visualizer.mcp_server.registry import DatabaseRegistry
        from ost_visualizer.mcp_server.server import build_mcp_server

        with tempfile.TemporaryDirectory() as tmp:
            registry = DatabaseRegistry(app_data_dir=Path(tmp))
            server = build_mcp_server(registry)
            tools = {tool["name"]: tool for tool in server.list_tools()}
        for name in (
            "list_databases",
            "list_projects",
            "list_bids",
            "get_selected_takeoffs_summary",
            "get_selected_pages_summary",
        ):
            self.assertEqual(
                tools[name]["inputSchema"]["properties"]["limit"]["default"],
                500,
            )


class FakeBridge:
    """Live-context bridge replacement; the real one talks to a named pipe."""

    def __init__(self, context=None, status="bridge_unavailable"):
        self.context = context
        self.last_status = status

    def get_context(self):
        if self.context is not None:
            self.last_status = "live_context"
        return self.context


class FakePage:
    def __init__(self, uid):
        self.uid = uid


class McpServerGuardrailTests(unittest.TestCase):
    ALLOWED_TOOL_PREFIXES = (
        "list_",
        "get_",
        "search_",
        "find_",
        "review_",
        "compare_",
        "summarize_",
    )
    FORBIDDEN_INPUT_FRAGMENTS = ("path", "sql", "app_data", "dir", "command", "csv")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        registry = DatabaseRegistry(app_data_dir=Path(self.tmp.name))
        self.server = build_mcp_server(registry)

    def test_every_tool_is_a_read_verb(self):
        names = [tool["name"] for tool in self.server.list_tools()]
        self.assertEqual(len(names), 38)
        offenders = [n for n in names if not n.startswith(self.ALLOWED_TOOL_PREFIXES)]
        self.assertEqual(offenders, [])

    def test_tool_inputs_cannot_select_paths_sql_or_app_data(self):
        properties = set()
        for tool in self.server.list_tools():
            properties.update(tool["inputSchema"]["properties"])
        self.assertIn("database_id", properties)
        self.assertNotIn("database", properties)
        offenders = sorted(
            name
            for name in properties
            if any(fragment in name for fragment in self.FORBIDDEN_INPUT_FRAGMENTS)
        )
        self.assertEqual(offenders, [])

    def test_prompts_and_resources_expose_no_path_or_sql_inputs(self):
        argument_names = {
            argument["name"]
            for prompt in self.server.list_prompts()
            for argument in prompt["arguments"]
        }
        self.assertEqual(argument_names, {"database_id", "bid_uid", "page_uid"})
        uris = [r["uri"] for r in self.server.list_resources()]
        uris += [t["uriTemplate"] for t in self.server.list_resource_templates()]
        self.assertEqual(len(uris), 5)
        self.assertTrue(all(uri.startswith("ost://") for uri in uris))


class McpServerToolWiringTests(unittest.TestCase):
    """Tools are exercised through the protocol against a spec'd read service."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.read_service = create_autospec(McpReadService, instance=True)
        self.logger = logging.getLogger("test_mcp_server_wiring")
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False
        self.rebuild()

    def rebuild(self):
        with patch.object(
            server_module, "create_read_service", return_value=self.read_service
        ):
            self.registry = DatabaseRegistry(app_data_dir=self.root, logger=self.logger)
            self.server = build_mcp_server(self.registry, logger=self.logger)

    def call(self, name, arguments=None, bridge=None):
        bridge = bridge or FakeBridge()
        with patch.object(server_module, "McpBridgeClient", return_value=bridge):
            response = self.server._handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}},
                }
            )
        return response["result"]

    def register_database(self, name="demo.mdb"):
        db_path = self.root / "private" / name
        db_path.parent.mkdir(exist_ok=True)
        db_path.write_text("", encoding="utf-8")
        (self.root / "file_state.json").write_text(
            json.dumps(
                {"file_entries": [{"file_path": str(db_path), "is_checked": True}]}
            ),
            encoding="utf-8",
        )
        return db_path

    def test_get_summary_forwards_grouping_flags_and_limit_in_order(self):
        self.read_service.get_summary.return_value = McpSummaryDto(
            status="ok", database_id="db", bid_uid="bid"
        )
        result = self.call("get_summary", {"database_id": "db", "bid_uid": "bid"})
        self.read_service.get_summary.assert_called_once_with(
            "db", "bid", False, True, True, 500
        )
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["data"]["bid_uid"], "bid")
        self.read_service.get_summary.reset_mock()
        self.call(
            "get_summary",
            {
                "database_id": "db",
                "bid_uid": "bid",
                "group_by_page": True,
                "group_by_type": False,
                "group_by_area": False,
                "limit": 7,
            },
        )
        self.read_service.get_summary.assert_called_once_with(
            "db", "bid", True, False, False, 7
        )

    def test_list_bids_forwards_project_scope_and_limit_with_meta(self):
        meta = McpResultMetaDto(
            limit=5, returned_count=1, total_count=3, truncated=True, has_more=True
        )
        self.read_service.list_bids.return_value = McpLimitedList(
            [McpBidDto(uid="b1", name="Bid")], meta
        )
        result = self.call(
            "list_bids", {"database_id": "db", "project_uid": "p1", "limit": 5}
        )
        self.read_service.list_bids.assert_called_once_with("db", "p1", limit=5)
        content = result["structuredContent"]
        self.assertEqual(content["status"], "truncated")
        self.assertEqual(content["data"][0]["uid"], "b1")
        self.assertEqual(
            content["meta"],
            {
                "limit": 5,
                "returned_count": 1,
                "total_count": 3,
                "truncated": True,
                "has_more": True,
            },
        )

    def test_plain_list_results_get_bounded_meta_and_status(self):
        self.read_service.list_projects.return_value = []
        empty = self.call("list_projects", {"database_id": "db", "limit": 99999})
        self.read_service.list_projects.assert_called_once_with("db", limit=99999)
        self.assertEqual(empty["structuredContent"]["status"], "empty")
        self.assertEqual(empty["structuredContent"]["meta"]["limit"], 5000)
        self.read_service.list_projects.return_value = ["p1", "p2"]
        full = self.call("list_projects", {"database_id": "db", "limit": 0})
        self.assertEqual(full["structuredContent"]["status"], "ok")
        self.assertEqual(full["structuredContent"]["meta"]["limit"], 1)
        self.assertEqual(full["structuredContent"]["meta"]["returned_count"], 2)

    def test_compare_bids_forwards_arguments_and_uses_result_status_and_meta(self):
        meta = McpResultMetaDto(limit=3, returned_count=2, total_count=2)
        self.read_service.compare_bids_by_ref_no.return_value = BidComparisonResult(
            data={"counts": {"added": 1}}, status="ok", meta=meta
        )
        result = self.call(
            "compare_bids_by_ref_no",
            {
                "database_id": "db",
                "old_bid_uid": "old",
                "new_bid_uid": "new",
                "include_details": True,
                "limit": 3,
            },
        )
        self.read_service.compare_bids_by_ref_no.assert_called_once_with(
            "db", "old", "new", include_details=True, limit=3
        )
        content = result["structuredContent"]
        self.assertEqual(content["data"], {"counts": {"added": 1}})
        self.assertEqual(content["meta"]["limit"], 3)
        self.read_service.compare_bids_by_ref_no.reset_mock()
        self.call(
            "compare_bids_by_ref_no",
            {"database_id": "db", "old_bid_uid": "old", "new_bid_uid": "new"},
        )
        self.read_service.compare_bids_by_ref_no.assert_called_once_with(
            "db", "old", "new", include_details=False, limit=250
        )

    def test_read_errors_become_error_envelopes_with_stable_codes(self):
        cases = (
            ("Unknown database_id: nope", "invalid_database_id"),
            ("Unknown bid_uid: nope", "not_found"),
            ("limit must be positive", "read_error"),
        )
        for message, code in cases:
            with self.subTest(code=code):
                self.read_service.get_bid_summary.side_effect = McpReadError(message)
                result = self.call(
                    "get_bid_summary", {"database_id": "db", "bid_uid": "bid"}
                )
                self.assertTrue(result["isError"])
                self.assertEqual(
                    result["structuredContent"],
                    {
                        "success": False,
                        "status": code,
                        "error": {"code": code, "message": message},
                    },
                )

    def test_unexpected_read_failures_are_logged_and_reported_not_raised(self):
        self.read_service.get_bid_summary.side_effect = RuntimeError("disk exploded")
        with self.assertLogs(self.logger, level="ERROR") as logged:
            result = self.call(
                "get_bid_summary", {"database_id": "db", "bid_uid": "bid"}
            )
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["status"], "unexpected_error")
        self.assertEqual(
            result["structuredContent"]["error"]["message"], "disk exploded"
        )
        self.assertIn("MCP read failed", logged.output[0])

    def test_list_databases_reloads_checked_files_on_every_call(self):
        self.read_service.list_databases.return_value = McpLimitedList(
            [], McpResultMetaDto(limit=500)
        )
        empty = self.call("list_databases")
        self.assertEqual(empty["structuredContent"]["status"], "no_checked_database")
        self.assertEqual(self.read_service.set_databases.call_args.args[0], [])
        db_path = self.register_database()
        self.read_service.list_databases.return_value = McpLimitedList(
            ["demo"], McpResultMetaDto(limit=500, returned_count=1, total_count=1)
        )
        found = self.call("list_databases")
        self.assertEqual(found["structuredContent"]["status"], "ok")
        refs = self.read_service.set_databases.call_args.args[0]
        self.assertEqual(
            [(ref.display_name, ref.file_path) for ref in refs],
            [("demo", str(db_path.resolve()))],
        )

    def test_live_context_is_redacted_and_resolved_to_database_ids(self):
        db_path = self.register_database()
        self.rebuild()
        database_id = self.registry.databases[0].database_id
        self.read_service.resolve_area_name.return_value = "North Wing"
        live = {
            "selected_file_path": str(db_path),
            "file_path": str(db_path),
            "selected_bid_ref": {"file_path": str(db_path), "bid_uid": "b1"},
            "current_bid_ref": None,
            "selected_bid_refs": [{"file_path": str(db_path), "bid_uid": "b1"}],
            "active_page_uid": "page-9",
            "selected_area_uid": "area-1",
        }
        result = self.call("get_current_context", bridge=FakeBridge(live))
        content = result["structuredContent"]
        self.assertEqual(content["status"], "live_context")
        data = content["data"]
        self.assertEqual(data["database_id"], database_id)
        self.assertEqual(data["bid_uid"], "b1")
        self.assertEqual(data["selected_page_uid"], "page-9")
        self.assertEqual(data["selected_area_name"], "North Wing")
        self.assertEqual(data["selected_file_basename"], "demo.mdb")
        self.assertEqual(data["selected_bid_ref"]["file_basename"], "demo.mdb")
        self.assertEqual(data["selected_bid_refs"][0]["database_id"], database_id)
        self.assertNotIn(str(db_path), json.dumps(content))
        self.assertNotIn("file_path", json.dumps(content))
        self.read_service.resolve_area_name.assert_called_once_with(
            database_id, "b1", "area-1"
        )

    def test_live_context_area_name_is_none_when_resolution_fails(self):
        db_path = self.register_database()
        self.rebuild()
        live = {
            "selected_bid_ref": {"file_path": str(db_path), "bid_uid": "b1"},
            "selected_area_uid": "area-1",
        }
        self.read_service.resolve_area_name.side_effect = McpReadError("Unknown area")
        data = self.call("get_current_context", bridge=FakeBridge(live))[
            "structuredContent"
        ]["data"]
        self.assertIsNone(data["selected_area_name"])
        self.read_service.resolve_area_name.side_effect = RuntimeError("boom")
        with self.assertLogs(self.logger, level="ERROR"):
            data = self.call("get_current_context", bridge=FakeBridge(live))[
                "structuredContent"
            ]["data"]
        self.assertIsNone(data["selected_area_name"])

    def test_live_context_without_a_real_area_does_not_resolve_a_name(self):
        db_path = self.register_database()
        self.rebuild()
        ref = {"file_path": str(db_path), "bid_uid": "b1"}
        for area_uid in (UNASSIGNED_AREA_UID, None):
            with self.subTest(area_uid=area_uid):
                live = {"selected_bid_ref": ref, "selected_area_uid": area_uid}
                data = self.call("get_current_context", bridge=FakeBridge(live))[
                    "structuredContent"
                ]["data"]
                self.assertIn("selected_area_name", data)
                self.assertIsNone(data["selected_area_name"])
        live = {"selected_area_uid": "area-1"}
        data = self.call("get_current_context", bridge=FakeBridge(live))[
            "structuredContent"
        ]["data"]
        self.assertIsNone(data["selected_area_name"])
        self.read_service.resolve_area_name.assert_not_called()

    def test_saved_context_reports_bridge_status_and_resolves_current_page(self):
        db_path = self.register_database()
        (self.root / "workspace_state.json").write_text(
            json.dumps(
                {
                    "project_workspace": {
                        "selected_node": {
                            "kind": "bid",
                            "file_path": str(db_path),
                            "bid_uid": "bid-1",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        self.rebuild()
        self.read_service.get_current_page.return_value = FakePage("p9")
        result = self.call(
            "get_current_context",
            bridge=FakeBridge(None, status="malformed_bridge_payload"),
        )
        content = result["structuredContent"]
        self.assertEqual(content["status"], "saved_context")
        data = content["data"]
        self.assertEqual(data["source"], "saved_workspace")
        self.assertEqual(data["bridge_status"], "malformed_bridge_payload")
        self.assertEqual(data["selected_page_uid"], "p9")
        self.assertEqual(data["file_basename"], "demo.mdb")
        self.assertEqual(data["bid_uid"], "bid-1")
        self.read_service.get_current_page.assert_called_once_with(
            self.registry.databases[0].database_id, "bid-1"
        )
        self.assertNotIn("file_path", data)
        self.read_service.get_current_page.side_effect = McpReadError("Unknown bid_uid")
        data = self.call("get_current_context")["structuredContent"]["data"]
        self.assertIsNone(data["selected_page_uid"])

    def test_saved_context_without_checked_databases_says_so(self):
        data = self.call("get_current_context")["structuredContent"]
        self.assertEqual(data["status"], "no_checked_database")
        self.assertEqual(data["data"]["source"], "saved_workspace")
        self.assertEqual(data["data"]["bridge_status"], "bridge_unavailable")
        self.assertIsNone(data["data"]["database_id"])
        self.read_service.get_current_page.assert_not_called()

    def test_selected_takeoffs_summary_reports_each_unavailable_state(self):
        unavailable = self.call(
            "get_selected_takeoffs_summary",
            bridge=FakeBridge(None, status="malformed_bridge_payload"),
        )["structuredContent"]["data"]
        self.assertEqual(unavailable["status"], "malformed_bridge_payload")
        self.assertIn("not running", unavailable["message"])
        no_bid = self.call(
            "get_selected_takeoffs_summary",
            bridge=FakeBridge({"selected_takeoff_uids": ["t1"]}),
        )["structuredContent"]["data"]
        self.assertEqual(no_bid["status"], "no_active_bid")
        db_path = self.register_database()
        self.rebuild()
        database_id = self.registry.databases[0].database_id
        ref = {"file_path": str(db_path), "bid_uid": "b1"}
        for selection in ([], None):
            with self.subTest(selection=selection):
                none = self.call(
                    "get_selected_takeoffs_summary",
                    bridge=FakeBridge(
                        {"selected_bid_ref": ref, "selected_takeoff_uids": selection}
                    ),
                )["structuredContent"]["data"]
                self.assertEqual(none["status"], "no_selection")
                self.assertEqual(
                    (none["database_id"], none["bid_uid"]), (database_id, "b1")
                )
        self.read_service.get_selected_takeoffs_summary.assert_not_called()

    def test_selected_takeoffs_and_pages_forward_live_selection(self):
        db_path = self.register_database()
        self.rebuild()
        database_id = self.registry.databases[0].database_id
        ref = {"file_path": str(db_path), "bid_uid": "b1"}
        self.read_service.get_selected_takeoffs_summary.return_value = (
            McpSelectedTakeoffsSummaryDto(status="ok")
        )
        self.call(
            "get_selected_takeoffs_summary",
            {"limit": 4},
            bridge=FakeBridge(
                {"selected_bid_ref": ref, "selected_takeoff_uids": ["t1", "t2"]}
            ),
        )
        self.read_service.get_selected_takeoffs_summary.assert_called_once_with(
            database_id, "b1", ["t1", "t2"], limit=4
        )
        self.read_service.get_selected_pages_summary.return_value = (
            McpSelectedPagesSummaryDto(status="ok")
        )
        self.call(
            "get_selected_pages_summary",
            {"limit": 6},
            bridge=FakeBridge(
                {
                    "selected_bid_ref": ref,
                    "selected_page_uids": ["pg1"],
                    "active_view": "2d",
                    "active_page_uid": "pg1",
                }
            ),
        )
        self.read_service.get_selected_pages_summary.assert_called_once_with(
            database_id, "b1", ["pg1"], "2d", "pg1", limit=6
        )

    def test_selected_pages_summary_reports_each_unavailable_state(self):
        unavailable = self.call(
            "get_selected_pages_summary",
            bridge=FakeBridge(None, status="malformed_bridge_payload"),
        )["structuredContent"]["data"]
        self.assertEqual(unavailable["status"], "malformed_bridge_payload")
        no_bid = self.call(
            "get_selected_pages_summary",
            bridge=FakeBridge({"active_view": "3d", "active_page_uid": "pg1"}),
        )["structuredContent"]["data"]
        self.assertEqual(no_bid["status"], "no_active_bid")
        self.assertEqual(
            (no_bid["active_view"], no_bid["active_page_uid"]), ("3d", "pg1")
        )
        db_path = self.register_database()
        self.rebuild()
        ref = {"file_path": str(db_path), "bid_uid": "b1"}
        none = self.call(
            "get_selected_pages_summary",
            bridge=FakeBridge({"selected_bid_ref": ref, "selected_page_uids": []}),
        )["structuredContent"]["data"]
        self.assertEqual(none["status"], "no_selection")
        self.read_service.get_selected_pages_summary.assert_not_called()


class McpServerHelperTests(unittest.TestCase):
    def test_read_error_codes_follow_message_prefix(self):
        self.assertEqual(
            server_module._read_error_code("Unknown database_id: x"),
            "invalid_database_id",
        )
        self.assertEqual(
            server_module._read_error_code("Unknown page_uid: x"), "not_found"
        )
        self.assertEqual(
            server_module._read_error_code("limit too large"), "read_error"
        )

    def test_basename_handles_both_separators_and_trailing_slash(self):
        self.assertEqual(server_module._basename("C:\\plans\\demo.mdb"), "demo.mdb")
        self.assertEqual(server_module._basename("/srv/plans/demo.mdb"), "demo.mdb")
        self.assertEqual(server_module._basename("/srv/plans/"), "plans")

    def test_tool_limit_is_clamped_and_falls_back_to_default(self):
        clean = server_module._clean_tool_limit
        self.assertEqual(clean(10), 10)
        self.assertEqual(clean(0), 1)
        self.assertEqual(clean(-5), 1)
        self.assertEqual(clean(99999), 5000)
        self.assertEqual(clean("25"), 25)
        self.assertEqual(clean("many"), 500)
        self.assertEqual(clean(None), 500)

    def test_with_database_id_strips_path_and_adds_id_and_basename(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "demo.mdb"
        db_path.write_text("", encoding="utf-8")
        (Path(tmp.name) / "file_state.json").write_text(
            json.dumps(
                {"file_entries": [{"file_path": str(db_path), "is_checked": True}]}
            ),
            encoding="utf-8",
        )
        registry = DatabaseRegistry(app_data_dir=Path(tmp.name))
        original = {"file_path": str(db_path), "bid_uid": "b1"}
        converted = server_module._with_database_id(original, registry)
        self.assertEqual(
            converted,
            {
                "bid_uid": "b1",
                "database_id": registry.databases[0].database_id,
                "file_basename": "demo.mdb",
            },
        )
        self.assertIn("file_path", original)
        self.assertEqual(server_module._with_database_id("text", registry), "text")
        self.assertIsNone(server_module._with_database_id(None, registry))
        unknown = server_module._with_database_id(
            {"file_path": str(Path(tmp.name) / "other.mdb")}, registry
        )
        self.assertIsNone(unknown["database_id"])
        self.assertNotIn("file_path", unknown)


if __name__ == "__main__":
    unittest.main()
