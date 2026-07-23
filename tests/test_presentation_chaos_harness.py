import os
import random
import traceback
import unittest
from dataclasses import dataclass, field

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from test_plan_view_action_handler import (
    FakeAccess,
    FakeAnnotationWriteService,
    FakeDeferredPersistence,
    FakeEventBus,
    FakePageSettingsBar,
    FakePlanView,
    FakeProjectData,
    FakeUiState,
    FakeUndoService,
    FakeWriteService,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeMainWindow as CoordinatorFakeMainWindow,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeMeshAccess as CoordinatorFakeMeshAccess,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeMeshPlanSignaler as CoordinatorFakeMeshPlanSignaler,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeMeshReceiver as CoordinatorFakeMeshReceiver,
)
from test_ui_event_coordinator_takeoffs_changed import FakeNav as CoordinatorFakeNav
from test_ui_event_coordinator_takeoffs_changed import (
    FakePageSettingsBar as CoordinatorFakePageSettingsBar,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakePlacement as CoordinatorFakePlacement,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeProjectData as CoordinatorFakeProjectData,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeSidebar as CoordinatorFakeSidebar,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeTakeoffSidebar as CoordinatorFakeTakeoffSidebar,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeToolbar as CoordinatorFakeToolbar,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeUiState as CoordinatorFakeUiState,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeViewer as CoordinatorFakeViewer,
)
from test_ui_event_coordinator_takeoffs_changed import (
    FakeVisualization as CoordinatorFakeVisualization,
)
from test_ui_event_coordinator_takeoffs_changed import configure_mesh_state
from test_viewer_sync_coordinator_overlay_refresh import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshSceneIdentity
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.annotation_view import AnnotationView
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.handlers import (
    plan_view_action_handler as action_handler_module,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_SELECT,
)

DEFAULT_CHAOS_SEEDS = (101, 202, 303, 404, 505)
DEFAULT_CHAOS_STEPS = 35


def _app():
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


