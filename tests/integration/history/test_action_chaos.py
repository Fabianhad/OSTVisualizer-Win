from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
import os
import random
import traceback
import unittest
from dataclasses import dataclass, field

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.handlers import (
    plan_view_action_handler as action_handler_module,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    PlanSurfaceAccessState,
)
from PySide6.QtWidgets import QApplication
from tests.presentation.handlers.test_plan_view_action_handler import (
    FakeAccess,
    FakeAnnotationWriteService,
    FakeDeferredPersistence,
    FakeEventBus,
    FakePageSettingsBar,
    FakePlanView,
    FakeProjectData,
    FakeUiState,
    FakeWriteService,
)

DEFAULT_CHAOS_SEEDS = (101, 202, 303, 404, 505)
DEFAULT_CHAOS_STEPS = 35


def _chaos_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return int(raw)


def _configured_seeds() -> list[int]:
    explicit = os.environ.get("PRESENTATION_CHAOS_SEED")
    if explicit not in (None, ""):
        return [int(explicit)]
    count = _env_int("PRESENTATION_CHAOS_SEEDS", len(DEFAULT_CHAOS_SEEDS))
    return list(DEFAULT_CHAOS_SEEDS[: max(1, count)])


@dataclass
class ChaosActionResult:
    name: str
    detail: str = ""

    def describe(self) -> str:
        return self.name if not self.detail else f"{self.name}: {self.detail}"


class HandlerChaosPlanView(FakePlanView):
    def get_takeoff(self, uid):
        takeoff = self.data.get_takeoff(uid) if self.data is not None else None
        if takeoff is None or takeoff.page_uid != self.current_page_uid:
            return None
        return takeoff


class HandlerChaosUiState(FakeUiState):
    def __init__(self):
        self.place_condition_uids = []
        self.active_page_uid = "p1"


class HandlerChaosAnnotationWriteService(FakeAnnotationWriteService):
    def __init__(self):
        super().__init__()
        self._next_uid_index = 0

    def insert_annotations(
        self,
        db_path,
        bid_uid,
        specs,
        ref_remap=None,
        publish_database_refreshed_after_write=True,
    ):
        self.insert_calls.append(
            (
                db_path,
                bid_uid,
                specs,
                ref_remap,
                publish_database_refreshed_after_write,
            )
        )
        count = len(specs)
        start = self._next_uid_index
        result = list(self.next_uids[start : start + count])
        while len(result) < count:
            result.append(f"ann-chaos-{start + len(result)}")
        self._next_uid_index += count
        return result


