import unittest
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_GROUP_AREA,
    SUMMARY_GROUP_PAGE,
    SUMMARY_GROUP_TYPE,
    SUMMARY_MULTI_AREA_TOTAL_LABEL,
    SUMMARY_NODE_AREA_DETAIL,
    SUMMARY_NODE_CONDITION,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_GROUP,
    SUMMARY_NODE_MULTI_AREA_TOTAL,
)
from ost_visualizer.application.dtos.pdf_metadata_dtos import (
    PdfPageInfoDto,
    PdfTextRunDto,
    PdfVectorSegmentDto,
)
from ost_visualizer.application.services.mcp_read_service import (
    McpDatabaseRef,
    McpReadError,
    McpReadService,
)
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.file_results import BidLoadResult, FileLoadResult
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH


class FakeProjectRepository:
    def __init__(self):
        self.file_path = r"C:\jobs\private\demo.mdb"
        self.hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=self.file_path,
                    display_name="Demo",
                    bid_projects={
                        "project-1": HierarchyProjectInfo(
                            name="Project One",
                            bids=[
                                HierarchyBidInfo(
                                    uid="bid-1",
                                    name="Bid One",
                                    page_count=2,
                                    condition_count=2,
                                )
                            ],
                        )
                    },
                )
            ]
        )
        visible = Condition(
            uid="cond-1",
            name="Visible Count",
            condition_type=Condition.TYPE_COUNT,
            calc_type1=CALC_COUNT,
            uom1=UOM_EACH,
            ref_no=1,
            layer_uid="layer-1",
            cdn_type_uid="type-a",
            cdn_type_name="Type A",
            folder_uid="folder-1",
            height=12.0,
            notes="Visible notes",
        )
        hidden = Condition(
            uid="cond-2",
            name="Hidden Count",
            condition_type=Condition.TYPE_COUNT,
            calc_type1=CALC_COUNT,
            uom1=UOM_EACH,
            ref_no=2,
            layer_visible=False,
            layer_uid="layer-2",
            cdn_type_uid="type-b",
            cdn_type_name="Type B",
        )
        unused = Condition(
            uid="cond-3",
            name="Unused Linear",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=3,
            layer_uid="layer-1",
            cdn_type_uid="type-a",
            cdn_type_name="Type A",
            folder_uid="folder-1",
        )
        page1 = Page(
            uid="page-1",
            name="A101",
            sheet_no="S-101",
            sequence=10,
            image_path=r"C:\plans\A101.pdf",
            overlay_image_path=r"C:\plans\A101-overlay.pdf",
            overlay_offset_x=1.5,
            overlay_offset_y=2.5,
            overlay_rotation=0.25,
            deskew_rotation_overlay=0.5,
            overlay_rect=(0.0, 0.0, 306.0, 396.0),
            image_show_mode=2,
            page_index=0,
        )
        page2 = Page(
            uid="page-2",
            name="A102",
            sheet_no="S-102",
            sequence=20,
            image_path=r"C:\plans\A102.pdf",
            page_index=1,
        )
        page3 = Page(
            uid="page-3",
            name="A103",
            sheet_no="S-103",
            sequence=30,
            image_path=r"C:\plans\A103.pdf",
            page_index=2,
        )
        t1 = Takeoff(
            uid="takeoff-1",
            condition_uid="cond-1",
            page_uid="page-1",
            area_uid="area-1",
            position=[1.0, 2.0],
        )
        t2 = Takeoff(
            uid="takeoff-2",
            condition_uid="cond-1",
            page_uid="page-1",
            area_uid="area-1",
            position=[3.0, 4.0],
        )
        t3 = Takeoff(
            uid="takeoff-hidden",
            condition_uid="cond-2",
            page_uid="page-2",
            area_uid="0",
            position=[5.0, 6.0],
        )
        page1.takeoffs = [t1, t2]
        page2.takeoffs = [t3]
        self.bid_data = BidLoadResult(
            bid_conditions={"cond-1": visible, "cond-2": hidden, "cond-3": unused},
            bid_condition_folders={
                "folder-1": BidConditionFolder(
                    uid="folder-1", bid_uid="bid-1", name="Foundation"
                )
            },
            bid_takeoffs=[t1, t2, t3],
            bid_areas={
                "area-1": BidArea(
                    uid="area-1",
                    bid_uid="bid-1",
                    parent_uid="",
                    name="Level One Deck",
                    sequence=1,
                    guid="{AREA-1}",
                ),
                "area-2": BidArea(
                    uid="area-2",
                    bid_uid="bid-1",
                    parent_uid="area-1",
                    name="Nested Area",
                    sequence=2,
                    guid="{AREA-2}",
                ),
            },
            bid_layers=[
                BidLayer(
                    uid="layer-1",
                    bid_uid="bid-1",
                    name="Takeoff",
                    show=True,
                    sequence=1,
                ),
                BidLayer(
                    uid="layer-2",
                    bid_uid="bid-1",
                    name="Hidden",
                    show=False,
                    sequence=2,
                    is_locked=True,
                ),
            ],
            bid_annotations=[
                BidAnnotation(
                    uid="text-1",
                    annotation_type="text",
                    page_uid="page-1",
                    layer_uid="layer-1",
                    position=[15.0, 25.0, 40.0, 10.0, 0.0],
                    properties={
                        "Text": (
                            "Private owner note with a deliberately long markup text "
                            "body that should be summarized without returning the full "
                            "annotation contents"
                        )
                    },
                ),
                BidAnnotation(
                    uid="dimension-1",
                    annotation_type="dimension",
                    page_uid="page-1",
                    position=[0.0, 0.0, 3.0, 4.0],
                    properties={"BidTakeoffFromUID": "takeoff-1"},
                ),
                BidAnnotation(
                    uid="view-1",
                    annotation_type="namedview",
                    page_uid="page-1",
                    position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
                    properties={"Text": "Lobby Detail"},
                ),
                BidAnnotation(
                    uid="hotlink-1",
                    annotation_type="hotlink",
                    page_uid="page-2",
                    layer_uid="layer-1",
                    properties={"BidPageViewUID": "view-1"},
                ),
            ],
            pages={"page-1": page1, "page-2": page2, "page-3": page3},
            selected_page_uid="page-2",
        )

    def load_file(self, file_path):
        return FileLoadResult(success=True, hierarchy=self.hierarchy)

    def load_bid(self, bid_uid, file_path=None):
        return self.bid_data if bid_uid == "bid-1" else BidLoadResult()


