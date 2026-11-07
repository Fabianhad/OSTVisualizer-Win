from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyFolderInfo,
    HierarchyPageInfo,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.cover_sheet import CoverSheetData, JobStatus
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.folder import Folder
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.condition import Condition
from types import SimpleNamespace
import unittest
from ost_visualizer.domain.services.uom_service import (
    CALC_LINEAR_BOTH_SIDES,
    CALC_LINEAR_LENGTH,
    CALC_VOLUME,
    UOM_CUBIC_FEET,
    UOM_LINEAR_FEET,
    UOM_M,
    UOM_M2,
    UOM_M3,
    UOM_SQUARE_FEET,
    normalize_condition_uoms_for_system,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_TEXT,
)
from ost_visualizer.domain.entities.area import BidArea, UNASSIGNED_AREA_UID


class _AreaUsageModel:
    def __init__(self, takeoffs, conditions, page_takeoffs=None):
        self._takeoffs = list(takeoffs)
        self.bid_conditions = dict(conditions)
        page_takeoff_list = self._takeoffs if page_takeoffs is None else page_takeoffs
        self._pages = {
            "page-1": Page("page-1", "Page", takeoffs=list(page_takeoff_list))
        }

    def get_all_takeoffs(self):
        return list(self._takeoffs)

    def get_page(self, page_uid):
        return self._pages.get(page_uid)


def _condition(uid, condition_type=Condition.TYPE_AREA, layer_visible=True):
    return Condition(
        uid=uid,
        condition_type=condition_type,
        layer_visible=layer_visible,
    )


def _takeoff(
    uid,
    condition_uid="condition-area",
    area_uid="0",
    position=None,
    parent_uid="0",
):
    return Takeoff(
        uid=uid,
        condition_uid=condition_uid,
        page_uid="page-1",
        area_uid=area_uid,
        position=list(position or []),
        parent_uid=parent_uid,
    )


class FakeProjectModel:
    def __init__(self):
        self.bid_conditions = {
            "c1": Condition(uid="c1", layer_uid="l1", layer_visible=True),
            "c2": Condition(uid="c2", layer_uid="l2", layer_visible=True),
        }
        self.pages = [
            Page(uid="p1", name="First", layer_visible=True),
            Page(uid="p2", name="Second", layer_visible=True),
        ]
        self.bid_layer_visibility = {}
        self.bid_layer_names_by_uid = {}
        self.bid_layer_visibility_by_name = {}
        self.bid_layers = []
        self.annotations = []
        self.bid_takeoffs = []
        self.bid_takeoff_extras = {}
        self.page_area_selections = {}
        self.current_bid_ref = BidRef("test.mdb", "bid-1")

    def get_bid_conditions(self):
        return dict(self.bid_conditions)

    def get_all_pages(self):
        return list(self.pages)

    def get_all_annotations(self):
        return list(self.annotations)

    def add_annotations(self, annotations):
        self.annotations.extend(annotations)

    def set_annotations(self, annotations):
        self.annotations = list(annotations)

    def set_pages(self, pages):
        self.pages = list(pages.values())


class RecordingProjectDataService(ProjectDataService):
    def __init__(self, model):
        super().__init__(model)
        self.annotation_visibility_syncs = 0

    def _synchronize_annotation_visibility(self, layer_uids=None):
        self.annotation_visibility_syncs += 1
        super()._synchronize_annotation_visibility(layer_uids)


class ProjectDataServiceAreaUsageTests(unittest.TestCase):
    def test_direct_condition_update_rejects_incompatible_selection_atomically(self):
        conditions = {
            "linear": _condition("linear", Condition.TYPE_LINEAR),
            "area": _condition("area", Condition.TYPE_AREA),
        }
        linear = _takeoff(
            "linear-takeoff",
            condition_uid="linear",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        area = _takeoff(
            "area-takeoff",
            condition_uid="area",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
        )
        service = ProjectDataService(_AreaUsageModel([linear, area], conditions))
        page_uids = service.update_takeoffs_condition(
            ["linear-takeoff", "area-takeoff"], "linear"
        )
        self.assertEqual(page_uids, [])
        self.assertEqual(linear.condition_uid, "linear")
        self.assertEqual(area.condition_uid, "area")
        self.assertEqual(
            service.update_takeoffs_condition(["linear-takeoff", "missing"], "linear"),
            [],
        )
        self.assertEqual(linear.condition_uid, "linear")

    def test_direct_condition_update_allows_compatible_selection(self):
        conditions = {
            "linear-a": _condition("linear-a", Condition.TYPE_LINEAR),
            "linear-b": _condition("linear-b", Condition.TYPE_LINEAR),
        }
        takeoff = _takeoff("takeoff", condition_uid="linear-a")
        service = ProjectDataService(_AreaUsageModel([takeoff], conditions))
        page_uids = service.update_takeoffs_condition(["takeoff"], "linear-b")
        self.assertEqual(page_uids, ["page-1"])
        self.assertEqual(takeoff.condition_uid, "linear-b")

    def test_visible_renderable_unassigned_takeoff_bolds_unassigned_area(self):
        conditions = {
            "condition-count": _condition("condition-count", Condition.TYPE_COUNT)
        }
        takeoffs = [
            _takeoff(
                "takeoff-1",
                condition_uid="condition-count",
                area_uid="0",
                position=[10.0, 20.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), {"0"})

    def test_unrenderable_unassigned_takeoff_does_not_bold_unassigned_area(self):
        conditions = {
            "condition-area": _condition("condition-area", Condition.TYPE_AREA)
        }
        takeoffs = [
            _takeoff(
                "stale-takeoff",
                condition_uid="condition-area",
                area_uid="0",
                position=[10.0, 20.0, 30.0, 40.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), set())

    def test_hidden_condition_takeoff_does_not_bold_unassigned_area(self):
        conditions = {
            "condition-area": _condition(
                "condition-area",
                Condition.TYPE_AREA,
                layer_visible=False,
            )
        }
        takeoffs = [
            _takeoff(
                "hidden-takeoff",
                condition_uid="condition-area",
                area_uid="0",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), set())

    def test_takeoff_with_missing_condition_does_not_bold_unassigned_area(self):
        takeoffs = [
            _takeoff(
                "orphaned-condition-takeoff",
                condition_uid="missing-condition",
                area_uid="0",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, {}))
        self.assertEqual(service.get_area_uids_with_takeoff(), set())

    def test_hole_row_does_not_independently_bold_unassigned_area(self):
        conditions = {
            "condition-area": _condition("condition-area", Condition.TYPE_AREA)
        }
        takeoffs = [
            _takeoff(
                "parent-area",
                condition_uid="condition-area",
                area_uid="area-1",
                position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0],
            ),
            _takeoff(
                "hole-row",
                condition_uid="condition-area",
                area_uid="0",
                position=[5.0, 5.0, 10.0, 5.0, 10.0, 10.0],
                parent_uid="parent-area",
            ),
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), {"area-1"})

    def test_stored_area_usage_keeps_delete_protection_separate_from_combo_bold(self):
        conditions = {
            "condition-area": _condition(
                "condition-area",
                Condition.TYPE_AREA,
                layer_visible=False,
            )
        }
        takeoffs = [
            _takeoff(
                "hidden-assigned-takeoff",
                condition_uid="condition-area",
                area_uid="area-1",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), set())
        self.assertEqual(
            service.get_assigned_area_uids_with_stored_takeoff(),
            {"area-1"},
        )

    def test_page_area_usage_uses_same_relevance_filter(self):
        conditions = {
            "condition-count": _condition("condition-count", Condition.TYPE_COUNT),
            "condition-area": _condition("condition-area", Condition.TYPE_AREA),
        }
        bid_takeoffs = [
            _takeoff(
                "valid-unassigned",
                condition_uid="condition-count",
                area_uid="0",
                position=[1.0, 2.0],
            ),
            _takeoff(
                "invalid-unassigned",
                condition_uid="condition-area",
                area_uid="0",
                position=[],
            ),
            _takeoff(
                "assigned-area",
                condition_uid="condition-area",
                area_uid="area-1",
                position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0],
            ),
        ]
        other_page_takeoff = Takeoff(
            uid="other-page-takeoff",
            condition_uid="condition-count",
            page_uid="page-2",
            area_uid="other-page-area",
            position=[1.0, 2.0],
        )
        service = ProjectDataService(
            _AreaUsageModel(
                [*bid_takeoffs, other_page_takeoff],
                conditions,
                page_takeoffs=bid_takeoffs,
            )
        )
        self.assertEqual(
            service.get_area_uids_with_takeoff_for_page("page-1"),
            {"0", "area-1"},
        )
        self.assertEqual(service.get_area_uids_with_takeoff_for_page("missing"), set())
        self.assertEqual(
            service.get_area_uids_with_takeoff(), {"0", "area-1", "other-page-area"}
        )


class ProjectDataServiceFamilyProjectionTests(unittest.TestCase):
    def test_remote_pages_replace_loaded_bid_navigation_structure(self):
        bid_ref = BidRef("sql-db", "bid-1")
        old_root = Page(uid="old-root", name="Old root", sequence=1)
        old_nested = Page(
            uid="old-nested", name="Old nested", sequence=2, folder_uid="folder-1"
        )
        replacement = Page(
            uid="new-nested", name="New nested", sequence=3, folder_uid="folder-1"
        )
        aggregate = OstAggregate(None)
        aggregate.current_bid_ref = bid_ref
        aggregate.current_bid = Bid(
            uid=bid_ref.bid_uid,
            name="Bid",
            page_count=2,
            folders={
                "folder-1": Folder(uid="folder-1", name="Folder", pages=[old_nested])
            },
            pages_without_folder=[old_root],
        )
        aggregate.set_pages({old_root.uid: old_root, old_nested.uid: old_nested})
        retained_bid = aggregate.current_bid
        service = ProjectDataService(aggregate)
        self.assertTrue(
            service.replace_remote_bid_families(
                bid_ref,
                BidLoadResult(pages={replacement.uid: replacement}),
                {"pages"},
            )
        )
        self.assertEqual(aggregate.current_bid.pages_without_folder, [])
        self.assertEqual(
            aggregate.current_bid.folders["folder-1"].pages,
            [replacement],
        )
        self.assertEqual(aggregate.current_bid.page_count, 1)
        self.assertIs(aggregate.current_bid, retained_bid)
        self.assertIs(aggregate.current_bid.folders["folder-1"].pages[0], replacement)
        self.assertIs(aggregate.get_page(replacement.uid), replacement)
        self.assertIsNone(aggregate.get_page(old_root.uid))
        self.assertIsNone(aggregate.get_page(old_nested.uid))

    def test_remote_family_updates_synchronize_annotation_visibility_once(self):
        cases = (
            ("annotations only", {"annotations"}, True, False),
            ("layers only", {"layers"}, False, False),
            ("annotations and layers", {"annotations", "layers"}, True, False),
            ("pages and annotations", {"pages", "annotations"}, True, True),
            ("empty families", set(), False, False),
        )
        for name, families, replace_annotation, replace_pages in cases:
            with self.subTest(name=name):
                model = FakeProjectModel()
                existing = BidAnnotation(
                    uid="ann-existing",
                    annotation_type="text",
                    page_uid="p1",
                    layer_uid="annotation",
                    visible=True,
                )
                incoming = BidAnnotation(
                    uid="ann-incoming",
                    annotation_type="text",
                    page_uid="p-new",
                    layer_uid="annotation",
                    visible=True,
                )
                model.annotations = [existing]
                service = RecordingProjectDataService(model)
                service.set_bid_layer_visibility(
                    [
                        BidLayer(
                            uid="annotation",
                            bid_uid="bid-1",
                            name="Annotation",
                            show=False,
                            sequence=1,
                        )
                    ]
                )
                service.annotation_visibility_syncs = 0
                result = BidLoadResult(
                    bid_annotations=[incoming],
                    bid_layers=[
                        BidLayer(
                            uid="annotation",
                            bid_uid="bid-1",
                            name="Annotation",
                            show=True,
                            sequence=1,
                        )
                    ],
                    pages={"p-new": Page(uid="p-new", name="New")},
                )
                self.assertTrue(
                    service.replace_remote_bid_families(
                        model.current_bid_ref, result, families
                    )
                )
                expected_annotations = [incoming] if replace_annotation else [existing]
                self.assertEqual(model.annotations, expected_annotations)
                self.assertTrue(
                    all(
                        annotation.visible is ("layers" in families)
                        for annotation in model.annotations
                    )
                )
                self.assertEqual(
                    [page.uid for page in model.pages],
                    ["p-new"] if replace_pages else ["p1", "p2"],
                )
                self.assertEqual(
                    service.annotation_visibility_syncs,
                    1 if families & {"annotations", "layers"} else 0,
                )

    def test_combined_remote_family_replacement_does_not_duplicate_annotations(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="rect",
            page_uid="p1",
            layer_uid="annotation",
        )
        result = BidLoadResult(
            bid_annotations=[annotation],
            bid_layers=[
                BidLayer(
                    uid="annotation",
                    bid_uid="bid-1",
                    name="Annotation",
                    show=True,
                    sequence=1,
                )
            ],
        )
        for _ in range(2):
            self.assertTrue(
                service.replace_remote_bid_families(
                    model.current_bid_ref,
                    result,
                    {"annotations", "layers"},
                )
            )
        self.assertEqual([item.uid for item in model.annotations], ["ann-1"])
        self.assertTrue(model.annotations[0].visible)

    def test_remote_page_load_applies_initial_hidden_annotation_layer_once(self):
        model = FakeProjectModel()
        service = RecordingProjectDataService(model)
        annotation = BidAnnotation(
            uid="ann-hidden",
            annotation_type="dimension",
            page_uid="p-new",
            layer_uid="annotation",
            visible=True,
        )
        result = BidLoadResult(
            bid_annotations=[annotation],
            bid_layers=[
                BidLayer(
                    uid="annotation",
                    bid_uid="bid-1",
                    name="Annotation",
                    show=False,
                    sequence=1,
                )
            ],
            pages={"p-new": Page(uid="p-new", name="New")},
        )
        self.assertTrue(
            service.replace_remote_bid_families(
                model.current_bid_ref,
                result,
                {"annotations", "layers", "pages"},
            )
        )
        self.assertEqual([item.uid for item in model.annotations], ["ann-hidden"])
        self.assertFalse(model.annotations[0].visible)
        self.assertEqual([page.uid for page in model.pages], ["p-new"])
        self.assertEqual(service.annotation_visibility_syncs, 1)

    def test_loaded_layer_visibility_tracks_hidden_layer_uids(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                BidLayer(
                    uid="l1", bid_uid="bid-1", name="Annotation", show=False, sequence=1
                ),
                BidLayer(
                    uid="l2", bid_uid="bid-1", name="Takeoff", show=True, sequence=1
                ),
            ]
        )
        self.assertEqual(service.get_hidden_layer_uids(), {"l1"})

    def test_annotation_layer_visibility_tracks_loaded_and_toggled_state(self):
        model = FakeProjectModel()
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="text",
            layer_uid="annotation",
            visible=False,
        )
        model.annotations = [annotation]
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                BidLayer(
                    uid="annotation",
                    bid_uid="bid-1",
                    name="Annotation",
                    show=True,
                    sequence=1,
                ),
                BidLayer(
                    uid="takeoff",
                    bid_uid="bid-1",
                    name="Takeoff",
                    show=True,
                    sequence=1,
                ),
            ]
        )
        self.assertTrue(service.is_annotation_layer_visible())
        self.assertTrue(annotation.visible)
        service.update_layer_visibility("annotation", False)
        self.assertFalse(service.is_annotation_layer_visible())
        self.assertFalse(annotation.visible)
        service.update_all_layer_visibility(True)
        self.assertTrue(service.is_annotation_layer_visible())
        self.assertTrue(annotation.visible)

    def test_unrelated_layer_toggle_does_not_change_annotation_visibility(self):
        model = FakeProjectModel()
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="rect",
            layer_uid="annotation",
            visible=False,
        )
        model.annotations = [annotation]
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                BidLayer(
                    uid="annotation",
                    bid_uid="bid-1",
                    name="Annotation",
                    show=False,
                    sequence=1,
                ),
                BidLayer(
                    uid="takeoff",
                    bid_uid="bid-1",
                    name="Takeoff",
                    show=True,
                    sequence=1,
                ),
            ]
        )
        service.update_layer_visibility("takeoff", False)
        self.assertFalse(annotation.visible)

    def test_annotation_added_while_layer_hidden_is_revealed_by_same_state_path(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                BidLayer(
                    uid="annotation",
                    bid_uid="bid-1",
                    name="Annotation",
                    show=False,
                    sequence=1,
                )
            ]
        )
        annotations = [
            BidAnnotation(
                uid=f"ann-{annotation_type}",
                annotation_type=annotation_type,
                layer_uid="annotation",
                visible=True,
            )
            for annotation_type in ("text", "dimension", "arrow", "hotlink")
        ]
        service.add_annotations(annotations)
        self.assertEqual(model.annotations, annotations)
        self.assertTrue(all(not annotation.visible for annotation in annotations))
        service.update_layer_visibility("annotation", True)
        self.assertTrue(all(annotation.visible for annotation in annotations))

    def test_annotation_layer_visibility_prefers_layer_uid_state(self):
        model = FakeProjectModel()
        model.bid_layer_visibility = {"l1": False}
        model.bid_layer_names_by_uid = {"l1": "Annotation"}
        model.bid_layer_visibility_by_name = {"annotation": True}
        service = ProjectDataService(model)
        self.assertEqual(service.get_annotation_layer_uid(), "l1")
        self.assertFalse(service.is_annotation_layer_visible())

    def test_layer_visibility_updates_condition_memory_immediately(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        changed_pages = service.update_layer_visibility("l1", False)
        self.assertEqual(changed_pages, [])
        self.assertFalse(model.bid_conditions["c1"].layer_visible)
        self.assertTrue(model.bid_conditions["c2"].layer_visible)
        self.assertTrue(model.pages[0].layer_visible)
        self.assertEqual(service.get_hidden_layer_uids(), {"l1"})

    def test_image_layer_visibility_updates_page_memory_immediately(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                BidLayer(
                    uid="image", bid_uid="bid-1", name="Image", show=True, sequence=1
                ),
                BidLayer(
                    uid="l1", bid_uid="bid-1", name="Takeoff", show=True, sequence=1
                ),
            ]
        )
        changed_pages = service.update_layer_visibility("image", False)
        self.assertEqual(changed_pages, ["p1", "p2"])
        self.assertFalse(model.pages[0].layer_visible)
        self.assertFalse(model.pages[1].layer_visible)
        self.assertEqual(service.get_hidden_layer_uids(), {"image"})

    def test_layer_visibility_state_sources_remain_synchronized_by_layer_kind(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                BidLayer(
                    uid="image", bid_uid="bid-1", name="Image", show=True, sequence=1
                ),
                BidLayer(
                    uid="annotation",
                    bid_uid="bid-1",
                    name="Annotation",
                    show=True,
                    sequence=1,
                ),
                BidLayer(
                    uid="l1", bid_uid="bid-1", name="Takeoff", show=True, sequence=1
                ),
                BidLayer(
                    uid="custom",
                    bid_uid="bid-1",
                    name="Future Visual",
                    show=True,
                    sequence=1,
                ),
            ]
        )
        with self.subTest(layer="annotation"):
            changed_pages = service.update_layer_visibility("annotation", False)
            self.assertEqual(changed_pages, [])
            self.assertFalse(model.bid_layer_visibility["annotation"])
            self.assertFalse(model.bid_layer_visibility_by_name["annotation"])
            self.assertTrue(model.bid_conditions["c1"].layer_visible)
            self.assertTrue(model.pages[0].layer_visible)
        with self.subTest(layer="condition"):
            changed_pages = service.update_layer_visibility("l1", False)
            self.assertEqual(changed_pages, [])
            self.assertFalse(model.bid_layer_visibility["l1"])
            self.assertFalse(model.bid_layer_visibility_by_name["takeoff"])
            self.assertFalse(model.bid_conditions["c1"].layer_visible)
            self.assertTrue(model.bid_conditions["c2"].layer_visible)
            self.assertTrue(model.pages[0].layer_visible)
        with self.subTest(layer="custom"):
            changed_pages = service.update_layer_visibility("custom", False)
            self.assertEqual(changed_pages, [])
            self.assertFalse(model.bid_layer_visibility["custom"])
            self.assertFalse(model.bid_layer_visibility_by_name["future visual"])
            self.assertTrue(model.pages[0].layer_visible)
        with self.subTest(layer="image"):
            changed_pages = service.update_layer_visibility("image", False)
            self.assertEqual(changed_pages, ["p1", "p2"])
            self.assertFalse(model.bid_layer_visibility["image"])
            self.assertFalse(model.bid_layer_visibility_by_name["image"])
            self.assertFalse(model.pages[0].layer_visible)
            self.assertFalse(model.pages[1].layer_visible)

    def test_non_image_layer_visibility_does_not_update_page_memory_by_name_guess(
        self,
    ):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                BidLayer(
                    uid="l1",
                    bid_uid="bid-1",
                    name="Future Visual",
                    show=True,
                    sequence=1,
                ),
                BidLayer(
                    uid="image", bid_uid="bid-1", name="Image", show=True, sequence=1
                ),
            ]
        )
        changed_pages = service.update_layer_visibility("l1", False)
        self.assertEqual(changed_pages, [])
        self.assertTrue(model.pages[0].layer_visible)
        self.assertTrue(model.pages[1].layer_visible)
        self.assertFalse(model.bid_conditions["c1"].layer_visible)

    def test_show_all_layer_visibility_updates_conditions_and_pages_immediately(self):
        model = FakeProjectModel()
        model.bid_conditions["c1"].layer_visible = False
        model.pages[0].layer_visible = False
        model.bid_layer_visibility = {"l1": False, "l2": True}
        model.bid_layer_names_by_uid = {"l1": "annotation", "l2": "takeoff"}
        model.bid_layer_visibility_by_name = {"annotation": False, "takeoff": True}
        service = ProjectDataService(model)
        changed_pages = service.update_all_layer_visibility(True)
        self.assertEqual(changed_pages, ["p1", "p2"])
        self.assertTrue(model.bid_conditions["c1"].layer_visible)
        self.assertTrue(model.bid_conditions["c2"].layer_visible)
        self.assertTrue(model.pages[0].layer_visible)
        self.assertTrue(model.pages[1].layer_visible)
        self.assertEqual(service.get_hidden_layer_uids(), set())

    def test_remove_takeoffs_clears_page_bid_and_supplemental_state(self):
        model = FakeProjectModel()
        removed = Takeoff(uid="t1", condition_uid="c1", page_uid="p1")
        retained = Takeoff(uid="t2", condition_uid="c2", page_uid="p2")
        model.pages[0].takeoffs = [removed]
        model.pages[1].takeoffs = [retained]
        model.bid_takeoffs = [removed, retained]
        model.bid_takeoff_extras = {
            "t1": {"condition_name": "Removed"},
            "t2": {"condition_name": "Retained"},
        }
        model.get_all_takeoffs = lambda: [
            takeoff for page in model.pages for takeoff in page.takeoffs
        ]
        model.get_page = lambda uid: next(
            (page for page in model.pages if page.uid == uid), None
        )
        changed_pages = ProjectDataService(model).remove_takeoffs(["t1"])
        self.assertEqual(changed_pages, ["p1"])
        self.assertEqual(model.bid_takeoffs, [retained])
        self.assertEqual(model.pages[0].takeoffs, [])
        self.assertEqual(model.pages[1].takeoffs, [retained])
        self.assertEqual(
            model.bid_takeoff_extras,
            {"t2": {"condition_name": "Retained"}},
        )


