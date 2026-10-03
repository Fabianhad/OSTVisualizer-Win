import json
import unittest
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_NODE_CONDITION,
)
from ost_visualizer.application.dtos.mcp_context_dtos import (
    MCP_BID_COMPARISON_DEFAULT_LIMIT,
    McpAreaDto,
    McpAreaSummaryDto,
    McpBidComparisonDto,
    McpBidComparisonMetaDto,
    McpBidDto,
    McpConditionDto,
    McpConditionQuantitySummaryDto,
    McpConditionSummaryDto,
    McpMarkupSampleDto,
    McpPageDto,
    McpPageMarkupsSummaryDto,
    McpPageOverlaySummaryDto,
    McpPageTakeoffSummaryDto,
    McpPdfTextRunDto,
    McpPdfTextSearchMatchDto,
    McpPdfTextSearchSummaryDto,
    McpPdfTextSummaryDto,
    McpPdfVectorSegmentDto,
    McpPdfVectorsSummaryDto,
    McpResultMetaDto,
    McpSelectedPagesSummaryDto,
    McpSelectedTakeoffsSummaryDto,
    McpSummaryDto,
    McpSummaryGroupingDto,
    McpSummaryNodeDto,
    McpSummaryValuesDto,
    McpTakeoffDto,
)
from ost_visualizer.mcp_server.serializers import error, ok, to_jsonable


@dataclass
class _Inner:
    when: datetime
    where: Path


@dataclass
class _Outer:
    inner: _Inner
    tags: tuple = ()
    by_number: dict = field(default_factory=dict)


class McpSerializerBehaviourTests(unittest.TestCase):
    def test_to_jsonable_converts_nested_dataclasses_and_non_json_types(self):
        value = _Outer(
            inner=_Inner(
                when=datetime(2026, 7, 7, 12, 30, 45),
                where=Path("plans") / "A101.pdf",
            ),
            tags=("a", "b"),
            by_number={1: date(2026, 1, 2), 2.5: [Path("x")]},
        )
        converted = to_jsonable(value)
        self.assertEqual(
            converted,
            {
                "inner": {
                    "when": "2026-07-07T12:30:45",
                    "where": str(Path("plans") / "A101.pdf"),
                },
                "tags": ["a", "b"],
                "by_number": {"1": "2026-01-02", "2.5": ["x"]},
            },
        )
        # The result must be accepted by the JSON encoder used on stdio.
        self.assertEqual(json.loads(json.dumps(converted)), converted)

    def test_to_jsonable_turns_sets_into_lists_and_keeps_scalars(self):
        self.assertEqual(to_jsonable({3}), [3])
        self.assertEqual(sorted(to_jsonable({"b", "a"})), ["a", "b"])
        for scalar in (None, True, 7, 1.5, "text"):
            with self.subTest(scalar=scalar):
                self.assertIs(to_jsonable(scalar), scalar)

    def test_ok_wraps_data_with_default_status_and_omits_absent_meta(self):
        payload = ok({"when": date(2026, 1, 2)})
        self.assertEqual(
            payload,
            {"success": True, "status": "ok", "data": {"when": "2026-01-02"}},
        )

    def test_ok_keeps_explicit_status_and_empty_meta(self):
        payload = ok([], status="empty", meta={})
        self.assertEqual(
            payload,
            {"success": True, "status": "empty", "data": [], "meta": {}},
        )

    def test_ok_serializes_meta_dataclass_values(self):
        payload = ok(None, meta=McpResultMetaDto(limit=7, returned_count=3))
        self.assertEqual(payload["meta"]["limit"], 7)
        self.assertEqual(payload["meta"]["returned_count"], 3)
        self.assertIsNone(payload["data"])

    def test_error_envelope_uses_default_code_and_stringifies_message(self):
        self.assertEqual(
            error(ValueError("bad input")),
            {
                "success": False,
                "status": "mcp_error",
                "error": {"code": "mcp_error", "message": "bad input"},
            },
        )
        self.assertEqual(
            error("gone", code="not_found"),
            {
                "success": False,
                "status": "not_found",
                "error": {"code": "not_found", "message": "gone"},
            },
        )


