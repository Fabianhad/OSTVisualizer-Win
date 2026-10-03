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
        self.rejected_inserts = 0
        # Returns the Named View uids currently persisted; the harness points it
        # at its model so inserts can mirror the MDB writer's dangling-target
        # validation (AnnotationOperationsMixin.insert_annotations).
        self.named_view_uids = lambda: set()

    def _has_dangling_hotlink_target(self, specs, ref_remap):
        remap = dict(ref_remap.namedview_uids) if ref_remap is not None else {}
        # A restore inserts its Named Views first, so their remapped uids are
        # persisted before the dependent Hot Links are validated.
        live = set(self.named_view_uids()) | {str(uid) for uid in remap.values()}
        for spec in specs:
            if spec.annotation_type != ANNOTATION_TYPE_HOTLINK:
                continue
            target = spec.properties.get("BidPageViewUID")
            if target in (None, "", "0", 0):
                continue
            if str(remap.get(str(target), target)) not in live:
                return True
        return False

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
        if self._has_dangling_hotlink_target(specs, ref_remap):
            # The real writer refuses the whole batch and returns no identities.
            self.rejected_inserts += 1
            return []
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
        self.ann_write.named_view_uids = lambda: {
            annotation.uid
            for annotation in self.data.annotations
            if annotation.is_namedview
        }
        self.write.annotation_write_service = self.ann_write
        # A refused Hot Link restore reports through this dialog; walks that keep
        # every Named View's history intact must never reach it.
        warning_patch = unittest.mock.patch.object(
            action_handler_module, "show_warning"
        )
        self.warnings = warning_patch.start()
        test_case.addCleanup(warning_patch.stop)
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
        current_page_uid = self.plan_view.current_page_uid
        off_page = [
            uid
            for uid in new_takeoffs
            if self.data.takeoffs[uid].page_uid != current_page_uid
        ] + [
            annotation.uid
            for annotation in self.data.annotations
            if (annotation.uid, annotation.annotation_type) in new_annotations
            and annotation.page_uid != current_page_uid
        ]
        if off_page:
            raise AssertionError(
                f"paste created items off the current page {current_page_uid}: "
                f"{off_page}"
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
        copied_named_views = [
            annotation.uid
            for annotation in clipboard.annotations
            if annotation.is_namedview
        ]
        if copied_named_views:
            raise AssertionError(
                f"clipboard captured Named Views: {copied_named_views}"
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

    def test_chaos_walk_is_deterministic_and_reaches_mutating_actions(self):
        # The default seeds are fixed, so a walk is replayable action for action,
        # and together the three default walks must actually reach pastes,
        # deletes, undo and redo (not only selection changes and no-ops).
        takeoff_pastes = annotation_pastes = annotation_deletes = 0
        performed = set()
        for seed in DEFAULT_CHAOS_SEEDS[:3]:
            with self.subTest(seed=seed):
                walks = []
                for _ in range(2):
                    harness = PlanViewActionHandlerChaosHarness(seed + 6000, self)
                    harness.run_random_actions(DEFAULT_CHAOS_STEPS)
                    walks.append(harness)
                first, second = walks
                self.assertEqual(
                    [entry.describe() for entry in first.history],
                    [entry.describe() for entry in second.history],
                )
                self.assertEqual(len(first.history), DEFAULT_CHAOS_STEPS)
                self.assertEqual(
                    sorted(first.data.takeoffs), sorted(second.data.takeoffs)
                )
                self.assertEqual(
                    sorted(
                        (a.uid, a.annotation_type, a.page_uid)
                        for a in first.data.annotations
                    ),
                    sorted(
                        (a.uid, a.annotation_type, a.page_uid)
                        for a in second.data.annotations
                    ),
                )
                takeoff_pastes += len(first.write.calls)
                annotation_pastes += len(first.ann_write.insert_calls)
                annotation_deletes += len(first.ann_write.delete_calls)
                performed.update(
                    entry.name for entry in first.history if entry.detail != "no-op"
                )
        self.assertGreaterEqual(takeoff_pastes, 1)
        self.assertGreaterEqual(annotation_pastes, 1)
        self.assertGreaterEqual(annotation_deletes, 1)
        self.assertTrue({"undo", "redo", "delete_selection"} <= performed, performed)

    def test_long_walks_keep_orphan_invariant_when_hotlinks_follow_restored_views(
        self,
    ):
        # These long seeds used to restore a Hot Link whose Named View had been
        # re-created under a new uid, which persistence refuses (the orphan-Hot
        # Link invariant tripped at steps 27-66, then every such restore was a
        # refused insert). Hot Links now follow the restored Named View, so the
        # walks restore Hot Links without any refused insert or warning.
        for seed in (1, 18, 62, 65):
            with self.subTest(seed=seed):
                harness = PlanViewActionHandlerChaosHarness(seed, self)
                harness.run_random_actions(100)
                self.assertEqual(harness.ann_write.rejected_inserts, 0)
                harness.warnings.assert_not_called()
                self.assertTrue(
                    any(
                        spec.annotation_type == ANNOTATION_TYPE_HOTLINK
                        for call in harness.ann_write.insert_calls
                        for spec in call[2]
                    )
                )

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

    def _delete_p1(self, harness, uid):
        harness.plan_view.set_selected_uids({uid})
        with unittest.mock.patch.object(
            action_handler_module, "confirm", return_value=True
        ) as confirm:
            harness.handler.on_elements_deleted([uid])
        harness._sync_plan_view_to_page("p1")
        harness._assert_invariants()
        return confirm

    def _undo_p1(self, harness):
        self.assertTrue(harness.undo.can_undo())
        harness.undo.undo()
        harness._sync_plan_view_to_page("p1")
        harness._assert_invariants()

    @staticmethod
    def _p1_state(harness):
        return sorted(
            (a.uid, a.annotation_type, a.properties.get("BidPageViewUID"))
            for a in harness.data.annotations
            if a.page_uid == "p1"
        )

    def test_known_sequence_hotlink_undo_follows_named_view_restored_under_new_uid(
        self,
    ):
        # Delete a Hot Link, then (separately) the Named View it targeted. Undoing
        # the Named View deletion restores it under a NEW uid; the older Hot Link
        # entry retained that Named View as a lifetime dependency, so undoing it
        # restores the link onto the new uid and the write fake accepts it.
        harness = PlanViewActionHandlerChaosHarness(9606, self)
        # The Hot Link is deleted first, so no cascade confirmation is needed.
        self.assertFalse(self._delete_p1(harness, "p1-hotlink").called)
        self.assertFalse(self._delete_p1(harness, "p1-named").called)
        text_only = [("p1-text", ANNOTATION_TYPE_TEXT, None)]
        self.assertEqual(self._p1_state(harness), text_only)
        self._undo_p1(harness)
        restored = [
            a for a in harness.data.annotations if a.page_uid == "p1" and a.is_namedview
        ]
        self.assertEqual([a.uid for a in restored], ["ann-1000"])
        self._undo_p1(harness)
        followed = [
            ("ann-1000", ANNOTATION_TYPE_NAMED_VIEW, None),
            ("ann-1001", ANNOTATION_TYPE_HOTLINK, "ann-1000"),
            ("p1-text", ANNOTATION_TYPE_TEXT, None),
        ]
        self.assertEqual(self._p1_state(harness), followed)
        self.assertEqual(harness.ann_write.rejected_inserts, 0)
        harness.warnings.assert_not_called()
        self.assertFalse(harness.undo.can_undo())
        # Redo and undo again: the Hot Link keeps following the restored view.
        harness.undo.redo()
        harness.undo.redo()
        harness._sync_plan_view_to_page("p1")
        harness._assert_invariants()
        self.assertEqual(self._p1_state(harness), text_only)
        self._undo_p1(harness)
        self._undo_p1(harness)
        hotlinks = [
            a for a in harness.data.annotations if a.page_uid == "p1" and a.is_hotlink
        ]
        views = [
            a for a in harness.data.annotations if a.page_uid == "p1" and a.is_namedview
        ]
        self.assertEqual(len(hotlinks), 1)
        self.assertEqual(len(views), 1)
        self.assertEqual(hotlinks[0].properties["BidPageViewUID"], views[0].uid)
        self.assertEqual(harness.ann_write.rejected_inserts, 0)

    def test_known_sequence_cascade_delete_undo_remaps_hotlink_to_restored_view(self):
        # A Named View delete that cascades to its Hot Link is one batch, so the
        # restore remaps the link onto the restored view's new uid and the write
        # fake accepts it (the target is a same-batch Named View, not dangling).
        harness = PlanViewActionHandlerChaosHarness(9608, self)
        self.assertTrue(self._delete_p1(harness, "p1-named").called)
        self.assertEqual(
            self._p1_state(harness), [("p1-text", ANNOTATION_TYPE_TEXT, None)]
        )
        self._undo_p1(harness)
        self.assertEqual(harness.ann_write.rejected_inserts, 0)
        self.assertEqual(
            self._p1_state(harness),
            [
                ("ann-1000", ANNOTATION_TYPE_NAMED_VIEW, None),
                ("ann-1001", ANNOTATION_TYPE_HOTLINK, "ann-1000"),
                ("p1-text", ANNOTATION_TYPE_TEXT, None),
            ],
        )

    def test_known_sequence_hotlink_undo_without_named_view_deletion_restores_link(
        self,
    ):
        # Positive control: with the Named View never deleted, the same Hot Link
        # undo keeps its original target (nothing is re-pointed).
        harness = PlanViewActionHandlerChaosHarness(9607, self)
        self._delete_p1(harness, "p1-hotlink")
        self._undo_p1(harness)
        links = [a for a in harness.data.annotations if a.uid == "ann-1000"]
        self.assertEqual(len(links), 1)
        self.assertTrue(links[0].is_hotlink)
        self.assertEqual(links[0].properties["BidPageViewUID"], "p1-named")
        self.assertEqual(harness.ann_write.rejected_inserts, 0)


class HotlinkUndoAgainstPersistenceValidationTests(unittest.TestCase):
    """The delete/undo chain above, run against the real MDB annotation writer.
    The chaos harness fakes cannot reject dangling Hot Link targets, so this
    drives the real PlanViewActionHandler, UndoRedoService, AnnotationWriteCoordinator
    and ProjectWriteService paste composite over a sqlite-backed
    AnnotationOperationsMixin, which validates every Hot Link target against
    BidNamedViews exactly as the Access writer does.
    """

    PAGE = "9"

    def setUp(self):
        import logging
        import sqlite3
        import uuid
        from ost_visualizer.application.dtos.collaboration_dtos import (
            DatabaseMutationResult,
            MutationOutcomeStatus,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )
        from tests.application.services.test_project_write_service import (
            MdbSqlBehaviorParityTests,
            _Recorder,
        )
        from tests.integration.annotations.dimension_support import (
            _DimensionWriteOps,
        )

        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        # A refused Hot Link restore reports through this dialog, which would
        # block the offscreen run; every test inspects the recorded calls instead.
        warning_patch = unittest.mock.patch.object(
            action_handler_module, "show_warning"
        )
        self.warning = warning_patch.start()
        self.addCleanup(warning_patch.stop)
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE Bids (UID INTEGER);
            INSERT INTO Bids VALUES (7);
            CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);
            INSERT INTO BidPages VALUES (9, 7);
            CREATE TABLE BidNamedViews (
                UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, Name TEXT,
                Position BLOB, Color INTEGER, Origin INTEGER);
            CREATE TABLE BidHotLinks (
                UID INTEGER, BidUID INTEGER, BidPageUID INTEGER,
                BidPageViewUID INTEGER, BidLayerUID INTEGER, Position BLOB,
                Color INTEGER);
            """
        )
        self.conn = conn
        ops = _DimensionWriteOps(conn)

        def spec(kind, properties, position):
            return InsertAnnotationSpec(
                page_uid=self.PAGE,
                annotation_type=kind,
                position=position,
                color="#ff0000",
                width=1.0,
                properties=properties,
            )

        # Named View 5 is the target; Named View 9 exists with a higher UID so a
        # restore of view 5 is allocated a new UID (10) instead of reusing 5.
        ops.insert_annotations(
            "bid.mdb", "7", [spec("namedview", {"Text": "A"}, [0.0, 0.0, 10.0, 10.0])]
        )
        conn.execute("UPDATE BidNamedViews SET UID=5")
        ops.insert_annotations(
            "bid.mdb", "7", [spec("namedview", {"Text": "B"}, [0.0, 0.0, 10.0, 10.0])]
        )
        conn.execute("UPDATE BidNamedViews SET UID=9 WHERE UID=6")
        ops.insert_annotations(
            "bid.mdb",
            "7",
            [spec("hotlink", {"BidPageViewUID": "5"}, [20.0, 20.0])],
        )
        self.assertEqual(self.named_views(), [5, 9])
        self.assertEqual(self.hotlinks(), [(1, 5)])
        self.ops = ops

        class PersistedAnnotationWrites(FakeAnnotationWriteService):
            def delete_annotations(
                writer, db_path, keys, publish_database_refreshed_after_write=True
            ):
                return ops.delete_annotations(db_path, keys)

            def insert_annotations(
                writer,
                db_path,
                bid_uid,
                specs,
                ref_remap=None,
                publish_database_refreshed_after_write=True,
            ):
                return ops.insert_annotations(db_path, bid_uid, specs, ref_remap)

        class PersistedInsert:
            def execute(_self, database_id, bid_uid, specs, ref_remap):
                return ops.insert_annotations(database_id, bid_uid, specs, ref_remap)

        class PersistedDelete:
            def execute(_self, database_id, keys):
                return ops.delete_annotations(database_id, keys)

        service = MdbSqlBehaviorParityTests._local_composite_service()
        service._insert_annotations = PersistedInsert()
        service._delete_annotations = PersistedDelete()
        self.failed_mutations = []

        def execute_mutation(database_id, resources, operation, **options):
            try:
                value = operation(_Recorder())
            except Exception as exc:
                self.failed_mutations.append(str(exc))
                status = MutationOutcomeStatus.FAILED_BEFORE_COMMIT
                value = None
            else:
                status = MutationOutcomeStatus.COMMITTED
            return DatabaseMutationResult(
                operation_id=str(uuid.uuid4()), outcome_status=status, value=value
            )

        service._execute_database_mutation = execute_mutation
        self.data = FakeProjectData()
        self.data.annotation_layer_uid = ""
        self.data.annotations = [
            BidAnnotation(
                uid="5",
                annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
                page_uid=self.PAGE,
                position=[0.0, 0.0, 10.0, 10.0],
                properties={"Text": "A"},
            ),
            BidAnnotation(
                uid="9",
                annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
                page_uid=self.PAGE,
                position=[0.0, 0.0, 10.0, 10.0],
                properties={"Text": "B"},
            ),
            BidAnnotation(
                uid="1",
                annotation_type=ANNOTATION_TYPE_HOTLINK,
                page_uid=self.PAGE,
                position=[20.0, 20.0],
                properties={"BidPageViewUID": "5"},
            ),
        ]
        self.plan_view = FakePlanView(self.data)
        self.undo = UndoRedoService()
        self.undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        self.handler = PlanViewActionHandler(
            plan_view=self.plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=self.data,
            project_write_svc=service,
            annotation_write_svc=PersistedAnnotationWrites(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=self.undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
        )
        self.sync()

    def sync(self):
        self.plan_view.annotations = {
            f"{a.annotation_type}:{a.uid}": a for a in self.data.annotations
        }
        self.plan_view.annotation_key_map = {
            (a.uid, a.annotation_type): f"{a.annotation_type}:{a.uid}"
            for a in self.data.annotations
        }

    def named_views(self):
        return [
            row[0]
            for row in self.conn.execute("SELECT UID FROM BidNamedViews ORDER BY UID")
        ]

    def hotlinks(self):
        return self.conn.execute(
            "SELECT UID, BidPageViewUID FROM BidHotLinks"
        ).fetchall()

    def model(self):
        return sorted(
            (a.annotation_type, a.uid, a.properties.get("BidPageViewUID"))
            for a in self.data.annotations
        )

    def delete(self, key):
        self.sync()
        with unittest.mock.patch.object(
            action_handler_module, "confirm", return_value=True
        ) as confirm:
            self.handler.on_elements_deleted([key])
        self.sync()
        return confirm

    def delete_named_view_outside_history(self, uid):
        # A deletion this undo history never recorded (another window, another
        # client): the row and the model entry disappear, and the other history
        # owner's lifetime event invalidates the lifetimes retained here.
        self.ops.delete_annotations("bid.mdb", [(uid, "namedview")])
        self.data.annotations = [
            a
            for a in self.data.annotations
            if not (a.annotation_type == ANNOTATION_TYPE_NAMED_VIEW and a.uid == uid)
        ]
        self.undo.invalidate_deleted_annotation_lifetimes(
            "bid.mdb", "7", {(self.PAGE, "namedview", uid)}, "another-window"
        )
        self.sync()

    def add_unrelated_named_view(self, uid):
        # An unrelated Named View that merely reuses a deleted Named View's UID.
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )

        self.ops.insert_annotations(
            "bid.mdb",
            "7",
            [
                InsertAnnotationSpec(
                    page_uid=self.PAGE,
                    annotation_type="namedview",
                    position=[0.0, 0.0, 10.0, 10.0],
                    color="#ff0000",
                    width=1.0,
                    properties={"Text": "Unrelated"},
                )
            ],
        )
        self.conn.execute(
            "UPDATE BidNamedViews SET UID=? WHERE Name='Unrelated'", (int(uid),)
        )
        self.data.annotations.append(
            BidAnnotation(
                uid=uid,
                annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
                page_uid=self.PAGE,
                position=[0.0, 0.0, 10.0, 10.0],
                properties={"Text": "Unrelated"},
            )
        )
        self.sync()

    def undo_expecting_warning(self):
        self.warning.reset_mock()
        self.undo.undo()
        self.sync()
        return self.warning

    def assert_hotlink_restore_refused(self, warning, model_before):
        # Clean refusal: the user is told, nothing was written, no Hot Link
        # (dangling or re-pointed) exists, and the entry stays for retry.
        warning.assert_called_once()
        self.assertIn("Named View", warning.call_args.args[2])
        self.assertEqual(self.failed_mutations, [])
        self.assertEqual(self.hotlinks(), [])
        self.assertEqual(self.model(), model_before)
        self.assertTrue(self.undo.can_undo())

    def test_hotlink_undo_follows_named_view_restored_under_new_uid(self):
        self.assertFalse(self.delete("hotlink:1").called)
        self.assertEqual(self.hotlinks(), [])
        self.assertFalse(self.delete("namedview:5").called)
        self.assertEqual(self.named_views(), [9])
        self.assertEqual(self.model(), [("namedview", "9", None)])
        self.undo.undo()
        self.sync()
        # The Named View came back under a new persisted UID.
        self.assertEqual(self.named_views(), [9, 10])
        self.assertEqual(
            self.model(), [("namedview", "10", None), ("namedview", "9", None)]
        )
        self.assertEqual(self.failed_mutations, [])
        self.undo.undo()
        self.sync()
        # The Hot Link follows the restored Named View instead of its old UID.
        self.assertEqual(self.failed_mutations, [])
        self.assertEqual(self.named_views(), [9, 10])
        self.assertEqual(self.hotlinks(), [(1, 10)])
        self.assertEqual(
            self.model(),
            [
                ("hotlink", "1", "10"),
                ("namedview", "10", None),
                ("namedview", "9", None),
            ],
        )
        self.assertFalse(self.undo.can_undo())
        self.warning.assert_not_called()

    def test_hotlink_follows_named_view_through_redo_undo_cycles(self):
        self.delete("hotlink:1")
        self.delete("namedview:5")
        for _cycle in range(3):
            self.undo.undo()
            self.undo.undo()
            self.sync()
            self.assertEqual(self.named_views(), [9, 10])
            self.assertEqual(self.hotlinks(), [(1, 10)])
            self.assertEqual(
                self.model(),
                [
                    ("hotlink", "1", "10"),
                    ("namedview", "10", None),
                    ("namedview", "9", None),
                ],
            )
            self.undo.redo()
            self.undo.redo()
            self.sync()
            self.assertEqual(self.named_views(), [9])
            self.assertEqual(self.hotlinks(), [])
            self.assertEqual(self.model(), [("namedview", "9", None)])
        self.assertEqual(self.failed_mutations, [])
        self.warning.assert_not_called()

    def test_hotlink_undo_refused_when_named_view_was_not_restored(self):
        self.delete("hotlink:1")
        self.delete_named_view_outside_history("5")
        before = self.model()
        warning = self.undo_expecting_warning()
        self.assert_hotlink_restore_refused(warning, before)
        self.assertEqual(self.named_views(), [9])
        # Repeating the undo is refused the same way instead of corrupting state.
        warning = self.undo_expecting_warning()
        self.assert_hotlink_restore_refused(warning, before)

    def test_hotlink_undo_not_repointed_to_unrelated_named_view_reusing_the_uid(self):
        self.delete("hotlink:1")
        self.delete_named_view_outside_history("5")
        self.add_unrelated_named_view("5")
        self.assertEqual(self.named_views(), [5, 9])
        before = self.model()
        warning = self.undo_expecting_warning()
        # Named View 5 exists again, but it is not the deleted Named View.
        self.assert_hotlink_restore_refused(warning, before)
        self.assertEqual(self.named_views(), [5, 9])

    def test_hotlink_undo_refused_after_history_cleared(self):
        self.delete("hotlink:1")
        self.delete("namedview:5")
        self.undo.clear()
        self.undo.undo()
        self.sync()
        self.assertFalse(self.undo.can_undo())
        self.assertEqual(self.hotlinks(), [])
        self.assertEqual(self.named_views(), [9])
        self.assertEqual(self.model(), [("namedview", "9", None)])
        self.assertEqual(self.failed_mutations, [])

    def test_hotlink_undo_refused_when_named_view_uid_belongs_to_another_page(self):
        self.delete("hotlink:1")
        for annotation in self.data.annotations:
            if annotation.uid == "5":
                annotation.page_uid = "8"
        self.sync()
        before = self.model()
        warning = self.undo_expecting_warning()
        self.assert_hotlink_restore_refused(warning, before)

    def hotlink_spec(self, target):
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )

        return InsertAnnotationSpec(
            page_uid=self.PAGE,
            annotation_type="hotlink",
            position=[40.0, 40.0],
            color="#ff0000",
            width=1.0,
            properties={"BidPageViewUID": target},
        )

    def bid_ref(self):
        return FakeUiState().get_selected_bid_ref()

    def test_hotlink_placement_redo_follows_named_view_restored_by_cascade_delete(self):
        # Place a second Hot Link on Named View 5, then delete the Named View;
        # confirming removes both links and the view in one history entry.
        placed = self.handler._insert_annotations_with_undo(
            self.bid_ref(), [self.hotlink_spec("5")]
        )
        self.assertEqual(placed, ["2"])
        self.sync()
        self.assertEqual(self.hotlinks(), [(1, 5), (2, 5)])
        self.assertTrue(self.delete("namedview:5").called)
        self.assertEqual(self.hotlinks(), [])
        self.undo.undo()
        self.undo.undo()
        self.sync()
        # Restoring the cascade gave the Named View a new UID; the placement was
        # undone, so only the cascade-restored link remains.
        self.assertEqual(self.named_views(), [9, 10])
        self.assertEqual([view for _uid, view in self.hotlinks()], [10])
        self.undo.redo()
        self.sync()
        self.assertEqual(self.failed_mutations, [])
        self.assertEqual([view for _uid, view in self.hotlinks()], [10, 10])
        self.assertTrue(
            all(
                a.properties["BidPageViewUID"] == "10"
                for a in self.data.annotations
                if a.annotation_type == ANNOTATION_TYPE_HOTLINK
            )
        )
        self.warning.assert_not_called()

    def test_hotlink_paste_redo_follows_named_view_restored_by_cascade_delete(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.collaboration_resource_catalog import (
            annotation_resource_id,
        )

        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            annotation_source_uids=(annotation_resource_id("hotlink", "1"),),
            annotation_specs=(self.hotlink_spec("5"),),
        )
        self.handler._execute_mdb_plan_items_paste_payload(self.bid_ref(), payload, ())
        self.sync()
        self.assertEqual(self.hotlinks(), [(1, 5), (2, 5)])
        self.assertTrue(self.delete("namedview:5").called)
        self.assertEqual(self.hotlinks(), [])
        self.undo.undo()
        self.undo.undo()
        self.sync()
        self.assertEqual(self.named_views(), [9, 10])
        self.assertEqual([view for _uid, view in self.hotlinks()], [10])
        self.undo.redo()
        self.sync()
        self.assertEqual(self.failed_mutations, [])
        self.assertEqual([view for _uid, view in self.hotlinks()], [10, 10])
        self.warning.assert_not_called()

    def test_paste_redo_of_named_view_with_its_hotlink_keeps_same_batch_remap(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.collaboration_resource_catalog import (
            annotation_resource_id,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )

        view_copy = InsertAnnotationSpec(
            page_uid=self.PAGE,
            annotation_type="namedview",
            position=[100.0, 100.0, 110.0, 110.0],
            color="#ff0000",
            width=1.0,
            properties={"Text": "A copy"},
        )
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            annotation_source_uids=(
                annotation_resource_id("namedview", "5"),
                annotation_resource_id("hotlink", "1"),
            ),
            annotation_specs=(view_copy, self.hotlink_spec("5")),
        )
        self.handler._execute_mdb_plan_items_paste_payload(self.bid_ref(), payload, ())
        self.sync()
        # The pasted link belongs to the pasted copy (10), not the original (5).
        self.assertEqual(self.named_views(), [5, 9, 10])
        self.assertEqual(self.hotlinks(), [(1, 5), (2, 10)])
        # Deleting the original view cascades to its own link only.
        self.assertTrue(self.delete("namedview:5").called)
        self.assertEqual(self.named_views(), [9, 10])
        self.assertEqual(self.hotlinks(), [(2, 10)])
        self.undo.undo()
        self.undo.undo()
        self.sync()
        self.assertEqual(self.named_views(), [9, 11])
        self.assertEqual(self.hotlinks(), [(3, 11)])
        self.undo.redo()
        self.sync()
        # The redone paste creates a fresh copy; its link must target that copy,
        # not the original Named View that was restored under UID 11.
        self.assertEqual(self.failed_mutations, [])
        self.assertEqual(self.named_views(), [9, 11, 12])
        self.assertEqual(self.hotlinks(), [(3, 11), (4, 12)])
        self.warning.assert_not_called()

    def test_hotlink_undo_refused_when_named_view_vanished_without_lifetime_event(
        self,
    ):
        self.delete("hotlink:1")
        # The Named View disappears from the database and model without any
        # lifetime event, so the retained target still looks available.
        self.ops.delete_annotations("bid.mdb", [("5", "namedview")])
        self.data.annotations = [a for a in self.data.annotations if a.uid != "5"]
        self.sync()
        before = self.model()
        warning = self.undo_expecting_warning()
        self.assert_hotlink_restore_refused(warning, before)
        self.assertEqual(self.named_views(), [9])

    def test_hotlink_undo_with_live_named_view_restores_target(self):
        # Positive control: the same Hot Link undo succeeds when its Named View
        # was never deleted, so the refusals above come from the missing Named View.
        self.delete("hotlink:1")
        self.undo.undo()
        self.sync()
        self.assertEqual(self.failed_mutations, [])
        self.assertEqual(self.hotlinks(), [(1, 5)])
        self.assertIn(("hotlink", "1", "5"), self.model())
        self.warning.assert_not_called()