class ProjectDataServiceSnapshotTests(unittest.TestCase):
    def test_hierarchy_reconstruction_refreshes_condition_type_label_by_uid(self):
        condition = Condition(
            uid="condition-1",
            cdn_type_uid="type-a",
            cdn_type_name="Old name",
        )

        class _Repository:
            active_file_path = "C:/Data/Test.mdb"
            cdn_types = {}

            @classmethod
            def get_cdn_types(cls, _file_path):
                return dict(cls.cdn_types)

        class _FileManager:
            project_repository = _Repository()

            @staticmethod
            def register_loaded_hierarchy(_file_entry, cdn_types):
                _Repository.cdn_types = dict(cdn_types)
                return HierarchyData()

        model = SimpleNamespace(
            file_manager=_FileManager(),
            cdn_types={},
            current_bid_ref=BidRef("c:\\data\\test.mdb", "bid-1"),
            current_bid=None,
            bid_conditions={condition.uid: condition},
            set_hierarchy=lambda _hierarchy: None,
            projects=[],
        )
        ProjectDataService(model).replace_database_hierarchy(
            HierarchyFileEntry(file_path="C:/Data/Test.mdb"),
            {"type-b": CdnType(uid="type-b", name="Old name")},
        )
        self.assertEqual(condition.cdn_type_uid, "type-a")
        self.assertEqual(condition.cdn_type_name, "Unknown")
        ProjectDataService(model).replace_database_hierarchy(
            HierarchyFileEntry(file_path="C:/Data/Test.mdb"),
            {"type-a": CdnType(uid="type-a", name="Renamed")},
        )
        self.assertEqual(condition.cdn_type_uid, "type-a")
        self.assertEqual(condition.cdn_type_name, "Renamed")

    def test_sql_projection_snapshots_do_not_expose_authoritative_mutable_state(self):
        service = ProjectDataService(SimpleNamespace())
        layer = BidLayer(
            uid="layer-1", bid_uid="8", name="Original", show=True, sequence=1
        )
        job_status = JobStatus(uid="status-1", name="Open")
        employee = Employee(uid="employee-1", first_name="Ada")
        pay_class = PayClass(uid="pay-class-1", name="Estimator")
        cover_sheet = CoverSheetData(
            bid_uid="8",
            job_status_uid="status-1",
            job_name="Original bid",
            estimator_uid="",
            notes="",
            bid_date="",
            bid_no="",
            job_id="",
            job_statuses=[JobStatus(uid="status-1", name="Open")],
        )
        defaults = {"nested": {"value": "original"}}
        service.replace_database_settings(
            "database",
            default_layers=[layer],
            job_statuses=[job_status],
            employees=[employee],
            pay_classes=[pay_class],
        )
        service.replace_cover_sheet_data("database", "8", cover_sheet)
        service.replace_settings_defaults("database", defaults)
        layer.name = "Mutated input"
        job_status.name = "Mutated input"
        employee.first_name = "Mutated input"
        pay_class.name = "Mutated input"
        cover_sheet.job_name = "Mutated input"
        defaults["nested"]["value"] = "mutated input"
        layer_snapshot = service.get_default_layer_snapshot("database")
        job_status_snapshot = service.get_job_status_snapshot("database")
        employee_snapshot = service.get_employee_snapshot("database")
        pay_class_snapshot = service.get_pay_class_snapshot("database")
        cover_sheet_snapshot = service.get_cover_sheet_snapshot("database", "8")
        defaults_snapshot = service.get_settings_defaults_snapshot("database")
        layer_snapshot[0].name = "Mutated output"
        job_status_snapshot[0].name = "Mutated output"
        employee_snapshot[0].first_name = "Mutated output"
        pay_class_snapshot[0].name = "Mutated output"
        cover_sheet_snapshot.job_statuses[0].name = "Mutated output"
        defaults_snapshot["nested"]["value"] = "mutated output"
        self.assertEqual(
            service.get_default_layer_snapshot("database")[0].name, "Original"
        )
        self.assertEqual(service.get_job_status_snapshot("database")[0].name, "Open")
        self.assertEqual(service.get_employee_snapshot("database")[0].first_name, "Ada")
        self.assertEqual(
            service.get_pay_class_snapshot("database")[0].name, "Estimator"
        )
        current_cover_sheet = service.get_cover_sheet_snapshot("database", "8")
        self.assertEqual(current_cover_sheet.job_name, "Original bid")
        self.assertEqual(current_cover_sheet.job_statuses[0].name, "Open")
        self.assertEqual(
            service.get_settings_defaults_snapshot("database"),
            {"nested": {"value": "original"}},
        )


class ProjectDataServiceCollaborationTests(unittest.TestCase):
    def test_unrelated_remote_takeoff_refresh_preserves_pending_preview(self):
        database_id = "database"
        aggregate = OstAggregate(None)
        aggregate.current_bid_ref = BidRef(database_id, "8")
        aggregate.set_pages({"20": Page(uid="20", name="Sheet")})
        project_data = ProjectDataService(aggregate)
        preview = Takeoff(
            uid="pending:takeoff-placement:operation-1:0",
            condition_uid="10",
            page_uid="20",
        )
        project_data.add_transient_takeoffs([preview])
        remote = Takeoff(uid="30", condition_uid="10", page_uid="20")
        self.assertTrue(
            project_data.replace_remote_bid_families(
                BidRef(database_id, "8"),
                BidLoadResult(
                    bid_takeoffs=[remote],
                    pages={
                        "20": Page(
                            uid="20",
                            name="Sheet",
                            takeoffs=[remote],
                        )
                    },
                ),
                {"takeoffs"},
            )
        )
        self.assertEqual(
            {takeoff.uid for takeoff in aggregate.bid_takeoffs},
            {preview.uid, remote.uid},
        )
        self.assertEqual(
            {takeoff.uid for takeoff in aggregate.get_page("20").takeoffs},
            {preview.uid, remote.uid},
        )
        self.assertIs(project_data.get_takeoff(preview.uid), preview)
        self.assertIs(aggregate.get_page("20").takeoffs[1], preview)

    def test_clearing_bid_discards_previews_before_same_page_uid_is_loaded(self):
        aggregate = OstAggregate(None)
        aggregate.current_bid_ref = BidRef("first.mdb", "8")
        aggregate.set_pages({"20": Page("20", "First")})
        service = ProjectDataService(aggregate)
        preview = Takeoff("pending:old", "10", page_uid="20", position=[1, 2])
        service.add_transient_takeoffs([preview])
        self.assertIs(service.get_takeoff(preview.uid), preview)
        service.clear_bid()
        other_ref = BidRef("second.mdb", "8")
        aggregate.current_bid_ref = other_ref
        current = Takeoff("30", "10", page_uid="20", position=[3, 4])
        page = Page("20", "Second", takeoffs=[current])
        self.assertTrue(
            service.replace_remote_bid_families(
                other_ref,
                BidLoadResult(bid_takeoffs=[current], pages={page.uid: page}),
                {"takeoffs", "pages"},
            )
        )
        self.assertEqual(aggregate.bid_takeoffs, [current])
        self.assertEqual(page.takeoffs, [current])
        self.assertIsNone(service.get_takeoff(preview.uid))


class AnnotationLayerVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.model = OstAggregate(None)
        self.data = ProjectDataService(self.model)

    def select_bid(self, bid_uid, page_uid):
        self.model.clear_bid()
        self.model.current_bid_ref = BidRef("layers.mdb", bid_uid)
        self.model.set_pages({page_uid: Page(uid=page_uid, name="Page")})

    def test_unassigned_annotation_added_to_hidden_template_stays_hidden(self):
        self.select_bid("179326", "20")
        self.data.set_bid_layer_visibility(
            [BidLayer("2", "", "Annotation", False, 1, True, True)]
        )
        annotation = BidAnnotation(
            uid="new", annotation_type="rect", page_uid="20", layer_uid=""
        )
        self.data.add_annotations([annotation])
        self.assertEqual(self.model.get_all_annotations(), [annotation])
        self.assertFalse(annotation.visible)
        self.assertEqual(annotation.layer_uid, "")

    def test_remote_projection_preserves_null_and_explicit_ownership_with_display_visibility(
        self,
    ):
        self.select_bid("179326", "20")
        unassigned = BidAnnotation(
            uid="1", annotation_type="rect", page_uid="20", layer_uid=""
        )
        explicit = BidAnnotation(
            uid="2", annotation_type="rect", page_uid="20", layer_uid="7"
        )
        self.assertTrue(
            self.data.replace_remote_bid_families(
                self.model.current_bid_ref,
                BidLoadResult(
                    bid_annotations=[unassigned, explicit],
                    bid_layers=[
                        BidLayer("2", "", "Annotation", False, 1, True, True),
                        BidLayer("7", "179326", "Custom", True, 2),
                    ],
                ),
                {"annotations", "layers"},
            )
        )
        self.assertEqual(
            [a.layer_uid for a in self.model.get_all_annotations()], ["", "7"]
        )
        self.assertFalse(unassigned.visible)
        self.assertTrue(explicit.visible)
        self.data.update_layer_visibility("2", True)
        self.assertTrue(unassigned.visible)
        self.assertEqual(unassigned.layer_uid, "")


class TakeoffHydrationContractTests(unittest.TestCase):
    def test_layer_usage_follows_takeoff_condition_contract(self):
        takeoff = Takeoff(uid="4485", condition_uid="10", page_uid="20")
        annotation = BidAnnotation(
            uid="99", annotation_type="rectangle", page_uid="20", layer_uid="30"
        )
        model = SimpleNamespace(
            bid_conditions={
                "10": Condition(uid="10", layer_uid="25"),
                "unused": Condition(uid="unused", layer_uid="unused-layer"),
            },
            get_all_takeoffs=lambda: [takeoff],
            get_all_annotations=lambda: [annotation],
        )
        self.assertEqual(
            ProjectDataService(model).get_layer_uids_in_use(), {"25", "30"}
        )


