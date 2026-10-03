"""Direct tests for AnnotationWriteCoordinator.
Real objects: ProjectDataService on a real OstAggregate (the model the coordinator
projects into), the real EventBus (it builds AnnotationsChangedEvent from the
published payload, so a wrong key fails loudly) and the real UndoRedoService where
history ownership matters. Explicit fakes: the annotation write service (records
each call with the real keyword names and returns configured results) and an undo
recorder. No SQL Server or Access database is involved; SQL completion projection
is exercised through the coordinator's public project_* entry points and through
the injected ``execute_paste`` callable.
"""

import inspect
import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PlanItemsPastePayload,
)
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    annotation_resource_id,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.paste_ref_remap_dto import PasteRefRemap
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.annotation_write_service import (
    AnnotationWriteService,
)
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.file_manager_service import FileManager
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.services.annotation_history import (
    AnnotationHistoryBinding,
    AnnotationHistoryDependencyError,
)
from ost_visualizer.presentation.services.annotation_write_coordinator import (
    AnnotationWriteCoordinator,
)
from ost_visualizer.presentation.services.undo_redo_service import (
    AnnotationHistoryTarget,
    UndoRedoService,
)

BID = BidRef("bid.mdb", "7")
DB = "bid.mdb"


class _WriteService:
    """Fake of the AnnotationWriteService surface the coordinator drives.
    Parameter names and defaults mirror the real service exactly (checked by
    AnnotationWriteServiceFakeContractTests), so a renamed or dropped keyword
    fails instead of being silently accepted.
    """

    def __init__(self):
        self.calls = []
        self.save_result = True
        self.delete_result = True
        self.insert_result = []

    def save_annotation_positions(
        self, db_path, positions, publish_database_refreshed_after_write=True
    ):
        self.calls.append(
            (
                "positions",
                db_path,
                positions,
                publish_database_refreshed_after_write,
            )
        )
        return self.save_result

    def save_annotation_text_properties(
        self, db_path, updates, publish_database_refreshed_after_write=True
    ):
        self.calls.append(
            (
                "text",
                db_path,
                updates,
                publish_database_refreshed_after_write,
            )
        )
        return self.save_result

    def save_annotation_styles(
        self, db_path, updates, publish_database_refreshed_after_write=True
    ):
        self.calls.append(
            (
                "styles",
                db_path,
                updates,
                publish_database_refreshed_after_write,
            )
        )
        return self.save_result

    def insert_annotations(
        self,
        db_path,
        bid_uid,
        specs,
        ref_remap=None,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(
            (
                "insert",
                db_path,
                bid_uid,
                specs,
                ref_remap,
                publish_database_refreshed_after_write,
            )
        )
        return self.insert_result

    def delete_annotations(
        self, db_path, annotations, publish_database_refreshed_after_write=True
    ):
        self.calls.append(
            (
                "delete",
                db_path,
                annotations,
                publish_database_refreshed_after_write,
            )
        )
        return self.delete_result


class _Undo:
    """Records what a history binding asks the undo service to do."""

    def __init__(self):
        self.suspend_calls = []
        self.rebind_calls = []
        self.suspend_result = ("suspended-marker",)

    def suspend_deleted_annotations(self, bid_ref, deleted):
        self.suspend_calls.append((bid_ref, deleted))
        return self.suspend_result

    def rebind_restored_annotations(self, bid_ref, restored, targets):
        self.rebind_calls.append((bid_ref, dict(restored), targets))


class _Context:
    def __init__(self, *, annotation_layer="L-ann"):
        self.model = OstAggregate(FileManager(None))
        self.data = ProjectDataService(self.model)
        self.model.current_bid_ref = BID
        self.model.set_pages(
            {
                "p1": Page("p1", "One"),
                "p2": Page("p2", "Two", scale_factor1=2.0, scale_factor2=4.0),
                "p3": Page("p3", "Three", scale_factor1=0.0, scale_factor2=0.0),
            }
        )
        if annotation_layer:
            self.model.bid_layers = [
                BidLayer(annotation_layer, "7", "Annotation", True, 1)
            ]
        self.bus = EventBus()
        self.events = []
        self.bus.subscribe(
            AppEvents.ANNOTATIONS_CHANGED, lambda **payload: self.events.append(payload)
        )
        self.write = _WriteService()
        self.coordinator = AnnotationWriteCoordinator(self.write, self.data, self.bus)

    def seed(self, *annotations):
        self.model.set_annotations(list(annotations))
        return annotations

    def stored(self):
        return {
            (item.uid, item.annotation_type): item
            for item in self.model.get_all_annotations()
        }


def _rect(uid, page="p1", position=None, **properties):
    return BidAnnotation(
        uid=uid,
        annotation_type="rect",
        page_uid=page,
        layer_uid="L-ann",
        position=list(position if position is not None else [0, 0, 10, 10]),
        properties=dict(properties),
    )


def _view(uid, page="p1", name="View"):
    return BidAnnotation(
        uid=uid,
        annotation_type="namedview",
        page_uid=page,
        position=[0, 0, 10, 10],
        properties={"Text": name},
    )


def _link(uid, target, page="p1"):
    return BidAnnotation(
        uid=uid,
        annotation_type="hotlink",
        page_uid=page,
        position=[5, 5],
        properties={"BidPageViewUID": target},
    )


def _spec(page="p1", kind="rect", position=None, **kwargs):
    return InsertAnnotationSpec(
        page_uid=page,
        annotation_type=kind,
        position=list(position if position is not None else [1, 2, 3, 4]),
        color=kwargs.pop("color", "#00FF00"),
        width=kwargs.pop("width", 2.5),
        properties=kwargs.pop("properties", {}),
        layer_uid=kwargs.pop("layer_uid", ""),
    )


def _event(page_uid, page_uids, uids, types):
    return {
        "page_uid": page_uid,
        "page_uids": page_uids,
        "annotation_uids": uids,
        "annotation_types": types,
    }


class AnnotationWriteServiceFakeContractTests(unittest.TestCase):
    """The explicit fakes must not be looser than the real collaborators."""

    def assert_same_parameters(self, real, fake):
        real_parameters = [
            (p.name, p.default, p.kind)
            for p in list(inspect.signature(real).parameters.values())[1:]
        ]
        fake_parameters = [
            (p.name, p.default, p.kind)
            for p in list(inspect.signature(fake).parameters.values())[1:]
        ]
        self.assertEqual(fake_parameters, real_parameters)

    def test_fake_write_service_signatures_match_the_real_service(self):
        for name in (
            "save_annotation_positions",
            "save_annotation_text_properties",
            "save_annotation_styles",
            "insert_annotations",
            "delete_annotations",
        ):
            with self.subTest(name):
                self.assert_same_parameters(
                    getattr(AnnotationWriteService, name), getattr(_WriteService, name)
                )

    def test_fake_undo_signatures_match_the_real_undo_service(self):
        for name in ("suspend_deleted_annotations", "rebind_restored_annotations"):
            with self.subTest(name):
                self.assert_same_parameters(
                    getattr(UndoRedoService, name), getattr(_Undo, name)
                )


class AnnotationWriteCoordinatorSaveTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _Context()

    def test_save_positions_writes_then_projects_and_publishes_once_per_batch(self):
        self.ctx.seed(_rect("a1", "p1"), _rect("a2", "p2"), _rect("a3", "p1"))
        positions = [("a1", "rect", [1, 2, 3, 4]), ("a2", "rect", [5, 6, 7, 8])]
        self.assertTrue(self.ctx.coordinator.save_positions(DB, positions))
        self.assertEqual(self.ctx.write.calls, [("positions", DB, positions, False)])
        stored = self.ctx.stored()
        self.assertEqual(stored[("a1", "rect")].position, [1, 2, 3, 4])
        self.assertEqual(stored[("a2", "rect")].position, [5, 6, 7, 8])
        self.assertEqual(stored[("a3", "rect")].position, [0, 0, 10, 10])
        self.assertEqual(
            self.ctx.events,
            [_event("", ["p1", "p2"], ["a1", "a2"], ["rect", "rect"])],
        )

    def test_single_page_batch_publishes_page_uid_and_no_page_list(self):
        self.ctx.seed(_rect("a1", "p2"))
        self.assertTrue(
            self.ctx.coordinator.save_positions(DB, [("a1", "rect", [9, 9, 9, 9])])
        )
        self.assertEqual(self.ctx.events, [_event("p2", [], ["a1"], ["rect"])])

    def test_failed_write_leaves_projection_untouched_and_publishes_nothing(self):
        self.ctx.seed(_rect("a1", text="before"))
        self.ctx.write.save_result = False
        calls = {
            "positions": lambda: self.ctx.coordinator.save_positions(
                DB, [("a1", "rect", [7, 7, 7, 7])]
            ),
            "text": lambda: self.ctx.coordinator.save_text_properties(
                DB, [("a1", "rect", {"Text": "after"})]
            ),
            "styles": lambda: self.ctx.coordinator.save_styles(
                DB, [("a1", "rect", {"Color": "#123456", "Width": 9})]
            ),
        }
        for name, call in calls.items():
            with self.subTest(name):
                self.assertIs(call(), False)
        item = self.ctx.stored()[("a1", "rect")]
        self.assertEqual(item.position, [0, 0, 10, 10])
        self.assertEqual(item.properties, {"text": "before"})
        self.assertEqual((item.color, item.width), ("#FF0000", 1.0))
        self.assertEqual(self.ctx.events, [])
        self.assertEqual([call[0] for call in self.ctx.write.calls], list(calls))

    def test_empty_batches_succeed_without_writing_projecting_or_publishing(self):
        self.ctx.seed(_rect("a1"))
        coordinator = self.ctx.coordinator
        self.assertIs(coordinator.save_positions(DB, []), True)
        self.assertIs(coordinator.save_text_properties(DB, []), True)
        self.assertIs(coordinator.save_styles(DB, []), True)
        self.assertIs(coordinator.delete_annotations(DB, [], []), True)
        self.assertIs(coordinator.delete_saved_annotations(DB, []), True)
        self.assertEqual(
            coordinator.insert_saved_annotations(BID, [], execute_paste=None), []
        )
        self.assertEqual(self.ctx.write.calls, [])
        self.assertEqual(self.ctx.events, [])
        self.assertEqual(list(self.ctx.stored()), [("a1", "rect")])

    def test_save_text_properties_updates_projection_and_publishes(self):
        self.ctx.seed(_rect("a1", "p1", Text="old", Other="kept"))
        updates = [("a1", "rect", {"Text": "new"})]
        self.assertTrue(self.ctx.coordinator.save_text_properties(DB, updates))
        self.assertEqual(self.ctx.write.calls, [("text", DB, updates, False)])
        self.assertEqual(
            self.ctx.stored()[("a1", "rect")].properties,
            {"Text": "new", "Other": "kept"},
        )
        self.assertEqual(self.ctx.events, [_event("p1", [], ["a1"], ["rect"])])

    def test_named_view_rename_follows_only_named_view_text_updates(self):
        # A Text annotation and a Named View deliberately share the uid "5".
        view = _view("5", "p1", "Old name")
        text = BidAnnotation(
            uid="5",
            annotation_type="text",
            page_uid="p2",
            properties={"Text": "text body"},
        )
        self.ctx.seed(view, text, _view("6", "p1", "Untouched"))
        coordinator = self.ctx.coordinator
        # A text update with the same uid must not rename the Named View.
        self.assertTrue(
            coordinator.save_text_properties(DB, [("5", "text", {"Text": "edited"})])
        )
        stored = self.ctx.stored()
        self.assertEqual(stored[("5", "text")].properties["Text"], "edited")
        self.assertEqual(stored[("5", "namedview")].properties["Text"], "Old name")
        # A Named View update that carries no Text leaves the name alone.
        self.assertTrue(
            coordinator.save_text_properties(DB, [("5", "namedview", {"Other": 1})])
        )
        self.assertEqual(
            self.ctx.stored()[("5", "namedview")].properties["Text"], "Old name"
        )
        # A Named View Text update renames that view only; None becomes "".
        self.assertTrue(
            coordinator.save_text_properties(
                DB,
                [
                    ("5", "namedview", {"Text": "Renamed"}),
                    ("6", "namedview", {"Text": None}),
                ],
            )
        )
        stored = self.ctx.stored()
        self.assertEqual(stored[("5", "namedview")].properties["Text"], "Renamed")
        self.assertEqual(stored[("6", "namedview")].properties["Text"], "")
        self.assertEqual(stored[("5", "text")].properties["Text"], "edited")

    def test_failed_text_write_never_renames_named_view(self):
        self.ctx.seed(_view("5", "p1", "Old name"))
        self.ctx.write.save_result = False
        self.assertFalse(
            self.ctx.coordinator.save_text_properties(
                DB, [("5", "namedview", {"Text": "Renamed"})]
            )
        )
        self.assertEqual(
            self.ctx.stored()[("5", "namedview")].properties["Text"], "Old name"
        )

    def test_save_styles_updates_color_and_width_and_publishes(self):
        self.ctx.seed(_rect("a1", "p1"), _rect("a2", "p2"))
        updates = [
            ("a1", "rect", {"Color": "#0000FF", "Width": 3}),
            ("a2", "rect", {"Color": "#00FF00"}),
        ]
        self.assertTrue(self.ctx.coordinator.save_styles(DB, updates))
        self.assertEqual(self.ctx.write.calls, [("styles", DB, updates, False)])
        stored = self.ctx.stored()
        self.assertEqual(
            (stored[("a1", "rect")].color, stored[("a1", "rect")].width),
            ("#0000FF", 3.0),
        )
        self.assertEqual(
            (stored[("a2", "rect")].color, stored[("a2", "rect")].width),
            ("#00FF00", 1.0),
        )
        self.assertEqual(
            self.ctx.events,
            [_event("", ["p1", "p2"], ["a1", "a2"], ["rect", "rect"])],
        )

    def test_projection_of_an_annotation_missing_from_the_model_publishes_nothing(
        self,
    ):
        # The write succeeded but this window never had the annotation: no page
        # is affected, so no event is published (and nothing is projected).
        self.ctx.seed(_rect("a1"))
        self.assertTrue(
            self.ctx.coordinator.save_positions(DB, [("ghost", "rect", [1, 1, 2, 2])])
        )
        self.assertEqual(self.ctx.events, [])
        self.assertEqual(self.ctx.stored()[("a1", "rect")].position, [0, 0, 10, 10])


class AnnotationWriteCoordinatorPublishTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _Context()

    def test_pages_are_deduplicated_in_first_seen_order_and_blanks_dropped(self):
        self.ctx.coordinator.publish_annotations_changed_for_pages(
            ["p2", "", "p1", "p2", None], ["a", "b"], ["rect", "text"]
        )
        self.assertEqual(
            self.ctx.events, [_event("", ["p2", "p1"], ["a", "b"], ["rect", "text"])]
        )

    def test_no_affected_page_publishes_nothing(self):
        self.ctx.coordinator.publish_annotations_changed_for_pages([], ["a"], ["rect"])
        self.ctx.coordinator.publish_annotations_changed_for_pages(
            ["", None], ["a"], ["rect"]
        )
        self.assertEqual(self.ctx.events, [])

    def test_payload_lists_are_copies_and_types_are_stringified(self):
        uids = ["a"]
        types = ["rect"]
        self.ctx.coordinator.publish_annotations_changed_for_pages(["p1"], uids, types)
        uids.append("late")
        types.append("late")
        self.assertEqual(self.ctx.events, [_event("p1", [], ["a"], ["rect"])])


class AnnotationWriteCoordinatorInsertTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _Context()

    def test_insert_assigns_default_layer_writes_and_projects_exact_annotations(self):
        specs = [
            _spec("p1", "rect", [1, 2, 3, 4], properties={"Text": "x"}),
            _spec(
                "p2",
                "namedview",
                [10, 20, 30, 40],
                width=None,
                properties={"Text": "V"},
                layer_uid="L-other",
            ),
        ]
        self.ctx.write.insert_result = ["n1", "n2"]
        result = self.ctx.coordinator.insert_annotations(BID, specs)
        self.assertEqual(result, ["n1", "n2"])
        self.assertEqual(
            self.ctx.write.calls, [("insert", DB, "7", specs, None, False)]
        )
        self.assertIs(self.ctx.write.calls[0][3], specs)
        self.assertEqual([spec.layer_uid for spec in specs], ["L-ann", "L-other"])
        stored = self.ctx.stored()
        first, second = stored[("n1", "rect")], stored[("n2", "namedview")]
        self.assertEqual(
            (
                first.uid,
                first.page_uid,
                first.layer_uid,
                first.position,
                first.color,
                first.width,
                first.properties,
                first.visible,
            ),
            ("n1", "p1", "L-ann", [1, 2, 3, 4], "#00FF00", 2.5, {"Text": "x"}, True),
        )
        self.assertEqual(
            (second.page_uid, second.layer_uid, second.width, second.properties),
            ("p2", "L-other", 0.0, {"Text": "V"}),
        )
        # Named View geometry is normalized to the canonical 9-value outline.
        self.assertEqual(
            second.position,
            [30.0, 40.0, 10.0, 20.0, 30.0, 20.0, 10.0, 40.0, 0.0],
        )
        self.assertEqual(
            self.ctx.events,
            [_event("", ["p1", "p2"], ["n1", "n2"], ["rect", "namedview"])],
        )

    def test_projection_does_not_alias_spec_geometry_or_properties(self):
        spec = _spec("p1", "rect", [1, 2, 3, 4], properties={"Text": "x"})
        self.ctx.write.insert_result = ["n1"]
        self.ctx.coordinator.insert_annotations(BID, [spec])
        spec.position.append(99)
        spec.properties["Text"] = "mutated"
        item = self.ctx.stored()[("n1", "rect")]
        self.assertEqual(item.position, [1, 2, 3, 4])
        self.assertEqual(item.properties, {"Text": "x"})

    def test_ref_remap_reaches_the_write_and_remaps_projected_properties(self):
        remap = PasteRefRemap(
            takeoff_uids={"t-old": "t-new"}, namedview_uids={"v-old": "v-new"}
        )
        spec = _spec(
            "p1",
            "hotlink",
            [5, 5],
            properties={"BidPageViewUID": "v-old", "BidTakeoffFromUID": "t-old"},
        )
        self.ctx.write.insert_result = ["n1"]
        self.ctx.coordinator.insert_annotations(BID, [spec], ref_remap=remap)
        self.assertIs(self.ctx.write.calls[0][4], remap)
        self.assertEqual(
            self.ctx.stored()[("n1", "hotlink")].properties,
            {"BidPageViewUID": "v-new", "BidTakeoffFromUID": "t-new"},
        )
        # The retained spec keeps its original (pre-remap) references.
        self.assertEqual(spec.properties["BidPageViewUID"], "v-old")

    def test_empty_write_result_projects_nothing(self):
        self.ctx.write.insert_result = []
        self.assertEqual(self.ctx.coordinator.insert_annotations(BID, [_spec()]), [])
        self.assertEqual(self.ctx.stored(), {})
        self.assertEqual(self.ctx.events, [])

    def test_incomplete_identity_batch_is_rejected_before_projection(self):
        self.ctx.write.insert_result = ["n1"]
        with self.assertRaisesRegex(
            ValueError,
            "Annotation insert returned 1 identities for 2 requested annotations",
        ):
            self.ctx.coordinator.insert_annotations(BID, [_spec("p1"), _spec("p2")])
        self.assertEqual(self.ctx.stored(), {})
        self.assertEqual(self.ctx.events, [])

    def test_default_layer_is_not_resolved_when_every_spec_has_a_layer(self):
        # An unrelated Bid would make the data service refuse the layer lookup, so
        # a successful insert proves the lookup is skipped entirely.
        other = BidRef(DB, "99")
        specs = [_spec(layer_uid="L-explicit")]
        self.ctx.write.insert_result = ["n1"]
        self.ctx.coordinator.apply_default_annotation_layer(other, specs)
        self.assertEqual(specs[0].layer_uid, "L-explicit")

    def test_default_layer_lookup_for_another_bid_fails_before_any_write(self):
        with self.assertRaisesRegex(ValueError, "current Bid context"):
            self.ctx.coordinator.insert_annotations(BidRef(DB, "99"), [_spec()])
        self.assertEqual(self.ctx.write.calls, [])
        self.assertEqual(self.ctx.events, [])

    def test_missing_annotation_layer_leaves_specs_unlayered(self):
        ctx = _Context(annotation_layer=None)
        spec = _spec()
        ctx.write.insert_result = ["n1"]
        ctx.coordinator.insert_annotations(BID, [spec])
        self.assertEqual(spec.layer_uid, "")
        self.assertEqual(ctx.stored()[("n1", "rect")].layer_uid, "")

    def test_unlayered_spec_projects_an_empty_layer_never_the_text_none(self):
        ctx = _Context(annotation_layer=None)
        spec = _spec()
        spec.layer_uid = None
        ctx.write.insert_result = ["n1"]
        ctx.coordinator.insert_annotations(BID, [spec])
        self.assertEqual(ctx.stored()[("n1", "rect")].layer_uid, "")

    def test_projected_insert_follows_the_layer_visibility_of_its_layer(self):
        self.ctx.model.bid_layer_names_by_uid = {"L-ann": "Annotation"}
        self.ctx.model.bid_layer_visibility = {"L-ann": False}
        self.ctx.write.insert_result = ["n1", "n2"]
        self.ctx.coordinator.insert_annotations(
            BID, [_spec(layer_uid="L-ann"), _spec(layer_uid="L-other")]
        )
        stored = self.ctx.stored()
        self.assertFalse(stored[("n1", "rect")].visible)
        self.assertTrue(stored[("n2", "rect")].visible)

    def test_only_unlayered_specs_receive_the_default_layer(self):
        specs = [_spec(layer_uid=""), _spec(layer_uid="L-keep"), _spec(layer_uid="")]
        self.ctx.coordinator.apply_default_annotation_layer(BID, specs)
        self.assertEqual([s.layer_uid for s in specs], ["L-ann", "L-keep", "L-ann"])


class AnnotationWriteCoordinatorDeleteTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _Context()

    def test_delete_annotations_keys_by_uid_and_spec_type_then_projects(self):
        self.ctx.seed(_rect("a1", "p1"), _view("a2", "p2"), _rect("a3", "p1"))
        specs = [_spec("p1", "rect"), _spec("p2", "namedview")]
        self.assertTrue(
            self.ctx.coordinator.delete_annotations(DB, ["a1", "a2"], specs)
        )
        self.assertEqual(
            self.ctx.write.calls,
            [("delete", DB, [("a1", "rect"), ("a2", "namedview")], False)],
        )
        self.assertEqual(list(self.ctx.stored()), [("a3", "rect")])
        self.assertEqual(
            self.ctx.events,
            [_event("", ["p1", "p2"], ["a1", "a2"], ["rect", "namedview"])],
        )

    def test_failed_delete_keeps_annotations_and_publishes_nothing(self):
        self.ctx.seed(_rect("a1"))
        self.ctx.write.delete_result = False
        self.assertIs(
            self.ctx.coordinator.delete_annotations(DB, ["a1"], [_spec(kind="rect")]),
            False,
        )
        self.assertIs(
            self.ctx.coordinator.delete_saved_annotations(DB, [_rect("a1")]), False
        )
        self.assertEqual(list(self.ctx.stored()), [("a1", "rect")])
        self.assertEqual(self.ctx.events, [])

    def test_delete_with_fewer_specs_than_uids_is_refused_before_any_write(self):
        self.ctx.seed(_rect("a1"), _rect("a2"))
        with self.assertRaises(IndexError):
            self.ctx.coordinator.delete_annotations(
                DB, ["a1", "a2"], [_spec(kind="rect")]
            )
        self.assertEqual(self.ctx.write.calls, [])
        self.assertEqual(len(self.ctx.stored()), 2)

    def test_delete_saved_annotations_uses_each_annotations_own_type(self):
        saved = [_rect("a1", "p1"), _view("a2", "p2")]
        self.ctx.seed(*saved, _rect("a3", "p1"))
        self.assertTrue(self.ctx.coordinator.delete_saved_annotations(DB, saved))
        self.assertEqual(
            self.ctx.write.calls,
            [("delete", DB, [("a1", "rect"), ("a2", "namedview")], False)],
        )
        self.assertEqual(list(self.ctx.stored()), [("a3", "rect")])
        self.assertEqual(
            self.ctx.events,
            [_event("", ["p1", "p2"], ["a1", "a2"], ["rect", "namedview"])],
        )

    def test_delete_of_an_unprojected_annotation_reports_success_without_event(self):
        self.ctx.seed(_rect("a1"))
        self.assertTrue(
            self.ctx.coordinator.delete_annotations(DB, ["ghost"], [_spec(kind="rect")])
        )
        self.assertEqual(self.ctx.events, [])
        self.assertEqual(list(self.ctx.stored()), [("a1", "rect")])


class AnnotationWriteCoordinatorProjectionTests(unittest.TestCase):
    """The SQL completion projection entry points (no write is performed)."""

    def setUp(self):
        self.ctx = _Context()

    def test_project_inserted_adds_model_annotations_and_publishes(self):
        specs = [
            _spec("p1", "rect", properties={"Text": "a"}, layer_uid="L-ann"),
            _spec("p2", "text", [4, 4, 8, 8], properties={"Text": "b"}),
        ]
        self.ctx.coordinator.project_inserted_annotations(["u1", "u2"], specs)
        stored = self.ctx.stored()
        self.assertEqual(sorted(stored), [("u1", "rect"), ("u2", "text")])
        self.assertEqual(stored[("u2", "text")].page_uid, "p2")
        self.assertEqual(stored[("u2", "text")].layer_uid, "")
        self.assertEqual(
            self.ctx.events,
            [_event("", ["p1", "p2"], ["u1", "u2"], ["rect", "text"])],
        )
        self.assertEqual(self.ctx.write.calls, [])

    def test_project_inserted_with_no_uids_is_a_no_op(self):
        self.ctx.coordinator.project_inserted_annotations([], [_spec()])
        self.assertEqual(self.ctx.stored(), {})
        self.assertEqual(self.ctx.events, [])

    def test_project_inserted_rejects_a_partial_identity_map(self):
        with self.assertRaisesRegex(ValueError, "returned 1 identities for 2"):
            self.ctx.coordinator.project_inserted_annotations(
                ["u1"], [_spec(), _spec()]
            )
        self.assertEqual(self.ctx.stored(), {})
        self.assertEqual(self.ctx.events, [])

    def test_duplicate_completion_is_idempotent_for_the_model(self):
        spec = _spec("p1", "rect", properties={"Text": "a"})
        self.ctx.coordinator.project_inserted_annotations(["u1"], [spec])
        first = self.ctx.stored()[("u1", "rect")]
        self.ctx.coordinator.project_inserted_annotations(["u1"], [spec])
        self.assertEqual(len(self.ctx.model.get_all_annotations()), 1)
        self.assertIsNot(self.ctx.stored()[("u1", "rect")], first)
        self.assertEqual(len(self.ctx.events), 2)

    def test_project_inserted_remaps_references_for_restored_named_views(self):
        remap = PasteRefRemap(namedview_uids={"old-view": "new-view"})
        spec = _spec("p1", "hotlink", [5, 5], properties={"BidPageViewUID": "old-view"})
        self.ctx.coordinator.project_inserted_annotations(
            ["new-link"], [spec], ref_remap=remap
        )
        self.assertEqual(
            self.ctx.stored()[("new-link", "hotlink")].properties,
            {"BidPageViewUID": "new-view"},
        )

    def test_project_deleted_removes_keys_and_merges_extra_pages_in_order(self):
        self.ctx.seed(_rect("a1", "p1"), _rect("a2", "p2"), _rect("a3", "p3"))
        self.ctx.coordinator.project_deleted_annotations(
            [("a1", "rect"), ("a2", "rect")], page_uids=["p3", "p1", ""]
        )
        self.assertEqual(list(self.ctx.stored()), [("a3", "rect")])
        self.assertEqual(
            self.ctx.events,
            [_event("", ["p1", "p2", "p3"], ["a1", "a2"], ["rect", "rect"])],
        )

    def test_project_deleted_publishes_for_pages_even_if_already_removed(self):
        self.ctx.coordinator.project_deleted_annotations(
            [("gone", "rect")], page_uids=["p2"]
        )
        self.assertEqual(self.ctx.events, [_event("p2", [], ["gone"], ["rect"])])

    def test_project_deleted_with_no_keys_is_silent_even_if_pages_are_supplied(self):
        self.ctx.coordinator.project_deleted_annotations([], page_uids=["p1"])
        self.assertEqual(self.ctx.events, [])

    def test_project_deleted_without_keys_or_pages_is_silent(self):
        self.ctx.seed(_rect("a1"))
        self.ctx.coordinator.project_deleted_annotations([])
        self.ctx.coordinator.project_deleted_annotations([("gone", "rect")])
        self.assertEqual(self.ctx.events, [])
        self.assertEqual(list(self.ctx.stored()), [("a1", "rect")])


class AnnotationWriteCoordinatorInsertSavedTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _Context()
        self.requests = []

    def committed(self, mapping, *, status=MutationOutcomeStatus.COMMITTED):
        return MutationExecutionResult(
            outcome_status=status,
            authoritative_result=AuthoritativeMutationResult(
                created_uid_maps=(("annotations", tuple(mapping)),)
            ),
        )

    def execute(self, result):
        def execute_paste(file_path, payload, **kwargs):
            self.requests.append((file_path, payload, kwargs))
            return result

        return execute_paste

    def test_restore_submits_exact_payload_and_projects_authoritative_identities(self):
        view = _view("view", "p1", "Kept view")
        link = _link("link", "view")
        external = _link("ext", "outside")
        saved = [view, link, external]
        result = self.committed(
            [
                ("namedview/view", "view-2"),
                ("hotlink/link", "link-2"),
                ("hotlink/ext", "ext-2"),
            ]
        )
        restored = self.ctx.coordinator.insert_saved_annotations(
            BID, saved, execute_paste=self.execute(result)
        )
        ((file_path, payload, kwargs),) = self.requests
        self.assertEqual(file_path, DB)
        self.assertEqual(kwargs, {"publish_database_refreshed_after_write": False})
        self.assertIsInstance(payload, PlanItemsPastePayload)
        self.assertEqual(
            (payload.source_bid_uid, payload.destination_bid_uid), ("7", "7")
        )
        self.assertEqual(
            payload.annotation_source_uids,
            ("namedview/view", "hotlink/link", "hotlink/ext"),
        )
        self.assertEqual(
            [
                (s.page_uid, s.annotation_type, s.layer_uid)
                for s in payload.annotation_specs
            ],
            [
                ("p1", "namedview", "L-ann"),
                ("p1", "hotlink", "L-ann"),
                ("p1", "hotlink", "L-ann"),
            ],
        )
        # The batch's own Named View is remapped; the outside reference is kept.
        self.assertEqual(
            [(a.uid, a.annotation_type, dict(a.properties)) for a in restored],
            [
                ("view-2", "namedview", {"Text": "Kept view"}),
                ("link-2", "hotlink", {"BidPageViewUID": "view-2"}),
                ("ext-2", "hotlink", {"BidPageViewUID": "outside"}),
            ],
        )
        self.assertEqual(
            sorted(self.ctx.stored()),
            [("ext-2", "hotlink"), ("link-2", "hotlink"), ("view-2", "namedview")],
        )
        self.assertEqual(
            self.ctx.stored()[("link-2", "hotlink")].properties,
            {"BidPageViewUID": "view-2"},
        )
        self.assertEqual(
            self.ctx.events,
            [
                _event(
                    "p1",
                    [],
                    ["view-2", "link-2", "ext-2"],
                    ["namedview", "hotlink", "hotlink"],
                )
            ],
        )
        # The saved snapshots themselves are not rewritten.
        self.assertEqual(link.properties, {"BidPageViewUID": "view"})
        self.assertEqual(self.ctx.write.calls, [])

    def test_unavailable_outcomes_return_nothing_and_project_nothing(self):
        for status in MutationOutcomeStatus:
            if status == MutationOutcomeStatus.COMMITTED:
                continue
            with self.subTest(status=status):
                self.requests.clear()
                result = MutationExecutionResult(outcome_status=status)
                self.assertEqual(
                    self.ctx.coordinator.insert_saved_annotations(
                        BID, [_rect("a1")], execute_paste=self.execute(result)
                    ),
                    [],
                )
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(self.ctx.stored(), {})
                self.assertEqual(self.ctx.events, [])

    def test_committed_result_without_identity_map_is_an_error(self):
        result = MutationExecutionResult(outcome_status=MutationOutcomeStatus.COMMITTED)
        with self.assertRaisesRegex(ValueError, "authoritative identity map"):
            self.ctx.coordinator.insert_saved_annotations(
                BID, [_rect("a1")], execute_paste=self.execute(result)
            )
        self.assertEqual(self.ctx.stored(), {})
        self.assertEqual(self.ctx.events, [])

    def test_identity_map_missing_a_restored_annotation_projects_nothing(self):
        result = self.committed([("rect/a1", "a1-2")])
        with self.assertRaises((KeyError, ValueError)):
            self.ctx.coordinator.insert_saved_annotations(
                BID,
                [_rect("a1"), _rect("a2")],
                execute_paste=self.execute(result),
            )
        self.assertEqual(self.ctx.stored(), {})
        self.assertEqual(self.ctx.events, [])

    def test_restore_does_not_resolve_a_layer_for_already_layered_annotations(self):
        saved = [_rect("a1")]
        result = self.committed([("rect/a1", "a1-2")])
        self.ctx.coordinator.insert_saved_annotations(
            BidRef(DB, "7"), saved, execute_paste=self.execute(result)
        )
        payload = self.requests[0][1]
        self.assertEqual(payload.annotation_specs[0].layer_uid, "L-ann")
        self.assertEqual(saved[0].layer_uid, "L-ann")


class AnnotationWriteCoordinatorSpecHelperTests(unittest.TestCase):
    def test_specs_from_saved_copy_every_field_and_detach_containers(self):
        saved = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            layer_uid="L1",
            position=[1, 2, 3, 4],
            color="#112233",
            width=4.5,
            properties={"Text": "hello"},
            visible=False,
        )
        (spec,) = AnnotationWriteCoordinator.annotation_specs_from_saved([saved])
        self.assertEqual(
            spec,
            InsertAnnotationSpec(
                "p1", "text", [1, 2, 3, 4], "#112233", 4.5, {"Text": "hello"}, "L1"
            ),
        )
        spec.position.append(9)
        spec.properties["Text"] = "changed"
        self.assertEqual(saved.position, [1, 2, 3, 4])
        self.assertEqual(saved.properties, {"Text": "hello"})

    def test_annotation_with_uid_keeps_fields_and_remaps_references(self):
        saved = BidAnnotation(
            uid="old",
            annotation_type="hotlink",
            page_uid="p1",
            layer_uid="L1",
            position=[5, 5],
            color="#445566",
            width=2.0,
            properties={"BidPageViewUID": "v-old", "Other": "kept"},
            visible=False,
        )
        remap = PasteRefRemap(namedview_uids={"v-old": "v-new"})
        copy = AnnotationWriteCoordinator.annotation_with_uid(saved, 42, remap)
        self.assertEqual(
            copy,
            BidAnnotation(
                uid="42",
                annotation_type="hotlink",
                page_uid="p1",
                layer_uid="L1",
                position=[5, 5],
                color="#445566",
                width=2.0,
                properties={"BidPageViewUID": "v-new", "Other": "kept"},
                visible=False,
            ),
        )
        copy.position.append(1)
        self.assertEqual(saved.position, [5, 5])
        self.assertEqual(saved.properties["BidPageViewUID"], "v-old")