class FakePdfMetadataProvider:
    def get_page_info(self, file_path, page_index):
        if file_path.endswith("A101-overlay.pdf"):
            return PdfPageInfoDto(
                status="ok",
                page_count=1,
                effective_width_pts=300.0,
                effective_height_pts=200.0,
                media_width_pts=300.0,
                media_height_pts=200.0,
                crop_width_pts=300.0,
                crop_height_pts=200.0,
                intrinsic_rotation=90,
            )
        if file_path.endswith(".pdf"):
            return PdfPageInfoDto(
                status="ok",
                page_count=3,
                effective_width_pts=612.0,
                effective_height_pts=792.0,
                media_width_pts=612.0,
                media_height_pts=792.0,
                crop_width_pts=612.0,
                crop_height_pts=792.0,
                intrinsic_rotation=0,
            )
        return PdfPageInfoDto(status="not_pdf")

    def get_text_runs(self, file_path, page_index):
        if file_path.endswith("A103.pdf"):
            return []
        if file_path.endswith("A101-overlay.pdf"):
            return [
                PdfTextRunDto(
                    text="Overlay note",
                    left=1.0,
                    top=2.0,
                    right=20.0,
                    bottom=8.0,
                )
            ]
        return [
            PdfTextRunDto(
                text="Private title block with a deliberately long embedded PDF text run",
                left=10.0,
                top=20.0,
                right=100.0,
                bottom=30.0,
            ),
            PdfTextRunDto(
                text="Door schedule",
                left=12.0,
                top=40.0,
                right=80.0,
                bottom=50.0,
            ),
        ]

    def get_vector_segments(self, file_path, page_index):
        if file_path.endswith("A103.pdf"):
            return []
        if file_path.endswith("A101-overlay.pdf"):
            return [PdfVectorSegmentDto(0.0, 0.0, 0.0, 20.0)]
        return [
            PdfVectorSegmentDto(0.0, 0.0, 10.0, 0.0),
            PdfVectorSegmentDto(10.0, 0.0, 10.0, 10.0),
            PdfVectorSegmentDto(0.0, 0.0, 10.0, 10.0),
        ]


class McpReadServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeProjectRepository()
        self.service = McpReadService(
            self.repo,
            [
                McpDatabaseRef(
                    database_id="db-1",
                    file_path=self.repo.file_path,
                    display_name="Demo",
                )
            ],
            pdf_metadata_provider=FakePdfMetadataProvider(),
        )

    def test_lists_projects_and_bids(self):
        projects = self.service.list_projects("db-1")
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].uid, "project-1")
        bids = self.service.list_bids("db-1")
        self.assertEqual(len(bids), 1)
        self.assertEqual(bids[0].uid, "bid-1")

    def test_database_and_page_outputs_redact_local_paths(self):
        databases = self.service.list_databases()
        self.assertEqual(databases[0].basename, "demo.mdb")
        self.assertFalse("file_path" in databases[0].__dict__)
        pages = self.service.list_pages("db-1", "bid-1")
        self.assertEqual(pages[0].image_basename, "A101.pdf")
        self.assertEqual(pages[0].overlay_basename, "A101-overlay.pdf")
        self.assertEqual(pages[0].image_path_status, "configured")
        self.assertEqual(pages[0].overlay_path_status, "configured")
        self.assertFalse("image_path" in pages[0].__dict__)
        self.assertFalse("overlay_image_path" in pages[0].__dict__)

    def test_page_metadata_includes_safe_pdf_summary_without_paths(self):
        page = self.service.get_page_metadata("db-1", "bid-1", "page-1")
        self.assertEqual(page.source_kind, "composite")
        self.assertEqual(page.pdf_metadata_status, "ok")
        self.assertEqual(page.page_width, 612.0)
        self.assertEqual(page.page_height, 792.0)
        self.assertEqual(page.pdf_page_count, 3)
        self.assertTrue(page.has_embedded_text)
        self.assertEqual(page.text_run_count, 2)
        self.assertEqual(page.snap_line_count, 3)
        self.assertEqual(page.snap_point_count, 3)
        self.assertEqual(page.overlay_kind, "pdf")
        self.assertEqual(page.overlay_transform_summary.offset_x, 1.5)
        self.assertEqual(page.overlay_transform_summary.offset_y, 2.5)
        self.assertEqual(page.overlay_transform_summary.rotation, 0.75)
        self.assertFalse("image_path" in page.__dict__)
        self.assertFalse("overlay_image_path" in page.__dict__)

    def test_pdf_text_summary_is_bounded_and_redacted_by_default(self):
        summary = self.service.get_page_pdf_text_summary(
            "db-1", "bid-1", "page-1", limit=1
        )
        self.assertEqual(summary.status, "truncated")
        self.assertEqual(summary.source, "main")
        self.assertEqual(summary.meta.returned_count, 1)
        self.assertEqual(summary.meta.total_count, 2)
        self.assertTrue(summary.meta.has_more)
        self.assertEqual(summary.text_run_count, 2)
        self.assertGreater(summary.character_count, summary.returned_character_count)
        self.assertIsNone(summary.runs[0].text)
        self.assertTrue(summary.runs[0].snippet.startswith("Private title block"))

    def test_pdf_text_summary_can_include_strictly_limited_text_and_overlay_source(
        self,
    ):
        summary = self.service.get_page_pdf_text_summary(
            "db-1",
            "bid-1",
            "page-1",
            source="overlay",
            include_text=True,
            limit=5,
        )
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.source, "overlay")
        self.assertEqual(summary.meta.returned_count, 1)
        self.assertEqual(summary.runs[0].text, "Overlay note")
        self.assertEqual(summary.runs[0].left, 1.0)
        self.assertEqual(summary.runs[0].character_count, 12)

    def test_pdf_vectors_summary_is_bounded_and_reports_snap_counts(self):
        summary = self.service.get_page_pdf_vectors_summary(
            "db-1", "bid-1", "page-1", limit=2
        )
        self.assertEqual(summary.status, "truncated")
        self.assertEqual(summary.source, "main")
        self.assertEqual(summary.snap_line_count, 3)
        self.assertEqual(summary.snap_point_count, 3)
        self.assertEqual(summary.meta.returned_count, 2)
        self.assertTrue(summary.meta.has_more)
        self.assertEqual(summary.segments[0].orientation, "horizontal")
        self.assertEqual(summary.segments[1].orientation, "vertical")

    def test_pdf_summaries_handle_no_text_and_overlay_vectors(self):
        empty_text = self.service.get_page_pdf_text_summary("db-1", "bid-1", "page-3")
        self.assertEqual(empty_text.status, "empty")
        self.assertEqual(empty_text.meta.returned_count, 0)
        overlay_vectors = self.service.get_page_pdf_vectors_summary(
            "db-1", "bid-1", "page-1", source="overlay"
        )
        self.assertEqual(overlay_vectors.status, "ok")
        self.assertEqual(overlay_vectors.source, "overlay")
        self.assertEqual(overlay_vectors.snap_line_count, 1)
        self.assertEqual(overlay_vectors.segments[0].orientation, "vertical")

    def test_pdf_summary_rejects_unknown_source_without_path_inputs(self):
        with self.assertRaises(McpReadError):
            self.service.get_page_pdf_text_summary(
                "db-1", "bid-1", "page-1", source=r"C:\plans\A101.pdf"
            )

    def test_page_markups_summary_is_bounded_and_redacts_text(self):
        summary = self.service.get_page_markups_summary(
            "db-1", "bid-1", "page-1", limit=2
        )
        self.assertEqual(summary.status, "truncated")
        self.assertEqual(summary.total_markup_count, 3)
        self.assertEqual(summary.visible_markup_count, 3)
        self.assertEqual(summary.text_annotation_count, 1)
        self.assertEqual(summary.dimension_count, 1)
        self.assertEqual(summary.named_view_count, 1)
        self.assertEqual(summary.counts_by_type["text"], 1)
        self.assertEqual(summary.meta.limit, 2)
        self.assertEqual(summary.meta.returned_count, 2)
        self.assertEqual(summary.meta.total_count, 3)
        self.assertTrue(summary.meta.truncated)
        self.assertTrue(summary.meta.has_more)
        by_type = {sample.annotation_type: sample for sample in summary.samples}
        self.assertIn("text", by_type)
        self.assertIn("dimension", by_type)
        self.assertTrue(by_type["text"].text_snippet.startswith("Private owner note"))
        self.assertLess(
            len(by_type["text"].text_snippet),
            by_type["text"].text_character_count,
        )
        self.assertFalse("text" in by_type["text"].__dict__)
        self.assertFalse("position" in by_type["text"].__dict__)
        self.assertFalse("properties" in by_type["text"].__dict__)
        self.assertEqual(by_type["dimension"].length, 5.0)
        self.assertEqual(by_type["dimension"].linked_takeoff_count, 1)
        self.assertFalse("image_path" in summary.__dict__)
        self.assertFalse("overlay_image_path" in summary.__dict__)

    def test_page_overlay_summary_redacts_paths_and_reports_show_mode(self):
        summary = self.service.get_page_overlay_summary("db-1", "bid-1", "page-1")
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.source_kind, "composite")
        self.assertEqual(summary.image_basename, "A101.pdf")
        self.assertEqual(summary.overlay_basename, "A101-overlay.pdf")
        self.assertEqual(summary.overlay_kind, "pdf")
        self.assertTrue(summary.show_original)
        self.assertTrue(summary.show_overlay)
        self.assertEqual(summary.overlay_transform_summary.rotation, 0.75)
        self.assertFalse("image_path" in summary.__dict__)
        self.assertFalse("overlay_image_path" in summary.__dict__)

    def test_search_page_pdf_text_is_bounded_and_snippet_only(self):
        summary = self.service.search_page_pdf_text(
            "db-1", "bid-1", "page-1", query="schedule", limit=1
        )
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.source, "main")
        self.assertEqual(summary.match_count, 1)
        self.assertEqual(summary.meta.limit, 1)
        self.assertEqual(summary.meta.returned_count, 1)
        self.assertEqual(summary.meta.total_count, 1)
        self.assertFalse(summary.meta.truncated)
        self.assertFalse(summary.meta.has_more)
        self.assertEqual(summary.matches[0].snippet, "Door schedule")
        self.assertEqual(summary.matches[0].page_name, "A101")
        self.assertFalse("text" in summary.matches[0].__dict__)

    def test_search_page_pdf_text_rejects_unknown_source(self):
        with self.assertRaises(McpReadError):
            self.service.search_page_pdf_text(
                "db-1", "bid-1", "page-1", "schedule", source=r"C:\plans\A101.pdf"
            )

    def test_page_lists_include_sheet_sequence_and_limit_metadata(self):
        pages = self.service.list_pages("db-1", "bid-1", limit=2)
        self.assertEqual([page.uid for page in pages], ["page-1", "page-2"])
        self.assertEqual(pages[0].sheet_no, "S-101")
        self.assertEqual(pages[0].sequence, 10)
        self.assertEqual(pages.meta.limit, 2)
        self.assertEqual(pages.meta.returned_count, 2)
        self.assertEqual(pages.meta.total_count, 3)
        self.assertTrue(pages.meta.has_more)

    def test_hierarchy_lookup_does_not_fall_back_to_unmatched_file(self):
        self.repo.hierarchy.loaded_files[0].file_path = "other.mdb"
        with self.assertRaises(McpReadError):
            self.service.list_projects("db-1")

    def test_current_page_uses_saved_bid_selected_page(self):
        page = self.service.get_current_page("db-1", "bid-1")
        self.assertIsNotNone(page)
        self.assertEqual(page.uid, "page-2")
        self.assertTrue(page.is_pdf)

    def test_list_takeoffs_filters_visible_and_limit(self):
        takeoffs = self.service.list_takeoffs("db-1", "bid-1", limit=1)
        self.assertEqual([t.uid for t in takeoffs], ["takeoff-1"])
        self.assertEqual(takeoffs.meta.total_count, 2)
        self.assertTrue(takeoffs.meta.has_more)
        self.assertEqual(takeoffs[0].area_name, "Level One Deck")
        all_takeoffs = self.service.list_takeoffs("db-1", "bid-1", visible_only=False)
        self.assertEqual(len(all_takeoffs), 3)
        self.assertIsNone(all_takeoffs[2].area_name)
        geometry_takeoffs = self.service.list_takeoffs(
            "db-1", "bid-1", include_geometry=True, limit=99999
        )
        self.assertEqual(geometry_takeoffs.meta.limit, 250)
        self.assertIsNotNone(geometry_takeoffs[0].position)

    def test_area_tools_report_metadata_and_usage(self):
        areas = self.service.list_areas("db-1", "bid-1")
        self.assertEqual([area.uid for area in areas], ["area-1", "area-2"])
        self.assertEqual(areas[0].name, "Level One Deck")
        self.assertEqual(areas[0].guid, "{AREA-1}")
        self.assertEqual(areas[0].child_uids, ["area-2"])
        self.assertEqual(areas[0].takeoff_count, 2)
        self.assertEqual(areas[0].visible_takeoff_count, 2)
        self.assertEqual(areas[0].page_count, 1)
        summary = self.service.get_area_summary("db-1", "bid-1", "area-1")
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.area.name, "Level One Deck")
        self.assertEqual([page.page_uid for page in summary.pages], ["page-1"])
        self.assertEqual([child.uid for child in summary.children], ["area-2"])

    def test_unassigned_area_summary_uses_clear_synthetic_metadata(self):
        summary = self.service.get_area_summary("db-1", "bid-1", "0")
        self.assertEqual(summary.area.uid, "0")
        self.assertEqual(summary.area.name, "Unassigned")
        self.assertEqual(summary.area.takeoff_count, 1)
        self.assertEqual([page.page_uid for page in summary.pages], ["page-2"])

    def test_quantity_summary_reuses_domain_quantity_logic(self):
        quantities = self.service.get_page_quantity_summary("db-1", "bid-1", "page-1")
        self.assertEqual(len(quantities), 1)
        self.assertEqual(quantities[0].condition_uid, "cond-1")
        self.assertEqual(quantities[0].quantity1, 2.0)
        self.assertEqual(quantities[0].uom1_label, "EA")

    def test_search_takeoffs_uses_narrow_text_fields(self):
        matches = self.service.search_takeoffs("db-1", "bid-1", "visible")
        self.assertEqual([m.uid for m in matches], ["takeoff-1", "takeoff-2"])
        by_area_name = self.service.search_takeoffs("db-1", "bid-1", "deck")
        self.assertEqual([m.uid for m in by_area_name], ["takeoff-1", "takeoff-2"])
        filtered = self.service.search_takeoffs(
            "db-1", "bid-1", "visible", condition_uid="cond-1", limit=1
        )
        self.assertEqual([m.uid for m in filtered], ["takeoff-1"])

    def test_search_conditions_is_bounded(self):
        matches = self.service.search_conditions("db-1", "bid-1", "count", limit=1)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].uid, "cond-1")

    def test_search_pages_layers_named_views_and_hotlinks(self):
        pages = self.service.search_pages("db-1", "bid-1", "S-102")
        self.assertEqual([page.uid for page in pages], ["page-2"])
        layers = self.service.list_layers("db-1", "bid-1")
        self.assertEqual([layer.name for layer in layers], ["Takeoff", "Hidden"])
        self.assertEqual(layers[0].condition_count, 2)
        self.assertEqual(layers[0].takeoff_count, 2)
        self.assertEqual(layers[0].annotation_count, 2)
        self.assertFalse(layers[1].visible)
        self.assertTrue(layers[1].is_locked)
        named_views = self.service.list_named_views("db-1", "bid-1")
        self.assertEqual(named_views[0].name, "Lobby Detail")
        self.assertEqual(named_views[0].page_name, "A101")
        self.assertEqual(named_views[0].width, 10.0)
        hotlinks = self.service.list_hotlinks("db-1", "bid-1", page_uid="page-2")
        self.assertEqual(hotlinks[0].target_named_view_uid, "view-1")
        self.assertEqual(hotlinks[0].target_page_uid, "page-1")
        self.assertEqual(hotlinks[0].target_page_name, "A101")

    def test_condition_summary_includes_pages_and_quantities(self):
        summary = self.service.get_condition_summary("db-1", "bid-1", "cond-1")
        self.assertEqual(summary.condition.uid, "cond-1")
        self.assertEqual(summary.takeoff_count, 2)
        self.assertEqual(summary.visible_takeoff_count, 2)
        self.assertEqual(summary.pages[0].page_uid, "page-1")
        self.assertEqual(summary.quantities[0].quantity1, 2.0)

    def test_selected_takeoffs_summary_uses_selected_ids(self):
        summary = self.service.get_selected_takeoffs_summary(
            "db-1", "bid-1", ["takeoff-2", "missing"]
        )
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.selected_takeoff_count, 1)
        self.assertEqual(summary.missing_takeoff_uids, ["missing"])
        self.assertEqual(summary.takeoffs[0].uid, "takeoff-2")
        self.assertEqual(summary.takeoffs[0].area_name, "Level One Deck")
        self.assertEqual(summary.pages[0].page_uid, "page-1")

    def test_selected_takeoffs_summary_handles_no_selection(self):
        summary = self.service.get_selected_takeoffs_summary("db-1", "bid-1", [])
        self.assertEqual(summary.status, "no_selection")

    def test_selected_pages_summary_preserves_multi_page_selection_order(self):
        summary = self.service.get_selected_pages_summary(
            "db-1",
            "bid-1",
            ["page-2", "page-1", "missing"],
            active_view="3d",
            active_page_uid="page-1",
        )
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.active_view, "3d")
        self.assertEqual(summary.active_page_uid, "page-1")
        self.assertEqual(summary.selected_page_uids, ["page-2", "page-1"])
        self.assertEqual(summary.missing_page_uids, ["missing"])
        self.assertEqual([page.uid for page in summary.pages], ["page-2", "page-1"])

    def test_consistency_checks_find_unused_pages_and_conditions(self):
        pages = self.service.find_pages_without_takeoffs("db-1", "bid-1")
        self.assertEqual([page.uid for page in pages], ["page-3"])
        conditions = self.service.find_conditions_without_takeoffs("db-1", "bid-1")
        self.assertEqual([condition.uid for condition in conditions], ["cond-3"])

    def test_bid_quantity_summary_has_stable_shape_and_limit_metadata(self):
        summary = self.service.get_bid_quantity_summary("db-1", "bid-1", limit=2)
        self.assertEqual(summary.status, "truncated")
        self.assertEqual(summary.meta.limit, 2)
        self.assertEqual(summary.meta.returned_count, 2)
        self.assertEqual(summary.meta.total_count, 3)
        first = summary.conditions[0]
        self.assertEqual(first.condition.uid, "cond-1")
        self.assertEqual(first.page_count, 1)
        self.assertFalse(first.zero_quantity)

    def test_structured_summary_uses_default_type_area_grouping(self):
        summary = self.service.get_summary("db-1", "bid-1")
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.bid_name, "Bid One")
        self.assertEqual(summary.project_uid, "project-1")
        self.assertEqual(summary.project_name, "Project One")
        self.assertFalse(summary.grouping.group_by_page)
        self.assertTrue(summary.grouping.group_by_type)
        self.assertTrue(summary.grouping.group_by_area)
        self.assertEqual(summary.root_label, "Conditions - Bid One")
        self.assertEqual(
            [node.label for node in summary.nodes],
            ["Foundation", "Type B"],
        )
        folder = summary.nodes[0]
        self.assertEqual(folder.kind, SUMMARY_NODE_FOLDER)
        self.assertEqual(folder.folder_path, ["Foundation"])
        self.assertEqual(folder.children[0].kind, SUMMARY_NODE_GROUP)
        self.assertEqual(folder.children[0].group_level, SUMMARY_GROUP_TYPE)
        self.assertEqual(folder.children[0].children[0].group_level, SUMMARY_GROUP_AREA)
        condition = folder.children[0].children[0].children[0]
        self.assertEqual(condition.kind, SUMMARY_NODE_CONDITION)
        self.assertEqual(condition.condition_uid, "cond-1")
        self.assertEqual(condition.type_name, "Type A")
        self.assertEqual(condition.area, "Level One Deck")
        self.assertEqual(condition.values.name, "Visible Count")
        self.assertEqual(condition.values.height, "1' 0\"")
        self.assertEqual(condition.values.height_inches, 12.0)
        self.assertEqual(condition.values.quantity1, 2.0)
        self.assertEqual(condition.values.uom1_label, "EA")
        self.assertEqual(condition.values.notes, "Visible notes")
        self.assertTrue(condition.copyable)
        self.assertTrue(condition.deletable)

    def test_structured_summary_supports_all_grouping_combinations(self):
        cases = [
            ((False, False, False), set()),
            ((False, False, True), {SUMMARY_GROUP_AREA}),
            ((False, True, False), {SUMMARY_GROUP_TYPE}),
            ((True, False, False), {SUMMARY_GROUP_PAGE}),
            ((False, True, True), {SUMMARY_GROUP_TYPE, SUMMARY_GROUP_AREA}),
            ((True, False, True), {SUMMARY_GROUP_PAGE, SUMMARY_GROUP_AREA}),
            ((True, True, False), {SUMMARY_GROUP_PAGE, SUMMARY_GROUP_TYPE}),
            (
                (True, True, True),
                {SUMMARY_GROUP_PAGE, SUMMARY_GROUP_TYPE, SUMMARY_GROUP_AREA},
            ),
        ]
        for flags, expected_levels in cases:
            with self.subTest(flags=flags):
                summary = self.service.get_summary(
                    "db-1",
                    "bid-1",
                    group_by_page=flags[0],
                    group_by_type=flags[1],
                    group_by_area=flags[2],
                )
                self.assertEqual(summary.status, "ok")
                self.assertEqual(
                    (
                        summary.grouping.group_by_page,
                        summary.grouping.group_by_type,
                        summary.grouping.group_by_area,
                    ),
                    flags,
                )
                group_levels = {
                    node.group_level
                    for node in self._summary_nodes(summary.nodes)
                    if node.kind == SUMMARY_NODE_GROUP
                }
                self.assertEqual(group_levels, expected_levels)

    def test_structured_summary_excludes_unused_conditions(self):
        summary = self.service.get_summary("db-1", "bid-1", group_by_type=False)
        condition_uids = [
            node.condition_uid
            for node in self._summary_nodes(summary.nodes)
            if node.condition_uid
        ]
        self.assertIn("cond-1", condition_uids)
        self.assertIn("cond-2", condition_uids)
        self.assertNotIn("cond-3", condition_uids)

    def test_structured_summary_preserves_multi_area_total_and_details(self):
        self.repo.bid_data.bid_takeoffs.append(
            Takeoff(
                uid="takeoff-3",
                condition_uid="cond-1",
                page_uid="page-1",
                area_uid="area-2",
            )
        )
        summary = self.service.get_summary(
            "db-1",
            "bid-1",
            group_by_page=False,
            group_by_type=False,
            group_by_area=False,
        )
        nodes = self._summary_nodes(summary.nodes)
        total = next(
            node for node in nodes if node.kind == SUMMARY_NODE_MULTI_AREA_TOTAL
        )
        self.assertEqual(total.condition_uid, "cond-1")
        self.assertEqual(total.area, SUMMARY_MULTI_AREA_TOTAL_LABEL)
        self.assertEqual(total.values.quantity1, 3.0)
        self.assertEqual(
            [child.kind for child in total.children],
            [SUMMARY_NODE_AREA_DETAIL, SUMMARY_NODE_AREA_DETAIL],
        )
        self.assertEqual(
            [child.area for child in total.children],
            ["Level One Deck", "Nested Area"],
        )

    def test_structured_summary_reports_empty_and_truncated_results(self):
        self.repo.bid_data.bid_takeoffs.clear()
        empty = self.service.get_summary("db-1", "bid-1")
        self.assertEqual(empty.status, "empty")
        self.assertEqual(empty.total_node_count, 0)
        self.assertEqual(empty.meta.returned_count, 0)
        self.assertEqual(empty.nodes, [])
        self.repo = FakeProjectRepository()
        self.service = McpReadService(
            self.repo,
            [
                McpDatabaseRef(
                    database_id="db-1",
                    file_path=self.repo.file_path,
                    display_name="Demo",
                )
            ],
            pdf_metadata_provider=FakePdfMetadataProvider(),
        )
        limited = self.service.get_summary("db-1", "bid-1", limit=2)
        self.assertEqual(limited.status, "truncated")
        self.assertEqual(limited.meta.limit, 2)
        self.assertEqual(limited.meta.returned_count, 2)
        self.assertGreater(limited.meta.total_count, 2)
        self.assertTrue(limited.meta.has_more)

    def test_summary_limits_are_clamped_and_report_exact_counts(self):
        summary = self.service.get_bid_quantity_summary("db-1", "bid-1", limit=0)
        self.assertEqual(summary.status, "truncated")
        self.assertEqual(summary.meta.limit, 1)
        self.assertEqual(summary.meta.returned_count, 1)
        self.assertEqual(summary.meta.total_count, 3)
        self.assertTrue(summary.meta.truncated)
        empty = self.service.find_duplicate_conditions("db-1", "bid-1", limit=99999)
        self.assertEqual(empty.status, "empty")
        self.assertEqual(empty.meta.limit, 5000)
        self.assertEqual(empty.meta.returned_count, 0)
        self.assertEqual(empty.meta.total_count, 0)
        self.assertFalse(empty.meta.truncated)

    def test_scope_duplicate_zero_unplaced_and_page_context_checks(self):
        duplicate = Condition(uid="cond-4", name="Visible Count", ref_no=4)
        self.repo.bid_data.bid_conditions[duplicate.uid] = duplicate
        unplaced = Takeoff(uid="unplaced-1", condition_uid="cond-1", page_uid="")
        self.repo.bid_data.bid_takeoffs.append(unplaced)
        gaps = self.service.review_scope_gaps("db-1", "bid-1")
        self.assertEqual(gaps.status, "ok")
        self.assertEqual(gaps.meta.total_count, 4)
        self.assertEqual(gaps.meta.returned_count, 4)
        self.assertEqual([page.uid for page in gaps.pages_without_takeoffs], ["page-3"])
        self.assertEqual([t.uid for t in gaps.takeoffs_missing_pages], ["unplaced-1"])
        duplicates = self.service.find_duplicate_conditions("db-1", "bid-1")
        self.assertEqual(duplicates.status, "ok")
        self.assertEqual(duplicates.groups[0].name, "Visible Count")
        self.assertEqual(
            [condition.uid for condition in duplicates.groups[0].conditions],
            ["cond-1", "cond-4"],
        )
        zero = self.service.find_zero_quantity_conditions("db-1", "bid-1")
        self.assertEqual([item.condition.uid for item in zero.conditions], ["cond-2"])
        unplaced_summary = self.service.find_unplaced_takeoffs("db-1", "bid-1")
        self.assertEqual(
            [takeoff.uid for takeoff in unplaced_summary.takeoffs],
            ["unplaced-1"],
        )
        page_context = self.service.get_page_context("db-1", "bid-1", "page-1")
        self.assertEqual(page_context.status, "ok")
        self.assertEqual(page_context.page_label, "A101")
        self.assertEqual(page_context.source_file_name, "A101.pdf")
        self.assertTrue(page_context.has_pdf_source)
        self.assertEqual(page_context.page_text_status, "deferred")

    def test_rejects_unknown_database_and_filter_ids(self):
        with self.assertRaises(McpReadError):
            self.service.list_projects("missing")
        with self.assertRaises(McpReadError):
            self.service.list_takeoffs("db-1", "bid-1", page_uid="missing")
        with self.assertRaises(McpReadError):
            self.service.list_takeoffs("db-1", "bid-1", condition_uid="missing")

    def _summary_nodes(self, nodes):
        result = []
        for node in nodes:
            result.append(node)
            result.extend(self._summary_nodes(node.children))
        return result


if __name__ == "__main__":
    unittest.main()