class ConditionUomConsistencyTests(unittest.TestCase):
    def test_same_condition_uid_in_another_bid_cannot_replace_active_family(self):
        active_ref = BidRef("active.mdb", "2")
        other_ref = BidRef("other.mdb", "1")
        active_condition = Condition(
            uid="shared",
            condition_type=Condition.TYPE_LINEAR,
            calc_type1=CALC_LINEAR_LENGTH,
            calc_type2=CALC_LINEAR_BOTH_SIDES,
            calc_type3=CALC_VOLUME,
            uom1=UOM_LINEAR_FEET,
            uom2=UOM_SQUARE_FEET,
            uom3=UOM_CUBIC_FEET,
        )
        model = SimpleNamespace(
            current_bid_ref=active_ref,
            current_bid=Bid(uid="2", name="Imperial", measure_base=0),
            bid_conditions={active_condition.uid: active_condition},
            bid_condition_folders={},
        )
        service = ProjectDataService(model)
        other_condition = normalize_condition_uoms_for_system(
            Condition(
                uid="shared",
                condition_type=Condition.TYPE_LINEAR,
                calc_type1=CALC_LINEAR_LENGTH,
                calc_type2=CALC_LINEAR_BOTH_SIDES,
                calc_type3=CALC_VOLUME,
                uom1=UOM_LINEAR_FEET,
                uom2=UOM_SQUARE_FEET,
                uom3=UOM_CUBIC_FEET,
            ),
            metric=True,
        )
        self.assertFalse(
            service.replace_condition_family(
                other_ref, {other_condition.uid: other_condition}, {}
            )
        )
        self.assertIs(model.bid_conditions["shared"], active_condition)
        self.assertEqual(
            (other_condition.uom1, other_condition.uom2, other_condition.uom3),
            (UOM_M, UOM_M2, UOM_M3),
        )
        self.assertTrue(
            service.replace_condition_family(
                active_ref, {other_condition.uid: other_condition}, {}
            )
        )
        self.assertEqual(
            (other_condition.uom1, other_condition.uom2, other_condition.uom3),
            (UOM_LINEAR_FEET, UOM_SQUARE_FEET, UOM_CUBIC_FEET),
        )


class ThreejsExportLayerTests(unittest.TestCase):
    def test_collect_takeoffs_for_pages_can_include_hidden_layer_takeoffs(self):
        model = OstAggregate(None)
        model.bid_conditions = {
            "visible": Condition(uid="visible", layer_visible=True),
            "hidden": Condition(uid="hidden", layer_visible=False),
        }
        takeoffs = [
            Takeoff("takeoff-visible", "visible", page_uid="page-1"),
            Takeoff("takeoff-hidden", "hidden", page_uid="page-1"),
        ]
        model.set_pages(
            {
                "page-1": Page("page-1", "First", takeoffs=takeoffs),
                "empty": Page("empty", "Empty"),
            }
        )
        service = ProjectDataService(model)
        visible = service.collect_takeoffs_for_pages(["page-1", "empty", "missing"])
        all_takeoffs = service.collect_takeoffs_for_pages(
            ["page-1"], visible_only=False
        )
        self.assertEqual(
            [takeoff.uid for takeoff in visible.takeoffs], ["takeoff-visible"]
        )
        self.assertEqual(
            [takeoff.uid for takeoff in all_takeoffs.takeoffs],
            ["takeoff-visible", "takeoff-hidden"],
        )
        self.assertEqual(visible.valid_page_uids, ["page-1"])
        self.assertEqual(all_takeoffs.valid_page_uids, ["page-1"])
        self.assertIs(visible.takeoffs[0], takeoffs[0])
        self.assertIs(all_takeoffs.takeoffs[1], takeoffs[1])
        empty = service.collect_takeoffs_for_pages(["empty", "missing"])
        self.assertEqual(empty.takeoffs, [])
        self.assertEqual(empty.valid_page_uids, [])

    def test_bid_layer_snapshot_fallback_filters_comments_layer(self):
        model = SimpleNamespace(
            bid_layers=[],
            bid_layer_names_by_uid={
                "image-layer": "image",
                "comments-layer": "comments",
            },
            bid_layer_visibility={
                "image-layer": True,
                "comments-layer": True,
            },
            current_bid_ref=BidRef("export.mdb", "bid"),
        )
        service = ProjectDataService(model)
        snapshot = service.get_bid_layer_snapshot()
        self.assertEqual([layer.uid for layer in snapshot], ["image-layer"])
        self.assertEqual(snapshot[0].bid_uid, "bid")
        self.assertEqual(snapshot[0].name, "image")
        self.assertTrue(snapshot[0].show)

    def test_bid_area_snapshot_uses_real_areas_and_skips_unassigned_takeoffs(self):
        model = SimpleNamespace(
            bid_areas={
                "area-1": BidArea(
                    uid="area-1",
                    bid_uid="bid",
                    parent_uid="",
                    name="Area One",
                    sequence=2,
                ),
                "area-2": BidArea(
                    uid="area-2",
                    bid_uid="bid",
                    parent_uid="",
                    name="Area Two",
                    sequence=1,
                ),
            }
        )
        service = ProjectDataService(model)
        snapshot = service.get_bid_area_snapshot(
            [
                Takeoff(uid="takeoff-1", condition_uid="c1", area_uid="area-1"),
                Takeoff(uid="takeoff-2", condition_uid="c1", area_uid="0"),
            ]
        )
        self.assertEqual([area.uid for area in snapshot], ["area-1"])
        self.assertEqual(
            [area.uid for area in service.get_bid_area_snapshot()], ["area-2", "area-1"]
        )
        self.assertEqual(service.get_bid_area_snapshot([]), [])


class PageScaleProjectionTests(unittest.TestCase):
    def _data(self):
        bid_ref = BidRef("scale.mdb", "7")
        takeoff = Takeoff("10", "20", page_uid="42", position=[20.0, 40.0])
        page = Page(
            "42",
            "A101",
            takeoffs=[takeoff],
            scale_factor1=1.0,
            scale_factor2=10.0,
            overlay_rect=(2.0, 4.0, 6.0, 8.0),
            overlay_offset_x=2.0,
            overlay_offset_y=4.0,
        )
        annotation = BidAnnotation(
            "30",
            ANNOTATION_TYPE_TEXT,
            page_uid="42",
            position=[2.0, 4.0, 6.0, 8.0, 33.0],
        )
        model = OstAggregate(SimpleNamespace())
        model.current_bid_ref = bid_ref
        model.current_bid = Bid("7", "Bid")
        model.bid_takeoffs = [takeoff]
        model.set_pages({page.uid: page})
        model.set_annotations([annotation])
        return ProjectDataService(model), bid_ref, page, takeoff, annotation

    def test_committed_scale_projects_only_scale_dependent_model_state(self):
        data, bid_ref, page, takeoff, annotation = self._data()
        changed = data.apply_page_scales(bid_ref, [page], 1.0, 20.0)
        self.assertEqual(changed, (page.uid,))
        self.assertEqual((page.scale_factor1, page.scale_factor2), (1.0, 20.0))
        self.assertEqual(takeoff.position, [40.0, 80.0])
        self.assertEqual(annotation.position, [4.0, 8.0, 12.0, 16.0, 33.0])
        self.assertEqual(page.overlay_rect, (4.0, 8.0, 12.0, 16.0))
        self.assertEqual((page.overlay_offset_x, page.overlay_offset_y), (4.0, 8.0))

    def test_scale_projection_rejects_another_bid_without_mutation(self):
        data, _bid_ref, page, takeoff, annotation = self._data()
        changed = data.apply_page_scales(BidRef("scale.mdb", "8"), [page], 1.0, 20.0)
        self.assertEqual(changed, ())
        self.assertEqual(page.scale_factor2, 10.0)
        self.assertEqual(takeoff.position, [20.0, 40.0])
        self.assertEqual(annotation.position, [2.0, 4.0, 6.0, 8.0, 33.0])
        self.assertEqual(page.overlay_rect, (2.0, 4.0, 6.0, 8.0))
        self.assertEqual((page.overlay_offset_x, page.overlay_offset_y), (2.0, 4.0))

    def test_scale_batch_rejects_replaced_page_before_mutating_valid_sibling(self):
        data, bid_ref, page, takeoff, annotation = self._data()
        foreign_same_uid = Page(page.uid, "Replacement", scale_factor2=10.0)
        changed = data.apply_page_scales(bid_ref, [page, foreign_same_uid], 1.0, 20.0)
        self.assertEqual(changed, ())
        self.assertEqual((page.scale_factor1, page.scale_factor2), (1.0, 10.0))
        self.assertEqual(takeoff.position, [20.0, 40.0])
        self.assertEqual(annotation.position, [2.0, 4.0, 6.0, 8.0, 33.0])
        self.assertEqual(page.overlay_rect, (2.0, 4.0, 6.0, 8.0))
        self.assertEqual(foreign_same_uid.scale_factor2, 10.0)


class PageAreaProjectionTests(unittest.TestCase):
    def test_local_area_refresh_clears_only_deleted_area_references(self):
        bid_ref = BidRef("areas.mdb", "7")
        removed = Takeoff("1", "10", page_uid="42", area_uid="20")
        retained = Takeoff("2", "10", page_uid="42", area_uid="21")
        page = Page("42", "A101", takeoffs=[removed, retained])
        model = OstAggregate(SimpleNamespace())
        model.current_bid_ref = bid_ref
        model.current_bid = Bid("7", "Bid")
        model.bid_takeoffs = [removed, retained]
        model.page_area_selections = {"42": "20", "43": "21"}
        model.set_pages({page.uid: page})
        data = ProjectDataService(model)
        applied = data.replace_bid_areas_after_local_save(
            bid_ref,
            [BidArea("21", "7", "", "Retained", 1)],
            ["20"],
        )
        self.assertTrue(applied)
        self.assertIsNone(model.page_area_selections["42"])
        self.assertEqual(model.page_area_selections["43"], "21")
        self.assertEqual(removed.area_uid, UNASSIGNED_AREA_UID)
        self.assertEqual(retained.area_uid, "21")


class ProjectDataServiceOwningBidOfPageTests(unittest.TestCase):
    """Decision Q2: the hierarchy answers which Bid of a database owns a page (used by
    the SQL page delete to key the locked-Bid guard on each owning Bid)."""

    @staticmethod
    def _bid(uid, *, pages=(), folders=None):
        return HierarchyBidInfo(
            uid=uid,
            pages_without_folder=[HierarchyPageInfo(uid=p, name=p) for p in pages],
            folders=folders or {},
        )

    def _service(self):
        nested = HierarchyFolderInfo(
            name="Nested", pages=[HierarchyPageInfo(uid="22", name="22")]
        )
        folder = HierarchyFolderInfo(
            name="Folder",
            pages=[HierarchyPageInfo(uid="21", name="21")],
            subfolders={"f2": nested},
        )
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="C:/Data/Test.mdb",
                    bid_projects={
                        "proj": HierarchyProjectInfo(
                            name="P",
                            bids=[
                                self._bid("7", pages=["20"], folders={"f1": folder}),
                                self._bid("8", pages=["30", ""]),
                            ],
                        )
                    },
                    orphan_bids=[self._bid("9", pages=["40"])],
                ),
                HierarchyFileEntry(
                    file_path="C:/Data/Other.mdb",
                    orphan_bids=[self._bid("5", pages=["20", "50"])],
                ),
                HierarchyFileEntry(
                    file_path="", orphan_bids=[self._bid("1", pages=["60"])]
                ),
            ]
        )
        return ProjectDataService(SimpleNamespace(get_hierarchy_data=lambda: hierarchy))

    def test_the_owning_bid_is_found_at_every_nesting_level_and_for_orphan_bids(self):
        service = self._service()
        for page_uid, bid_uid in (
            ("20", "7"),
            ("21", "7"),
            ("22", "7"),
            ("30", "8"),
            ("40", "9"),
        ):
            with self.subTest(page=page_uid):
                self.assertEqual(
                    service.find_owning_bid_uid_for_page("C:/Data/Test.mdb", page_uid),
                    bid_uid,
                )

    def test_the_lookup_is_scoped_to_the_database_and_tolerates_path_spelling(self):
        service = self._service()
        owner = service.find_owning_bid_uid_for_page
        self.assertEqual(owner("C:/Data/Other.mdb", "20"), "5")
        self.assertEqual(owner("C:/Data/Other.mdb", "50"), "5")
        self.assertIsNone(owner("C:/Data/Test.mdb", "50"))
        self.assertEqual(owner(r"c:\data\TEST.mdb", "30"), "8")
        self.assertIsNone(owner("C:/Data/Missing.mdb", "20"))

    def test_an_unknown_or_empty_page_has_no_owner(self):
        service = self._service()
        for page_uid in ("99", "", None):
            with self.subTest(page=page_uid):
                self.assertIsNone(
                    service.find_owning_bid_uid_for_page("C:/Data/Test.mdb", page_uid)
                )
        self.assertIsNone(service.find_owning_bid_uid_for_page("", "60"))


def _real_service(**attributes):
    """ProjectDataService over a real OstAggregate (file manager is not needed here)."""
    aggregate = OstAggregate(SimpleNamespace(current_file_path=None))
    for name, value in attributes.items():
        setattr(aggregate, name, value)
    return ProjectDataService(aggregate), aggregate


def _hierarchy_with_projects():
    def bid(uid):
        return HierarchyBidInfo(uid=uid, name=f"Bid {uid}")

    return HierarchyData(
        loaded_files=[
            HierarchyFileEntry(
                file_path="C:/a.mdb",
                bid_projects={
                    "p1": HierarchyProjectInfo(name="One", bids=[bid("b1"), bid("b2")]),
                    "p2": HierarchyProjectInfo(name="Two", bids=[]),
                    "p3": HierarchyProjectInfo(name="Three", bids=[bid("b3")]),
                },
            ),
            HierarchyFileEntry(
                file_path="C:/b.mdb",
                bid_projects={
                    "p1": HierarchyProjectInfo(name="Other", bids=[bid("b9")])
                },
            ),
        ]
    )


