import unittest
from ost_visualizer.application.dtos.mcp_context_dtos import (
    McpAreaDto,
    McpAreaSummaryDto,
    McpConditionDto,
    McpConditionQuantitySummaryDto,
    McpConditionSummaryDto,
    McpMarkupSampleDto,
    McpPageDto,
    McpPageMarkupsSummaryDto,
    McpPageOverlaySummaryDto,
    McpPageTakeoffSummaryDto,
    McpPdfTextSearchMatchDto,
    McpPdfTextSearchSummaryDto,
    McpPdfTextRunDto,
    McpPdfTextSummaryDto,
    McpPdfVectorSegmentDto,
    McpPdfVectorsSummaryDto,
    McpResultMetaDto,
    McpSelectedTakeoffsSummaryDto,
    McpTakeoffDto,
)
from ost_visualizer.mcp_server.serializers import error, ok


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
                "selected_takeoff_count",
                "missing_takeoff_uids",
                "takeoffs",
                "quantities",
                "pages",
                "condition_uids",
            },
        )

    def test_takeoff_shape_includes_area_name(self):
        payload = ok(McpTakeoffDto(uid="t1", condition_uid="c1"))
        self.assertIn("area_uid", payload["data"])
        self.assertIn("area_name", payload["data"])

    def test_page_shape_redacts_source_paths(self):
        payload = ok(McpPageDto(uid="p1", name="A101", image_basename="A101.pdf"))
        self.assertIn("image_basename", payload["data"])
        self.assertIn("image_path_status", payload["data"])
        self.assertIn("source_kind", payload["data"])
        self.assertIn("text_run_count", payload["data"])
        self.assertIn("snap_line_count", payload["data"])
        self.assertNotIn("image_path", payload["data"])
        self.assertNotIn("overlay_image_path", payload["data"])

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


if __name__ == "__main__":
    unittest.main()