class McpSchemaSnapshotTests(unittest.TestCase):
    def test_success_and_error_envelopes_have_stable_keys(self):
        success = ok({"value": 1}, status="ok", meta=McpResultMetaDto(limit=10))
        self.assertEqual(set(success.keys()), {"success", "status", "data", "meta"})
        self.assertEqual(
            set(success["meta"].keys()),
            {
                "limit",
                "returned_count",
                "total_count",
                "truncated",
                "has_more",
            },
        )
        failure = error("missing", code="not_found")
        self.assertEqual(set(failure.keys()), {"success", "status", "error"})
        self.assertEqual(set(failure["error"].keys()), {"code", "message"})

    def test_condition_summary_shape_is_stable(self):
        condition = McpConditionDto(
            uid="cond-1",
            name="Condition",
            condition_type=2,
            condition_type_name="count",
        )
        payload = ok(McpConditionSummaryDto(condition=condition))
        summary = payload["data"]
        self.assertEqual(
            set(summary.keys()),
            {
                "condition",
                "quantities",
                "pages",
                "takeoff_count",
                "visible_takeoff_count",
            },
        )

    def test_bid_comparison_default_shape_has_no_condition_details(self):
        payload = ok(
            McpBidComparisonDto(
                old_bid=McpBidDto(uid="old", name="Old"),
                new_bid=McpBidDto(uid="new", name="New"),
            ),
            meta=McpBidComparisonMetaDto(limit=MCP_BID_COMPARISON_DEFAULT_LIMIT),
        )
        self.assertEqual(
            set(payload["data"]),
            {
                "old_bid",
                "new_bid",
                "counts",
                "bid_metadata_changed",
                "bid_metadata_changes",
                "groups",
                "details",
                "duplicate_ref_nos",
                "warnings",
            },
        )
        self.assertEqual(payload["data"]["details"], [])
        self.assertEqual(
            set(payload["meta"]),
            {
                "limit",
                "returned_count",
                "total_count",
                "truncated",
                "has_more",
                "matched_by",
                "grouped_by",
                "details_included",
                "detail_returned_count",
                "detail_total_count",
                "details_truncated",
            },
        )
        self.assertEqual(payload["meta"]["matched_by"], "ref_no")
        self.assertEqual(payload["meta"]["grouped_by"], "cdn_type_name")

    def test_selected_takeoffs_summary_shape_is_stable(self):
        payload = ok(
            McpSelectedTakeoffsSummaryDto(
                status="ok",
                takeoffs=[McpTakeoffDto(uid="t1", condition_uid="c1")],
            )
        )
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "status",
                "message",
                "database_id",
                "bid_uid",
                "meta",
                "selected_takeoff_count",
                "missing_takeoff_uids",
                "takeoffs",
                "quantities",
                "pages",
                "condition_uids",
            },
        )

    def test_selected_pages_summary_shape_is_stable(self):
        payload = ok(McpSelectedPagesSummaryDto(status="ok"))
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "status",
                "message",
                "database_id",
                "bid_uid",
                "meta",
                "active_view",
                "active_page_uid",
                "selected_page_uids",
                "missing_page_uids",
                "pages",
            },
        )

    def test_takeoff_shape_includes_area_name(self):
        payload = ok(McpTakeoffDto(uid="t1", condition_uid="c1"))
        self.assertIn("area_uid", payload["data"])
        self.assertIn("area_name", payload["data"])
        self.assertEqual(
            set(payload["data"]),
            {
                "uid",
                "condition_uid",
                "condition_name",
                "page_uid",
                "page_name",
                "area_uid",
                "area_name",
                "parent_uid",
                "is_hole",
                "is_negative",
                "visible",
                "rotation",
                "curve",
                "point_count",
                "position",
            },
        )

    def test_page_shape_redacts_source_paths(self):
        payload = ok(McpPageDto(uid="p1", name="A101", image_basename="A101.pdf"))
        self.assertIn("image_basename", payload["data"])
        self.assertIn("image_path_status", payload["data"])
        self.assertIn("source_kind", payload["data"])
        self.assertIn("text_run_count", payload["data"])
        self.assertIn("snap_line_count", payload["data"])
        self.assertNotIn("image_path", payload["data"])
        self.assertNotIn("overlay_image_path", payload["data"])
        self.assertEqual(
            set(payload["data"]),
            {
                "uid",
                "name",
                "sheet_no",
                "sequence",
                "folder_uid",
                "image_basename",
                "image_path_status",
                "is_pdf",
                "page_index",
                "width_pts",
                "height_pts",
                "scale_factor1",
                "scale_factor2",
                "rotation",
                "layer_visible",
                "overlay_basename",
                "overlay_path_status",
                "has_overlay",
                "source_kind",
                "page_width",
                "page_height",
                "pdf_metadata_status",
                "pdf_page_count",
                "media_width_pts",
                "media_height_pts",
                "crop_width_pts",
                "crop_height_pts",
                "intrinsic_rotation",
                "has_embedded_text",
                "text_run_count",
                "character_count",
                "snap_line_count",
                "snap_point_count",
                "overlay_kind",
                "overlay_transform_summary",
                "takeoff_count",
            },
        )

    def test_pdf_text_summary_shape_is_stable(self):
        payload = ok(
            McpPdfTextSummaryDto(
                status="ok",
                database_id="db",
                bid_uid="bid",
                page_uid="page",
                source="main",
                source_status="configured",
                meta=McpResultMetaDto(limit=1),
                runs=[McpPdfTextRunDto(snippet="Door schedule")],
            )
        )
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "status",
                "database_id",
                "bid_uid",
                "page_uid",
                "source",
                "source_status",
                "meta",
                "text_run_count",
                "character_count",
                "returned_character_count",
                "runs",
            },
        )

    def test_pdf_vectors_summary_shape_is_stable(self):
        payload = ok(
            McpPdfVectorsSummaryDto(
                status="ok",
                database_id="db",
                bid_uid="bid",
                page_uid="page",
                source="main",
                source_status="configured",
                meta=McpResultMetaDto(limit=1),
                segments=[McpPdfVectorSegmentDto(0.0, 0.0, 1.0, 0.0)],
            )
        )
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "status",
                "database_id",
                "bid_uid",
                "page_uid",
                "source",
                "source_status",
                "meta",
                "snap_line_count",
                "snap_point_count",
                "segments",
            },
        )

    def test_page_markups_summary_shape_is_stable(self):
        payload = ok(
            McpPageMarkupsSummaryDto(
                status="ok",
                database_id="db",
                bid_uid="bid",
                page_uid="page",
                page_name="A101",
                sheet_no="S-101",
                meta=McpResultMetaDto(limit=1),
                samples=[McpMarkupSampleDto(uid="m1", annotation_type="text")],
            )
        )
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "status",
                "database_id",
                "bid_uid",
                "page_uid",
                "page_name",
                "sheet_no",
                "meta",
                "total_markup_count",
                "visible_markup_count",
                "dimension_count",
                "text_annotation_count",
                "callout_count",
                "hotlink_count",
                "named_view_count",
                "counts_by_type",
                "samples",
            },
        )
        self.assertNotIn("image_path", payload["data"])
        self.assertNotIn("text", payload["data"]["samples"][0])
        self.assertNotIn("position", payload["data"]["samples"][0])
        self.assertNotIn("properties", payload["data"]["samples"][0])

    def test_page_overlay_summary_shape_is_stable(self):
        payload = ok(
            McpPageOverlaySummaryDto(
                status="ok",
                database_id="db",
                bid_uid="bid",
                page_uid="page",
                page_name="A101",
                sheet_no="S-101",
            )
        )
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "status",
                "database_id",
                "bid_uid",
                "page_uid",
                "page_name",
                "sheet_no",
                "source_kind",
                "image_basename",
                "image_path_status",
                "is_pdf",
                "has_overlay",
                "overlay_basename",
                "overlay_path_status",
                "overlay_kind",
                "show_mode",
                "show_original",
                "show_overlay",
                "overlay_transform_summary",
            },
        )
        self.assertNotIn("overlay_image_path", payload["data"])
        self.assertNotIn("image_path", payload["data"])

    def test_pdf_text_search_summary_shape_is_stable(self):
        payload = ok(
            McpPdfTextSearchSummaryDto(
                status="ok",
                database_id="db",
                bid_uid="bid",
                page_uid="page",
                query="door",
                source="main",
                source_status="configured",
                meta=McpResultMetaDto(limit=1),
                matches=[
                    McpPdfTextSearchMatchDto(
                        page_uid="page",
                        page_name="A101",
                        sheet_no="S-101",
                        source="main",
                        snippet="Door schedule",
                    )
                ],
            )
        )
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "status",
                "database_id",
                "bid_uid",
                "page_uid",
                "query",
                "source",
                "source_status",
                "meta",
                "match_count",
                "matches",
            },
        )
        self.assertNotIn("text", payload["data"]["matches"][0])

    def test_area_summary_shape_is_stable(self):
        payload = ok(
            McpAreaSummaryDto(
                status="ok",
                database_id="db",
                bid_uid="bid",
                area=McpAreaDto(uid="a1", bid_uid="bid"),
                meta=McpResultMetaDto(limit=10),
                pages=[McpPageTakeoffSummaryDto(page_uid="p1", page_name="A101")],
            )
        )
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "status",
                "database_id",
                "bid_uid",
                "area",
                "meta",
                "pages",
                "children",
            },
        )

    def test_richer_quantity_summary_shape_is_stable(self):
        condition = McpConditionDto(
            uid="cond-1",
            name="Condition",
            condition_type=2,
            condition_type_name="count",
        )
        payload = ok(McpConditionQuantitySummaryDto(condition=condition))
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "condition",
                "quantities",
                "pages",
                "takeoff_count",
                "visible_takeoff_count",
                "page_count",
                "zero_quantity",
            },
        )

    def test_summary_shape_is_stable(self):
        payload = ok(
            McpSummaryDto(
                status="ok",
                database_id="db",
                bid_uid="bid",
                grouping=McpSummaryGroupingDto(),
                nodes=[
                    McpSummaryNodeDto(
                        kind=SUMMARY_NODE_CONDITION,
                        condition_uid="cond-1",
                        values=McpSummaryValuesDto(name="Condition"),
                    )
                ],
            )
        )
        self.assertEqual(
            set(payload["data"].keys()),
            {
                "status",
                "database_id",
                "bid_uid",
                "bid_name",
                "project_uid",
                "project_name",
                "grouping",
                "meta",
                "root_label",
                "total_node_count",
                "nodes",
            },
        )
        self.assertEqual(
            set(payload["data"]["grouping"].keys()),
            {"group_by_page", "group_by_type", "group_by_area"},
        )
        node = payload["data"]["nodes"][0]
        self.assertEqual(
            set(node.keys()),
            {
                "kind",
                "label",
                "condition_uid",
                "folder_uid",
                "group_level",
                "folder_path",
                "page",
                "type_name",
                "area",
                "values",
                "children",
                "child_count",
                "copyable",
                "deletable",
                "layer_visible",
                "color_fill",
                "pattern",
            },
        )
        self.assertEqual(
            set(node["values"].keys()),
            {
                "number",
                "name",
                "type_name",
                "height",
                "height_inches",
                "area",
                "quantity1",
                "uom1",
                "uom1_label",
                "quantity2",
                "uom2",
                "uom2_label",
                "quantity3",
                "uom3",
                "uom3_label",
                "notes",
            },
        )


if __name__ == "__main__":
    unittest.main()