class ProjectDataServiceDatabaseSettingsTests(unittest.TestCase):
    def test_settings_are_stored_per_database_as_deep_copies(self):
        service, _ = _real_service()
        layer = BidLayer("l1", "b", "Layer", True, 1)
        job = JobStatus(uid="j1", name="Open")
        employee = Employee(uid="e1", first_name="Ann", pay_class_uid="pc1")
        pay_class = PayClass(uid="pc1", name="Hourly")
        service.replace_database_settings(
            "db1",
            default_layers=[layer],
            job_statuses=[job],
            employees=[employee],
            pay_classes=[pay_class],
            used_job_status_uids=["j1"],
            used_employee_uids=["e1"],
        )
        layer.name = "changed"
        snapshots = (
            service.get_default_layer_snapshot("db1"),
            service.get_job_status_snapshot("db1"),
            service.get_employee_snapshot("db1"),
            service.get_pay_class_snapshot("db1"),
        )
        self.assertEqual([l.name for l in snapshots[0]], ["Layer"])
        self.assertEqual([j.name for j in snapshots[1]], ["Open"])
        self.assertEqual([e.first_name for e in snapshots[2]], ["Ann"])
        self.assertEqual([p.name for p in snapshots[3]], ["Hourly"])
        snapshots[0][0].name = "mutated"
        self.assertEqual(service.get_default_layer_snapshot("db1")[0].name, "Layer")
        for getter in (
            service.get_default_layer_snapshot,
            service.get_job_status_snapshot,
            service.get_employee_snapshot,
            service.get_pay_class_snapshot,
        ):
            self.assertEqual(getter("other-db"), [])
        self.assertEqual(service.get_used_job_status_uids("db1"), {"j1"})
        self.assertEqual(service.get_used_employee_uids("db1"), {"e1"})
        self.assertEqual(service.get_used_job_status_uids("other-db"), set())
        self.assertEqual(service.get_used_employee_uids("other-db"), set())
        service.get_used_job_status_uids("db1").add("x")
        self.assertEqual(service.get_used_job_status_uids("db1"), {"j1"})

    def test_a_partial_replacement_touches_only_the_supplied_settings(self):
        service, _ = _real_service()
        service.replace_database_settings(
            "db1",
            job_statuses=[JobStatus(uid="j1", name="Open")],
            employees=[Employee(uid="e1", first_name="Ann")],
            used_employee_uids=["e1"],
        )
        service.replace_database_settings(
            "db1",
            pay_classes=[PayClass(uid="pc", name="P")],
            used_job_status_uids=["j1"],
        )
        self.assertEqual(len(service.get_job_status_snapshot("db1")), 1)
        self.assertEqual(len(service.get_employee_snapshot("db1")), 1)
        self.assertEqual(len(service.get_pay_class_snapshot("db1")), 1)
        self.assertEqual(service.get_used_employee_uids("db1"), {"e1"})
        self.assertEqual(service.get_used_job_status_uids("db1"), {"j1"})
        service.replace_database_settings(
            "db1", job_statuses=[], employees=[], used_employee_uids=[]
        )
        self.assertEqual(service.get_job_status_snapshot("db1"), [])
        self.assertEqual(service.get_employee_snapshot("db1"), [])
        self.assertEqual(service.get_used_employee_uids("db1"), set())
        self.assertEqual(len(service.get_pay_class_snapshot("db1")), 1)

    def test_master_data_usage_by_kind(self):
        service, _ = _real_service()
        service.replace_database_settings(
            "db1",
            employees=[
                Employee(uid="e1", first_name="A", pay_class_uid="pc1"),
                Employee(uid="e2", first_name="B", pay_class_uid=""),
                Employee(uid="e3", first_name="C", pay_class_uid=7),
                Employee(uid="e4", first_name="D", pay_class_uid="pc1"),
            ],
            used_job_status_uids=["j1", "j2"],
            used_employee_uids=["e2"],
        )
        self.assertEqual(
            service.get_master_data_uids_in_use("db1", "employees"), {"e2"}
        )
        self.assertEqual(
            service.get_master_data_uids_in_use("db1", "job_statuses"), {"j1", "j2"}
        )
        self.assertEqual(
            service.get_master_data_uids_in_use("db1", "pay_classes"), {"pc1", "7"}
        )
        self.assertEqual(
            service.get_master_data_uids_in_use("db2", "pay_classes"), set()
        )
        with self.assertRaisesRegex(ValueError, "^Unsupported master-data usage kind$"):
            service.get_master_data_uids_in_use("db1", "layers")

    def test_unsupported_master_data_kinds_are_refused_whatever_they_sort_like(self):
        service, _ = _real_service()
        service.replace_database_settings(
            "db1", used_job_status_uids=["j1"], used_employee_uids=["e1"]
        )
        # The three real kinds are "employees" < "job_statuses" < "pay_classes"; probe names on every side of them.
        for kind in ("a", "employee", "g", "layers", "pay", "zzz", "", "Employees"):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(
                    ValueError, "^Unsupported master-data usage kind$"
                ):
                    service.get_master_data_uids_in_use("db1", kind)

    def test_cover_sheet_page_delete_content_and_defaults_are_keyed_by_database_and_bid(
        self,
    ):
        service, _ = _real_service()
        cover = SimpleNamespace(job_name="Cover", pages=[1])
        service.replace_cover_sheet_data("db", 7, cover)
        self.assertEqual(service.get_cover_sheet_snapshot("db", "7"), cover)
        self.assertIsNot(service.get_cover_sheet_snapshot("db", "7"), cover)
        self.assertIsNone(service.get_cover_sheet_snapshot("db", "8"))
        self.assertIsNone(service.get_cover_sheet_snapshot("other", "7"))
        service.replace_page_delete_content_uids("db", 7, [1, "2", 2])
        self.assertEqual(
            service.get_page_delete_content_snapshot("db", "7"), {"1", "2"}
        )
        self.assertEqual(service.get_page_delete_content_snapshot("db", 8), set())
        service.get_page_delete_content_snapshot("db", "7").add("9")
        self.assertEqual(
            service.get_page_delete_content_snapshot("db", "7"), {"1", "2"}
        )
        defaults = {"a": [1]}
        service.replace_settings_defaults("db", defaults)
        defaults["a"].append(2)
        self.assertEqual(service.get_settings_defaults_snapshot("db"), {"a": [1]})
        self.assertEqual(service.get_settings_defaults_snapshot("other"), {})

    def test_reset_clears_every_per_database_store_and_the_bid_state(self):
        service, aggregate = _real_service()
        service.replace_database_settings(
            "db",
            default_layers=[BidLayer("l", "b", "L", True, 1)],
            job_statuses=[JobStatus(uid="j", name="J")],
            employees=[Employee(uid="e", first_name="E")],
            pay_classes=[PayClass(uid="p", name="P")],
            used_job_status_uids=["j"],
            used_employee_uids=["e"],
        )
        service.replace_cover_sheet_data("db", "1", SimpleNamespace(job_name="x"))
        service.replace_page_delete_content_uids("db", "1", ["p"])
        service.replace_settings_defaults("db", {"x": 1})
        service.add_transient_takeoffs(
            [Takeoff(uid="t", condition_uid="c", page_uid="p")]
        )
        aggregate.cdn_types = {"1": CdnType(uid="1", name="Type")}
        aggregate.projects = ["something"]
        aggregate.set_hierarchy(_hierarchy_with_projects())
        aggregate.current_bid_ref = BidRef("C:/a.mdb", "b1")
        service.reset()
        self.assertEqual(service.get_default_layer_snapshot("db"), [])
        self.assertEqual(service.get_job_status_snapshot("db"), [])
        self.assertEqual(service.get_employee_snapshot("db"), [])
        self.assertEqual(service.get_pay_class_snapshot("db"), [])
        self.assertEqual(service.get_used_job_status_uids("db"), set())
        self.assertEqual(service.get_used_employee_uids("db"), set())
        self.assertIsNone(service.get_cover_sheet_snapshot("db", "1"))
        self.assertEqual(service.get_page_delete_content_snapshot("db", "1"), set())
        self.assertEqual(service.get_settings_defaults_snapshot("db"), {})
        self.assertEqual(service._transient_takeoffs, {})
        self.assertEqual((aggregate.cdn_types, aggregate.projects), ({}, []))
        self.assertFalse(service.has_loaded_files())
        self.assertIsNone(aggregate.current_bid_ref)


class ProjectDataServiceHierarchyQueryTests(unittest.TestCase):
    def setUp(self):
        self.service, self.aggregate = _real_service()
        self.aggregate.set_hierarchy(_hierarchy_with_projects())

    def test_loaded_files_flag_and_hierarchy_accessor(self):
        self.assertIs(self.service.has_loaded_files(), True)
        self.assertIs(self.service.get_hierarchy(), self.aggregate.get_hierarchy_data())
        empty, _ = _real_service()
        self.assertIs(empty.has_loaded_files(), False)

    def test_project_has_bids_looks_in_the_requested_file_or_the_first_file_with_that_project(
        self,
    ):
        self.assertIs(self.service.project_has_bids("p1"), True)
        self.assertIs(self.service.project_has_bids("p2"), False)
        self.assertIs(self.service.project_has_bids("p3", "C:/a.mdb"), True)
        self.assertIs(self.service.project_has_bids("p3", "C:/b.mdb"), False)
        self.assertIs(self.service.project_has_bids("p1", "C:/b.mdb"), True)
        self.assertIs(self.service.project_has_bids("missing"), False)
        self.assertIs(self.service.project_has_bids("p1", "C:/none.mdb"), False)
        # An empty project in the first file shadows the same uid elsewhere only when it matches first.
        self.assertIs(self.service.project_has_bids("p2", "C:/b.mdb"), False)

    def test_project_exists_requires_the_exact_file_path_and_project(self):
        self.assertIs(self.service.project_exists("p1", "C:/a.mdb"), True)
        self.assertIs(self.service.project_exists("p2", "C:/a.mdb"), True)
        self.assertIs(self.service.project_exists("p2", "C:/b.mdb"), False)
        self.assertIs(self.service.project_exists("p1", "c:/a.mdb"), False)
        self.assertIs(self.service.project_exists("p9", "C:/a.mdb"), False)

    def test_project_bid_uids_are_those_of_the_requested_projects_in_that_file_only(
        self,
    ):
        self.assertEqual(
            self.service.get_project_bid_uids("C:/a.mdb", ["p1", "p3"]),
            ["b1", "b2", "b3"],
        )
        self.assertEqual(self.service.get_project_bid_uids("C:/a.mdb", ["p3"]), ["b3"])
        self.assertEqual(self.service.get_project_bid_uids("C:/a.mdb", ["p2"]), [])
        self.assertEqual(
            self.service.get_project_bid_uids("C:/b.mdb", ["p1", "p3"]), ["b9"]
        )
        self.assertEqual(self.service.get_project_bid_uids("C:/none.mdb", ["p1"]), [])
        self.assertEqual(
            self.service.get_project_bid_uids("C:/a.mdb", iter(["p1"])), ["b1", "b2"]
        )

    def test_project_of_a_bid_is_found_by_file_path_and_bid_uid(self):
        self.assertEqual(
            self.service.find_project_uid_for_bid(BidRef("C:/a.mdb", "b3")), "p3"
        )
        self.assertEqual(
            self.service.find_project_uid_for_bid(BidRef("C:/b.mdb", "b9")), "p1"
        )
        self.assertIsNone(
            self.service.find_project_uid_for_bid(BidRef("C:/b.mdb", "b3"))
        )
        self.assertIsNone(
            self.service.find_project_uid_for_bid(BidRef("C:/a.mdb", "zz"))
        )

    def test_hierarchy_queries_skip_other_files_whichever_way_their_path_sorts(self):
        def bid(uid):
            return HierarchyBidInfo(uid=uid, name=uid)

        # "C:/z.mdb" is listed first and has the same bid uid as the project in "C:/a.mdb"; the project uid exists
        # only in the z file, so an answer for the a file taken from the z file would be visibly wrong.
        self.aggregate.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        file_path="C:/z.mdb",
                        bid_projects={
                            "pz": HierarchyProjectInfo(name="Z", bids=[bid("b1")])
                        },
                    ),
                    HierarchyFileEntry(
                        file_path="C:/a.mdb",
                        bid_projects={"pa": HierarchyProjectInfo(name="A", bids=[])},
                    ),
                ]
            )
        )
        self.assertIsNone(
            self.service.find_project_uid_for_bid(BidRef("C:/a.mdb", "b1"))
        )
        self.assertEqual(
            self.service.find_project_uid_for_bid(BidRef("C:/z.mdb", "b1")), "pz"
        )
        self.assertIs(self.service.project_has_bids("pz", "C:/a.mdb"), False)
        self.assertIs(self.service.project_has_bids("pz", "C:/z.mdb"), True)
        self.assertIs(self.service.project_exists("pz", "C:/a.mdb"), False)
        self.assertIs(self.service.project_exists("pz", "C:/z.mdb"), True)
        self.assertEqual(self.service.get_project_bid_uids("C:/a.mdb", ["pz"]), [])
        self.assertEqual(self.service.get_project_bid_uids("C:/z.mdb", ["pz"]), ["b1"])
        # The mirror image: the file that holds the project is listed last and sorts before the other one.
        self.aggregate.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        file_path="C:/a.mdb",
                        bid_projects={"pa": HierarchyProjectInfo(name="A", bids=[])},
                    ),
                    HierarchyFileEntry(
                        file_path="C:/z.mdb",
                        bid_projects={
                            "pz": HierarchyProjectInfo(name="Z", bids=[bid("b1")])
                        },
                    ),
                ]
            )
        )
        self.assertEqual(
            self.service.find_project_uid_for_bid(BidRef("C:/z.mdb", "b1")), "pz"
        )
        self.assertIsNone(
            self.service.find_project_uid_for_bid(BidRef("C:/a.mdb", "b1"))
        )
        self.assertIs(self.service.project_has_bids("pz", "C:/z.mdb"), True)
        self.assertIs(self.service.project_exists("pz", "C:/z.mdb"), True)
        self.assertEqual(self.service.get_project_bid_uids("C:/z.mdb", ["pz"]), ["b1"])

    def test_get_bid_prefers_the_loaded_current_bid_object_over_a_rebuilt_one(self):
        ref = BidRef("C:/a.mdb", "b1")
        rebuilt = self.service.get_bid(ref)
        self.assertEqual((rebuilt.uid, rebuilt.name), ("b1", "Bid b1"))
        self.assertIsNone(self.service.get_bid(BidRef("C:/a.mdb", "unknown")))
        current = Bid(uid="b1", name="Loaded copy")
        self.aggregate.current_bid_ref = ref
        self.aggregate.current_bid = current
        self.assertIs(self.service.get_bid(ref), current)
        self.assertEqual(self.service.get_bid(BidRef("C:/a.mdb", "b2")).name, "Bid b2")
        self.aggregate.current_bid = None
        self.assertEqual(self.service.get_bid(ref).name, "Bid b1")
        # A current bid that is no longer in the hierarchy is not returned.
        self.aggregate.current_bid = current
        self.aggregate.current_bid_ref = BidRef("C:/a.mdb", "gone")
        self.assertIsNone(self.service.get_bid(BidRef("C:/a.mdb", "gone")))


class ProjectDataServiceAnnotationUpdateTests(unittest.TestCase):
    def setUp(self):
        self.service, self.aggregate = _real_service()
        self.rect = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 2.0],
            color="#111111",
            width=2.0,
        )
        self.oval = BidAnnotation(
            uid="a1", annotation_type="oval", page_uid="p2", position=[3.0, 4.0]
        )
        self.other = BidAnnotation(
            uid="a2", annotation_type="rect", page_uid="p1", position=[5.0, 6.0]
        )
        self.pageless = BidAnnotation(uid="a3", annotation_type="rect", page_uid="")
        self.view = BidAnnotation(
            uid="v1",
            annotation_type="namedview",
            page_uid="p3",
            properties={"Text": "Old"},
        )
        self.link = BidAnnotation(
            uid="h1",
            annotation_type="hotlink",
            page_uid="p4",
            properties={"BidPageViewUID": "v1"},
        )
        self.aggregate.set_annotations(
            [self.rect, self.oval, self.other, self.pageless, self.view, self.link]
        )

    def test_pages_for_annotation_keys_are_unique_ordered_and_match_uid_and_type_together(
        self,
    ):
        pages = self.service.get_page_uids_for_annotation_keys
        self.assertEqual(
            pages([("a1", "rect"), ("a1", "oval"), ("a2", "rect")]), ["p1", "p2"]
        )
        self.assertEqual(
            pages([("a1", "oval"), ("a1", "rect")]), ["p1", "p2"]
        )  # model order, not query order
        self.assertEqual(pages([("a1", "rect"), ("a2", "rect")]), ["p1"])
        self.assertEqual(pages([("a3", "rect")]), [])
        self.assertEqual(pages([("a1", "namedview")]), [])
        self.assertEqual(pages([]), [])
        self.assertEqual(pages(iter([(1, "rect")])), [])
        a_five = BidAnnotation(uid=5, annotation_type="rect", page_uid="p9")
        self.aggregate.add_annotations([a_five])
        self.assertEqual(pages([("5", "rect")]), ["p9"])

    def test_position_updates_apply_to_the_matching_annotation_only_and_copy_the_list(
        self,
    ):
        new_position = [9.0, 9.5]
        pages = self.service.update_annotation_positions(
            [("a1", "rect", new_position), ("a3", "rect", [7.0])]
        )
        self.assertEqual(pages, ["p1"])
        self.assertEqual(self.rect.position, [9.0, 9.5])
        self.assertEqual(self.pageless.position, [7.0])
        self.assertEqual(self.oval.position, [3.0, 4.0])
        self.assertEqual(self.other.position, [5.0, 6.0])
        new_position.append(1.0)
        self.assertEqual(self.rect.position, [9.0, 9.5])
        self.assertIsNot(self.rect.position, new_position)
        self.assertEqual(self.service.update_annotation_positions([]), [])
        self.assertEqual(
            self.service.update_annotation_positions([("nope", "rect", [1.0])]), []
        )

    def test_text_property_updates_merge_into_the_matching_annotation(self):
        self.rect.properties.update({"Keep": 1, "Text": "old"})
        updates = {"Text": "new", "FontSize": 12}
        pages = self.service.update_annotation_text_properties(
            [("a1", "rect", updates)]
        )
        self.assertEqual(pages, ["p1"])
        self.assertEqual(
            self.rect.properties, {"Keep": 1, "Text": "new", "FontSize": 12}
        )
        self.assertNotIn("Text", self.oval.properties)
        updates["Text"] = "changed later"
        self.assertEqual(self.rect.properties["Text"], "new")
        self.assertEqual(self.service.update_annotation_text_properties([]), [])

    def test_style_updates_set_color_and_width_independently_and_coerce_values(self):
        pages = self.service.update_annotation_styles(
            [("a1", "rect", {"Color": "#abcdef"})]
        )
        self.assertEqual(
            (pages, self.rect.color, self.rect.width), (["p1"], "#abcdef", 2.0)
        )
        self.service.update_annotation_styles([("a1", "rect", {"Width": "5.5"})])
        self.assertEqual((self.rect.color, self.rect.width), ("#abcdef", 5.5))
        self.service.update_annotation_styles([("a1", "rect", {"Width": None})])
        self.assertEqual(self.rect.width, 0.0)
        self.service.update_annotation_styles([("a1", "rect", {"Color": 5})])
        self.assertEqual(self.rect.color, "5")
        self.service.update_annotation_styles([("a1", "rect", {"Other": "x"})])
        self.assertEqual((self.rect.color, self.rect.width), ("5", 0.0))
        before = (self.oval.color, self.oval.width)
        self.service.update_annotation_styles(
            [("a1", "rect", {"Color": "#000001", "Width": 3})]
        )
        self.assertEqual((self.oval.color, self.oval.width), before)
        self.assertEqual(self.service.update_annotation_styles([]), [])

    def test_named_view_renames_only_touch_named_views_and_report_each_page_once(self):
        second = BidAnnotation(
            uid="v2",
            annotation_type="namedview",
            page_uid="p3",
            properties={"Text": "Two"},
        )
        third = BidAnnotation(
            uid="v3",
            annotation_type="namedview",
            page_uid="",
            properties={"Text": "Three"},
        )
        self.aggregate.add_annotations([second, third])
        pages = self.service.update_named_view_names(
            [
                ("v1", "New 1"),
                ("v2", "New 2"),
                ("v3", "New 3"),
                ("a1", "Not a view"),
                ("zz", "x"),
            ]
        )
        self.assertEqual(pages, ["p3"])
        self.assertEqual(
            (
                self.view.properties["Text"],
                second.properties["Text"],
                third.properties["Text"],
            ),
            ("New 1", "New 2", "New 3"),
        )
        self.assertNotIn("Text", self.rect.properties)
        self.assertEqual(self.service.update_named_view_names([]), [])
        self.assertEqual(self.service.update_named_view_names([(7, 8)]), [])

    def test_hotlinks_are_found_by_their_target_view_uid(self):
        other = BidAnnotation(
            uid="h2",
            annotation_type="hotlink",
            page_uid="p5",
            properties={"BidPageViewUID": "v2"},
        )
        self.aggregate.add_annotations([other])
        found = self.service.find_hotlinks_targeting
        self.assertEqual([a.uid for a in found(["v1"])], ["h1"])
        self.assertEqual([a.uid for a in found(["v1", "v2"])], ["h1", "h2"])
        self.assertEqual(found(["zz"]), [])
        self.assertEqual(found([]), [])
        self.assertEqual(found(["", None]), [])
        self.assertEqual([a.uid for a in found(iter(["v2"]))], ["h2"])

    def test_remove_annotations_and_visibility_hooks_reach_the_aggregate(self):
        self.assertEqual(
            self.service.remove_annotations_by_keys([("a1", "rect")]), ["p1"]
        )
        self.assertEqual(len(self.service.get_all_annotations()), 5)
        self.assertEqual(
            [a.uid for a in self.service.get_page_annotations("p1")], ["a2"]
        )
        self.service.add_annotations([])
        self.assertEqual(len(self.service.get_all_annotations()), 5)