class PlanViewActionHandlerChaosHarness:
    def __init__(self, seed: int, test_case: unittest.TestCase):
        self.seed = seed
        self.test_case = test_case
        self.rng = random.Random(seed)
        self.history: list[ChaosActionResult] = []
        self.data = FakeProjectData()
        self.ui_state = HandlerChaosUiState()
        self.plan_view = HandlerChaosPlanView(self.data)
        self.write = FakeWriteService()
        self.write.next_uids = [str(uid) for uid in range(1000, 1100)]
        self.ann_write = HandlerChaosAnnotationWriteService()
        self.ann_write.next_uids = [f"ann-{uid}" for uid in range(1000, 1100)]
        self.write.annotation_write_service = self.ann_write
        self.undo = UndoRedoService()
        self.undo.set_active_bid(self.ui_state.get_selected_bid_ref())
        self.event_bus = FakeEventBus()
        self.access = FakeAccess(
            {
                Feature.SELECT_PLAN_ITEMS,
                Feature.EDIT_PLAN_ITEMS,
                Feature.PLACE_PLAN_ITEMS,
                Feature.PLACE_ANNOTATIONS,
                Feature.EDIT_PAGE_SETTINGS,
            }
        )
        self.handler = PlanViewActionHandler(
            plan_view=self.plan_view,
            ui_state_manager=self.ui_state,
            project_data_svc=self.data,
            project_write_svc=self.write,
            annotation_write_svc=self.ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=self.undo,
            event_bus=self.event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=self.access,
        )
        self.pages = {"p1", "p2"}
        self._build_model()
        self._sync_plan_view_to_page("p1")

    def _build_model(self) -> None:
        self.data.pages["p2"] = Page(uid="p2", name="Page 2")
        self.data.page_names["p2"] = "Page 2"
        self.data.takeoffs = {
            "t1": Takeoff(
                uid="t1",
                condition_uid="42",
                page_uid="p1",
                position=[10.0, 10.0, 50.0, 10.0],
            ),
            "t2": Takeoff(
                uid="t2",
                condition_uid="42",
                page_uid="p1",
                position=[25.0, 25.0],
            ),
            "t3": Takeoff(
                uid="t3",
                condition_uid="42",
                page_uid="p2",
                position=[75.0, 75.0, 125.0, 75.0],
            ),
        }
        self.data.annotations = [
            BidAnnotation(
                uid="p1-text",
                annotation_type=ANNOTATION_TYPE_TEXT,
                page_uid="p1",
                position=[5.0, 5.0, 45.0, 15.0],
                properties={"Text": "Page 1 note"},
            ),
            BidAnnotation(
                uid="p1-named",
                annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
                page_uid="p1",
                position=[0.0, 0.0, 50.0, 0.0, 0.0, 50.0, 50.0, 50.0, 0.0],
                properties={"Text": "Page 1 view"},
            ),
            BidAnnotation(
                uid="p1-hotlink",
                annotation_type=ANNOTATION_TYPE_HOTLINK,
                page_uid="p1",
                position=[20.0, 20.0],
                properties={"BidPageViewUID": "p1-named"},
            ),
            BidAnnotation(
                uid="p2-text",
                annotation_type=ANNOTATION_TYPE_TEXT,
                page_uid="p2",
                position=[8.0, 8.0, 44.0, 16.0],
                properties={"Text": "Page 2 note"},
            ),
            BidAnnotation(
                uid="p2-named",
                annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
                page_uid="p2",
                position=[0.0, 0.0, 60.0, 0.0, 0.0, 60.0, 60.0, 60.0, 0.0],
                properties={"Text": "Page 2 view"},
            ),
            BidAnnotation(
                uid="p2-hotlink",
                annotation_type=ANNOTATION_TYPE_HOTLINK,
                page_uid="p2",
                position=[22.0, 22.0],
                properties={"BidPageViewUID": "p2-named"},
            ),
        ]

    def run_random_actions(self, steps: int) -> None:
        for index in range(steps):
            self._run_action(index, self.rng.choice(self._all_actions()))

    def run_sequence(self, names: list[str]) -> None:
        actions = {
            action.__name__.replace("action_", ""): action
            for action in self._all_actions()
        }
        for index, name in enumerate(names):
            self._run_action(index, actions[name])

    def _all_actions(self):
        return [
            self.action_switch_page,
            self.action_select_current_takeoff,
            self.action_select_current_annotation,
            self.action_select_all_current,
            self.action_clear_selection,
            self.action_copy_selection,
            self.action_paste_clipboard,
            self.action_delete_selection,
            self.action_toggle_select_access,
            self.action_undo,
            self.action_redo,
        ]

    def _run_action(self, index: int, action) -> None:
        try:
            result = action()
            self.history.append(result)
            _chaos_app().processEvents()
            self._sync_plan_view_to_page(self.plan_view.current_page_uid)
            self._assert_invariants()
        except Exception as exc:
            self.test_case.fail(self._failure_message(index, action.__name__, exc))

    def _sync_plan_view_to_page(self, page_uid: str) -> None:
        self.plan_view.current_page_uid = page_uid
        self.ui_state.active_page_uid = page_uid
        annotations = [
            annotation
            for annotation in self.data.annotations
            if annotation.page_uid == page_uid and annotation.is_interactive
        ]
        self.plan_view.annotations = {
            annotation.uid: annotation for annotation in annotations
        }
        self.plan_view.annotation_key_map = {
            (annotation.uid, annotation.annotation_type): annotation.uid
            for annotation in annotations
        }
        current_uids = self._current_page_uids()
        self.plan_view.selected &= current_uids

    def _current_page_uids(self) -> set[str]:
        page_uid = self.plan_view.current_page_uid
        return {
            takeoff.uid
            for takeoff in self.data.takeoffs.values()
            if takeoff.page_uid == page_uid
        } | {
            annotation.uid
            for annotation in self.data.annotations
            if annotation.page_uid == page_uid and annotation.is_interactive
        }

    def action_switch_page(self) -> ChaosActionResult:
        page_uid = "p2" if self.plan_view.current_page_uid == "p1" else "p1"
        self._sync_plan_view_to_page(page_uid)
        return ChaosActionResult("switch_page", page_uid)

    def action_select_current_takeoff(self) -> ChaosActionResult:
        uids = sorted(
            takeoff.uid
            for takeoff in self.data.takeoffs.values()
            if takeoff.page_uid == self.plan_view.current_page_uid
        )
        if not uids:
            return ChaosActionResult("select_current_takeoff", "no-op")
        uid = self.rng.choice(uids)
        self.plan_view.set_selected_uids({uid})
        return ChaosActionResult("select_current_takeoff", uid)

    def action_select_current_annotation(self) -> ChaosActionResult:
        uids = sorted(self.plan_view.annotations)
        if not uids:
            return ChaosActionResult("select_current_annotation", "no-op")
        uid = self.rng.choice(uids)
        self.plan_view.set_selected_uids({uid})
        return ChaosActionResult("select_current_annotation", uid)

    def action_select_all_current(self) -> ChaosActionResult:
        uids = self._current_page_uids()
        self.plan_view.set_selected_uids(uids)
        return ChaosActionResult("select_all_current", ",".join(sorted(uids)))

    def action_clear_selection(self) -> ChaosActionResult:
        self.plan_view.clear_selection()
        return ChaosActionResult("clear_selection")

    def action_copy_selection(self) -> ChaosActionResult:
        selected = sorted(self.plan_view.selected)
        should_update_clipboard = (
            Feature.SELECT_PLAN_ITEMS in self.access.allowed_features
            and self._selection_has_copyable_current_items(selected)
        )
        self.handler.on_copy_requested(selected)
        if should_update_clipboard:
            self._assert_clipboard_from_current_page()
        return ChaosActionResult("copy_selection", ",".join(selected) or "empty")

    def action_paste_clipboard(self) -> ChaosActionResult:
        before_takeoffs = set(self.data.takeoffs)
        before_annotations = {
            (annotation.uid, annotation.annotation_type)
            for annotation in self.data.annotations
        }
        self.handler.on_paste_requested()
        new_takeoffs = sorted(set(self.data.takeoffs) - before_takeoffs)
        new_annotations = sorted(
            {
                (annotation.uid, annotation.annotation_type)
                for annotation in self.data.annotations
            }
            - before_annotations
        )
        return ChaosActionResult(
            "paste_clipboard",
            f"takeoffs={new_takeoffs}; annotations={new_annotations}",
        )

    def action_delete_selection(self) -> ChaosActionResult:
        selected = sorted(self.plan_view.selected)
        if not selected:
            return ChaosActionResult("delete_selection", "no-op")
        confirmation = self.rng.choice([True, False])
        with unittest.mock.patch.object(
            action_handler_module,
            "confirm",
            return_value=confirmation,
        ):
            self.handler.on_elements_deleted(selected)
        return ChaosActionResult(
            "delete_selection", f"{','.join(selected)}; confirm={confirmation}"
        )

    def action_toggle_select_access(self) -> ChaosActionResult:
        allowed = Feature.SELECT_PLAN_ITEMS in self.access.allowed_features
        if allowed:
            self.access.allowed_features.remove(Feature.SELECT_PLAN_ITEMS)
        else:
            self.access.allowed_features.add(Feature.SELECT_PLAN_ITEMS)
        return ChaosActionResult("toggle_select_access", f"allowed={not allowed}")

    def action_undo(self) -> ChaosActionResult:
        if not self.undo.can_undo():
            return ChaosActionResult("undo", "no-op")
        self.undo.undo()
        return ChaosActionResult("undo")

    def action_redo(self) -> ChaosActionResult:
        if not self.undo.can_redo():
            return ChaosActionResult("redo", "no-op")
        self.undo.redo()
        return ChaosActionResult("redo")

    def _assert_clipboard_from_current_page(self) -> None:
        clipboard = self.handler._clipboard_svc
        if not clipboard.has_content():
            return
        current_page_uid = self.plan_view.current_page_uid
        wrong_takeoffs = [
            takeoff.uid
            for takeoff in clipboard.items
            if takeoff.page_uid != current_page_uid
        ]
        wrong_annotations = [
            annotation.uid
            for annotation in clipboard.annotations
            if annotation.page_uid != current_page_uid
        ]
        if wrong_takeoffs or wrong_annotations:
            raise AssertionError(
                "clipboard captured non-current page items: "
                f"takeoffs={wrong_takeoffs}, annotations={wrong_annotations}"
            )

    def _selection_has_copyable_current_items(self, selected: list[str]) -> bool:
        for uid in selected:
            takeoff = self.plan_view.get_takeoff(uid)
            if takeoff is not None:
                return True
            annotation = self.plan_view.get_annotation(uid)
            if annotation and annotation.is_interactive and not annotation.is_namedview:
                return True
        return False

    def _assert_invariants(self) -> None:
        selected = set(self.plan_view.selected)
        stale_selected = selected - self._current_page_uids()
        if stale_selected:
            raise AssertionError(
                f"handler selection has stale uids: {sorted(stale_selected)}"
            )
        takeoff_page_errors = [
            takeoff.uid
            for takeoff in self.data.takeoffs.values()
            if takeoff.page_uid not in self.pages
        ]
        if takeoff_page_errors:
            raise AssertionError(f"takeoffs with unknown pages: {takeoff_page_errors}")
        annotation_keys = [
            (annotation.uid, annotation.annotation_type)
            for annotation in self.data.annotations
        ]
        if len(annotation_keys) != len(set(annotation_keys)):
            raise AssertionError("duplicate annotation uid/type keys in handler model")
        current_annotation_pages = {
            annotation.uid: annotation.page_uid
            for annotation in self.plan_view.annotations.values()
        }
        wrong_plan_annotations = {
            uid: page_uid
            for uid, page_uid in current_annotation_pages.items()
            if page_uid != self.plan_view.current_page_uid
        }
        if wrong_plan_annotations:
            raise AssertionError(
                f"plan view has off-page annotations: {wrong_plan_annotations}"
            )
        named_view_uids = {
            annotation.uid
            for annotation in self.data.annotations
            if annotation.is_namedview
        }
        orphan_hotlinks = [
            annotation.uid
            for annotation in self.data.annotations
            if annotation.is_hotlink
            and annotation.hotlink_target_view_uid
            and annotation.hotlink_target_view_uid not in named_view_uids
        ]
        if orphan_hotlinks:
            raise AssertionError(
                f"orphan hotlinks after handler action: {orphan_hotlinks}"
            )
        for call in self.write.calls:
            _db_path, _bid_uid, specs, _publish = call
            bad_specs = [
                spec.page_uid for spec in specs if spec.page_uid not in self.pages
            ]
            if bad_specs:
                raise AssertionError(
                    f"takeoff paste wrote specs for unknown pages: {bad_specs}"
                )
        for call in self.ann_write.insert_calls:
            _db_path, _bid_uid, specs, _ref_remap, _publish = call
            bad_specs = [
                spec.page_uid for spec in specs if spec.page_uid not in self.pages
            ]
            if bad_specs:
                raise AssertionError(
                    f"annotation paste wrote specs for unknown pages: {bad_specs}"
                )

    def _failure_message(self, index: int, action_name: str, exc: BaseException) -> str:
        return (
            "Plan view action handler chaos harness failure\n"
            f"Current state: {{'seed': {self.seed}, 'action_index': {index}, "
            f"'action': {action_name.replace('action_', '')!r}, "
            f"'page': {self.plan_view.current_page_uid!r}, "
            f"'selected': {sorted(self.plan_view.selected)}, "
            f"'takeoffs': {sorted((uid, t.page_uid) for uid, t in self.data.takeoffs.items())}, "
            f"'annotations': {sorted((a.uid, a.annotation_type, a.page_uid) for a in self.data.annotations)}, "
            f"'access': {sorted(feature.value for feature in self.access.allowed_features)}}}\n"
            f"Recent actions: {[entry.describe() for entry in self.history[-15:]]}\n"
            f"Exception: {exc!r}\n"
            f"{traceback.format_exc()}"
        )


class PlanViewActionHandlerChaosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _chaos_app()

    def test_action_handler_chaos_default_seeds(self):
        steps = _env_int("PRESENTATION_CHAOS_STEPS", DEFAULT_CHAOS_STEPS)
        for seed in _configured_seeds()[:3]:
            with self.subTest(seed=seed, steps=steps):
                harness = PlanViewActionHandlerChaosHarness(seed + 6000, self)
                harness.run_random_actions(steps)

    def test_known_sequence_copy_paste_keeps_current_page_scope(self):
        harness = PlanViewActionHandlerChaosHarness(9601, self)
        harness.run_sequence(
            [
                "select_all_current",
                "copy_selection",
                "switch_page",
                "paste_clipboard",
            ]
        )
        pasted_takeoffs = [
            takeoff
            for uid, takeoff in harness.data.takeoffs.items()
            if uid not in {"t1", "t2", "t3"}
        ]
        pasted_annotations = [
            annotation
            for annotation in harness.data.annotations
            if annotation.uid.startswith("ann-")
        ]
        self.assertTrue(pasted_takeoffs)
        self.assertTrue(pasted_annotations)
        self.assertEqual({takeoff.page_uid for takeoff in pasted_takeoffs}, {"p2"})
        self.assertEqual(
            {annotation.page_uid for annotation in pasted_annotations}, {"p2"}
        )

    def test_known_sequence_declined_named_view_delete_keeps_linked_hotlink(self):
        harness = PlanViewActionHandlerChaosHarness(9602, self)
        harness.plan_view.set_selected_uids({"p1-named"})
        with unittest.mock.patch.object(
            action_handler_module, "confirm", return_value=False
        ):
            harness.handler.on_elements_deleted(["p1-named"])
        harness._sync_plan_view_to_page("p1")
        harness._assert_invariants()
        remaining = {(a.uid, a.annotation_type) for a in harness.data.annotations}
        self.assertIn(("p1-named", ANNOTATION_TYPE_NAMED_VIEW), remaining)
        self.assertIn(("p1-hotlink", ANNOTATION_TYPE_HOTLINK), remaining)

    def test_known_sequence_confirmed_named_view_delete_removes_linked_hotlink(self):
        harness = PlanViewActionHandlerChaosHarness(9603, self)
        harness.plan_view.set_selected_uids({"p1-named"})
        with unittest.mock.patch.object(
            action_handler_module, "confirm", return_value=True
        ):
            harness.handler.on_elements_deleted(["p1-named"])
        harness._sync_plan_view_to_page("p1")
        harness._assert_invariants()
        remaining = {(a.uid, a.annotation_type) for a in harness.data.annotations}
        self.assertNotIn(("p1-named", ANNOTATION_TYPE_NAMED_VIEW), remaining)
        self.assertNotIn(("p1-hotlink", ANNOTATION_TYPE_HOTLINK), remaining)

    def test_paste_retains_hotlink_to_existing_named_view(self):
        harness = PlanViewActionHandlerChaosHarness(9604, self)
        harness.plan_view.set_selected_uids({"p1-hotlink"})
        harness.action_copy_selection()
        harness.action_switch_page()
        harness.action_paste_clipboard()
        harness._assert_invariants()
        copied_hotlinks = [
            annotation
            for annotation in harness.data.annotations
            if annotation.page_uid == "p2"
            and annotation.uid != "p2-hotlink"
            and annotation.is_hotlink
        ]
        self.assertEqual(len(copied_hotlinks), 1)
        self.assertEqual(copied_hotlinks[0].properties["BidPageViewUID"], "p1-named")

    def test_paste_skips_stale_hotlink_but_keeps_other_clipboard_annotations(self):
        harness = PlanViewActionHandlerChaosHarness(9605, self)
        harness.action_switch_page()
        harness.plan_view.set_selected_uids({"p2-hotlink", "p2-text"})
        harness.action_copy_selection()
        with unittest.mock.patch.object(
            action_handler_module, "confirm", return_value=True
        ):
            harness.handler.on_elements_deleted(["p2-named"])
        harness.plan_view.clear_selection()
        before_text_uids = {
            annotation.uid
            for annotation in harness.data.annotations
            if annotation.annotation_type == ANNOTATION_TYPE_TEXT
        }
        harness.action_paste_clipboard()
        harness._assert_invariants()
        self.assertFalse(
            any(
                annotation.is_hotlink
                and annotation.properties.get("BidPageViewUID") == "p2-named"
                for annotation in harness.data.annotations
            )
        )
        after_text_uids = {
            annotation.uid
            for annotation in harness.data.annotations
            if annotation.annotation_type == ANNOTATION_TYPE_TEXT
        }
        self.assertGreater(len(after_text_uids), len(before_text_uids))