class AnnotationWriteCoordinatorFilterCopyableTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _Context()

    def filter(self, sources):
        specs = AnnotationWriteCoordinator.annotation_specs_from_saved(sources)
        kept, kept_specs = self.ctx.coordinator.filter_copyable_annotations(
            sources, specs
        )
        self.assertEqual(
            [spec.annotation_type for spec in kept_specs],
            [item.annotation_type for item in kept],
        )
        return [item.uid for item in kept]

    def test_misaligned_sources_and_specs_are_refused(self):
        with self.assertRaisesRegex(ValueError, "must stay aligned"):
            self.ctx.coordinator.filter_copyable_annotations([_rect("a")], [])

    def test_hotlinks_survive_only_with_a_reachable_named_view(self):
        self.ctx.seed(_view("live"), _rect("shared-uid"))
        sources = [
            _view("copied"),
            _link("to-copied", "copied"),
            _link("to-live", "live"),
            _link("to-missing", "missing"),
            _link("to-non-view", "shared-uid"),
            _link("no-target", ""),
            _link("zero-target", "0"),
            _rect("plain"),
        ]
        self.assertEqual(
            self.filter(sources),
            ["copied", "to-copied", "to-live", "no-target", "zero-target", "plain"],
        )

    def test_a_non_hotlink_with_a_dangling_view_property_is_kept(self):
        item = _rect("plain")
        item.properties["BidPageViewUID"] = "missing"
        self.assertEqual(self.filter([item]), ["plain"])


class AnnotationWriteCoordinatorHistoryTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _Context()
        self.undo = _Undo()

    def test_capture_page_scales_normalizes_each_page_and_defaults_zero_scales(self):
        scales = self.ctx.coordinator.capture_page_scales(["p1", "p2", "p3", "p1"])
        self.assertEqual(scales, {"p1": (1.0, 1.0), "p2": (2.0, 4.0), "p3": (1.0, 1.0)})

    def test_capture_page_scales_refuses_a_page_that_no_longer_exists(self):
        with self.assertRaisesRegex(ValueError, "Annotation Page no longer exists"):
            self.ctx.coordinator.capture_page_scales(["p1", "gone"])

    def test_capture_history_targets_follow_the_authoritative_page(self):
        self.ctx.seed(_rect("a1", "p1"), _rect("a2", "p2"), _view("a1", "p2"))
        binding = self.ctx.coordinator.capture_history(
            BID,
            [("a1", "rect", {"Text": "x"}), ("a2", "rect", [1, 2, 3, 4])],
            self.undo,
        )
        self.assertIsInstance(binding, AnnotationHistoryBinding)
        self.assertEqual(binding.bid_ref, BID)
        self.assertEqual(
            binding.targets,
            {
                ("a1", "rect"): AnnotationHistoryTarget(BID, "p1", "rect", "a1"),
                ("a2", "rect"): AnnotationHistoryTarget(BID, "p2", "rect", "a2"),
            },
        )
        self.assertEqual(binding.view_dependencies, ())
        self.assertEqual(binding.history_targets(), tuple(binding.targets.values()))
        self.assertTrue(all(t.available for t in binding.targets.values()))

    def test_capture_history_captures_current_page_scales_unless_supplied(self):
        self.ctx.seed(_rect("a2", "p2"))
        updates = [("a2", "rect", [1, 2, 3, 4])]
        binding = self.ctx.coordinator.capture_history(BID, updates, self.undo)
        # p2 is scaled 2:4, so a stored 1:1 geometry doubles when replayed there.
        self.ctx.model.get_page("p2").scale_factor2 = 8.0
        self.assertEqual(
            binding.positions([("a2", "rect", [10, 10, 20, 20])]),
            [("a2", "rect", [20.0, 20.0, 40.0, 40.0])],
        )
        supplied = self.ctx.coordinator.capture_history(
            BID, updates, self.undo, captured_scales={"p2": (1.0, 1.0)}
        )
        self.assertEqual(
            supplied.positions([("a2", "rect", [10, 10, 20, 20])]),
            [("a2", "rect", [40.0, 40.0, 80.0, 80.0])],
        )

    def test_capture_history_refuses_annotations_that_are_not_authoritative(self):
        self.ctx.seed(_rect("a1", "p1"))
        with self.assertRaisesRegex(ValueError, "no longer authoritative"):
            self.ctx.coordinator.capture_history(
                BID, [("a1", "rect", {}), ("a1", "text", {})], self.undo
            )

    def test_capture_history_retains_external_named_view_of_hotlink_specs(self):
        self.ctx.seed(_rect("a1", "p1"), _view("v1", "p2"))
        hotlink = _spec("p1", "hotlink", [5, 5], properties={"BidPageViewUID": "v1"})
        binding = self.ctx.coordinator.capture_history(
            BID, [("a1", "rect", {})], self.undo, specs=[hotlink]
        )
        (dependency,) = binding.view_dependencies
        self.assertEqual(
            dependency, AnnotationHistoryTarget(BID, "p2", "namedview", "v1")
        )
        self.assertEqual(
            binding.history_targets(), (*binding.targets.values(), dependency)
        )

    def test_history_from_specs_keys_new_identities_by_spec_page_and_type(self):
        specs = [
            _spec("p1", "rect"),
            _spec("p2", "text"),
        ]
        binding = self.ctx.coordinator.history_from_specs(
            BID, specs, [11, "12"], self.undo, captured_scales={}
        )
        self.assertEqual(
            binding.targets,
            {
                ("11", "rect"): AnnotationHistoryTarget(BID, "p1", "rect", "11"),
                ("12", "text"): AnnotationHistoryTarget(BID, "p2", "text", "12"),
            },
        )
        self.assertEqual(binding.view_dependencies, (None, None))

    def test_history_from_specs_depends_on_external_view_but_not_batch_views(self):
        self.ctx.seed(_view("v1", "p2"))
        specs = [
            _spec("p1", "hotlink", [5, 5], properties={"BidPageViewUID": "v1"}),
            _spec("p1", "namedview", [0, 0, 5, 5], properties={"Text": "n"}),
        ]
        external = self.ctx.coordinator.history_from_specs(
            BID, specs, ["l1", "n1"], self.undo, captured_scales={}
        )
        self.assertEqual(
            external.view_dependencies,
            (AnnotationHistoryTarget(BID, "p2", "namedview", "v1"), None),
        )
        batch = self.ctx.coordinator.history_from_specs(
            BID,
            specs,
            ["l1", "n1"],
            self.undo,
            captured_scales={},
            source_uids=[
                annotation_resource_id("namedview", "v1"),
                annotation_resource_id("hotlink", "src"),
            ],
        )
        self.assertEqual(batch.view_dependencies, (None, None))
        with self.assertRaisesRegex(ValueError, "Invalid annotation collaboration"):
            self.ctx.coordinator.history_from_specs(
                BID, specs, ["l1", "n1"], self.undo, source_uids=["not-a-resource"]
            )

    def test_history_from_saved_excludes_named_views_saved_in_the_same_batch(self):
        self.ctx.seed(_view("outside", "p2"))
        saved = [
            _view("v-own", "p1"),
            _link("l-own", "v-own"),
            _link("l-out", "outside"),
        ]
        binding = self.ctx.coordinator.history_from_saved(
            BID, saved, self.undo, captured_scales={}
        )
        self.assertEqual(
            sorted(binding.targets),
            [("l-out", "hotlink"), ("l-own", "hotlink"), ("v-own", "namedview")],
        )
        self.assertEqual(
            binding.view_dependencies,
            (None, None, AnnotationHistoryTarget(BID, "p2", "namedview", "outside")),
        )
        self.assertEqual(
            binding.targets[("v-own", "namedview")],
            AnnotationHistoryTarget(BID, "p1", "namedview", "v-own"),
        )

    def test_binding_suspend_and_rebind_drive_the_undo_service_with_identities(self):
        specs = [_spec("p1", "rect"), _spec("p2", "text")]
        binding = self.ctx.coordinator.history_from_specs(
            BID, specs, ["a1", "a2"], self.undo, captured_scales={}
        )
        binding.suspend()
        ((bid, deleted),) = self.undo.suspend_calls
        self.assertEqual(bid, BID)
        self.assertEqual(deleted, tuple(binding.targets.values()))
        binding.rebind(["r1", 2])
        self.assertEqual(
            self.undo.rebind_calls,
            [
                (
                    BID,
                    {("p1", "rect", "a1"): "r1", ("p2", "text", "a2"): "2"},
                    ("suspended-marker",),
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "incomplete identity map"):
            binding.rebind(["only-one"])
        self.assertEqual(len(self.undo.rebind_calls), 1)

    def test_deleting_a_named_view_and_hotlink_restores_with_real_history(self):
        # End to end with the real UndoRedoService: after an accepted restore map
        # reactivates the Named View, the Hot Link's retained spec follows it.
        undo = UndoRedoService()
        undo.set_active_bid(BID)
        view, link = _view("view", "p1"), _link("link", "view")
        self.ctx.seed(view, link)
        coordinator = self.ctx.coordinator
        link_binding = coordinator.history_from_saved(BID, [link], undo)
        (dependency,) = link_binding.view_dependencies
        self.assertEqual((dependency.uid, dependency.available), ("view", True))
        view_binding = coordinator.history_from_saved(BID, [view], undo)
        undo.push_local(
            lambda: True,
            lambda: True,
            annotation_targets=(
                *link_binding.history_targets(),
                *view_binding.targets.values(),
            ),
        )
        self.ctx.model.remove_annotations_by_keys([("view", "namedview")])
        view_binding.suspend()
        self.assertFalse(dependency.available)
        with self.assertRaises(AnnotationHistoryDependencyError):
            link_binding.saved_annotations([link], restoring=True)
        self.ctx.model.add_annotations([replace(view, uid="view-2")])
        view_binding.rebind(["view-2"])
        (resolved,) = link_binding.saved_annotations([link], restoring=True)
        self.assertEqual(resolved.properties["BidPageViewUID"], "view-2")
        self.assertEqual(link.properties["BidPageViewUID"], "view")


if __name__ == "__main__":
    unittest.main()