class ProjectDataServiceTakeoffUpdateTests(unittest.TestCase):
    def setUp(self):
        self.service, self.aggregate = _real_service()
        self.t1 = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0, 0, 1, 1]
        )
        self.t2 = Takeoff(
            uid="t2", condition_uid="c1", page_uid="p1", position=[0, 0, 2, 2]
        )
        self.t3 = Takeoff(
            uid="t3", condition_uid="c2", page_uid="p2", position=[0, 0, 3, 3]
        )
        self.aggregate.bid_conditions = {
            "c1": Condition(uid="c1", condition_type=Condition.TYPE_LINEAR),
            "c2": Condition(uid="c2", condition_type=Condition.TYPE_LINEAR),
            "c3": Condition(uid="c3", condition_type=Condition.TYPE_AREA),
        }
        self.aggregate.set_pages(
            {
                "p1": Page("p1", "One", takeoffs=[self.t1, self.t2]),
                "p2": Page("p2", "Two", takeoffs=[self.t3]),
            }
        )
        self.aggregate.bid_takeoffs = [self.t1, self.t2, self.t3]

    def test_page_and_condition_lookups_are_unique_ordered_and_ignore_empty_ids(self):
        self.assertEqual(
            self.service.get_page_uids_for_takeoffs(["t3", "t1", "t2"]), ["p1", "p2"]
        )
        self.assertEqual(self.service.get_page_uids_for_takeoffs(["", None]), [])
        self.assertEqual(self.service.get_page_uids_for_takeoffs([]), [])
        self.assertEqual(self.service.get_page_uids_for_takeoffs(["zz"]), [])
        self.assertEqual(
            self.service.get_condition_uids_for_takeoffs(["t3", "t1", "t2"]),
            ["c1", "c2"],
        )
        self.assertEqual(
            self.service.get_condition_uids_for_takeoffs(["t1", "t2"]), ["c1"]
        )
        self.assertEqual(self.service.get_condition_uids_for_takeoffs(["", None]), [])
        self.assertEqual(self.service.get_condition_uids_for_takeoffs([]), [])
        self.assertEqual(self.service.get_condition_uids_for_takeoffs(["zz"]), [])
        self.assertEqual(self.service.get_page_uids_for_takeoffs(iter(["t2"])), ["p1"])
        self.assertEqual(
            self.service.get_condition_uids_for_takeoffs(iter(["t2"])), ["c1"]
        )

    def test_area_negative_curve_position_and_rotation_updates_report_the_pages_they_changed(
        self,
    ):
        self.assertEqual(
            self.service.update_takeoffs_area(["t1", "t3"], "area-5"), ["p1", "p2"]
        )
        self.assertEqual(
            (self.t1.area_uid, self.t2.area_uid, self.t3.area_uid),
            ("area-5", UNASSIGNED_AREA_UID, "area-5"),
        )
        self.assertEqual(self.service.update_takeoffs_area(["t1"], None), ["p1"])
        self.assertEqual(self.t1.area_uid, UNASSIGNED_AREA_UID)
        self.assertEqual(self.service.update_takeoffs_area([], "area-5"), [])
        self.assertEqual(self.service.update_takeoffs_negative(["t2"], 1), ["p1"])
        self.assertIs(self.t2.is_negative, True)
        self.assertEqual(
            self.service.update_takeoffs_negative(["t2", "t3"], 0), ["p1", "p2"]
        )
        self.assertEqual(
            (self.t2.is_negative, self.t3.is_negative, self.t1.is_negative),
            (False, False, False),
        )
        self.assertEqual(self.service.update_takeoffs_negative([], True), [])
        position = [9.0, 9.0, 8.0, 8.0]
        self.assertEqual(self.service.update_takeoff_curve("t3", position, "2"), ["p2"])
        self.assertEqual((self.t3.position, self.t3.curve), ([9.0, 9.0, 8.0, 8.0], 2))
        position.append(1.0)
        self.assertEqual(self.t3.position, [9.0, 9.0, 8.0, 8.0])
        self.assertEqual(
            self.service.update_takeoff_curve("t1", [1, 1, 1, 1], 0), ["p1"]
        )
        self.assertEqual(self.t1.curve, 0)
        self.assertEqual(self.t2.curve, -1)
        self.assertEqual(self.service.update_takeoff_curve("zz", [1], 0), [])
        self.assertEqual(
            self.service.update_takeoff_positions(
                [("t1", [5, 5, 6, 6]), ("t3", [7, 7, 8, 8])]
            ),
            ["p1", "p2"],
        )
        self.assertEqual(
            (self.t1.position, self.t2.position, self.t3.position),
            ([5, 5, 6, 6], [0, 0, 2, 2], [7, 7, 8, 8]),
        )
        self.assertEqual(self.service.update_takeoff_positions([]), [])
        self.assertEqual(
            self.service.update_takeoff_rotations([("t2", 45.0), ("t3", 0.0)]),
            ["p1", "p2"],
        )
        self.assertEqual(
            (self.t1.rotation, self.t2.rotation, self.t3.rotation), (0.0, 45.0, 0.0)
        )
        self.assertEqual(self.service.update_takeoff_rotations([]), [])

    def test_a_curve_update_changes_only_the_requested_takeoff_even_when_a_later_sorting_uid_is_listed_first(
        self,
    ):
        later = Takeoff(
            uid="t9", condition_uid="c1", page_uid="p1", position=[0, 0, 9, 9]
        )
        earlier = Takeoff(
            uid="t0", condition_uid="c1", page_uid="p1", position=[0, 0, 1, 1]
        )
        self.aggregate.set_pages({"p1": Page("p1", "One", takeoffs=[later, earlier])})
        self.aggregate.bid_takeoffs = [later, earlier]
        self.assertEqual(self.service.update_takeoff_curve("t0", [5, 5], 2), ["p1"])
        self.assertEqual((earlier.position, earlier.curve), ([5, 5], 2))
        self.assertEqual((later.position, later.curve), ([0, 0, 9, 9], -1))
        self.assertEqual(self.service.update_takeoff_curve("t9", [6, 6], 3), ["p1"])
        self.assertEqual((later.position, later.curve), ([6, 6], 3))
        self.assertEqual((earlier.position, earlier.curve), ([5, 5], 2))

    def test_condition_reassignment_is_all_or_nothing_and_geometry_checked(self):
        self.assertEqual(
            self.service.update_takeoffs_condition(["t1", "t3"], "c2"), ["p1", "p2"]
        )
        self.assertEqual(
            (self.t1.condition_uid, self.t2.condition_uid, self.t3.condition_uid),
            ("c2", "c1", "c2"),
        )
        self.assertEqual(self.service.update_takeoffs_condition(["t1"], "c3"), [])
        self.assertEqual(self.t1.condition_uid, "c2")
        self.assertEqual(
            self.service.update_takeoffs_condition(["t1", "ghost"], "c1"), []
        )
        self.assertEqual(self.t1.condition_uid, "c2")
        self.assertEqual(self.service.update_takeoffs_condition(["t1"], "missing"), [])
        self.assertEqual(self.service.update_takeoffs_condition([], "c1"), [])
        self.assertEqual(self.service.update_takeoffs_condition(["", None], "c1"), [])
        self.assertEqual(
            self.service.update_takeoffs_condition([self.t2.uid], "c2"), ["p1"]
        )

    def test_text_property_updates_cover_each_dimension_and_name_font_property(self):
        updates = {
            "dimension_font_name": 5,
            "dimension_font_color": "255",
            "dimension_font_size": 11.9,
            "dimension_font_bold": 1,
            "dimension_font_italic": 1,
            "dimension_font_underline": 1,
            "name_font_name": "Mono",
            "name_font_color": 7,
            "name_font_size": "9",
            "name_font_bold": 1,
            "name_font_italic": 1,
            "name_font_underline": 1,
        }
        self.assertEqual(
            self.service.update_takeoff_text_properties([("t1", updates)]), ["p1"]
        )
        self.assertEqual(
            (
                self.t1.dimension_font_name,
                self.t1.dimension_font_color,
                self.t1.dimension_font_size,
                self.t1.dimension_font_bold,
                self.t1.dimension_font_italic,
                self.t1.dimension_font_underline,
                self.t1.name_font_name,
                self.t1.name_font_color,
                self.t1.name_font_size,
                self.t1.name_font_bold,
                self.t1.name_font_italic,
                self.t1.name_font_underline,
            ),
            ("5", 255, 11, True, True, True, "Mono", 7, 9, True, True, True),
        )
        self.assertIsNone(self.t2.dimension_font_name)
        self.assertIs(self.t2.name_font_bold, False)
        self.service.update_takeoff_text_properties(
            [("t1", {"dimension_font_bold": 0, "name_font_underline": 0})]
        )
        self.assertEqual(
            (self.t1.dimension_font_bold, self.t1.name_font_underline), (False, False)
        )
        self.assertEqual(
            (self.t1.dimension_font_italic, self.t1.name_font_bold), (True, True)
        )
        self.service.update_takeoff_text_properties(
            [("t1", {"name_font_name": "Other"})]
        )
        self.assertEqual(
            (self.t1.name_font_name, self.t1.dimension_font_name), ("Other", "5")
        )
        self.assertEqual(self.service.update_takeoff_text_properties([]), [])
        self.assertEqual(
            self.service.update_takeoff_text_properties(
                [("zz", {"name_font_size": 3})]
            ),
            [],
        )
        shared = {"name_font_size": 3}
        self.service.update_takeoff_text_properties([("t2", shared), ("t3", shared)])
        shared["name_font_size"] = 99
        self.assertEqual((self.t2.name_font_size, self.t3.name_font_size), (3, 3))

    def test_transient_takeoffs_are_added_to_their_page_and_removable_by_uid(self):
        new = Takeoff(uid="n1", condition_uid="c1", page_uid="p1")
        orphan = Takeoff(uid="n2", condition_uid="c1", page_uid="unknown-page")
        self.service.add_transient_takeoffs([new, orphan])
        self.assertIn(new, self.aggregate.get_page("p1").takeoffs)
        self.assertIn(orphan, self.aggregate.bid_takeoffs)
        self.assertEqual(set(self.service._transient_takeoffs), {"n1", "n2"})
        self.assertEqual(self.service.remove_transient_takeoffs(["n1"]), ["p1"])
        self.assertNotIn(new, self.aggregate.get_page("p1").takeoffs)
        self.assertNotIn(new, self.aggregate.bid_takeoffs)
        self.assertEqual(set(self.service._transient_takeoffs), {"n2"})
        self.service.add_takeoffs([])
        self.assertEqual(len(self.aggregate.bid_takeoffs), 4)
        self.assertEqual(self.service.remove_takeoffs([]), [])
        self.assertEqual(self.service.remove_takeoffs(["", None]), [])
        self.assertIs(self.service.get_takeoff("t2"), self.t2)
        self.assertIsNone(self.service.get_takeoff("missing"))
        self.assertIs(
            self.service.get_condition("c1"), self.aggregate.bid_conditions["c1"]
        )
        self.assertIsNone(self.service.get_condition("zz"))


class CollectedTakeoffsResultTests(unittest.TestCase):
    def test_counts_default_to_the_collected_lists_and_explicit_counts_are_kept(self):
        from ost_visualizer.domain.services.project_data_service import (
            CollectedTakeoffsResult,
        )

        takeoffs = [
            Takeoff(uid="1", condition_uid="c"),
            Takeoff(uid="2", condition_uid="c"),
        ]
        derived = CollectedTakeoffsResult(
            takeoffs=takeoffs, valid_page_uids=["a", "b", "c"]
        )
        self.assertEqual((derived.page_count, derived.total_takeoffs), (3, 2))
        explicit = CollectedTakeoffsResult(
            takeoffs=takeoffs, valid_page_uids=["a"], page_count=9, total_takeoffs=8
        )
        self.assertEqual((explicit.page_count, explicit.total_takeoffs), (9, 8))
        empty = CollectedTakeoffsResult()
        self.assertEqual((empty.page_count, empty.total_takeoffs), (0, 0))
        self.assertIs(empty.is_empty(), True)
        self.assertIs(derived.is_empty(), False)

    def test_only_a_zero_count_means_derive_it_from_the_lists(self):
        from ost_visualizer.domain.services.project_data_service import (
            CollectedTakeoffsResult,
        )

        takeoffs = [
            Takeoff(uid="1", condition_uid="c"),
            Takeoff(uid="2", condition_uid="c"),
        ]
        for count in (-1, 1, 5):
            with self.subTest(count=count):
                result = CollectedTakeoffsResult(
                    takeoffs=takeoffs,
                    valid_page_uids=["a", "b", "c"],
                    page_count=count,
                    total_takeoffs=count,
                )
                self.assertEqual(
                    (result.page_count, result.total_takeoffs), (count, count)
                )


