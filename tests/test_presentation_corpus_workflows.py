import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from test_presentation_chaos_harness import (
    DeferredPersistenceChaosHarness,
    DetachedWindowChaosHarness,
    PlanViewActionHandlerChaosHarness,
    PresentationChaosHarness,
    UIEventCoordinatorChaosHarness,
    _app,
    action_handler_module,
)
from ost_visualizer.application.dtos.export_dto import (
    ExportProgressCallback,
    ExportResultDto,
)
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
)
from ost_visualizer.infrastructure.mdb.importers import (
    osp_importer as osp_importer_module,
)
from ost_visualizer.infrastructure.pdf_metadata_provider import (
    NativePdfMetadataProvider,
)
from ost_visualizer.presentation.visualization.exporters import (
    osp_exporter as osp_exporter_module,
)
from ost_visualizer.presentation.visualization.exporters.osp_exporter import OspExporter

CORPUS_ENV_VAR = "OSTV_PRESENTATION_CORPUS_DIR"
DEFAULT_CORPUS_DIR = Path("tests") / "presentation_corpus"
CORPUS_SUFFIXES = {".ost", ".osp", ".pdf", ".mdb"}


def _pump_events(rounds: int = 3) -> None:
    app = _app()
    for _ in range(rounds):
        app.processEvents()


def _corpus_root() -> Path:
    configured = os.environ.get(CORPUS_ENV_VAR)
    return Path(configured) if configured else DEFAULT_CORPUS_DIR


def _relative_corpus_name(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _is_safe_cab_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        return False
    return all(part not in ("", ".", "..") for part in normalized.split("/"))


class PresentationCorpusConventionTests(unittest.TestCase):
    def test_optional_local_corpus_files_have_basic_integrity(self):
        root = _corpus_root()
        if not root.exists():
            self.skipTest(
                f"No presentation corpus directory found. Set {CORPUS_ENV_VAR} "
                f"or create {DEFAULT_CORPUS_DIR.as_posix()} for local corpus runs."
            )
        files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in CORPUS_SUFFIXES
        )
        if not files:
            self.skipTest(f"No supported corpus files found under {root}")
        checked_files = []
        for path in files:
            rel_name = _relative_corpus_name(path, root)
            with self.subTest(corpus_file=rel_name):
                checked_files.append(rel_name)
                suffix = path.suffix.lower()
                if suffix == ".ost":
                    parsed = ET.parse(path)
                    self.assertIsNotNone(parsed.getroot())
                elif suffix == ".osp":
                    names = list(osp_importer_module.ost_cab.list_cab(str(path)))
                    self.assertTrue(names, f"{rel_name} has no CAB members")
                    self.assertTrue(
                        any(name.lower().endswith(".ost") for name in names),
                        f"{rel_name} has no .ost member",
                    )
                    unsafe = [name for name in names if not _is_safe_cab_member(name)]
                    self.assertEqual(unsafe, [])
                elif suffix == ".pdf":
                    info = NativePdfMetadataProvider().get_page_info(str(path), 0)
                    self.assertEqual(info.status, "ok", rel_name)
                    self.assertGreater(info.page_count, 0, rel_name)
                elif suffix == ".mdb":
                    self.assertGreater(path.stat().st_size, 0, rel_name)
        self.assertEqual(len(checked_files), len(files), checked_files)


class PresentationImportExportWorkflowTests(unittest.TestCase):
    def test_osp_export_keeps_named_view_hotlink_tables_and_distinct_same_filename_images(
        self,
    ):
        class CapturingOstExporter:
            captured_raw_data = None

            def __init__(self, _uom_service):
                pass

            def export(
                self,
                raw_data,
                output_path,
                on_progress: Optional[ExportProgressCallback] = None,
            ):
                CapturingOstExporter.captured_raw_data = raw_data
                Path(output_path).write_text("<XML_ROOT />", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first_dir = tmp_path / "first"
            second_dir = tmp_path / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "sheet.pdf"
            second = second_dir / "sheet.pdf"
            first.write_bytes(b"%PDF-1.4 first")
            second.write_bytes(b"%PDF-1.4 second")
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Corpus Workflow"},
                bid_tables={
                    "BidPages": [
                        {"UID": "10", "BidUID": "1", "ImagePath": str(first)},
                        {"UID": "11", "BidUID": "1", "ImagePath": str(second)},
                    ],
                    "BidNamedViews": [
                        {
                            "UID": "201",
                            "BidUID": "1",
                            "BidPageUID": "10",
                            "Name": "View A",
                        }
                    ],
                    "BidHotLinks": [
                        {"UID": "301", "BidUID": "1", "BidPageViewUID": "201"}
                    ],
                },
            )
            cab_calls = []
            original_create_cab = osp_exporter_module.ost_cab.create_cab_with_names
            try:
                osp_exporter_module.ost_cab.create_cab_with_names = (
                    lambda source_files, archive_names, output_file: cab_calls.append(
                        (list(source_files), list(archive_names), output_file)
                    )
                    or True
                )
                exporter = OspExporter(
                    SimpleNamespace(),
                    "1.0",
                    lambda uom_service: CapturingOstExporter(uom_service),
                )
                result = exporter.export(raw_data, str(tmp_path / "out.osp"), "Bid")
            finally:
                osp_exporter_module.ost_cab.create_cab_with_names = original_create_cab
        self.assertTrue(result.success)
        captured = CapturingOstExporter.captured_raw_data
        self.assertIsNotNone(captured)
        page_paths = [row["ImagePath"] for row in captured.bid_tables["BidPages"]]
        self.assertEqual(len(set(page_paths)), 2)
        self.assertTrue(all(path.endswith("\\sheet.pdf") for path in page_paths))
        self.assertEqual(
            captured.bid_tables["BidNamedViews"],
            [{"UID": "201", "BidUID": "1", "BidPageUID": "10", "Name": "View A"}],
        )
        self.assertEqual(
            captured.bid_tables["BidHotLinks"],
            [{"UID": "301", "BidUID": "1", "BidPageViewUID": "201"}],
        )
        self.assertEqual(len(cab_calls), 1)
        image_archive_names = [
            name for name in cab_calls[0][1] if name.startswith("TempImages!.tmp\\")
        ]
        self.assertEqual(len(image_archive_names), 2)
        self.assertEqual(len(set(image_archive_names)), 2)


class PresentationScriptedWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_long_copy_paste_named_view_delete_and_write_failure_workflow(self):
        harness = PlanViewActionHandlerChaosHarness(11201, self)
        harness.run_sequence(
            ["select_all_current", "copy_selection", "switch_page", "paste_clipboard"]
        )
        _pump_events()
        pasted_takeoffs = [
            takeoff
            for uid, takeoff in harness.data.takeoffs.items()
            if uid not in {"t1", "t2", "t3"}
        ]
        self.assertTrue(pasted_takeoffs)
        self.assertEqual({takeoff.page_uid for takeoff in pasted_takeoffs}, {"p2"})
        harness._assert_invariants()
        harness._sync_plan_view_to_page("p1")
        harness.plan_view.set_selected_uids({"p1-named"})
        with mock.patch.object(action_handler_module, "confirm", return_value=False):
            harness.handler.on_elements_deleted(["p1-named"])
        _pump_events()
        remaining = {(a.uid, a.annotation_type) for a in harness.data.annotations}
        self.assertIn(("p1-named", ANNOTATION_TYPE_NAMED_VIEW), remaining)
        self.assertIn(("p1-hotlink", ANNOTATION_TYPE_HOTLINK), remaining)
        harness._assert_invariants()
        with mock.patch.object(action_handler_module, "confirm", return_value=True):
            harness.handler.on_elements_deleted(["p1-named"])
        _pump_events()
        harness._sync_plan_view_to_page("p1")
        harness._assert_invariants()
        remaining = {(a.uid, a.annotation_type) for a in harness.data.annotations}
        self.assertNotIn(("p1-named", ANNOTATION_TYPE_NAMED_VIEW), remaining)
        self.assertNotIn(("p1-hotlink", ANNOTATION_TYPE_HOTLINK), remaining)
        original_delete = harness.write.delete_takeoffs
        harness.write.delete_takeoffs = lambda *args, **kwargs: False
        try:
            harness.plan_view.set_selected_uids({"t1"})
            harness.handler.on_elements_deleted(["t1"])
        finally:
            harness.write.delete_takeoffs = original_delete
        _pump_events()
        self.assertIn("t1", harness.data.takeoffs)
        self.assertEqual(harness.plan_view.selected, {"t1"})
        harness._assert_invariants()

    def test_plan_view_render_failure_then_page_switch_clears_preview_and_stale_state(
        self,
    ):
        harness = PresentationChaosHarness(11202, self)
        try:
            harness.run_sequence(
                ["enter_annotation_placement", "mouse_move_during_placement"]
            )
            harness.state.active_page_uid = "p2"
            page = harness.state.active_page
            self.assertTrue(
                harness.view.load_page(
                    page,
                    harness.state.active_takeoffs(),
                    harness.state.conditions,
                    {},
                    bid_ref=harness.state.bid_ref,
                    annotations=harness.state.active_annotations(),
                    hidden_layer_uids=harness.state.hidden_layer_uids,
                )
            )
            request_id, request = harness.rendering_service.page_requests.pop()
            request["callback"](RenderResult(request_id, False, None, "missing"))
            _pump_events()
            harness.run_sequence(
                ["switch_page", "cancel_placement", "refresh_overlays"]
            )
            self.assertIsNone(harness.view.annotation_place_type)
            self.assertEqual(harness.view._place_preview_items, [])
        finally:
            harness.cleanup()

    def test_coordinator_deferred_and_detached_event_order_after_deletes(self):
        coordinator = UIEventCoordinatorChaosHarness(11203, self)
        coordinator.run_sequence(
            [
                "switch_to_2d_view",
                "takeoffs_changed_active_page",
                "switch_to_3d_view",
                "native_scene_updated",
                "clear_selected_pages",
                "takeoffs_changed_active_page",
            ]
        )
        _pump_events()
        self.assertFalse(coordinator.coordinator._mesh_scene_dirty)
        coordinator._assert_invariants()
        deferred = DeferredPersistenceChaosHarness(11204, self)
        try:
            deferred.run_sequence(
                [
                    "schedule_bid_selected_page",
                    "cancel_deleting_bid_selected_page",
                    "fail_next_write",
                    "schedule_layer_visibility",
                    "flush",
                    "toggle_expected_block",
                    "flush_for_file",
                ]
            )
            deferred._assert_invariants()
        finally:
            deferred.cleanup()
        detached = DetachedWindowChaosHarness(11205, self)
        detached.run_sequence(
            [
                "database_refresh_matching_file",
                "delete_active_page",
                "refresh_window",
                "annotations_changed_current_page",
                "close_window",
                "delete_active_page",
                "reopen_window",
                "refresh_window",
            ]
        )
        _pump_events()
        detached._assert_invariants()


if __name__ == "__main__":
    unittest.main()