@dataclass
class ChaosState:
    rng: random.Random
    bid_ref: BidRef = field(default_factory=lambda: BidRef("chaos.mdb", "bid-1"))
    pages: list[Page] = field(default_factory=list)
    conditions: dict[str, Condition] = field(default_factory=dict)
    takeoffs_by_page: dict[str, list[Takeoff]] = field(default_factory=dict)
    annotations_by_page: dict[str, list[BidAnnotation]] = field(default_factory=dict)
    hidden_layer_uids: set[str] = field(default_factory=set)
    active_page_uid: str = ""
    deleted_takeoff_uids: set[str] = field(default_factory=set)
    deleted_annotation_uids: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, seed: int) -> "ChaosState":
        rng = random.Random(seed)
        state = cls(rng=rng)
        state.pages = []
        for index in range(1, 4):
            source_dir = "A" if index != 2 else "B"
            state.pages.append(
                Page(
                    uid=f"p{index}",
                    name=f"Page {index}",
                    width_pts=612.0 + index,
                    height_pts=792.0 + index,
                    image_path=f"plans/{source_dir}/shared-sheet.png",
                    sequence=index,
                )
            )
        state.active_page_uid = state.pages[0].uid
        state.conditions = {
            "area": Condition(
                uid="area",
                name="Area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
            ),
            "linear": Condition(
                uid="linear",
                name="Linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            ),
            "count": Condition(
                uid="count",
                name="Count",
                condition_type=Condition.TYPE_COUNT,
                layer_visible=True,
            ),
        }
        for index, page in enumerate(state.pages, start=1):
            uid_base = index * 100
            state.takeoffs_by_page[page.uid] = [
                Takeoff(
                    uid=str(uid_base + 1),
                    condition_uid="area",
                    page_uid=page.uid,
                    position=[10.0, 10.0, 80.0, 10.0, 80.0, 70.0, 10.0, 70.0],
                ),
                Takeoff(
                    uid=str(uid_base + 2),
                    condition_uid="linear",
                    page_uid=page.uid,
                    position=[25.0, 120.0, 125.0, 120.0],
                ),
                Takeoff(
                    uid=str(uid_base + 3),
                    condition_uid="count",
                    page_uid=page.uid,
                    position=[45.0, 155.0],
                ),
            ]
            named_view_uid = f"{page.uid}-named"
            state.annotations_by_page[page.uid] = [
                BidAnnotation(
                    uid=f"{page.uid}-text",
                    annotation_type=ANNOTATION_TYPE_TEXT,
                    page_uid=page.uid,
                    position=[120.0, 60.0, 80.0, 24.0],
                    properties={
                        "Text": f"Note {page.uid}",
                        "FontName": "Arial",
                        "FontColor": 0,
                        "FontSize": 12,
                    },
                ),
                BidAnnotation(
                    uid=named_view_uid,
                    annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
                    page_uid=page.uid,
                    position=[
                        10.0,
                        10.0,
                        80.0,
                        10.0,
                        10.0,
                        70.0,
                        80.0,
                        70.0,
                        0.0,
                    ],
                    properties={"Text": f"View {page.uid}"},
                ),
                BidAnnotation(
                    uid=f"{page.uid}-hotlink",
                    annotation_type=ANNOTATION_TYPE_HOTLINK,
                    page_uid=page.uid,
                    position=[160.0, 80.0],
                    properties={"BidPageViewUID": named_view_uid},
                ),
                BidAnnotation(
                    uid=f"{page.uid}-hotlink-empty",
                    annotation_type=ANNOTATION_TYPE_HOTLINK,
                    page_uid=page.uid,
                    position=[190.0, 80.0],
                    properties={},
                ),
            ]
        return state

    @property
    def active_page(self) -> Page:
        return next(page for page in self.pages if page.uid == self.active_page_uid)

    def active_takeoffs(self) -> list[Takeoff]:
        return list(self.takeoffs_by_page.get(self.active_page_uid, []))

    def active_annotations(self) -> list[BidAnnotation]:
        return list(self.annotations_by_page.get(self.active_page_uid, []))

    def current_page_uids(self) -> set[str]:
        return {takeoff.uid for takeoff in self.active_takeoffs()} | {
            annotation.uid for annotation in self.active_annotations()
        }

    def linked_hotlink_targets(self) -> set[str]:
        return {
            str(annotation.properties.get("BidPageViewUID") or "")
            for annotations in self.annotations_by_page.values()
            for annotation in annotations
            if annotation.annotation_type == ANNOTATION_TYPE_HOTLINK
        }


class PresentationChaosHarness:
    def __init__(self, seed: int, test_case: unittest.TestCase):
        self.seed = seed
        self.test_case = test_case
        self.state = ChaosState.build(seed)
        self.history: list[ChaosActionResult] = []
        self.takeoff_renderer = RecordingPathTakeoffRenderer()
        self.rendering_service = FakeRenderingService()
        self.copy_requests: list[list[str]] = []
        self.paste_requests = 0
        self.view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=self.rendering_service,
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=self.takeoff_renderer,
            annotation_renderer=FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        self.view.resize(360, 260)
        self.view.set_selection_enabled(True)
        self.view.set_annotation_placement_allowed_fn(lambda: True)
        self.view.copy_requested.connect(self._record_copy_request)
        self.view.paste_requested.connect(self._record_paste_request)
        self._load_active_page()

    def cleanup(self) -> None:
        self.view.cleanup()
        _app().processEvents()

    def _record_paste_request(self) -> None:
        self.paste_requests += 1

    def _record_copy_request(self, uids: list[str]) -> None:
        copied = [str(uid) for uid in uids]
        stale = set(copied) - self.state.current_page_uids()
        if stale:
            raise AssertionError(f"copy request included stale uids: {sorted(stale)}")
        self.copy_requests.append(copied)

    def run_random_actions(self, steps: int) -> None:
        for index in range(steps):
            action = self.state.rng.choice(self._random_actions())
            self._run_action(index, action)

    def run_sequence(self, names: list[str]) -> None:
        actions = {
            action.__name__.replace("action_", ""): action
            for action in self._all_actions()
        }
        for index, name in enumerate(names):
            self._run_action(index, actions[name])

    def _run_action(self, index: int, action) -> None:
        try:
            result = action()
            self.history.append(result)
            self._pump_events()
            self._assert_invariants()
        except Exception as exc:
            self.test_case.fail(self._failure_message(index, action.__name__, exc))

    def _all_actions(self):
        return [
            self.action_switch_page,
            self.action_reload_page,
            self.action_refresh_overlays,
            self.action_select_one_current_item,
            self.action_multi_select_current_items,
            self.action_select_all,
            self.action_clear_selection,
            self.action_copy_selected,
            self.action_paste_requested,
            self.action_delete_selected_from_model,
            self.action_delete_named_view_and_linked_hotlinks,
            self.action_toggle_annotation_layer,
            self.action_enter_annotation_placement,
            self.action_cancel_placement,
            self.action_mouse_move_during_placement,
            self.action_resize_viewport,
            self.action_apply_pending_visible_state,
        ]

    def _random_actions(self):
        return self._all_actions()

    def _load_active_page(self) -> None:
        page = self.state.active_page
        loaded = self.view.load_page(
            page,
            self.state.active_takeoffs(),
            self.state.conditions,
            {},
            bid_ref=self.state.bid_ref,
            annotations=self.state.active_annotations(),
            hidden_layer_uids=self.state.hidden_layer_uids,
        )
        if not loaded:
            raise AssertionError(f"load_page returned False for {page.uid}")

    def _refresh_active_page(self) -> bool:
        return bool(
            self.view.refresh_current_page_overlays(
                self.state.active_page,
                self.state.active_takeoffs(),
                self.state.conditions,
                {},
                bid_ref=self.state.bid_ref,
                annotations=self.state.active_annotations(),
                hidden_layer_uids=self.state.hidden_layer_uids,
            )
        )

    def _pump_events(self) -> None:
        app = _app()
        for _ in range(2):
            app.processEvents()
        while self.rendering_service.page_requests:
            request_id, request = self.rendering_service.page_requests.pop(0)
            callback = request.get("callback")
            if callback:
                callback(
                    RenderResult(
                        request_id,
                        True,
                        QImage(240, 320, QImage.Format.Format_ARGB32),
                        None,
                    )
                )
            app.processEvents()

    def action_switch_page(self) -> ChaosActionResult:
        pages = [page.uid for page in self.state.pages]
        current_index = pages.index(self.state.active_page_uid)
        next_index = (current_index + 1 + self.state.rng.randrange(len(pages))) % len(
            pages
        )
        self.state.active_page_uid = pages[next_index]
        self._load_active_page()
        return ChaosActionResult("switch_page", self.state.active_page_uid)

    def action_reload_page(self) -> ChaosActionResult:
        self._load_active_page()
        return ChaosActionResult("reload_page", self.state.active_page_uid)

    def action_refresh_overlays(self) -> ChaosActionResult:
        refreshed = self._refresh_active_page()
        return ChaosActionResult("refresh_overlays", str(refreshed))

    def action_select_one_current_item(self) -> ChaosActionResult:
        uids = sorted(self.state.current_page_uids())
        if not uids:
            return ChaosActionResult("select_one_current_item", "no-op")
        uid = self.state.rng.choice(uids)
        self.view.set_selected_uids({uid})
        return ChaosActionResult("select_one_current_item", uid)

    def action_multi_select_current_items(self) -> ChaosActionResult:
        uids = sorted(self.state.current_page_uids())
        if len(uids) < 2:
            return ChaosActionResult("multi_select_current_items", "no-op")
        count = self.state.rng.randint(2, len(uids))
        selected = set(self.state.rng.sample(uids, count))
        self.view.set_selected_uids(selected)
        return ChaosActionResult(
            "multi_select_current_items", ",".join(sorted(selected))
        )

    def action_select_all(self) -> ChaosActionResult:
        self.view.select_all()
        return ChaosActionResult("select_all", ",".join(self.view.get_selected_uids()))

    def action_clear_selection(self) -> ChaosActionResult:
        self.view.clear_selection()
        return ChaosActionResult("clear_selection")

    def action_copy_selected(self) -> ChaosActionResult:
        before = len(self.copy_requests)
        self.view.copy_selected()
        return ChaosActionResult(
            "copy_selected", f"emitted={len(self.copy_requests) > before}"
        )

    def action_paste_requested(self) -> ChaosActionResult:
        before = self.paste_requests
        self.view.paste_clipboard()
        return ChaosActionResult(
            "paste_requested", f"emitted={self.paste_requests > before}"
        )

    def action_delete_selected_from_model(self) -> ChaosActionResult:
        selected = set(self.view.get_selected_uids())
        if not selected:
            return ChaosActionResult("delete_selected_from_model", "no-op")
        page_uid = self.state.active_page_uid
        before_takeoffs = self.state.takeoffs_by_page[page_uid]
        before_annotations = self.state.annotations_by_page[page_uid]
        selected_named_views = {
            annotation.uid
            for annotation in before_annotations
            if annotation.uid in selected
            and annotation.annotation_type == ANNOTATION_TYPE_NAMED_VIEW
        }
        if selected_named_views:
            selected.update(
                annotation.uid
                for annotation in before_annotations
                if annotation.annotation_type == ANNOTATION_TYPE_HOTLINK
                and annotation.properties.get("BidPageViewUID") in selected_named_views
            )
        self.state.takeoffs_by_page[page_uid] = [
            takeoff for takeoff in before_takeoffs if takeoff.uid not in selected
        ]
        self.state.annotations_by_page[page_uid] = [
            annotation
            for annotation in before_annotations
            if annotation.uid not in selected
        ]
        self.state.deleted_takeoff_uids.update(
            takeoff.uid for takeoff in before_takeoffs if takeoff.uid in selected
        )
        self.state.deleted_annotation_uids.update(
            annotation.uid
            for annotation in before_annotations
            if annotation.uid in selected
        )
        self._load_active_page()
        return ChaosActionResult(
            "delete_selected_from_model", ",".join(sorted(selected))
        )

    def action_delete_named_view_and_linked_hotlinks(self) -> ChaosActionResult:
        page_uid = self.state.active_page_uid
        named_views = [
            annotation
            for annotation in self.state.annotations_by_page[page_uid]
            if annotation.annotation_type == ANNOTATION_TYPE_NAMED_VIEW
        ]
        if not named_views:
            return ChaosActionResult("delete_named_view_and_linked_hotlinks", "no-op")
        named_view = self.state.rng.choice(named_views)
        delete_uids = {
            named_view.uid,
            *[
                annotation.uid
                for annotation in self.state.annotations_by_page[page_uid]
                if annotation.annotation_type == ANNOTATION_TYPE_HOTLINK
                and annotation.properties.get("BidPageViewUID") == named_view.uid
            ],
        }
        self.state.annotations_by_page[page_uid] = [
            annotation
            for annotation in self.state.annotations_by_page[page_uid]
            if annotation.uid not in delete_uids
        ]
        self.state.deleted_annotation_uids.update(delete_uids)
        self._load_active_page()
        return ChaosActionResult(
            "delete_named_view_and_linked_hotlinks", ",".join(sorted(delete_uids))
        )

    def action_toggle_annotation_layer(self) -> ChaosActionResult:
        if "annotation-layer" in self.state.hidden_layer_uids:
            self.state.hidden_layer_uids.remove("annotation-layer")
        else:
            self.state.hidden_layer_uids.add("annotation-layer")
        self._refresh_active_page()
        return ChaosActionResult(
            "toggle_annotation_layer",
            "hidden" if self.state.hidden_layer_uids else "visible",
        )

    def action_enter_annotation_placement(self) -> ChaosActionResult:
        annotation_type = self.state.rng.choice(
            [ANNOTATION_TYPE_TEXT, ANNOTATION_TYPE_HOTLINK, ANNOTATION_TYPE_NAMED_VIEW]
        )
        activated = self.view.activate_annotation_placement(annotation_type)
        return ChaosActionResult(
            "enter_annotation_placement", f"{annotation_type}={activated}"
        )

    def action_cancel_placement(self) -> ChaosActionResult:
        self.view.cancel_place_mode()
        return ChaosActionResult("cancel_placement")

    def action_mouse_move_during_placement(self) -> ChaosActionResult:
        pos = QtCore.QPoint(
            self.state.rng.randint(5, 220),
            self.state.rng.randint(5, 180),
        )
        self.view._last_mouse_vp_pos = pos
        if self.view.annotation_place_type:
            self.view.update_annotation_place_preview(self.view.mapToScene(pos))
        return ChaosActionResult("mouse_move_during_placement", f"{pos.x()},{pos.y()}")

    def action_resize_viewport(self) -> ChaosActionResult:
        width = self.state.rng.randint(220, 640)
        height = self.state.rng.randint(180, 520)
        self.view.resize(width, height)
        return ChaosActionResult("resize_viewport", f"{width}x{height}")

    def action_apply_pending_visible_state(self) -> ChaosActionResult:
        TakeoffPlanView._apply_pending_visible_view_state(self.view)
        return ChaosActionResult("apply_pending_visible_state")

    def _assert_invariants(self) -> None:
        view = self.view
        current_page_uid = view.current_page_uid
        if current_page_uid != self.state.active_page_uid:
            raise AssertionError(
                f"loaded page {current_page_uid!r} does not match model "
                f"{self.state.active_page_uid!r}"
            )
        selected = set(view.get_selected_uids())
        unknown_selected = selected - self.state.current_page_uids()
        if unknown_selected:
            raise AssertionError(
                f"selected stale/non-current uids: {sorted(unknown_selected)}"
            )
        deleted_selected = selected & (
            self.state.deleted_takeoff_uids | self.state.deleted_annotation_uids
        )
        if deleted_selected:
            raise AssertionError(f"selected deleted uids: {sorted(deleted_selected)}")
        for uid in selected:
            if uid not in view._uid_to_items:
                raise AssertionError(f"selected uid {uid!r} has no rendered items")
        for uid, takeoff in view._current_takeoffs.items():
            if takeoff.page_uid != self.state.active_page_uid:
                raise AssertionError(f"takeoff {uid!r} loaded from wrong page")
        for uid, annotation in view._current_annotations.items():
            if annotation.page_uid != self.state.active_page_uid:
                raise AssertionError(f"annotation {uid!r} loaded from wrong page")
        for uid, items in view._uid_to_items.items():
            if uid not in (
                view._current_takeoffs.keys() | view._current_annotations.keys()
            ):
                raise AssertionError(f"rendered uid {uid!r} is not in current model")
            if len({id(item) for item in items}) != len(items):
                raise AssertionError(f"duplicate item object stored for uid {uid!r}")
            for item in items:
                if item.scene() is not view._scene:
                    raise AssertionError(
                        f"item for uid {uid!r} is not in the plan scene"
                    )
        target_uids = {
            annotation.uid
            for annotations in self.state.annotations_by_page.values()
            for annotation in annotations
            if annotation.annotation_type == ANNOTATION_TYPE_NAMED_VIEW
        }
        orphan_targets = self.state.linked_hotlink_targets() - target_uids - {""}
        if orphan_targets:
            raise AssertionError(
                f"orphan hotlink target uids: {sorted(orphan_targets)}"
            )
        if (
            view._cursor_mode != CURSOR_MODE_ANNOTATION_PLACE
            and view.annotation_place_type
        ):
            raise AssertionError(
                f"annotation place type {view.annotation_place_type!r} "
                f"left active in cursor mode {view._cursor_mode!r}"
            )
        if view._cursor_mode == CURSOR_MODE_SELECT and view._place_preview_items:
            raise AssertionError("select mode retained placement preview items")
        if view._applying_pending_visible_view_state:
            raise AssertionError("pending visible view state guard left active")

    def _failure_message(self, index: int, action_name: str, exc: BaseException) -> str:
        recent = [entry.describe() for entry in self.history[-15:]]
        current = {
            "seed": self.seed,
            "action_index": index,
            "action": action_name.replace("action_", ""),
            "active_page": self.state.active_page_uid,
            "view_page": self.view.current_page_uid,
            "selected": self.view.get_selected_uids(),
            "cursor_mode": self.view._cursor_mode,
            "annotation_place_type": self.view.annotation_place_type,
            "current_takeoffs": sorted(self.view._current_takeoffs),
            "current_annotations": sorted(self.view._current_annotations),
        }
        return (
            "Presentation chaos harness failure\n"
            f"Current state: {current}\n"
            f"Recent actions: {recent}\n"
            f"Exception: {exc!r}\n"
            f"{traceback.format_exc()}"
        )


class PresentationChaosHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _run_harness(self, seed: int, steps: int) -> None:
        harness = PresentationChaosHarness(seed, self)
        try:
            harness.run_random_actions(steps)
        finally:
            harness.cleanup()

    def test_plan_view_chaos_default_seeds(self):
        steps = _env_int("PRESENTATION_CHAOS_STEPS", DEFAULT_CHAOS_STEPS)
        for seed in _configured_seeds():
            with self.subTest(seed=seed, steps=steps):
                self._run_harness(seed, steps)

    def test_known_sequence_page_switch_drops_stale_selection(self):
        harness = PresentationChaosHarness(9001, self)
        try:
            harness.run_sequence(
                [
                    "select_all",
                    "switch_page",
                    "refresh_overlays",
                    "apply_pending_visible_state",
                ]
            )
            self.assertEqual(set(harness.view.get_selected_uids()), set())
        finally:
            harness.cleanup()

    def test_known_sequence_named_view_delete_removes_linked_hotlink(self):
        harness = PresentationChaosHarness(9002, self)
        try:
            harness.run_sequence(
                [
                    "delete_named_view_and_linked_hotlinks",
                    "refresh_overlays",
                    "switch_page",
                    "switch_page",
                ]
            )
        finally:
            harness.cleanup()

    def test_known_sequence_cancel_placement_clears_preview_and_mode(self):
        harness = PresentationChaosHarness(9003, self)
        try:
            harness.run_sequence(
                [
                    "enter_annotation_placement",
                    "mouse_move_during_placement",
                    "resize_viewport",
                    "cancel_placement",
                    "apply_pending_visible_state",
                ]
            )
            self.assertEqual(harness.view._cursor_mode, CURSOR_MODE_SELECT)
            self.assertIsNone(harness.view.annotation_place_type)
            self.assertEqual(harness.view._place_preview_items, [])
        finally:
            harness.cleanup()


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
        self.undo = FakeUndoService()
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
            _app().processEvents()
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
        if self.undo.undo is None:
            return ChaosActionResult("undo", "no-op")
        self.undo.undo()
        return ChaosActionResult("undo")

    def action_redo(self) -> ChaosActionResult:
        if self.undo.redo is None:
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
        cls.app = _app()

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


class CoordinatorChaosPlanView:
    def __init__(self):
        self.reset_ctrl_held_calls = 0

    def reset_ctrl_held(self):
        self.reset_ctrl_held_calls += 1


class UIEventCoordinatorChaosHarness:
    def __init__(self, seed: int, test_case: unittest.TestCase):
        self.seed = seed
        self.test_case = test_case
        self.rng = random.Random(seed)
        self.history: list[ChaosActionResult] = []
        self.coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        self.coordinator.ui_state_manager = CoordinatorFakeUiState()
        self.active_bid_ref = BidRef("chaos.mdb", "bid-1")
        self.coordinator.project_data = CoordinatorFakeProjectData()
        self.coordinator.takeoff_sidebar = CoordinatorFakeTakeoffSidebar()
        self.coordinator._page_settings_bar = CoordinatorFakePageSettingsBar()
        self.coordinator._viewer = CoordinatorFakeViewer()
        self.coordinator._sidebar = CoordinatorFakeSidebar()
        self.coordinator._toolbar = CoordinatorFakeToolbar()
        self.coordinator.main_window = CoordinatorFakeMainWindow()
        self.coordinator._placement = CoordinatorFakePlacement()
        self.coordinator._is_cleaning_up = False
        self.coordinator._nav = CoordinatorFakeNav()
        self.coordinator.ui_access_manager = CoordinatorFakeMeshAccess()
        self.coordinator._plan_view_signaler = CoordinatorFakeMeshPlanSignaler()
        self.coordinator.plan_view = CoordinatorChaosPlanView()
        self.coordinator._pending_hotlink_page_uid = None
        self.coordinator._pending_hotlink_named_view = None
        self.coordinator._last_mesh_scene = None
        self.coordinator._update_page_info_status = self._record_page_info_update
        self.page_info_updates = 0
        configure_mesh_state(
            self.coordinator,
            visualization=CoordinatorFakeVisualization(),
            opengl_viewer=CoordinatorFakeMeshReceiver(),
        )
        self.known_pages = {"page-1", "page-2"}

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
            self.action_takeoffs_changed_active_page,
            self.action_takeoffs_changed_other_page,
            self.action_annotations_changed_active_page,
            self.action_annotations_changed_no_page,
            self.action_clear_selected_pages,
            self.action_restore_selected_pages,
            self.action_switch_to_3d_view,
            self.action_switch_to_2d_view,
            self.action_native_scene_updated,
            self.action_toggle_detached_mesh,
        ]

    def _run_action(self, index: int, action) -> None:
        try:
            result = action()
            self.history.append(result)
            _app().processEvents()
            self._assert_invariants()
        except Exception as exc:
            self.test_case.fail(self._failure_message(index, action.__name__, exc))

    def _record_page_info_update(self):
        self.page_info_updates += 1

    def action_takeoffs_changed_active_page(self) -> ChaosActionResult:
        self.coordinator._on_takeoffs_changed(
            page_uid="page-1",
            takeoff_uids=["t-1"],
            condition_uids=["c-1"],
        )
        return ChaosActionResult("takeoffs_changed_active_page")

    def action_takeoffs_changed_other_page(self) -> ChaosActionResult:
        self.coordinator._on_takeoffs_changed(
            page_uid="page-2",
            takeoff_uids=["t-2"],
            condition_uids=["c-2"],
        )
        return ChaosActionResult("takeoffs_changed_other_page")

    def action_annotations_changed_active_page(self) -> ChaosActionResult:
        self.coordinator._on_annotations_changed(
            page_uid="page-1",
            annotation_uids=["ann-1"],
            annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        return ChaosActionResult("annotations_changed_active_page")

    def action_annotations_changed_no_page(self) -> ChaosActionResult:
        self.coordinator._on_annotations_changed(
            page_uid="",
            annotation_uids=["ann-empty"],
            annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        return ChaosActionResult("annotations_changed_no_page")

    def action_clear_selected_pages(self) -> ChaosActionResult:
        self.coordinator.project_data.selected_page_uids = []
        return ChaosActionResult("clear_selected_pages")

    def action_restore_selected_pages(self) -> ChaosActionResult:
        self.coordinator.project_data.selected_page_uids = ["page-1"]
        return ChaosActionResult("restore_selected_pages")

    def action_switch_to_3d_view(self) -> ChaosActionResult:
        self.coordinator._view_stack.setCurrentIndex(0)
        self.coordinator._on_view_stack_changed(0)
        return ChaosActionResult("switch_to_3d_view")

    def action_switch_to_2d_view(self) -> ChaosActionResult:
        self.coordinator._view_stack.setCurrentIndex(1)
        self.coordinator._on_view_stack_changed(1)
        return ChaosActionResult("switch_to_2d_view")

    def action_native_scene_updated(self) -> ChaosActionResult:
        with unittest.mock.patch.object(
            self.coordinator.ui_state_manager,
            "get_selected_bid_ref",
            return_value=self.active_bid_ref,
        ):
            self.coordinator._on_native_scene_updated(
                geometries=[],
                scene_identity=MeshSceneIdentity(
                    self.active_bid_ref,
                    tuple(self.coordinator.project_data.get_selected_page_uids()),
                    1,
                ),
                scene_failed=False,
            )
        return ChaosActionResult("native_scene_updated")

    def action_toggle_detached_mesh(self) -> ChaosActionResult:
        if self.coordinator._mesh_window is None:
            self.coordinator._mesh_window = CoordinatorFakeMeshReceiver(visible=True)
            state = "open"
        else:
            self.coordinator._mesh_window = None
            state = "closed"
        return ChaosActionResult("toggle_detached_mesh", state)

    def _assert_invariants(self) -> None:
        dirty_pages = set(self.coordinator._dirty_mesh_page_uids)
        unknown_dirty_pages = dirty_pages - self.known_pages
        if unknown_dirty_pages:
            raise AssertionError(
                f"dirty mesh pages are unknown: {sorted(unknown_dirty_pages)}"
            )
        selected_pages = set(self.coordinator.project_data.selected_page_uids)
        unknown_selected_pages = selected_pages - self.known_pages
        if unknown_selected_pages:
            raise AssertionError(
                f"selected mesh pages are unknown: {sorted(unknown_selected_pages)}"
            )
        invalid_plan_pages = [
            page_uid
            for page_uid in self.coordinator._viewer.plan_pages
            if page_uid not in self.known_pages and page_uid != "active"
        ]
        if invalid_plan_pages:
            raise AssertionError(
                f"viewer refreshed invalid plan pages: {invalid_plan_pages}"
            )
        if self.coordinator._view_stack.currentIndex() == 0:
            if self.coordinator._placement.is_active:
                raise AssertionError("placement stayed active after switching to 3D")
            if self.coordinator.ui_state_manager.place_condition_uid is not None:
                raise AssertionError("place condition stayed set after switching to 3D")
        for pages in self.coordinator.visualization_service.mesh_pages:
            unknown_pages = set(pages) - self.known_pages
            if unknown_pages:
                raise AssertionError(f"mesh refresh requested unknown pages: {pages}")
        if (
            not self.coordinator._mesh_scene_dirty
            and self.coordinator._dirty_mesh_page_uids
        ):
            raise AssertionError(
                "dirty mesh page set remained after mesh state was clean"
            )

    def _failure_message(self, index: int, action_name: str, exc: BaseException) -> str:
        return (
            "UI event coordinator chaos harness failure\n"
            f"Current state: {{'seed': {self.seed}, 'action_index': {index}, "
            f"'action': {action_name.replace('action_', '')!r}, "
            f"'view_index': {self.coordinator._view_stack.currentIndex()}, "
            f"'selected_pages': {self.coordinator.project_data.selected_page_uids}, "
            f"'plan_pages': {self.coordinator._viewer.plan_pages[-10:]}, "
            f"'mesh_pages': {self.coordinator.visualization_service.mesh_pages[-10:]}, "
            f"'mesh_dirty': {self.coordinator._mesh_scene_dirty}, "
            f"'dirty_pages': {sorted(self.coordinator._dirty_mesh_page_uids)}, "
            f"'pending_dirty_refresh': {self.coordinator._pending_dirty_mesh_refresh}}}\n"
            f"Recent actions: {[entry.describe() for entry in self.history[-15:]]}\n"
            f"Exception: {exc!r}\n"
            f"{traceback.format_exc()}"
        )


class UIEventCoordinatorChaosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_ui_event_coordinator_chaos_default_seeds(self):
        steps = _env_int("PRESENTATION_CHAOS_STEPS", DEFAULT_CHAOS_STEPS)
        for seed in _configured_seeds()[:3]:
            with self.subTest(seed=seed, steps=steps):
                harness = UIEventCoordinatorChaosHarness(seed + 6500, self)
                harness.run_random_actions(steps)

    def test_known_sequence_dirty_2d_changes_flush_when_3d_opens(self):
        harness = UIEventCoordinatorChaosHarness(9651, self)
        harness.run_sequence(
            [
                "switch_to_2d_view",
                "takeoffs_changed_active_page",
                "switch_to_3d_view",
                "native_scene_updated",
            ]
        )
        self.assertFalse(harness.coordinator._mesh_scene_dirty)
        self.assertFalse(harness.coordinator._pending_dirty_mesh_refresh)
        self.assertEqual(harness.coordinator._dirty_mesh_page_uids, set())

    def test_known_sequence_no_selected_pages_publishes_empty_mesh_scene(self):
        harness = UIEventCoordinatorChaosHarness(9652, self)
        harness.run_sequence(
            [
                "clear_selected_pages",
                "takeoffs_changed_active_page",
            ]
        )
        visualization = harness.coordinator.visualization_service
        self.assertEqual(visualization.mesh_pages, [[]])
        self.assertEqual(visualization.cancelled_mesh_refreshes, 0)


class DeferredChaosWriteService:
    def __init__(self):
        self.calls: list[tuple] = []
        self.fail_next = False
        self.expected_blocked = False

    def is_expected_deferred_write_blocked(self, _db_path):
        return self.expected_blocked

    def _record(self, call):
        self.calls.append(call)
        if self.fail_next:
            self.fail_next = False
            return False
        return True

    def save_page_view_state(self, db_path, page_uid, zoom_fac, current_x, current_y):
        return self._record(
            ("page_view_state", db_path, page_uid, zoom_fac, current_x, current_y)
        )

    def save_bid_selected_page(self, db_path, bid_uid, page_uid):
        return self._record(("bid_selected_page", db_path, bid_uid, page_uid))

    def update_layer_show(
        self,
        db_path,
        layer_uid,
        show,
        publish_database_refreshed_after_write=True,
    ):
        return self._record(
            (
                "layer_show",
                db_path,
                layer_uid,
                show,
                publish_database_refreshed_after_write,
            )
        )


class SilentChaosLogger:
    def warning(self, *_args, **_kwargs):
        pass


class DeferredPersistenceChaosHarness:
    def __init__(self, seed: int, test_case: unittest.TestCase):
        self.seed = seed
        self.test_case = test_case
        self.rng = random.Random(seed)
        self.history: list[ChaosActionResult] = []
        self.service = DeferredChaosWriteService()
        self.manager = DeferredPersistenceManager(
            self.service, logger_=SilentChaosLogger()
        )
        self.deleted_bid_uids: set[str] = set()
        self.last_failed_flush = False

    def cleanup(self) -> None:
        self.service.expected_blocked = True
        self.manager.cleanup()
        _app().processEvents()

    def run_random_actions(self, steps: int) -> None:
        for index in range(steps):
            action = self.rng.choice(self._all_actions())
            self._run_action(index, action)

    def run_sequence(self, names: list[str]) -> None:
        actions = {
            action.__name__.replace("action_", ""): action
            for action in self._all_actions()
        }
        for index, name in enumerate(names):
            self._run_action(index, actions[name])

    def _run_action(self, index: int, action) -> None:
        try:
            result = action()
            self.history.append(result)
            _app().processEvents()
            self._assert_invariants()
        except Exception as exc:
            self.test_case.fail(self._failure_message(index, action.__name__, exc))

    def _all_actions(self):
        return [
            self.action_schedule_page_view_state,
            self.action_schedule_bid_selected_page,
            self.action_schedule_layer_visibility,
            self.action_cancel_deleting_bid_selected_page,
            self.action_cancel_for_file,
            self.action_toggle_expected_block,
            self.action_fail_next_write,
            self.action_flush,
            self.action_flush_for_file,
        ]

    def action_schedule_page_view_state(self) -> ChaosActionResult:
        page_uid = self.rng.choice(["p1", "p2", "p3"])
        self.manager.schedule_page_view_state("chaos.mdb", page_uid, 1.5, 10.0, 20.0)
        return ChaosActionResult("schedule_page_view_state", page_uid)

    def action_schedule_bid_selected_page(self) -> ChaosActionResult:
        live_bid_uids = [
            uid for uid in ("b1", "b2") if uid not in self.deleted_bid_uids
        ]
        if not live_bid_uids:
            return ChaosActionResult("schedule_bid_selected_page", "no-op")
        bid_uid = self.rng.choice(live_bid_uids)
        page_uid = self.rng.choice(["p1", "p2", "stale-page"])
        self.manager.schedule_bid_selected_page("chaos.mdb", bid_uid, page_uid)
        return ChaosActionResult("schedule_bid_selected_page", f"{bid_uid}->{page_uid}")

    def action_schedule_layer_visibility(self) -> ChaosActionResult:
        layer_uid = self.rng.choice(["layer-a", "layer-b"])
        show = bool(self.rng.getrandbits(1))
        self.manager.schedule_layer_show("chaos.mdb", layer_uid, show)
        return ChaosActionResult("schedule_layer_visibility", f"{layer_uid}={show}")

    def action_cancel_deleting_bid_selected_page(self) -> ChaosActionResult:
        bid_uid = self.rng.choice(["b1", "b2"])
        self.deleted_bid_uids.add(bid_uid)
        self.manager.cancel_bid_selected_pages("chaos.mdb", [bid_uid])
        return ChaosActionResult("cancel_deleting_bid_selected_page", bid_uid)

    def action_cancel_for_file(self) -> ChaosActionResult:
        file_path = self.rng.choice(["chaos.mdb", "other.mdb"])
        self.manager.cancel_for_file(file_path)
        return ChaosActionResult("cancel_for_file", file_path)

    def action_toggle_expected_block(self) -> ChaosActionResult:
        self.service.expected_blocked = not self.service.expected_blocked
        return ChaosActionResult(
            "toggle_expected_block", str(self.service.expected_blocked)
        )

    def action_fail_next_write(self) -> ChaosActionResult:
        self.service.fail_next = True
        return ChaosActionResult("fail_next_write")

    def action_flush(self) -> ChaosActionResult:
        success = self.manager.flush()
        self.last_failed_flush = not success
        return ChaosActionResult("flush", str(success))

    def action_flush_for_file(self) -> ChaosActionResult:
        success = self.manager.flush_for_file("chaos.mdb")
        self.last_failed_flush = not success
        return ChaosActionResult("flush_for_file", str(success))

    def _assert_invariants(self) -> None:
        if self.manager.pending_count < 0:
            raise AssertionError("pending_count went negative")
        for bid_uid in self.deleted_bid_uids:
            if ("bid_selected_page", "chaos.mdb", bid_uid) in self.manager._pending:
                raise AssertionError(
                    f"deleted bid {bid_uid!r} still has pending selected-page write"
                )
        if self.service.expected_blocked:
            before_pending = self.manager.pending_count
            if not self.manager.flush_for_file("chaos.mdb"):
                raise AssertionError("expected-blocked flush_for_file returned False")
            if self.manager.pending_count > before_pending:
                raise AssertionError("flush increased pending writes")

    def _failure_message(self, index: int, action_name: str, exc: BaseException) -> str:
        return (
            "Deferred persistence chaos harness failure\n"
            f"Current state: {{'seed': {self.seed}, 'action_index': {index}, "
            f"'action': {action_name.replace('action_', '')!r}, "
            f"'pending_count': {self.manager.pending_count}, "
            f"'deleted_bid_uids': {sorted(self.deleted_bid_uids)}, "
            f"'expected_blocked': {self.service.expected_blocked}, "
            f"'calls': {self.service.calls[-10:]}}}\n"
            f"Recent actions: {[entry.describe() for entry in self.history[-15:]]}\n"
            f"Exception: {exc!r}\n"
            f"{traceback.format_exc()}"
        )


class DeferredPersistenceChaosHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_deferred_persistence_chaos_default_seeds(self):
        steps = _env_int("PRESENTATION_CHAOS_STEPS", DEFAULT_CHAOS_STEPS)
        for seed in _configured_seeds()[:3]:
            with self.subTest(seed=seed, steps=steps):
                harness = DeferredPersistenceChaosHarness(seed + 7000, self)
                try:
                    harness.run_random_actions(steps)
                finally:
                    harness.cleanup()

    def test_known_sequence_deleted_bid_selected_page_cannot_block_flush(self):
        harness = DeferredPersistenceChaosHarness(9701, self)
        try:
            harness.run_sequence(
                [
                    "schedule_bid_selected_page",
                    "cancel_deleting_bid_selected_page",
                    "flush_for_file",
                ]
            )
        finally:
            harness.cleanup()


class DetachedChaosRepository:
    def __init__(self, view: AnnotationView):
        self.view = view
        self.update_calls: list[tuple[str, str | None]] = []

    def get_active_view(self):
        return self.view

    def update_view(self, view):
        self.update_calls.append((view.target_page_uid, view.target_named_view_uid))


class DetachedChaosWindow:
    def __init__(self):
        self.page_updates: list[str | None] = []
        self.read_only_updates: list[bool] = []
        self.navigation_updates = 0

    def set_read_only(self, read_only):
        self.read_only_updates.append(bool(read_only))

    def update_page(self, page_data):
        self.page_updates.append(page_data.page.uid if page_data.page else None)


class DetachedChaosProjectData:
    def __init__(self, bid_ref: BidRef, pages: list[Page]):
        self.bid_ref = bid_ref
        self.pages = pages
        self.named_view_name_updates: list[tuple] = []

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_bid(self, _bid_ref):
        return SimpleBid(self.pages)

    def update_named_view_names(self, updates):
        self.named_view_name_updates.extend(list(updates))


class SimpleBid:
    def __init__(self, pages: list[Page]):
        self.folders = {}
        self.pages_without_folder = pages


class DetachedChaosRefreshSignaler:
    def __init__(self, manager):
        self.manager = manager
        self.requests = 0

    def request(self):
        self.requests += 1
        self.manager._refresh_window()


class DetachedWindowChaosHarness:
    def __init__(self, seed: int, test_case: unittest.TestCase):
        self.seed = seed
        self.test_case = test_case
        self.rng = random.Random(seed)
        self.history: list[ChaosActionResult] = []
        self.bid_ref = BidRef("detached.mdb", "bid-1")
        self.pages = [
            Page(uid="p1", name="Page 1", width_pts=612.0, height_pts=792.0),
            Page(uid="p2", name="Page 2", width_pts=612.0, height_pts=792.0),
            Page(uid="p3", name="Page 3", width_pts=612.0, height_pts=792.0),
        ]
        self.view = AnnotationView(
            uid="view-1",
            bid_uid=self.bid_ref.bid_uid,
            file_path=self.bid_ref.file_path,
            target_page_uid="p1",
        )
        self.window = DetachedChaosWindow()
        self.repository = DetachedChaosRepository(self.view)
        self.project_data = DetachedChaosProjectData(self.bid_ref, self.pages)
        self.manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        self.manager._window = self.window
        self.manager.repository = self.repository
        self.manager.project_data = self.project_data
        self.manager._is_read_only = lambda: False
        self.manager._update_window_navigation = self._update_window_navigation
        self.manager._get_page_data = self._get_page_data
        self.manager._refresh_signaler = DetachedChaosRefreshSignaler(self.manager)

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
            self.action_database_refresh_matching_file,
            self.action_database_refresh_other_file,
            self.action_layer_visibility_matching_bid,
            self.action_layer_visibility_other_bid,
            self.action_annotations_changed_current_page,
            self.action_annotations_changed_other_page,
            self.action_delete_active_page,
            self.action_refresh_window,
            self.action_close_window,
            self.action_reopen_window,
        ]

    def _run_action(self, index: int, action) -> None:
        try:
            result = action()
            self.history.append(result)
            _app().processEvents()
            self._assert_invariants()
        except Exception as exc:
            self.test_case.fail(self._failure_message(index, action.__name__, exc))

    def _get_page_data(self, view):
        page = next(
            (page for page in self.pages if page.uid == view.target_page_uid), None
        )
        return PageViewDto(page=page, bid_ref=view.bid_ref)

    def _update_window_navigation(self, _view):
        if self.manager._window is not None:
            self.manager._window.navigation_updates += 1

    def action_database_refresh_matching_file(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_database_refreshed(file_path=self.bid_ref.file_path)
        return ChaosActionResult(
            "database_refresh_matching_file",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_database_refresh_other_file(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_database_refreshed(file_path="other.mdb")
        return ChaosActionResult(
            "database_refresh_other_file",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_layer_visibility_matching_bid(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_layer_visibility_changed(
            file_path=self.bid_ref.file_path,
            bid_uid=self.bid_ref.bid_uid,
            layer_uid="layer",
            show=True,
        )
        return ChaosActionResult(
            "layer_visibility_matching_bid",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_layer_visibility_other_bid(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_layer_visibility_changed(
            file_path=self.bid_ref.file_path,
            bid_uid="other-bid",
            layer_uid="layer",
            show=True,
        )
        return ChaosActionResult(
            "layer_visibility_other_bid",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_annotations_changed_current_page(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_annotations_changed(page_uid=self.view.target_page_uid)
        return ChaosActionResult(
            "annotations_changed_current_page",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_annotations_changed_other_page(self):
        before = self.manager._refresh_signaler.requests
        self.manager._on_annotations_changed(page_uid="other-page")
        return ChaosActionResult(
            "annotations_changed_other_page",
            f"requested={self.manager._refresh_signaler.requests > before}",
        )

    def action_delete_active_page(self):
        deleted_uid = self.view.target_page_uid
        self.pages[:] = [page for page in self.pages if page.uid != deleted_uid]
        self.manager._refresh_window()
        return ChaosActionResult("delete_active_page", deleted_uid)

    def action_refresh_window(self):
        self.manager._refresh_window()
        return ChaosActionResult("refresh_window")

    def action_close_window(self):
        self.manager._window = None
        return ChaosActionResult("close_window")

    def action_reopen_window(self):
        if self.manager._window is None:
            self.window = DetachedChaosWindow()
            self.manager._window = self.window
            self.manager._refresh_window()
        return ChaosActionResult("reopen_window")

    def _assert_invariants(self) -> None:
        page_uids = {page.uid for page in self.pages}
        if (
            page_uids
            and self.manager._window is not None
            and self.view.target_page_uid not in page_uids
        ):
            raise AssertionError(
                f"open detached window targets missing page {self.view.target_page_uid!r}"
            )
        if self.manager._window is not None:
            latest_update = (
                self.manager._window.page_updates[-1]
                if self.manager._window.page_updates
                else None
            )
            if latest_update and latest_update not in page_uids:
                raise AssertionError(
                    f"latest window update targets deleted page: {latest_update!r}"
                )
        if (
            not page_uids
            and self.manager._window is not None
            and self.view.target_page_uid
        ):
            raise AssertionError(
                "detached view targets a page after all pages were deleted"
            )

    def _failure_message(self, index: int, action_name: str, exc: BaseException) -> str:
        return (
            "Detached window chaos harness failure\n"
            f"Current state: {{'seed': {self.seed}, 'action_index': {index}, "
            f"'action': {action_name.replace('action_', '')!r}, "
            f"'target_page_uid': {self.view.target_page_uid!r}, "
            f"'pages': {[page.uid for page in self.pages]}, "
            f"'window_open': {self.manager._window is not None}, "
            f"'repo_updates': {self.repository.update_calls}}}\n"
            f"Recent actions: {[entry.describe() for entry in self.history[-15:]]}\n"
            f"Exception: {exc!r}\n"
            f"{traceback.format_exc()}"
        )


class DetachedWindowChaosHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_detached_window_chaos_default_seeds(self):
        steps = _env_int("PRESENTATION_CHAOS_STEPS", DEFAULT_CHAOS_STEPS)
        for seed in _configured_seeds()[:3]:
            with self.subTest(seed=seed, steps=steps):
                harness = DetachedWindowChaosHarness(seed + 8000, self)
                harness.run_random_actions(steps)

    def test_known_sequence_deleted_active_page_retargets_before_update(self):
        harness = DetachedWindowChaosHarness(9801, self)
        harness.run_sequence(["delete_active_page", "refresh_window"])
        self.assertNotIn("p1", [page.uid for page in harness.pages])
        self.assertEqual(harness.view.target_page_uid, "p2")