class ProjectDataServiceModelDelegationTests(unittest.TestCase):
    def test_simple_accessors_report_the_authoritative_aggregate_state(self):
        service, aggregate = _real_service()
        takeoff = Takeoff(uid="t", condition_uid="c", page_uid="p")
        page = Page("p", "Page", takeoffs=[takeoff])
        aggregate.set_pages({"p": page})
        aggregate.bid_takeoffs = [takeoff]
        aggregate.bid_conditions = {"c": Condition(uid="c")}
        aggregate.bid_condition_folders = {"f": object()}
        aggregate.cdn_types = {"1": CdnType(uid="1", name="T")}
        aggregate.page_area_selections = {"p": "a1"}
        aggregate.bid_takeoff_extras = {"t": {"k": 1}}
        aggregate.current_bid_ref = BidRef("C:/a.mdb", "b1")
        aggregate.current_bid = Bid(uid="b1", name="Loaded")
        aggregate.last_selected_page_uid = "p"
        aggregate.set_annotations(
            [BidAnnotation(uid="a", annotation_type="rect", page_uid="p")]
        )
        aggregate.set_current_file_path("C:/a.mdb")
        service.select_pages(["p"])
        self.assertIs(service.get_current_bid(), aggregate.current_bid)
        self.assertEqual(service.get_selected_page_uids(), ["p"])
        self.assertIs(service.has_takeoffs_for_pages(["p"]), True)
        self.assertIs(service.has_takeoffs_for_pages(["zz"]), False)
        self.assertEqual(service.get_all_selected_takeoffs(), [takeoff])
        self.assertEqual(service.get_all_takeoffs(), [takeoff])
        self.assertEqual(service.get_page_takeoffs("p"), [takeoff])
        self.assertIs(service.get_page("p"), page)
        self.assertEqual(service.get_all_pages(), [page])
        self.assertEqual(service.get_page_name("p"), "Page")
        self.assertIs(service.get_bid_conditions(), aggregate.bid_conditions)
        self.assertIs(
            service.get_bid_condition_folders(), aggregate.bid_condition_folders
        )
        self.assertIs(service.get_cdn_types(), aggregate.cdn_types)
        self.assertIs(
            service.get_page_area_selections(), aggregate.page_area_selections
        )
        self.assertEqual(service.get_takeoff_extras("t"), {"k": 1})
        self.assertEqual(service.get_current_bid_ref(), BidRef("C:/a.mdb", "b1"))
        self.assertEqual(service.get_current_bid_file_path(), "C:/a.mdb")
        self.assertEqual(service.get_current_file_path(), "C:/a.mdb")
        self.assertEqual(service.get_last_selected_page_uid(), "p")
        self.assertEqual([a.uid for a in service.get_all_annotations()], ["a"])
        self.assertEqual([a.uid for a in service.get_page_annotations("p")], ["a"])
        self.assertIs(service.is_current_bid_locked(), False)
        service.set_current_bid_locked(True)
        self.assertIs(aggregate.current_bid_locked, True)
        self.assertIs(service.is_current_bid_locked(), True)
        service.set_current_file("C:/b.mdb")
        self.assertEqual(aggregate.get_current_file_path(), "C:/b.mdb")
        service.deselect_pages()
        self.assertEqual(service.get_selected_page_uids(), [])
        self.assertEqual(service.select_pages(["p", "p"]), ["p"])
        service.clear_page_selection()
        self.assertIsNone(service.get_page("p"))
        service.clear_bid()
        self.assertIsNone(aggregate.current_bid_ref)
        self.assertEqual(service.get_all_takeoffs(), [])

    def test_clear_bid_also_drops_transient_takeoff_tracking(self):
        service, _ = _real_service()
        service.add_transient_takeoffs(
            [Takeoff(uid="t", condition_uid="c", page_uid="p")]
        )
        service.clear_bid()
        self.assertEqual(service._transient_takeoffs, {})

    def test_quantities_for_pages_use_the_bid_conditions_and_page_takeoffs(self):
        service, aggregate = _real_service()
        condition = Condition(
            uid="c", condition_type=Condition.TYPE_LINEAR, calc_type1=1, uom1=1
        )
        takeoffs = [
            Takeoff(uid="1", condition_uid="c", page_uid="p1", position=[0, 0, 10, 0]),
            Takeoff(uid="2", condition_uid="c", page_uid="p2", position=[0, 0, 5, 0]),
            Takeoff(uid="3", condition_uid="c", page_uid="p3", position=[0, 0, 100, 0]),
        ]
        aggregate.bid_conditions = {"c": condition, "d": Condition(uid="d")}
        aggregate.set_pages(
            {f"p{i}": Page(f"p{i}", "P", takeoffs=[takeoffs[i - 1]]) for i in (1, 2, 3)}
        )
        self.assertEqual(
            service.compute_quantities_for_pages(["p1", "p2"]), {"c": (15.0, 0.0, 0.0)}
        )
        self.assertEqual(
            service.compute_quantities_for_pages(["p1"], {"d"}), {"d": (0.0, 0.0, 0.0)}
        )
        self.assertEqual(service.compute_quantities_for_pages([]), {})


class ProjectDataServicePageMetadataTests(unittest.TestCase):
    def setUp(self):
        self.service, self.aggregate = _real_service()
        self.ref = BidRef("C:/a.mdb", "b1")
        self.page = Page(
            "p1",
            "Old",
            scale_factor1=1.0,
            scale_factor2=96.0,
            overlay_rect=(10.0, 20.0, 30.0, 40.0),
            overlay_offset_x=4.0,
            overlay_offset_y=6.0,
        )
        self.page2 = Page("p2", "Two", scale_factor1=1.0, scale_factor2=96.0)
        self.aggregate.set_pages({"p1": self.page, "p2": self.page2})
        self.aggregate.current_bid_ref = self.ref
        self.aggregate.bid_takeoffs = [
            Takeoff(
                uid="t1",
                condition_uid="c",
                page_uid="p1",
                position=[96.0, 192.0, 288.0, 384.0],
            ),
            Takeoff(uid="t2", condition_uid="c", page_uid="p2", position=[96.0, 96.0]),
            Takeoff(
                uid="t3", condition_uid="c", page_uid="other", position=[96.0, 96.0]
            ),
        ]
        self.rect = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[96.0, 48.0, 192.0, 96.0, 0.5],
        )
        self.aggregate.set_annotations(
            [
                self.rect,
                BidAnnotation(
                    uid="a2",
                    annotation_type="rect",
                    page_uid="other",
                    position=[96.0, 96.0],
                ),
            ]
        )
        record = HierarchyPageInfo(
            uid="p1", name="Old", scale_factor1=1.0, scale_factor2=96.0
        )
        record2 = HierarchyPageInfo(uid="p2", name="Two")
        nested = HierarchyFolderInfo(
            name="N", pages=[HierarchyPageInfo(uid="p3", name="Nested")]
        )
        folder = HierarchyFolderInfo(
            name="F", pages=[record2], subfolders={"n": nested}
        )
        self.info = HierarchyBidInfo(
            uid="b1", pages_without_folder=[record], folders={"f": folder}
        )
        self.aggregate.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(file_path="C:/a.mdb", orphan_bids=[self.info])
                ]
            )
        )
        self.record, self.record2, self.nested_record = record, record2, nested.pages[0]

    def test_scales_rescale_geometry_overlay_and_metadata_for_exactly_the_selected_pages(
        self,
    ):
        result = self.service.apply_page_scales(self.ref, [self.page], 1.0, 48.0)
        self.assertEqual(result, ("p1",))
        self.assertEqual(
            (self.page.scale_factor1, self.page.scale_factor2), (1.0, 48.0)
        )
        self.assertEqual(
            (self.page2.scale_factor1, self.page2.scale_factor2), (1.0, 96.0)
        )
        self.assertEqual(
            self.aggregate.bid_takeoffs[0].position, [48.0, 96.0, 144.0, 192.0]
        )
        self.assertEqual(self.aggregate.bid_takeoffs[1].position, [96.0, 96.0])
        self.assertEqual(self.aggregate.bid_takeoffs[2].position, [96.0, 96.0])
        self.assertEqual(self.rect.position, [48.0, 24.0, 96.0, 48.0, 0.5])
        self.assertEqual(self.aggregate.get_all_annotations()[1].position, [96.0, 96.0])
        self.assertEqual(self.page.overlay_rect, (5.0, 10.0, 15.0, 20.0))
        self.assertEqual(
            (self.page.overlay_offset_x, self.page.overlay_offset_y), (2.0, 3.0)
        )
        self.assertEqual(
            (self.record.scale_factor1, self.record.scale_factor2), (1.0, 48.0)
        )
        self.assertEqual(
            (self.record2.scale_factor1, self.record2.scale_factor2), (1.0, 1.0)
        )

    def test_ordered_uids_follow_the_input_pages_and_overlay_is_only_scaled_with_a_real_rectangle(
        self,
    ):
        result = self.service.apply_page_scales(
            self.ref, [self.page2, self.page], 2.0, 96.0
        )
        self.assertEqual(result, ("p2", "p1"))
        self.assertEqual(
            (self.page2.overlay_rect, self.page2.overlay_offset_x),
            ((0.0, 0.0, 0.0, 0.0), 0.0),
        )
        # Scale 2/96 is 48 units per sheet inch, half of the old 96: the real rectangle and offsets are halved.
        self.assertEqual(self.page.overlay_rect, (5.0, 10.0, 15.0, 20.0))
        self.assertEqual(
            (self.page.overlay_offset_x, self.page.overlay_offset_y), (2.0, 3.0)
        )
        flat = Page(
            "p1",
            "Old",
            scale_factor1=1.0,
            scale_factor2=96.0,
            overlay_rect=(10.0, 20.0, 0.0, 40.0),
            overlay_offset_x=4.0,
        )
        self.aggregate.set_pages({"p1": flat})
        self.service.apply_page_scales(self.ref, [flat], 1.0, 48.0)
        self.assertEqual(
            (flat.overlay_rect, flat.overlay_offset_x), ((10.0, 20.0, 0.0, 40.0), 4.0)
        )
        tall = Page(
            "p1",
            "Old",
            scale_factor1=1.0,
            scale_factor2=96.0,
            overlay_rect=(10.0, 20.0, 30.0, 0.0),
            overlay_offset_x=4.0,
        )
        self.aggregate.set_pages({"p1": tall})
        self.service.apply_page_scales(self.ref, [tall], 1.0, 48.0)
        self.assertEqual(
            (tall.overlay_rect, tall.overlay_offset_x), ((10.0, 20.0, 30.0, 0.0), 4.0)
        )
        tiny = Page(
            "p1",
            "Old",
            scale_factor1=1.0,
            scale_factor2=96.0,
            overlay_rect=(1.0, 1.0, 0.5, 0.5),
        )
        self.aggregate.set_pages({"p1": tiny})
        self.service.apply_page_scales(self.ref, [tiny], 1.0, 48.0)
        self.assertEqual(tiny.overlay_rect, (0.5, 0.5, 0.25, 0.25))

    def test_an_overlay_with_a_negative_extent_is_not_a_real_rectangle_and_stays_unscaled(
        self,
    ):
        for rect in (
            (10.0, 20.0, -30.0, 40.0),
            (10.0, 20.0, 30.0, -40.0),
            (10.0, 20.0, -30.0, -40.0),
        ):
            with self.subTest(rect=rect):
                page = Page(
                    "p1",
                    "Old",
                    scale_factor1=1.0,
                    scale_factor2=96.0,
                    overlay_rect=rect,
                    overlay_offset_x=4.0,
                    overlay_offset_y=6.0,
                )
                self.aggregate.set_pages({"p1": page})
                self.service.apply_page_scales(self.ref, [page], 1.0, 48.0)
                self.assertEqual(
                    (page.overlay_rect, page.overlay_offset_x, page.overlay_offset_y),
                    (rect, 4.0, 6.0),
                )
                self.assertEqual((page.scale_factor1, page.scale_factor2), (1.0, 48.0))

    def test_scale_changes_are_refused_without_touching_anything_for_other_bids_empty_or_foreign_pages(
        self,
    ):
        other_ref = BidRef("C:/a.mdb", "b2")
        self.assertEqual(
            self.service.apply_page_scales(other_ref, [self.page], 1.0, 48.0), ()
        )
        self.assertEqual(self.service.apply_page_scales(self.ref, [], 1.0, 48.0), ())
        stranger = Page("p1", "Old", scale_factor1=1.0, scale_factor2=96.0)
        self.assertEqual(
            self.service.apply_page_scales(self.ref, [self.page, stranger], 1.0, 48.0),
            (),
        )
        self.assertEqual(
            self.service.apply_page_scales(self.ref, [Page("zz", "Z")], 1.0, 48.0), ()
        )
        self.assertEqual(
            (self.page.scale_factor1, self.page.scale_factor2), (1.0, 96.0)
        )
        self.assertEqual(
            self.aggregate.bid_takeoffs[0].position, [96.0, 192.0, 288.0, 384.0]
        )

    def test_scale_text_values_are_coerced_to_numbers(self):
        self.service.apply_page_scales(self.ref, [self.page], "1", "48")
        self.assertEqual(
            (self.page.scale_factor1, self.page.scale_factor2), (1.0, 48.0)
        )
        self.assertIsInstance(self.page.scale_factor1, float)

    def test_page_name_changes_need_the_current_bid_and_the_exact_page_object_and_sync_records(
        self,
    ):
        self.assertIs(self.service.apply_page_name(self.ref, self.page, "New"), True)
        self.assertEqual(self.page.name, "New")
        self.assertEqual(self.record.name, "New")
        self.assertEqual(self.record2.name, "Two")
        self.assertIs(
            self.service.apply_page_name(BidRef("C:/a.mdb", "b2"), self.page, "X"),
            False,
        )
        self.assertIs(
            self.service.apply_page_name(self.ref, Page("p1", "Old"), "X"), False
        )
        self.assertIs(
            self.service.apply_page_name(self.ref, Page("zz", "Z"), "X"), False
        )
        self.assertEqual(self.page.name, "New")

    def test_metadata_sync_reaches_nested_folder_records_the_current_bid_and_the_cover_sheet(
        self,
    ):
        nested_page = Page("p3", "Renamed", scale_factor1=1.0, scale_factor2=24.0)
        current = Bid(
            uid="b1",
            name="Loaded",
            pages_without_folder=[HierarchyPageInfo(uid="p1", name="Stale")],
        )
        self.aggregate.current_bid = current
        cover = SimpleNamespace(
            pages_without_folder=[HierarchyPageInfo(uid="p1", name="Cover stale")],
            folders={
                "f": HierarchyFolderInfo(
                    name="F", pages=[HierarchyPageInfo(uid="p2", name="Cover two")]
                )
            },
        )
        self.service.replace_cover_sheet_data("C:/a.mdb", "b1", cover)
        self.service._sync_page_metadata(
            self.ref, {"p1": self.page, "p2": self.page2, "p3": nested_page}
        )
        self.assertEqual(
            (self.nested_record.name, self.nested_record.scale_factor2),
            ("Renamed", 24.0),
        )
        self.assertEqual(current.pages_without_folder[0].name, "Old")
        stored = self.service._cover_sheet_by_database_bid[("C:/a.mdb", "b1")]
        self.assertEqual(stored.pages_without_folder[0].name, "Old")
        self.assertEqual(stored.folders["f"].pages[0].name, "Two")
        self.assertEqual((self.record2.name, self.record2.scale_factor2), ("Two", 96.0))


