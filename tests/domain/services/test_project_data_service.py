from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
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