class ProjectDataServiceFamilyReplacementTests(unittest.TestCase):
    def setUp(self):
        self.service, self.aggregate = _real_service()
        self.ref = BidRef("C:/a.mdb", "b1")
        self.aggregate.current_bid_ref = self.ref

    def test_condition_family_replacement_requires_the_current_bid_and_normalizes_units(
        self,
    ):
        metric = Condition(uid="c", calc_type1=CALC_LINEAR_LENGTH, uom1=UOM_LINEAR_FEET)
        folders = {"f": object()}
        self.aggregate.current_bid = Bid(uid="b1", name="B", measure_base=1)
        self.assertIs(
            self.service.replace_condition_family(self.ref, {"c": metric}, folders),
            True,
        )
        self.assertEqual(metric.uom1, UOM_M)
        self.assertEqual(self.aggregate.bid_conditions, {"c": metric})
        self.assertEqual(self.aggregate.bid_condition_folders, folders)
        self.assertIsNot(self.aggregate.bid_conditions, {"c": metric})
        imperial = Condition(uid="c2", calc_type1=CALC_LINEAR_LENGTH, uom1=UOM_M)
        self.aggregate.current_bid = Bid(uid="b1", name="B", measure_base=0)
        self.assertIs(
            self.service.replace_condition_family(self.ref, {"c2": imperial}, {}), True
        )
        self.assertEqual(imperial.uom1, UOM_LINEAR_FEET)
        self.aggregate.current_bid = None
        untouched = Condition(uid="c3", calc_type1=CALC_LINEAR_LENGTH, uom1=UOM_M)
        self.assertIs(
            self.service.replace_condition_family(self.ref, {"c3": untouched}, {}), True
        )
        self.assertEqual(untouched.uom1, UOM_M)
        before = dict(self.aggregate.bid_conditions)
        self.assertIs(
            self.service.replace_condition_family(
                BidRef("C:/a.mdb", "zz"), {"x": Condition(uid="x")}, {}
            ),
            False,
        )
        self.assertEqual(self.aggregate.bid_conditions, before)

    def test_area_replacement_and_local_delete_cleanup(self):
        areas = [BidArea("a1", "b1", "0", "A", 2), BidArea("a2", "b1", "0", "B", 1)]
        self.assertIs(
            self.service.replace_bid_areas(BidRef("C:/a.mdb", "zz"), areas), False
        )
        self.assertEqual(self.aggregate.bid_areas, {})
        self.assertIs(self.service.replace_bid_areas(self.ref, areas), True)
        self.assertEqual(set(self.aggregate.bid_areas), {"a1", "a2"})
        self.aggregate.page_area_selections = {
            "p1": "a1",
            "p2": "a2",
            "p3": None,
            "p4": 5,
        }
        t1 = Takeoff(uid="t1", condition_uid="c", area_uid="a1")
        t2 = Takeoff(uid="t2", condition_uid="c", area_uid="a2")
        t3 = Takeoff(uid="t3", condition_uid="c", area_uid="0")
        self.aggregate.bid_takeoffs = [t1, t2, t3]
        self.assertIs(
            self.service.replace_bid_areas_after_local_save(
                BidRef("C:/a.mdb", "zz"), areas, ["a1"]
            ),
            False,
        )
        self.assertEqual(t1.area_uid, "a1")
        self.assertIs(
            self.service.replace_bid_areas_after_local_save(self.ref, areas, []), True
        )
        self.assertIs(
            self.service.replace_bid_areas_after_local_save(
                self.ref, areas, [None, ""]
            ),
            True,
        )
        self.assertEqual(
            (t1.area_uid, self.aggregate.page_area_selections["p1"]), ("a1", "a1")
        )
        self.assertIs(
            self.service.replace_bid_areas_after_local_save(
                self.ref, [areas[1]], ["a1", 9]
            ),
            True,
        )
        self.assertEqual(set(self.aggregate.bid_areas), {"a2"})
        self.assertEqual(t1.area_uid, UNASSIGNED_AREA_UID)
        self.assertEqual((t2.area_uid, t3.area_uid), ("a2", "0"))
        self.assertEqual(
            self.aggregate.page_area_selections,
            {"p1": None, "p2": "a2", "p3": None, "p4": 5},
        )

    def test_only_measure_base_1_selects_the_metric_system_for_a_replaced_condition_family(
        self,
    ):
        # The same `== 1` rule is used by the MDB readers; any other value is imperial.
        for measure_base, expected in (
            (1, UOM_M),
            (0, UOM_LINEAR_FEET),
            (2, UOM_LINEAR_FEET),
            (-1, UOM_LINEAR_FEET),
        ):
            with self.subTest(measure_base=measure_base):
                self.aggregate.current_bid = Bid(
                    uid="b1", name="B", measure_base=measure_base
                )
                condition = Condition(
                    uid="c",
                    calc_type1=CALC_LINEAR_LENGTH,
                    uom1=UOM_LINEAR_FEET if expected == UOM_M else UOM_M,
                )
                self.assertIs(
                    self.service.replace_condition_family(
                        self.ref, {"c": condition}, {}
                    ),
                    True,
                )
                self.assertEqual(condition.uom1, expected)

    def test_an_area_without_a_sequence_counts_as_sequence_zero_in_the_snapshot(self):
        self.aggregate.bid_areas = {
            "none": BidArea("none", "b1", "0", "No sequence", None),
            "zero": BidArea("zero", "b1", "0", "Zero", 0),
            "negative": BidArea("negative", "b1", "0", "Negative", -1),
            "positive": BidArea("positive", "b1", "0", "Positive", 1),
        }
        self.assertEqual(
            [a.uid for a in self.service.get_bid_area_snapshot()],
            ["negative", "none", "zero", "positive"],
        )

    def test_area_snapshot_is_sorted_by_sequence_and_limited_to_used_areas(self):
        self.aggregate.bid_areas = {
            "a1": BidArea("a1", "b1", "0", "A", 3),
            "a2": BidArea("a2", "b1", "0", "B", 1),
            "a3": BidArea("a3", "b1", "0", "C", None),
        }
        self.assertEqual(
            [a.uid for a in self.service.get_bid_area_snapshot()], ["a3", "a2", "a1"]
        )
        used = [
            Takeoff(uid="1", condition_uid="c", area_uid="a1"),
            Takeoff(uid="2", condition_uid="c", area_uid="0"),
            Takeoff(uid="3", condition_uid="c", area_uid="a3"),
        ]
        self.assertEqual(
            [a.uid for a in self.service.get_bid_area_snapshot(used)], ["a3", "a1"]
        )
        self.assertEqual(self.service.get_bid_area_snapshot([]), [])

    def test_remote_families_replace_only_the_changed_collections_and_keep_transient_previews(
        self,
    ):
        old = Takeoff(uid="old", condition_uid="c", page_uid="p1")
        transient = Takeoff(uid="tr", condition_uid="c", page_uid="p1")
        self.service.add_transient_takeoffs([transient])
        self.aggregate.bid_takeoffs = [old, transient]
        self.aggregate.set_pages(
            {"p1": Page("p1", "Old page", takeoffs=[old, transient])}
        )
        keep_annotation = BidAnnotation(
            uid="keep", annotation_type="rect", page_uid="p1"
        )
        self.aggregate.set_annotations([keep_annotation])
        authoritative = Takeoff(uid="new", condition_uid="c", page_uid="p1")
        duplicate = Takeoff(uid="tr", condition_uid="c", page_uid="p1")
        bid_data = BidLoadResult(
            bid_takeoffs=[authoritative, duplicate],
            takeoff_extras={"new": {"x": 1}},
            pages={"p1": Page("p1", "New page"), "p2": Page("p2", "Other")},
            page_area_selections={"p1": "a9"},
            bid_annotations=[
                BidAnnotation(uid="fresh", annotation_type="rect", page_uid="p1")
            ],
            bid_layers=[BidLayer("l1", "b1", "Layer", False, 1)],
        )
        self.assertIs(
            self.service.replace_remote_bid_families(self.ref, bid_data, {"takeoffs"}),
            True,
        )
        self.assertEqual([t.uid for t in self.aggregate.bid_takeoffs], ["new", "tr"])
        self.assertIs(self.aggregate.bid_takeoffs[1], duplicate)
        self.assertEqual(self.aggregate.bid_takeoff_extras, {"new": {"x": 1}})
        self.assertEqual(
            [t.uid for t in self.aggregate.get_page("p1").takeoffs], ["new", "tr"]
        )
        self.assertEqual(self.aggregate.get_page("p1").name, "Old page")
        self.assertEqual(
            [a.uid for a in self.aggregate.get_all_annotations()], ["keep"]
        )
        self.assertEqual(self.aggregate.bid_layers, [])
        self.assertIs(
            self.service.replace_remote_bid_families(self.ref, bid_data, {"pages"}),
            True,
        )
        self.assertEqual(
            sorted(p.uid for p in self.aggregate.get_all_pages()), ["p1", "p2"]
        )
        self.assertEqual(self.aggregate.page_area_selections, {"p1": "a9"})
        self.assertEqual(self.aggregate.get_page("p1").takeoffs, [])
        self.assertIs(
            self.service.replace_remote_bid_families(
                self.ref, bid_data, {"annotations", "layers"}
            ),
            True,
        )
        self.assertEqual(
            [a.uid for a in self.aggregate.get_all_annotations()], ["fresh"]
        )
        self.assertEqual(self.aggregate.bid_layer_visibility, {"l1": False})
        self.assertIs(self.aggregate.get_all_annotations()[0].visible, True)
        before = list(self.aggregate.bid_takeoffs)
        self.assertIs(
            self.service.replace_remote_bid_families(
                BidRef("C:/a.mdb", "zz"), bid_data, {"takeoffs", "pages"}
            ),
            False,
        )
        self.assertEqual(self.aggregate.bid_takeoffs, before)
        self.assertIs(
            self.service.replace_remote_bid_families(self.ref, bid_data, set()), True
        )


class ProjectDataServiceLayerStateTests(unittest.TestCase):
    def setUp(self):
        self.service, self.aggregate = _real_service()
        self.ref = BidRef("C:/a.mdb", "b1")
        self.aggregate.current_bid_ref = self.ref
        self.layers = [
            BidLayer("t-ann", "0", "Annotation", True, 1, is_template=True),
            BidLayer("ann", "b1", "annotation", False, 2),
            BidLayer("img", "b1", "Image", True, 3),
            BidLayer("cm", "b1", "Comments", True, 4),
            BidLayer("other-bid", "b2", "Annotation", True, 5),
        ]

    def test_layer_visibility_state_is_rebuilt_from_the_layers_and_hidden_ids_listed(
        self,
    ):
        self.service.set_bid_layer_visibility(
            self.layers
            + [
                BidLayer("", "b1", "No uid", False, 9),
                BidLayer("blank", "b1", "", False, 10),
            ]
        )
        self.assertEqual(self.aggregate.bid_layer_visibility["ann"], False)
        self.assertEqual(self.aggregate.bid_layer_names_by_uid["ann"], "annotation")
        self.assertEqual(self.aggregate.bid_layer_visibility_by_name["image"], True)
        self.assertNotIn("", self.aggregate.bid_layer_visibility)
        self.assertNotIn("blank", self.aggregate.bid_layer_names_by_uid)
        self.assertEqual(self.service.get_hidden_layer_uids(), {"ann", "blank"})
        self.assertIs(self.service.is_annotation_layer_visible(), True)
        self.service.set_bid_layer_visibility(
            [BidLayer("ann", "b1", "Annotation", False, 1)]
        )
        self.assertIs(self.service.is_annotation_layer_visible(), False)
        self.assertEqual(self.service.get_annotation_layer_uid(), "ann")
        self.assertEqual(self.service.get_image_layer_uid(), None)

    def test_annotation_visibility_falls_back_to_the_named_state_when_there_is_no_layer(
        self,
    ):
        self.assertIs(self.service.is_annotation_layer_visible(), True)
        self.aggregate.bid_layer_visibility_by_name = {"annotation": False}
        self.assertIs(self.service.is_annotation_layer_visible(), False)

    def test_the_bid_annotation_layer_is_the_bids_own_override_and_requires_the_current_bid(
        self,
    ):
        self.aggregate.bid_layers = self.layers
        self.assertEqual(self.service.get_bid_annotation_layer_uid(self.ref), "ann")
        self.assertEqual(
            self.service.get_bid_annotation_layer_uid(BidRef("c:/A.MDB", "b1")), "ann"
        )
        for other in (BidRef("C:/a.mdb", "b2"), BidRef("C:/b.mdb", "b1")):
            with self.subTest(other=other):
                with self.assertRaisesRegex(
                    ValueError,
                    "^Annotation Layer lookup requires the current Bid context$",
                ):
                    self.service.get_bid_annotation_layer_uid(other)
        self.assertEqual(
            self.service.get_bid_annotation_layer_uid(BidRef("C:/a.mdb", "b1")), "ann"
        )
        self.aggregate.bid_layers = [
            BidLayer("img", "b1", "Image", True, 1),
            BidLayer("blank", "b1", "Annotation", True, 2),
        ]
        self.assertEqual(self.service.get_bid_annotation_layer_uid(self.ref), "blank")
        self.aggregate.bid_layers = [BidLayer("", "b1", "Annotation", True, 1)]
        self.assertIsNone(self.service.get_bid_annotation_layer_uid(self.ref))
        self.aggregate.bid_layers = [BidLayer("x", "b2", "Annotation", True, 1)]
        self.assertIsNone(self.service.get_bid_annotation_layer_uid(self.ref))
        self.aggregate.current_bid_ref = None
        with self.assertRaises(ValueError):
            self.service.get_bid_annotation_layer_uid(self.ref)

    def test_the_bid_annotation_layer_needs_exactly_the_current_bid_whichever_way_the_other_ref_sorts(
        self,
    ):
        self.aggregate.current_bid_ref = BidRef("C:/z.mdb", "b2")
        self.aggregate.bid_layers = [BidLayer("ann", "b2", "Annotation", True, 1)]
        for other in (
            BidRef("C:/a.mdb", "b2"),
            BidRef("C:/z.mdb", "b1"),
            BidRef("C:/zz.mdb", "b2"),
            BidRef("C:/z.mdb", "b3"),
        ):
            with self.subTest(other=other):
                with self.assertRaisesRegex(
                    ValueError,
                    "^Annotation Layer lookup requires the current Bid context$",
                ):
                    self.service.get_bid_annotation_layer_uid(other)
        self.assertEqual(
            self.service.get_bid_annotation_layer_uid(BidRef("C:/z.mdb", "b2")), "ann"
        )

    def test_the_bid_annotation_layer_ignores_other_bids_layers_and_other_named_layers_whichever_way_they_sort(
        self,
    ):
        self.aggregate.current_bid_ref = BidRef("C:/a.mdb", "b2")
        self.aggregate.bid_layers = [
            BidLayer("other-bid", "b1", "Annotation", True, 1),
            BidLayer("before", "b2", "Alpha", True, 2),
            BidLayer("after", "b2", "Zeta", True, 3),
        ]
        self.assertIsNone(
            self.service.get_bid_annotation_layer_uid(BidRef("C:/a.mdb", "b2"))
        )
        self.aggregate.bid_layers.append(BidLayer("ann", "b2", "Annotation", True, 4))
        self.assertEqual(
            self.service.get_bid_annotation_layer_uid(BidRef("C:/a.mdb", "b2")), "ann"
        )

    def test_a_layer_uid_text_none_is_not_the_layer_of_an_annotation_without_a_layer(
        self,
    ):
        without_layer = BidAnnotation(
            uid="a", annotation_type="rect", layer_uid=None, visible=False
        )
        self.aggregate.set_annotations([without_layer])
        # No layer is defined at all, so the default annotation layer has no uid (None, not the text "None").
        self.service._synchronize_annotation_visibility({"None"})
        self.assertIs(without_layer.visible, False)
        self.service._synchronize_annotation_visibility()
        self.assertIs(without_layer.visible, True)
        # With a hidden annotation layer the annotation belongs to it, and the text "None" is still not its layer.
        self.service.set_bid_layer_visibility(
            [BidLayer("ann", "b1", "Annotation", False, 1)]
        )
        without_layer.visible = True
        self.service._synchronize_annotation_visibility({"None"})
        self.assertIs(without_layer.visible, True)
        self.service._synchronize_annotation_visibility({"ann"})
        self.assertIs(without_layer.visible, False)

    def test_layer_snapshot_merges_templates_hides_comments_and_falls_back_to_the_names_map(
        self,
    ):
        self.aggregate.bid_layers = self.layers[:4]
        self.assertEqual(
            [l.uid for l in self.service.get_bid_layer_snapshot()], ["ann", "img"]
        )
        self.aggregate.bid_layers = []
        self.aggregate.bid_layer_names_by_uid = {
            "u1": "annotation",
            "u2": "comments",
            "u3": "",
            "u4": "image",
        }
        self.aggregate.bid_layer_visibility = {"u1": False}
        snapshot = self.service.get_bid_layer_snapshot()
        self.assertEqual(
            [(l.uid, l.bid_uid, l.name, l.show, l.sequence) for l in snapshot],
            [
                ("u1", "b1", "annotation", False, 0),
                ("u3", "b1", "u3", True, 2),
                ("u4", "b1", "image", True, 3),
            ],
        )
        self.aggregate.current_bid_ref = None
        self.assertEqual(self.service.get_bid_layer_snapshot()[0].bid_uid, "")
        self.aggregate.bid_layers = None
        self.assertEqual(len(self.service.get_bid_layer_snapshot()), 3)

    def test_layer_usage_collects_condition_and_annotation_layers_of_existing_content(
        self,
    ):
        self.aggregate.bid_conditions = {
            "c1": Condition(uid="c1", layer_uid="L1"),
            "c2": Condition(uid="c2", layer_uid=None),
            "c3": Condition(uid="c3", layer_uid="L3"),
        }
        self.aggregate.bid_takeoffs = [
            Takeoff(uid="1", condition_uid="c1", page_uid="p"),
            Takeoff(uid="2", condition_uid="c2", page_uid="p"),
            Takeoff(uid="3", condition_uid="ghost", page_uid="p"),
        ]
        self.aggregate.set_pages(
            {"p": Page("p", "P", takeoffs=list(self.aggregate.bid_takeoffs))}
        )
        self.aggregate.set_annotations(
            [
                BidAnnotation(uid="a", annotation_type="rect", layer_uid="L9"),
                BidAnnotation(uid="b", annotation_type="rect", layer_uid=None),
            ]
        )
        self.assertEqual(self.service.get_layer_uids_in_use(), {"L1", "L9"})

    def test_updating_one_layer_changes_conditions_layers_names_and_only_image_layers_touch_pages(
        self,
    ):
        self.service.set_bid_layer_visibility(self.layers[:4])
        condition = Condition(uid="c", layer_uid="ann", layer_visible=True)
        other_condition = Condition(uid="d", layer_uid="img", layer_visible=True)
        self.aggregate.bid_conditions = {"c": condition, "d": other_condition}
        page = Page("p", "P", layer_visible=True)
        self.aggregate.set_pages({"p": page})
        self.assertEqual(self.service.update_layer_visibility("ann", False), [])
        self.assertEqual(
            (
                condition.layer_visible,
                other_condition.layer_visible,
                page.layer_visible,
            ),
            (False, True, True),
        )
        self.assertIs(self.aggregate.bid_layer_visibility["ann"], False)
        self.assertIs(self.aggregate.bid_layer_visibility_by_name["annotation"], False)
        self.assertEqual(
            [l.show for l in self.aggregate.bid_layers if l.uid == "ann"], [False]
        )
        self.assertEqual(
            [l.show for l in self.aggregate.bid_layers if l.uid == "img"], [True]
        )
        self.assertEqual(self.service.update_layer_visibility("img", 0), ["p"])
        self.assertIs(page.layer_visible, False)
        self.assertIs(other_condition.layer_visible, False)
        self.assertEqual(self.service.update_layer_visibility("img", 1), ["p"])
        self.assertIs(page.layer_visible, True)
        self.assertIs(self.service.is_image_layer_uid("img"), True)
        self.assertIs(self.service.is_image_layer_uid(5), False)
        self.assertEqual(self.service.get_image_layer_uid(), "img")

    def test_updating_all_layers_shows_or_hides_everything_known(self):
        self.service.set_bid_layer_visibility(self.layers[:4])
        condition = Condition(uid="c", layer_uid="ann", layer_visible=True)
        self.aggregate.bid_conditions = {"c": condition}
        page = Page("p", "P", layer_visible=True)
        self.aggregate.set_pages({"p": page})
        self.assertEqual(self.service.update_all_layer_visibility(False), ["p"])
        self.assertEqual((condition.layer_visible, page.layer_visible), (False, False))
        self.assertEqual(set(self.aggregate.bid_layer_visibility.values()), {False})
        self.assertEqual(
            set(self.aggregate.bid_layer_visibility_by_name.values()), {False}
        )
        self.assertEqual({l.show for l in self.aggregate.bid_layers}, {False})
        self.assertEqual(self.service.update_all_layer_visibility(1), ["p"])
        self.assertEqual((condition.layer_visible, page.layer_visible), (True, True))
        self.assertEqual(set(self.aggregate.bid_layer_visibility.values()), {True})

    def test_adding_annotations_syncs_visibility_for_exactly_the_touched_layers(self):
        self.service.set_bid_layer_visibility(
            [
                BidLayer("hidden", "b1", "Annotation", False, 1),
                BidLayer("shown", "b1", "Other", True, 2),
            ]
        )
        on_hidden = BidAnnotation(
            uid="a", annotation_type="rect", layer_uid="hidden", visible=True
        )
        untouched = BidAnnotation(
            uid="b", annotation_type="rect", layer_uid="shown", visible=False
        )
        self.aggregate.set_annotations([untouched])
        self.service.add_annotations([on_hidden])
        self.assertIs(on_hidden.visible, False)
        self.assertIs(untouched.visible, False)
        unassigned = BidAnnotation(
            uid="c", annotation_type="rect", layer_uid=None, visible=True
        )
        self.service.add_annotations([unassigned])
        self.assertIs(unassigned.visible, False)
        self.assertIs(untouched.visible, False)


class ProjectDataServiceDatabaseHierarchyReplacementTests(unittest.TestCase):
    def setUp(self):
        self.cdn = {
            "7": CdnType(uid="7", name="Footings"),
            "8": CdnType(uid="8", name="Slabs"),
        }
        self.registered = []
        file_entry_ref = {}

        class FileManager:
            current_file_path = None

            def __init__(manager):
                manager.project_repository = SimpleNamespace(
                    active_file_path="C:/a.mdb",
                    get_cdn_types=lambda path: (
                        self_outer.cdn if path == "C:/a.mdb" else {}
                    ),
                )

            def register_loaded_hierarchy(manager, entry, cdn_types):
                self_outer.registered.append((entry, cdn_types))
                return self_outer.hierarchy

        self_outer = self
        self.aggregate = OstAggregate(FileManager())
        self.service = ProjectDataService(self.aggregate)
        self.ref = BidRef("C:/a.mdb", "b1")
        folder_page = HierarchyPageInfo(uid="p2", name="Two", sequence=2)
        info = HierarchyBidInfo(
            uid="b1",
            name="Fresh name",
            job_id="J-9",
            bid_no=42,
            bid_date="2026-02-03",
            notes="Fresh notes",
            status="Won",
            status_uid="s9",
            estimator="Ann",
            page_count=2,
            condition_count=5,
            measure_base=1,
            takeoff_increments=0.25,
            orig_bid_project_uid="op9",
            copy_from_bid_no=3,
            copy_timestamp="ts",
            folders={"f1": HierarchyFolderInfo(name="Folder", pages=[folder_page])},
            pages_without_folder=[HierarchyPageInfo(uid="p1", name="One", sequence=1)],
        )
        self.entry = HierarchyFileEntry(
            file_path="C:/a.mdb",
            bid_projects={"proj": HierarchyProjectInfo(name="P", bids=[info])},
        )
        self.hierarchy = HierarchyData(loaded_files=[self.entry])
        self.stale = Bid(
            uid="b1",
            name="Stale",
            bid_no=1,
            notes="old",
            job_id="old",
            status="Open",
            status_uid="s1",
            estimator="Bob",
            page_count=0,
            condition_count=1,
            measure_base=0,
            takeoff_increments=1.0,
            orig_bid_project_uid="op1",
            copy_from_bid_no=0,
            copy_timestamp=None,
        )
        self.aggregate.current_bid_ref = self.ref
        self.aggregate.current_bid = self.stale
        self.page1 = Page("p1", "One", sequence=1)
        self.page2 = Page("p2", "Two", sequence=2, folder_uid="f1")
        self.aggregate.set_pages({"p1": self.page1, "p2": self.page2})
        self.condition = Condition(
            uid="c",
            calc_type1=CALC_LINEAR_LENGTH,
            uom1=UOM_LINEAR_FEET,
            cdn_type_uid="7",
            cdn_type_name="Stale",
        )
        self.unknown_type = Condition(uid="d", cdn_type_uid="99", cdn_type_name="Old")
        self.no_type = Condition(uid="e", cdn_type_uid=None, cdn_type_name="Old")
        self.aggregate.bid_conditions = {
            "c": self.condition,
            "d": self.unknown_type,
            "e": self.no_type,
        }

    def test_refreshing_the_active_database_updates_the_loaded_bid_in_place_and_normalizes_units(
        self,
    ):
        self.service.replace_database_hierarchy(self.entry, self.cdn)
        self.assertEqual(self.registered, [(self.entry, self.cdn)])
        bid = self.stale
        self.assertIs(self.aggregate.current_bid, bid)
        self.assertEqual(
            (
                bid.name,
                bid.bid_no,
                bid.bid_date,
                bid.notes,
                bid.job_id,
                bid.status,
                bid.status_uid,
                bid.estimator,
                bid.condition_count,
                bid.measure_base,
                bid.takeoff_increments,
                bid.orig_bid_project_uid,
                bid.copy_from_bid_no,
                bid.copy_timestamp,
            ),
            (
                "Fresh name",
                42,
                "2026-02-03",
                "Fresh notes",
                "J-9",
                "Won",
                "s9",
                "Ann",
                5,
                1,
                0.25,
                "op9",
                3,
                "ts",
            ),
        )
        self.assertEqual(self.condition.uom1, UOM_M)
        self.assertEqual(
            (
                self.condition.cdn_type_name,
                self.unknown_type.cdn_type_name,
                self.no_type.cdn_type_name,
            ),
            ("Footings", "Unknown", "Unknown"),
        )
        self.assertEqual(self.aggregate.cdn_types, self.cdn)
        self.assertIs(self.aggregate.get_hierarchy_data(), self.hierarchy)
        self.assertEqual([p.uid for p in self.aggregate.projects], ["proj"])
        self.assertEqual(list(bid.folders), ["f1"])
        self.assertEqual([p.uid for p in bid.folders["f1"].pages], ["p2"])
        self.assertEqual([p.uid for p in bid.pages_without_folder], ["p1"])
        self.assertEqual(bid.page_count, 2)

    def test_the_measure_system_is_re_evaluated_each_refresh(self):
        self.entry.bid_projects["proj"].bids[0].measure_base = 0
        self.aggregate.bid_conditions["c"].uom1 = UOM_M
        self.service.replace_database_hierarchy(self.entry, self.cdn)
        self.assertEqual(self.stale.measure_base, 0)
        self.assertEqual(self.condition.uom1, UOM_LINEAR_FEET)

    def test_refreshing_another_database_leaves_the_active_bid_and_conditions_alone(
        self,
    ):
        other = HierarchyFileEntry(file_path="C:/other.mdb")
        self.hierarchy = HierarchyData(loaded_files=[other])
        self.service.replace_database_hierarchy(other, self.cdn)
        self.assertEqual(
            (self.stale.name, self.stale.measure_base, self.stale.condition_count),
            ("Stale", 0, 1),
        )
        self.assertEqual(
            (self.condition.cdn_type_name, self.condition.uom1),
            ("Stale", UOM_LINEAR_FEET),
        )
        self.assertEqual(
            (self.unknown_type.cdn_type_name, self.no_type.cdn_type_name),
            ("Old", "Old"),
        )
        self.assertIs(self.aggregate.get_hierarchy_data(), self.hierarchy)
        self.assertEqual(self.aggregate.projects, [])
        self.assertEqual(self.aggregate.cdn_types, self.cdn)

    def test_only_measure_base_1_selects_the_metric_system_on_refresh(self):
        for measure_base in (0, 2, -1):
            with self.subTest(measure_base=measure_base):
                self.entry.bid_projects["proj"].bids[0].measure_base = measure_base
                self.aggregate.bid_conditions["c"].uom1 = UOM_M
                self.service.replace_database_hierarchy(self.entry, self.cdn)
                self.assertEqual(self.stale.measure_base, measure_base)
                self.assertEqual(self.condition.uom1, UOM_LINEAR_FEET)

    def test_database_paths_are_compared_in_normalized_form(self):
        self.entry.file_path = "c:\\A.MDB"
        self.aggregate.current_bid_ref = BidRef("C:/a.mdb", "b1")
        self.service.replace_database_hierarchy(self.entry, self.cdn)
        self.assertEqual(self.condition.cdn_type_name, "Footings")

    def test_without_a_loaded_bid_or_without_the_bid_in_the_new_hierarchy_nothing_is_rewritten(
        self,
    ):
        self.aggregate.current_bid = None
        self.service.replace_database_hierarchy(self.entry, self.cdn)
        self.assertEqual(self.condition.cdn_type_name, "Footings")
        self.assertEqual(self.stale.name, "Stale")
        self.aggregate.current_bid = self.stale
        self.aggregate.current_bid_ref = BidRef("C:/a.mdb", "gone")
        self.service.replace_database_hierarchy(self.entry, self.cdn)
        self.assertEqual(self.stale.name, "Stale")
        self.aggregate.current_bid_ref = None
        self.condition.cdn_type_name = "Reset"
        self.service.replace_database_hierarchy(self.entry, self.cdn)
        self.assertEqual(
            (self.condition.cdn_type_name, self.stale.name), ("Reset", "Stale")
        )
        self.assertEqual([p.uid for p in self.aggregate.projects], ["proj"])


class ProjectDataServiceResidualContractTests(unittest.TestCase):
    def test_refreshing_another_database_never_rewrites_the_active_bid_from_a_same_uid_bid_elsewhere(
        self,
    ):
        setup = ProjectDataServiceDatabaseHierarchyReplacementTests(
            "test_refreshing_another_database_leaves_the_active_bid_and_conditions_alone"
        )
        setup.setUp()
        other = HierarchyFileEntry(file_path="C:/other.mdb")
        setup.hierarchy = HierarchyData(loaded_files=[setup.entry, other])
        setup.service.replace_database_hierarchy(other, setup.cdn)
        self.assertEqual((setup.stale.name, setup.stale.measure_base), ("Stale", 0))
        self.assertEqual(setup.condition.uom1, UOM_LINEAR_FEET)

    def test_refreshing_another_database_leaves_the_active_bid_alone_whichever_way_its_path_sorts(
        self,
    ):
        for other_path in ("C:/0.mdb", "C:/other.mdb"):
            with self.subTest(other_path=other_path):
                setup = ProjectDataServiceDatabaseHierarchyReplacementTests(
                    "test_refreshing_another_database_leaves_the_active_bid_and_conditions_alone"
                )
                setup.setUp()
                other = HierarchyFileEntry(file_path=other_path)
                setup.hierarchy = HierarchyData(loaded_files=[setup.entry, other])
                setup.service.replace_database_hierarchy(other, setup.cdn)
                self.assertEqual(
                    (
                        setup.stale.name,
                        setup.stale.measure_base,
                        setup.stale.condition_count,
                    ),
                    ("Stale", 0, 1),
                )
                self.assertEqual(
                    (setup.condition.cdn_type_name, setup.condition.uom1),
                    ("Stale", UOM_LINEAR_FEET),
                )
                self.assertEqual(
                    (setup.unknown_type.cdn_type_name, setup.no_type.cdn_type_name),
                    ("Old", "Old"),
                )

    def test_scale_changes_copy_both_scale_factors_to_the_hierarchy_records(self):
        setup = ProjectDataServicePageMetadataTests(
            "test_scales_rescale_geometry_overlay_and_metadata_for_exactly_the_selected_pages"
        )
        setup.setUp()
        setup.service.apply_page_scales(setup.ref, [setup.page], 2.0, 96.0)
        self.assertEqual(
            (setup.record.scale_factor1, setup.record.scale_factor2), (2.0, 96.0)
        )
        self.assertEqual(
            (setup.record2.scale_factor1, setup.record2.scale_factor2), (1.0, 1.0)
        )

    def test_replacing_layer_state_discards_entries_of_layers_that_no_longer_exist(
        self,
    ):
        service, aggregate = _real_service()
        service.set_bid_layer_visibility([BidLayer("old", "b", "Old name", False, 1)])
        self.assertIn("old", aggregate.bid_layer_visibility)
        service.set_bid_layer_visibility([BidLayer("new", "b", "New name", True, 1)])
        self.assertEqual(aggregate.bid_layer_visibility, {"new": True})
        self.assertEqual(aggregate.bid_layer_names_by_uid, {"new": "new name"})
        self.assertEqual(aggregate.bid_layer_visibility_by_name, {"new name": True})

    def test_a_named_layer_without_stored_visibility_counts_as_visible(self):
        service, aggregate = _real_service()
        aggregate.bid_layer_names_by_uid = {"u": "annotation"}
        aggregate.bid_layer_visibility = {}
        aggregate.bid_layer_visibility_by_name = {"annotation": False}
        self.assertIs(service.is_annotation_layer_visible(), True)

    def test_layer_toggles_update_each_layer_object_and_tolerate_a_missing_layer_list(
        self,
    ):
        service, aggregate = _real_service()
        service.set_bid_layer_visibility(
            [
                BidLayer("a", "b", "Annotation", True, 1),
                BidLayer("i", "b", "Image", True, 2),
            ]
        )
        service.update_layer_visibility("i", False)
        self.assertEqual(
            {layer.uid: layer.show for layer in aggregate.bid_layers},
            {"a": True, "i": False},
        )
        service.update_layer_visibility("i", True)
        self.assertEqual(
            {layer.uid: layer.show for layer in aggregate.bid_layers},
            {"a": True, "i": True},
        )
        service.update_all_layer_visibility(False)
        self.assertEqual({layer.show for layer in aggregate.bid_layers}, {False})
        aggregate.bid_layers = None
        service.update_layer_visibility("a", False)
        service.update_all_layer_visibility(True)
        aggregate.bid_layers = []
        service.update_layer_visibility("a", False)
        self.assertEqual(
            service.get_bid_layer_snapshot(),
            [
                BidLayer("a", "", "annotation", False, 0),
                BidLayer("i", "", "image", True, 1),
            ],
        )

    def test_layer_uid_text_none_is_not_confused_with_an_unassigned_condition_or_area(
        self,
    ):
        service, aggregate = _real_service()
        service.set_bid_layer_visibility([BidLayer("None", "b", "Weird", True, 1)])
        unassigned = Condition(uid="c", layer_uid=None, layer_visible=True)
        aggregate.bid_conditions = {"c": unassigned}
        service.update_layer_visibility("None", False)
        self.assertIs(unassigned.layer_visible, True)
        aggregate.current_bid_ref = BidRef("C:/a.mdb", "b1")
        aggregate.page_area_selections = {"p": None}
        takeoff = Takeoff(uid="t", condition_uid="c", area_uid=None)
        aggregate.bid_takeoffs = [takeoff]
        service.replace_bid_areas_after_local_save(
            aggregate.current_bid_ref, [], ["None"]
        )
        self.assertIsNone(takeoff.area_uid)
        self.assertEqual(aggregate.page_area_selections, {"p": None})

    def test_reassigning_two_takeoffs_of_one_page_reports_that_page_once(self):
        service, aggregate = _real_service()
        aggregate.bid_conditions = {
            "c1": Condition(uid="c1", condition_type=Condition.TYPE_LINEAR),
            "c2": Condition(uid="c2", condition_type=Condition.TYPE_LINEAR),
        }
        t1 = Takeoff(uid="t1", condition_uid="c1", page_uid="p1")
        t2 = Takeoff(uid="t2", condition_uid="c1", page_uid="p1")
        t3 = Takeoff(uid="t3", condition_uid="c1", page_uid="p2")
        aggregate.set_pages(
            {
                "p1": Page("p1", "One", takeoffs=[t1, t2]),
                "p2": Page("p2", "Two", takeoffs=[t3]),
            }
        )
        aggregate.bid_takeoffs = [t1, t2, t3]
        self.assertEqual(
            service.update_takeoffs_condition(["t1", "t2", "t3"], "c2"), ["p1", "p2"]
        )
        self.assertEqual([t.condition_uid for t in (t1, t2, t3)], ["c2", "c2", "c2"])
