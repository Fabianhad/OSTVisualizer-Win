from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.application.render_quality import INTERACTIVE_PDF_RENDER_SCALE
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.application.services.page_load_strategy_service import (
    LoadStrategy,
    PageLoadStrategyService,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    ClippedTextGraphicsItem,
    ImageBackgroundItem,
    TileGraphicsItem,
)
from ost_visualizer.presentation.components.plan_view.components.page_loader import (
    VISUAL_KIND_COMPOSITE,
    VISUAL_KIND_OVERLAY,
    VISUAL_KIND_PAGE,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.visualization.pdf.render_priority import RenderPriority
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_PASTE_BACKOUT,
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
)
from ost_visualizer.presentation.scene.plan_view_z_order import (
    PAGE_VISIBLE_FRAME_Z,
    PAPER_HIGHLIGHT_Z,
    TAKEOFF_BODY_Z,
)
from ost_visualizer.presentation.scene.scene_builder import SceneBuilder
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
    HighlightGraphicsItem,
)
from PySide6 import QtCore, QtTest, QtWidgets
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QTextCursor,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
)
from shiboken6 import delete
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeCoordinateSystem,
    FakeDebouncer,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakePageItem,
    FakePageSizeProvider,
    FakeRenderingService,
    FakeScene,
    FakeScrollBar,
    FakeSignal,
    FakeSizedViewport,
    FakeTakeoffRenderer,
    FakeTransform,
    FakeViewport,
    RecordingPathTakeoffRenderer,
)
from PySide6 import QtCore, QtWidgets
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    NAMED_VIEW_LABEL_ITEM_KIND,
)
from shiboken6 import delete, isValid
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    FakeTakeoffRenderer,
)
from ost_visualizer.presentation.modes.cursor import CURSOR_MODE_PLACE
from PySide6.QtWidgets import QApplication
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_POLYGON,
    BidAnnotation,
)
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_SELECT,
)
from PySide6 import QtCore
from PySide6.QtGui import QAction, QBrush, QColor, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QMenu,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from PySide6.QtGui import QImage
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)
from tests.presentation.components.plan_view.tracking_support import (
    FakeTrackingViewport as _preferences_support_FakeTrackingViewport,
    _plan_view_with_tracking_viewport as _preferences_support__plan_view_with_tracking_viewport,
)
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from pathlib import Path
import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsScene
from tests.presentation.components.plan_view.pdf_text_support import (
    FakeRenderingService as _pdf_text_support_FakeRenderingService,
    FakeTrackingViewport as _pdf_text_support_FakeTrackingViewport,
    _page_info as _pdf_text_support__page_info,
    _raw_char as _pdf_text_support__raw_char,
    _raw_run as _pdf_text_support__raw_run,
)
import tests.presentation.components.plan_view.test_view as view_fixtures
from tests.presentation.components.plan_view.components.interaction_support import (
    BaseKeyHandler as _interaction_support_BaseKeyHandler,
    FakeCoordinateSystem as _interaction_support_FakeCoordinateSystem,
    FakeCursorViewport as _interaction_support_FakeCursorViewport,
    FakeItem as _interaction_support_FakeItem,
    FakeSceneBuilder as _interaction_support_FakeSceneBuilder,
    InputHandlerHarness as _interaction_support_InputHandlerHarness,
    _FakeSignal as _interaction_support__FakeSignal,
    _app as _interaction_support__app,
)
import random
import traceback
from dataclasses import dataclass, field

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
        view = self.view
        view.cleanup()
        if isValid(view):
            delete(view)
        _chaos_app().processEvents()

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
        app = _chaos_app()
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


class _TakeoffPlanViewOverlayRefreshFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def _add_text_annotation(
        self,
        view,
        *,
        uid="a1",
        text="Text",
        page_uid="",
        position=None,
        font_size=12,
    ):
        if position is None:
            position = [0.0, 0.0, 80.0, 24.0]
        annotation = BidAnnotation(
            uid=uid,
            annotation_type="text",
            page_uid=page_uid,
            position=list(position),
            properties={
                "Text": text,
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": font_size,
                "FontBold": False,
                "FontItalic": False,
                "FontUnderline": False,
                "TextAlign": 0,
            },
        )
        item = QGraphicsTextItem(text)
        item.setData(0, uid)
        item.setFont(QFont("Arial", font_size))
        item.setTextWidth(position[2])
        view._scene.addItem(item)
        view._uid_to_items = {uid: [item]}
        view._current_annotations = {uid: annotation}
        view._selection_enabled = True
        return annotation, item

    def _capture_annotation_flushes(self, view):
        emitted_text = []
        emitted_positions = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted_text.extend(changes)
        )
        view.positions_flushed.connect(
            lambda _takeoffs, annotations: emitted_positions.extend(annotations)
        )
        return emitted_text, emitted_positions

    def _select_document_text(self, item):
        cursor = item.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        item.setTextCursor(cursor)

    def _left_press_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _left_move_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseMove,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _left_release_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _right_press_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _right_move_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseMove,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _right_release_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _make_plan_view(self, *, load_coordinator=None, annotation_renderer=None):
        view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=load_coordinator or FakeLoadCoordinator(),
            takeoff_renderer=FakeTakeoffRenderer(),
            annotation_renderer=annotation_renderer or FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        # Release test-owned windows before another test enters a native popup
        # loop. cleanup() releases services, but does not destroy the Qt widget.
        owned = [view]
        view.destroyed.connect(lambda: owned.clear())

        def release_view():
            if owned:
                delete(owned[0])

        self.addCleanup(release_view)
        # Production window composition projects access immediately after
        # constructing the view. Tests exercising edit workflows must model
        # that contract explicitly.
        view.set_editing_enabled(True)
        return view

    @staticmethod
    def _render_scene_pixel(view, x, y, size=216):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QPainter(image)
        rect = QtCore.QRectF(0.0, 0.0, float(size), float(size))
        view._scene.render(painter, rect, rect)
        painter.end()
        return image.pixelColor(x, y)

    def _make_page_scale_view(
        self,
        page=None,
        *,
        view_size=(420, 320),
        zoom_percent=137.0,
        scroll_values=(731, 913),
    ):
        view = self._make_plan_view()
        view.resize(*view_size)
        view.show()
        QApplication.processEvents()
        page = page or Page(
            uid="p1",
            name="P1",
            width_pts=1200.0,
            height_pts=1600.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        view.set_zoom_percent(zoom_percent)
        if scroll_values is not None:
            view.horizontalScrollBar().setValue(scroll_values[0])
            view.verticalScrollBar().setValue(scroll_values[1])
        QApplication.processEvents()
        return view, page

    def _reload_page_with_scale(self, view, page, scale_factor1, scale_factor2):
        zoom_fac, current_x, current_y = view.get_view_state()
        page = replace(
            page,
            scale_factor1=scale_factor1,
            scale_factor2=scale_factor2,
            zoom_fac=zoom_fac,
            current_x=current_x,
            current_y=current_y,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        QApplication.processEvents()
        return page

    @staticmethod
    def _viewport_state(view):
        center = view.mapToScene(view.viewport().rect()).boundingRect().center()
        return (
            (
                view.horizontalScrollBar().value(),
                view.verticalScrollBar().value(),
            ),
            center,
        )

    def _assert_viewport_state(self, view, expected):
        expected_scroll, expected_center = expected
        actual_scroll, actual_center = self._viewport_state(view)
        self.assertEqual(actual_scroll, expected_scroll)
        self.assertAlmostEqual(actual_center.x(), expected_center.x(), delta=1e-9)
        self.assertAlmostEqual(actual_center.y(), expected_center.y(), delta=1e-9)

    @staticmethod
    def _scroll_value_near_edge(scrollbar, edge):
        inset = max(1, round((scrollbar.maximum() - scrollbar.minimum()) * 0.05))
        if edge == "minimum":
            return scrollbar.minimum() + inset
        return scrollbar.maximum() - inset

    def _load_completed_page_visual(self, page, return_initial_canvas=False):
        view = self._make_plan_view()
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        self.assertTrue(view.load_page(page, [], {}, {}))
        initial_canvas = view._white_canvas_item
        if page.image_path and page.overlay_image_path and page.image_show_mode == 2:
            request_id, request = view._rendering_service.composite_requests[-1]
        elif page.image_path:
            request_id, request = view._rendering_service.page_requests[-1]
        else:
            request_id, request = view._rendering_service.overlay_requests[-1]
        request["callback"](
            RenderResult(
                request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        QApplication.processEvents()
        if return_initial_canvas:
            return view, initial_canvas
        return view

    def _install_page_canvas(self, view, page, scene_scale=2.0):
        view._current_page = page
        view._current_bid_page_uid = page.uid
        view._scene_scale = scene_scale
        item = QGraphicsRectItem(
            0.0,
            0.0,
            page.effective_width_pts * scene_scale,
            page.effective_height_pts * scene_scale,
        )
        item.setZValue(-1.0)
        view._white_canvas_item = item
        view._scene.addItem(item)
        view._scene.setSceneRect(item.rect())
        view.resize(300, 300)
        QApplication.processEvents()
        return item

    def _add_dimension_label_annotation(self, view, properties=None):
        annotation = BidAnnotation(
            uid="d1",
            annotation_type="dimension",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#000000",
            properties=dict(
                properties
                or {
                    "FontName": "Arial",
                    "FontColor": 0,
                    "FontSize": 10,
                    "FontBold": False,
                    "FontItalic": False,
                    "FontUnderline": False,
                }
            ),
        )
        label = QGraphicsTextItem("21' - 3\"")
        label.setData(0, annotation.uid)
        label.setData(2, DIMENSION_LABEL_ITEM_KIND)
        label.setFont(QFont("Arial", int(annotation.properties.get("FontSize", 10))))
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(label)
        view._uid_to_items = {annotation.uid: [label]}
        view._current_annotations = {annotation.uid: annotation}
        return annotation, label

    def _make_condition_label_path_item(self, uid):
        path = QPainterPath()
        path.moveTo(0.0, 0.0)
        path.lineTo(100.0, 0.0)
        path.lineTo(100.0, 100.0)
        path.lineTo(0.0, 100.0)
        path.closeSubpath()
        item = QGraphicsPathItem(path)
        item.setData(0, uid)
        return item

    def _first_selection_outline(self, view):
        return next(
            item
            for item in view._selection_items
            if isinstance(item, QGraphicsPolygonItem)
        )

    def _make_incremental_refresh_view(self, renderer):
        page = Page(uid="page-1", name="Page 1", width_pts=100.0, height_pts=100.0)
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene = QtWidgets.QGraphicsScene()
        view._scene_builder = SceneBuilder(renderer, FakeAnnotationRenderer())
        view._current_bid_page_uid = page.uid
        view._current_page = page
        view._current_bid_ref = bid_ref
        view._current_render_identity = TakeoffPlanView._build_render_identity(
            view, page, bid_ref
        )
        view._current_takeoffs = {
            "1": Takeoff(
                uid="1",
                condition_uid="c1",
                page_uid=page.uid,
                position=[1.0, 2.0],
            )
        }
        view._current_annotations = {}
        view._ann_db_uid_map = {}
        view._current_conditions = {
            "c1": Condition(uid="c1", condition_type=Condition.TYPE_COUNT)
        }
        view._current_color_map = {"c1": "#000000"}
        view._current_page_area_selections = {}
        view._inactive_object_color = Config.DEFAULT_INACTIVE_OBJECT_COLOR
        view._hidden_layer_uids = set()
        view._takeoff_items = []
        view._hotlink_items = []
        view._uid_to_items = {}
        view._selected_uids = set()
        view._pending_mutation_uids = set()
        view._selected_text_annotation_uid = None
        view._selection_items = []
        view._pdf_text_highlight_items = []
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._scene_scale = 1.0
        view._background_item = None
        view._visible_frame_item = None
        view._visible_frame_kind = None
        view._white_canvas_item = QGraphicsRectItem(0.0, 0.0, 100.0, 100.0)
        view._scene.addItem(view._white_canvas_item)
        view._defer_page_visual_reveal = False
        view._load_coordinator = FakeLoadCoordinator()
        view._has_loaded_page_visual_items = lambda: True
        view._current_page_transform = lambda: None
        view._invalidate_snap_index = lambda: None
        view._update_cursor = lambda: None
        view._editing_text_annotation_uid = None
        view._draft_text_annotation_uid = None
        view._finishing_text_annotation_edit = False
        view._editing_named_view_uid = None
        view._draft_named_view_uid = None
        calls = []
        view._sync_page_image_layer_visibility = lambda: calls.append("sync")
        view._update_scene_rect = lambda: calls.append("scene_rect")
        view.update_selection_visuals = lambda: calls.append("selection")
        view._selected_dimension_text_label_target = lambda: None
        view._selected_condition_text_label_target = lambda: None
        view._restore_selected_text_annotation_toolbar = lambda _uid: calls.append(
            "restore_text"
        )
        view._restore_selected_dimension_text_label_toolbar = (
            lambda _target: calls.append("restore_dimension")
        )
        view._restore_selected_condition_text_label_toolbar = (
            lambda _target: calls.append("restore_condition")
        )
        view.viewport = lambda: FakeViewport(calls)
        return view, page, bid_ref, calls

    def _text_annotation(self, uid="ann-1", text="old", page_uid="page-1"):
        return BidAnnotation(
            uid=uid,
            annotation_type=ANNOTATION_TYPE_TEXT,
            page_uid=page_uid,
            position=[20.0, 20.0, 80.0, 24.0],
            properties={"Text": text, "FontSize": 12},
            visible=True,
        )

    def _hotlink_annotation(self, uid="hot-1", page_uid="page-1"):
        return BidAnnotation(
            uid=uid,
            annotation_type=ANNOTATION_TYPE_HOTLINK,
            page_uid=page_uid,
            position=[20.0, 20.0],
            properties={"BidPageViewUID": "view-1"},
            visible=True,
        )

    def _named_view_annotation(self, uid="view-1", page_uid="page-1"):
        return BidAnnotation(
            uid=uid,
            annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
            page_uid=page_uid,
            position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
            color="#008000",
            width=2.0,
            properties={"Text": "Lobby"},
            visible=True,
        )

    def _install_annotation_item(self, view, annotation, key=None, hotlink=False):
        key = key or annotation.uid
        item = QGraphicsPathItem()
        item.setData(0, key)
        view._scene.addItem(item)
        view._current_annotations[key] = annotation
        view._uid_to_items[key] = [item]
        view._takeoff_items.append(item)
        if hotlink:
            view._hotlink_items.append(
                (
                    item,
                    HotlinkDto(
                        uid=annotation.uid,
                        bid_page_uid=annotation.page_uid,
                        target_view_uid=annotation.properties.get("BidPageViewUID"),
                        center_x=20.0,
                        center_y=20.0,
                        radius=10.0,
                    ),
                )
            )
        return item


class TakeoffPlanViewOverlayRefreshTests(_TakeoffPlanViewOverlayRefreshFixture):
    """TakeoffPlanView: lifecycle and combined contracts."""

    def test_plan_view_constructs_condition_text_toolbar_without_startup_crash(self):
        view = self._make_plan_view()
        self.assertIsNotNone(view._condition_text_toolbar)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_plan_view_cleanup_releases_native_snap_indexes(self):
        view = self._make_plan_view()
        self.assertIsNotNone(view._ensure_takeoff_snap_index())
        self.assertIsNotNone(view._ensure_pdf_snap_index())
        view.cleanup()
        self.assertIsNone(view._takeoff_snap_index)
        self.assertIsNone(view._pdf_snap_index)

    def test_plan_view_cleanup_is_idempotent_after_services_are_released(self):
        view = self._make_plan_view()
        rendering_service = view._rendering_service
        view.cleanup()
        view.cleanup()
        self.assertEqual(rendering_service.shutdown_calls, 1)

    def test_page_load_timer_callback_is_dropped_after_view_destruction(self):
        view = self._make_plan_view()
        calls = []
        view._finalize_page_load_if_ready = lambda: calls.append(True)
        TakeoffPlanView._finalize_queued_page_load_if_valid(view)
        self.assertEqual(calls, [True])
        delete(view)
        TakeoffPlanView._finalize_queued_page_load_if_valid(view)
        self.assertEqual(calls, [True])

    def test_plan_view_cleanup_continues_after_independent_stage_failures(self):
        view = self._make_plan_view()
        rendering_service = view._rendering_service
        inline_edit_commits = []

        def fail_inline_edit(*, commit):
            inline_edit_commits.append(commit)
            raise RuntimeError("inline edit failed")

        def fail_render_shutdown():
            rendering_service.shutdown_calls += 1
            raise RuntimeError("render shutdown failed")

        view._finish_active_inline_text_edit = fail_inline_edit
        rendering_service.shutdown = fail_render_shutdown
        with self.assertLogs(
            "ost_visualizer.presentation.components.plan_view.view", level="ERROR"
        ) as captured:
            view.cleanup()
        messages = "\n".join(captured.output)
        self.assertIn("finish the active inline text edit", messages)
        self.assertIn("shut down page rendering", messages)
        # Later cleanup stages (clearing the scene) also finish the edit.
        self.assertEqual(inline_edit_commits[0], True)
        self.assertEqual(set(inline_edit_commits), {True})
        self.assertEqual(rendering_service.shutdown_calls, 1)
        self.assertIsNone(view._condition_text_toolbar)
        self.assertIsNone(view._rendering_service)
        self.assertIsNone(view._scene_builder)
        self.assertIsNone(view._takeoff_snap_index)
        self.assertIsNone(view._pdf_snap_index)

    def test_place_preview_secondary_conditions_match_active_type(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._current_conditions = {
            "c1": Condition(
                uid="c1", layer_visible=True, condition_type=Condition.TYPE_AREA
            ),
            "c2": Condition(
                uid="c2", layer_visible=True, condition_type=Condition.TYPE_AREA
            ),
            "linear": Condition(
                uid="linear",
                layer_visible=True,
                condition_type=Condition.TYPE_LINEAR,
            ),
        }
        view._current_conditions["hidden"] = Condition(
            uid="hidden", layer_visible=False, condition_type=Condition.TYPE_AREA
        )
        self.assertEqual(
            view._secondary_place_condition_uids(
                "c2", ["c1", "c1", "linear", "c2", "hidden", "missing"]
            ),
            ["c1"],
        )
        self.assertEqual(view._secondary_place_condition_uids("missing", ["c1"]), [])

    def test_render_loading_bar_is_fixed_viewport_overlay(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self._install_page_canvas(view, page)
        view.show()
        # Mark the load as applied so the pending fit does not undo the zoom,
        # then scale past fit-to-page so both scrollbars have a non-zero range.
        view._load_view_applied = True
        view.scale(6.0, 6.0)
        QApplication.processEvents()
        bar = view._render_loading_bar
        self.assertIs(bar.parent(), view)
        self.assertIsNot(bar.parent(), view.viewport())
        view._start_current_page_render_loading()
        view._position_viewport_overlay_bars()
        expected = view.viewport().geometry()
        self.assertEqual(bar.geometry().x(), expected.x())
        self.assertEqual(bar.geometry().y(), expected.y())
        self.assertEqual(bar.geometry().width(), expected.width())
        initial_pos = bar.pos()
        initial_width = bar.geometry().width()
        self.assertGreater(view.horizontalScrollBar().maximum(), 0)
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        QApplication.processEvents()
        self.assertEqual(bar.pos(), initial_pos)
        view.resize(360, 260)
        QApplication.processEvents()
        expected = view.viewport().geometry()
        self.assertNotEqual(expected.width(), initial_width)
        self.assertEqual(bar.geometry().x(), expected.x())
        self.assertEqual(bar.geometry().y(), expected.y())
        self.assertEqual(bar.geometry().width(), expected.width())
        view.cleanup()

    def test_missing_page_file_bar_is_fixed_viewport_overlay(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="missing.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self._install_page_canvas(view, page)
        view.show()
        # Mark the load as applied so the pending fit does not undo the zoom,
        # then scale past fit-to-page so both scrollbars have a non-zero range.
        view._load_view_applied = True
        view.scale(6.0, 6.0)
        QApplication.processEvents()
        bar = view._missing_file_bar
        self.assertIs(bar.parent(), view)
        self.assertIsNot(bar.parent(), view.viewport())
        view._show_missing_page_file_status(
            "Page image/PDF was not found or could not be loaded: missing.pdf."
        )
        expected = view.viewport().geometry()
        self.assertEqual(bar.geometry().x(), expected.x())
        self.assertEqual(bar.geometry().y(), expected.y())
        self.assertEqual(bar.geometry().width(), expected.width())
        initial_pos = bar.pos()
        initial_width = bar.geometry().width()
        self.assertGreater(view.horizontalScrollBar().maximum(), 0)
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        QApplication.processEvents()
        self.assertEqual(bar.pos(), initial_pos)
        view.resize(360, 260)
        QApplication.processEvents()
        expected = view.viewport().geometry()
        self.assertNotEqual(expected.width(), initial_width)
        self.assertEqual(bar.geometry().x(), expected.x())
        self.assertEqual(bar.geometry().y(), expected.y())
        self.assertEqual(bar.geometry().width(), expected.width())
        view.cleanup()

    def test_nearby_prefetch_does_not_drive_loading_bar(self):
        class RecordingPrefetchCoordinator:
            def __init__(self):
                self.calls = []
                self.cancel_count = 0

            def prefetch_nearby_pages(self, current_page, ordered_pages, bid_ref):
                self.calls.append((current_page, ordered_pages, bid_ref))

            def cancel_pending(self):
                self.cancel_count += 1

        coordinator = RecordingPrefetchCoordinator()
        view = self._make_plan_view()
        view._prefetch_coordinator = coordinator
        current = Page(uid="p2", name="P2")
        ordered = [Page(uid="p1", name="P1"), current, Page(uid="p3", name="P3")]
        view.prefetch_nearby_pages(current, ordered, None)
        self.assertEqual(len(coordinator.calls), 1)
        self.assertIs(coordinator.calls[0][0], current)
        self.assertEqual(coordinator.calls[0][1], ordered)
        self.assertIsNone(coordinator.calls[0][2])
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertTrue(view._render_loading_bar.isHidden())
        view.cleanup()
        self.assertEqual(coordinator.cancel_count, 1)

    def test_stale_visible_frame_completion_does_not_hide_newer_loading_bar(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self._install_page_canvas(view, page)
        view._current_load_token = "load-token"
        view._current_render_identity = {}
        old_token = view._start_visible_frame_render_loading()
        new_token = view._start_current_page_render_loading()
        self.assertNotEqual(old_token, new_token)
        view._complete_visible_frame_render_loading(old_token)
        self.assertTrue(view._render_loading_bar.is_loading)
        self.assertEqual(view._current_page_loading_token, new_token)
        view._complete_current_page_render_loading()
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertIsNone(view._current_page_loading_token)
        view.cleanup()

    def test_rotate_handle_uses_white_fill_and_line_with_black_outline(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            position=[0.0, 0.0, 100.0, 100.0],
        )
        view._current_annotations = {"a1": annotation}
        view._element_center = lambda *_args: (50.0, 50.0)
        with patch.object(
            view,
            "_outlined_icon_pixmap",
            wraps=view._outlined_icon_pixmap,
        ) as build_pixmap:
            self.assertTrue(view._create_rotate_handle("a1"))
        build_pixmap.assert_called_once_with(
            "replay_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
            "#ffffff",
        )
        self.assertEqual(view._rotate_line_item.pen().color(), QColor(255, 255, 255))
        self.assertEqual(
            view._rotate_line_outline_item.pen().color(),
            QColor(0, 0, 0),
        )
        view.cleanup()

    def test_cold_composite_first_move_keeps_one_overlay_through_stale_frame(self):
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        view = self._load_completed_page_visual(page)
        original_composite = view._background_item

        def complete_move_previews():
            base_request_id, base_options = view._rendering_service.page_requests[-1]
            overlay_request_id, overlay_options = (
                view._rendering_service.overlay_requests[-1]
            )
            base_image = QImage(1224, 1584, QImage.Format.Format_ARGB32)
            base_image.fill(QColor(255, 80, 80).rgba())
            overlay_image = QImage(1088, 1408, QImage.Format.Format_ARGB32)
            overlay_image.fill(QColor(80, 80, 255).rgba())
            base_options["callback"](
                RenderResult(base_request_id, True, base_image, None)
            )
            overlay_options["callback"](
                RenderResult(overlay_request_id, True, overlay_image, None)
            )

        def finish_move(scene_delta):
            handle_pos = view.mapFromScene(view._overlay_move_handle_item.pos())
            self.assertTrue(view._begin_overlay_move(handle_pos))
            view._finish_overlay_move_drag(
                view._overlay_move_anchor_scene + scene_delta
            )

        def assert_preview_is_exclusive():
            self.assertFalse(view._background_item.isVisible())
            self.assertTrue(view._overlay_move_preview_base_item.isVisible())
            self.assertTrue(view._overlay_move_preview_overlay_item.isVisible())

        try:
            # Model a genuinely cold cache: the first zoom frame is still in flight
            # when move mode separates the composite into base and overlay previews.
            view._update_tile_coverage(4.0)
            self.assertEqual(
                len(view._rendering_service.composite_frame_requests),
                1,
            )
            frame_request_id, frame_options = (
                view._rendering_service.composite_frame_requests[-1]
            )
            self.assertTrue(view.show_overlay_move_handle())
            complete_move_previews()
            finish_move(QtCore.QPointF(144.0, 72.0))
            self.assertEqual(
                view._overlay_move_preview_rect,
                (64.0, 32.0, 544.0, 704.0),
            )
            assert_preview_is_exclusive()
            stale_frame = QImage(300, 300, QImage.Format.Format_ARGB32)
            stale_frame.fill(QColor(80, 80, 255).rgba())
            frame_options["callback"](
                RenderResult(frame_request_id, True, stale_frame, None)
            )
            self.assertIsNone(view._visible_frame_item)
            assert_preview_is_exclusive()
            view.cancel_overlay_move_mode(restore_preview=True)
            self.assertTrue(original_composite.isVisible())
            self.assertIsNone(view._overlay_move_preview_base_item)
            self.assertIsNone(view._overlay_move_preview_overlay_item)
            self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
            # The warm-session path must have the same exclusive ownership.
            self.assertTrue(view.show_overlay_move_handle())
            complete_move_previews()
            finish_move(QtCore.QPointF(72.0, 36.0))
            view._update_tile_coverage(4.0)
            assert_preview_is_exclusive()
            view.set_overlay_rect_save_handler(lambda _rect: True)
            view._commit_overlay_move()
            composite_request_id, composite_options = (
                view._rendering_service.composite_requests[-1]
            )
            committed_image = QImage(1224, 1584, QImage.Format.Format_ARGB32)
            committed_image.fill(QColor(255, 255, 255).rgba())
            composite_options["callback"](
                RenderResult(composite_request_id, True, committed_image, None)
            )
            self.assertTrue(view._background_item.isVisible())
            self.assertIsNone(view._overlay_move_preview_base_item)
            self.assertIsNone(view._overlay_move_preview_overlay_item)
            self.assertEqual(page.overlay_rect, (32.0, 16.0, 544.0, 704.0))
        finally:
            view.cleanup()

    def test_move_overlay_can_drag_multiple_times_before_commit(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = page.overlay_rect
        view._set_overlay_move_handle_pos(QtCore.QPointF(0.0, 0.0))
        view._apply_cursor_mode("move_overlay_handle")
        first_press = view.mapFromScene(view._overlay_move_handle_item.pos())
        view.mousePressEvent(self._left_press_event(first_press.x(), first_press.y()))
        first_release = view.mapFromScene(QtCore.QPointF(144.0, 72.0))
        view.mouseMoveEvent(self._left_move_event(first_release.x(), first_release.y()))
        view.mouseReleaseEvent(
            self._left_release_event(first_release.x(), first_release.y())
        )
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._overlay_move_preview_rect, (64.0, 32.0, 544.0, 704.0))
        second_press = view.mapFromScene(view._overlay_move_handle_item.pos())
        view.mousePressEvent(self._left_press_event(second_press.x(), second_press.y()))
        second_release = view.mapFromScene(
            view._overlay_move_anchor_scene + QtCore.QPointF(72.0, 36.0)
        )
        view.mouseMoveEvent(
            self._left_move_event(second_release.x(), second_release.y())
        )
        view.mouseReleaseEvent(
            self._left_release_event(second_release.x(), second_release.y())
        )
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._overlay_move_preview_rect, (96.0, 48.0, 544.0, 704.0))
        self.assertEqual(view._overlay_move_original_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._rendering_service.overlay_requests, [])
        view.cleanup()

    def test_move_overlay_cancel_restores_original_overlay_rect(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(64.0, 32.0, 544.0, 704.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._overlay_move_original_rect = (0.0, 0.0, 544.0, 704.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view.cancel_overlay_move_mode(restore_preview=True)
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        view.cleanup()

    def test_switching_cursor_mode_clears_rotate_handle(self):
        view = self._make_plan_view()
        handle = QGraphicsPathItem()
        view._scene.addItem(handle)
        view._rotate_handle_item = handle
        view._rotate_handle_uid = "t1"
        view._apply_cursor_mode("rotate")
        cursor_modes = []
        view.cursor_mode_change_requested.connect(cursor_modes.append)
        view.set_cursor_mode("pan")
        self.assertEqual(view._cursor_mode, "pan")
        self.assertEqual(cursor_modes, ["pan"])
        self.assertIsNone(view._rotate_handle_item)
        self.assertIsNone(view._rotate_handle_uid)
        self.assertIsNone(handle.scene())
        view.cleanup()

    def test_paste_uses_content_specific_callback_when_general_editing_is_disabled(
        self,
    ):
        view = self._make_plan_view()
        calls = []
        view.paste_requested.connect(lambda: calls.append("paste"))
        view.set_editing_enabled(False)
        view.set_paste_allowed_fn(lambda: True)
        view.paste_clipboard()
        self.assertEqual(calls, ["paste"])
        view.set_paste_allowed_fn(lambda: False)
        view.paste_clipboard()
        self.assertEqual(calls, ["paste"])
        view.set_paste_allowed_fn(None)
        view.paste_clipboard()
        self.assertEqual(calls, ["paste"])
        view.set_editing_enabled(True)
        view.paste_clipboard()
        self.assertEqual(calls, ["paste", "paste"])
        view.cleanup()

    def test_page_scale_reload_preserves_even_and_odd_fractional_zoom_viewports(self):
        for view_size in ((420, 320), (419, 319)):
            with self.subTest(view_size=view_size):
                view, page = self._make_page_scale_view(view_size=view_size)
                expected_viewport = self._viewport_state(view)
                expected_scene_rect = QtCore.QRectF(view.sceneRect())
                expected_transform = QTransform(view.transform())
                scaled_page = self._reload_page_with_scale(view, page, 1.0, 2.0)
                self._assert_viewport_state(view, expected_viewport)
                self.assertEqual(view.sceneRect(), expected_scene_rect)
                self.assertEqual(view.transform(), expected_transform)
                self.assertEqual(
                    (scaled_page.scale_factor1, scaled_page.scale_factor2),
                    (1.0, 2.0),
                )
                view.cleanup()

    def test_repeated_page_scale_reloads_do_not_accumulate_viewport_drift(self):
        view, page = self._make_page_scale_view()
        expected_viewport = self._viewport_state(view)
        for scale_factor1, scale_factor2 in (
            (1.0, 2.0),
            (1.0, 2.0),
            (2.0, 1.0),
            (1.0, 1.0),
        ) * 3:
            page = self._reload_page_with_scale(
                view, page, scale_factor1, scale_factor2
            )
            self._assert_viewport_state(view, expected_viewport)
        view.cleanup()

    def test_page_scale_reload_preserves_viewport_across_zoom_and_scroll_extremes(self):
        for zoom_percent in (25.0, 137.0, 800.0):
            for scroll_edge in ("minimum", "maximum"):
                with self.subTest(zoom_percent=zoom_percent, scroll_edge=scroll_edge):
                    view, page = self._make_page_scale_view(
                        zoom_percent=zoom_percent,
                        scroll_values=None,
                    )
                    h_scroll = view.horizontalScrollBar()
                    v_scroll = view.verticalScrollBar()
                    if zoom_percent > 100.0:
                        # Zoomed past the viewport, so the edge scroll values are
                        # real positions and not clamped zeros.
                        self.assertGreater(h_scroll.maximum(), h_scroll.minimum())
                        self.assertGreater(v_scroll.maximum(), v_scroll.minimum())
                    h_scroll.setValue(
                        self._scroll_value_near_edge(h_scroll, scroll_edge)
                    )
                    v_scroll.setValue(
                        self._scroll_value_near_edge(v_scroll, scroll_edge)
                    )
                    QApplication.processEvents()
                    expected_viewport = self._viewport_state(view)
                    page = self._reload_page_with_scale(view, page, 1.0, 4.0)
                    self._reload_page_with_scale(view, page, 4.0, 1.0)
                    self._assert_viewport_state(view, expected_viewport)
                    view.cleanup()

    def test_page_scale_reload_keeps_centered_small_page_stable(self):
        page = Page(uid="p1", name="P1", width_pts=100.0, height_pts=120.0)
        view, page = self._make_page_scale_view(
            page=page,
            view_size=(600, 500),
            zoom_percent=25.0,
            scroll_values=None,
        )
        expected_viewport = self._viewport_state(view)
        self._reload_page_with_scale(view, page, 1.0, 4.0)
        self._assert_viewport_state(view, expected_viewport)
        view.cleanup()

    def test_page_scale_reload_preserves_viewport_for_rotated_pages(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                page = Page(
                    uid="p1",
                    name="P1",
                    width_pts=900.0,
                    height_pts=1400.0,
                    rotation=rotation,
                )
                view, page = self._make_page_scale_view(
                    page=page,
                    scroll_values=(517, 683),
                )
                expected_viewport = self._viewport_state(view)
                self._reload_page_with_scale(view, page, 1.0, 4.0)
                self._assert_viewport_state(view, expected_viewport)
                view.cleanup()

    def test_restored_out_of_bounds_page_view_state_fits_to_page(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            zoom_fac=1.332,
            current_x=99999.0,
            current_y=99999.0,
        )
        self._install_page_canvas(view, page)
        calls = []
        view.fit_to_page = lambda: calls.append("fit")
        view._load_initial_view_mode = "restore"
        view._load_view_applied = False
        view._apply_current_view_contract(consume_scroll_state=False)
        self.assertEqual(calls, ["fit"])
        view.cleanup()

    def test_restored_out_of_range_page_zoom_fits_to_page(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            zoom_fac=0.001,
            current_x=408.0,
            current_y=528.0,
        )
        self._install_page_canvas(view, page)
        calls = []
        view.fit_to_page = lambda: calls.append("fit")
        view._load_initial_view_mode = "restore"
        view._load_view_applied = False
        view._apply_current_view_contract(consume_scroll_state=False)
        self.assertEqual(calls, ["fit"])
        view.cleanup()

    def test_restored_in_bounds_page_view_state_is_applied_without_fitting(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            zoom_fac=1.332,
            current_x=408.0,
            current_y=528.0,
        )
        self._install_page_canvas(view, page)
        view.show()
        QApplication.processEvents()
        calls = []
        view.fit_to_page = lambda: calls.append("fit")
        view._load_initial_view_mode = "restore"
        view._load_view_applied = False
        view._apply_current_view_contract(consume_scroll_state=False)
        self.assertEqual(calls, [])
        zoom_fac, current_x, current_y = view.get_view_state()
        self.assertAlmostEqual(zoom_fac, 1.332, places=3)
        self.assertAlmostEqual(current_x, 408.0, delta=1.0)
        self.assertAlmostEqual(current_y, 528.0, delta=1.0)
        view.cleanup()

    def test_condition_text_toolbar_uses_format_icons_and_color_swatch(self):
        view = self._make_plan_view()
        for button in (
            view._condition_text_bold_btn,
            view._condition_text_italic_btn,
            view._condition_text_underline_btn,
            view._condition_text_align_left_btn,
            view._condition_text_align_center_btn,
            view._condition_text_align_right_btn,
        ):
            self.assertEqual(button.text(), "")
            self.assertFalse(button.icon().isNull())
            self.assertTrue(button.isCheckable())
        self.assertEqual(view._condition_text_bold_btn.toolTip(), "Bold")
        self.assertEqual(view._condition_text_italic_btn.toolTip(), "Italic")
        self.assertEqual(view._condition_text_underline_btn.toolTip(), "Underline")
        self.assertEqual(view._condition_text_align_left_btn.toolTip(), "Align left")
        self.assertEqual(
            view._condition_text_align_center_btn.toolTip(), "Align center"
        )
        self.assertEqual(view._condition_text_align_right_btn.toolTip(), "Align right")
        self.assertEqual(view._condition_text_color_btn.text(), "")
        self.assertFalse(view._condition_text_color_btn.icon().isNull())
        view.cleanup()

    def test_selected_annotation_style_change_updates_only_selected_annotation(self):
        view = self._make_plan_view()
        selected = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            position=[1.0, 2.0, 13.0, 14.0],
            color="#ff0000",
            width=4.0,
        )
        other = BidAnnotation(
            uid="a2",
            annotation_type="rect",
            position=[20.0, 22.0, 33.0, 34.0],
            color="#0000ff",
            width=5.0,
        )
        view._current_annotations = {"a1": selected, "a2": other}
        view._selected_uids = {"a1"}
        view._context_menu_action_state = lambda _key: {"enabled": True}
        emitted = []
        view.annotation_styles_flushed.connect(lambda changes: emitted.extend(changes))
        view.apply_annotation_style_to_selection(color="#336699", width=7.0)
        self.assertEqual(selected.color, "#336699")
        self.assertEqual(selected.width, 7.0)
        self.assertEqual(other.color, "#0000ff")
        self.assertEqual(other.width, 5.0)
        self.assertEqual(
            [tuple(change) for change in emitted],
            [
                (
                    "a1",
                    "rect",
                    {"Color": "#ff0000", "Width": 4.0},
                    {"Color": "#336699", "Width": 7.0},
                )
            ],
        )
        view.cleanup()

    def test_selected_annotation_style_change_does_not_update_tool_defaults(self):
        from ost_visualizer.presentation.utils.annotation_defaults import (
            get_annotation_style_for_tool,
            set_annotation_style_for_tool,
        )

        original_style = get_annotation_style_for_tool("rect")
        try:
            set_annotation_style_for_tool("rect", color="#00aa00", line_width=6.0)
            view = self._make_plan_view()
            selected = BidAnnotation(
                uid="a1",
                annotation_type="rect",
                position=[1.0, 2.0, 13.0, 14.0],
                color="#ff0000",
                width=4.0,
            )
            view._current_annotations = {"a1": selected}
            view._selected_uids = {"a1"}
            view.apply_annotation_style_to_selection(color="#336699", width=7.0)
            self.assertEqual(selected.color, "#336699")
            self.assertEqual(selected.width, 7.0)
            default_style = get_annotation_style_for_tool("rect")
            self.assertEqual(default_style.color, "#00aa00")
            self.assertEqual(default_style.line_width, 6.0)
            view.cleanup()
        finally:
            set_annotation_style_for_tool(
                "rect",
                color=original_style.color,
                line_width=original_style.line_width,
            )

    def test_default_annotation_style_change_does_not_repaint_existing_annotation(self):
        from ost_visualizer.presentation.utils.annotation_defaults import (
            get_annotation_style_for_tool,
            set_annotation_style_for_tool,
        )

        view = self._make_plan_view(
            annotation_renderer=AnnotationItemRenderer(FakeCoordinateSystem())
        )
        page = Page(uid="p1", name="P1", width_pts=612.0, height_pts=792.0)
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid=page.uid,
            position=[1.0, 2.0, 13.0, 14.0],
            color="#336699",
            width=4.0,
        )
        self.assertTrue(
            view.load_page(
                page,
                [],
                {},
                {},
                bid_ref=BidRef("bid.mdb", "bid-1"),
                annotations=[annotation],
            )
        )
        (item,) = view._uid_to_items["a1"]
        self.assertEqual(item.pen().color().name(), "#336699")
        self.assertEqual(item.pen().widthF(), 4.0)
        original_style = get_annotation_style_for_tool("rect")
        try:
            set_annotation_style_for_tool("rect", color="#ff0000", line_width=12.0)
            view._rebuild_current_overlays_from_model()
            self.assertEqual(annotation.color, "#336699")
            self.assertEqual(annotation.width, 4.0)
            (rebuilt,) = view._uid_to_items["a1"]
            self.assertEqual(rebuilt.pen().color().name(), "#336699")
            self.assertEqual(rebuilt.pen().widthF(), 4.0)
        finally:
            set_annotation_style_for_tool(
                "rect",
                color=original_style.color,
                line_width=original_style.line_width,
            )
            view.cleanup()

    def test_named_view_rename_uses_inline_edit_without_text_toolbar(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            properties={"Text": "Before"},
        )
        background = QGraphicsRectItem(0.0, 0.0, 40.0, 18.0)
        background.setData(0, "nv1")
        background.setData(2, NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND)
        label = QGraphicsTextItem("Before")
        label.setData(0, "nv1")
        label.setData(2, NAMED_VIEW_LABEL_ITEM_KIND)
        view._scene.addItem(background)
        view._scene.addItem(label)
        view._uid_to_items = {"nv1": [background, label]}
        view._current_annotations = {"nv1": annotation}
        view._selection_enabled = True
        emitted = []
        edit_states = []
        view.annotation_text_properties_flushed.connect(emitted.extend)
        view.text_annotation_edit_mode_changed.connect(edit_states.append)
        self.assertTrue(view._begin_named_view_rename("nv1"))
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertTrue(view._condition_text_toolbar.isHidden())
        label.setPlainText("After")
        view._finish_active_inline_text_edit(commit=True)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        self.assertEqual(edit_states, [True, False])
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(
            [tuple(change) for change in emitted],
            [("nv1", "namedview", {"Text": "Before"}, {"Text": "After"})],
        )
        self.assertEqual(
            label.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.NoTextInteraction,
        )
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_duplicate_named_view_draft_commit_keeps_inline_edit_active(self):
        from ost_visualizer.presentation.utils.named_view_validation import (
            show_duplicate_named_view_name,
        )

        for dialog_result in (
            QtWidgets.QMessageBox.StandardButton.Ok,
            QtWidgets.QMessageBox.StandardButton.NoButton,
        ):
            with self.subTest(dialog_result=dialog_result):
                view = self._make_plan_view()
                view._selection_enabled = True
                emitted = []
                validator_calls = []
                view.named_view_created.connect(
                    lambda position, page_uid, properties: emitted.append(
                        (list(position), page_uid, dict(properties))
                    )
                )

                def validate(name, exclude_uid=None):
                    validator_calls.append((name, exclude_uid))
                    show_duplicate_named_view_name(view)
                    return False

                view.set_named_view_name_validator(validate)
                self.assertTrue(
                    view.begin_named_view_draft(
                        [10.0, 20.0, 50.0, 20.0, 50.0, 60.0, 10.0, 60.0],
                        "page-1",
                    )
                )
                uid = view._draft_named_view_uid
                item = view._editing_named_view_item
                item.setPlainText(" Lobby ")
                with patch(
                    "ost_visualizer.presentation.utils.named_view_validation.show_warning"
                ) as warning:
                    warning.return_value = dialog_result
                    view._finish_named_view_rename(commit=True)
                self.assertEqual(emitted, [])
                self.assertEqual(validator_calls, [("Lobby", uid)])
                self.assertEqual(view._draft_named_view_uid, uid)
                self.assertIn(uid, view._current_annotations)
                self.assertTrue(view.is_text_annotation_inline_edit_active())
                self.assertEqual(item.toPlainText(), " Lobby ")
                self.assertEqual(
                    item.textInteractionFlags(),
                    QtCore.Qt.TextInteractionFlag.TextEditorInteraction,
                )
                self.assertEqual(
                    warning.call_args.args[2],
                    "Named view should have unique name",
                )
                warning.assert_called_once()
                view.set_named_view_name_validator(None)
                view._finish_named_view_rename(commit=False)
                self.assertIsNone(view._draft_named_view_uid)
                self.assertNotIn(uid, view._current_annotations)
                self.assertFalse(view.is_text_annotation_inline_edit_active())
                self.assertEqual(emitted, [])
                view.cleanup()

    def test_duplicate_named_view_close_then_unique_commit_succeeds_once(self):
        view = self._make_plan_view()
        view._selection_enabled = True
        emitted = []
        duplicate = True
        view.named_view_created.connect(
            lambda position, page_uid, properties: emitted.append(
                (list(position), page_uid, dict(properties))
            )
        )

        def validate(_name, _exclude_uid=None):
            return not duplicate

        view.set_named_view_name_validator(validate)
        self.assertTrue(
            view.begin_named_view_draft(
                [10.0, 20.0, 50.0, 20.0, 50.0, 60.0, 10.0, 60.0],
                "page-1",
            )
        )
        uid = view._draft_named_view_uid
        item = view._editing_named_view_item
        item.setPlainText("Lobby")
        view._finish_named_view_rename(commit=True)
        self.assertEqual(emitted, [])
        self.assertEqual(view._draft_named_view_uid, uid)
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        duplicate = False
        item.setPlainText("Lobby 2")
        view._finish_named_view_rename(commit=True)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(
            emitted[0][0], [10.0, 20.0, 50.0, 20.0, 50.0, 60.0, 10.0, 60.0]
        )
        self.assertEqual(emitted[0][1], "page-1")
        self.assertEqual(emitted[0][2]["Text"], "Lobby 2")
        self.assertIsNone(view._draft_named_view_uid)
        self.assertNotIn(uid, view._current_annotations)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        view.cleanup()

    def test_empty_named_view_draft_commit_keeps_editor_active(self):
        view = self._make_plan_view()
        view._selection_enabled = True
        emitted = []
        view.named_view_created.connect(
            lambda position, page_uid, properties: emitted.append(
                (list(position), page_uid, dict(properties))
            )
        )
        self.assertTrue(
            view.begin_named_view_draft(
                [10.0, 20.0, 50.0, 20.0, 50.0, 60.0, 10.0, 60.0],
                "page-1",
            )
        )
        uid = view._draft_named_view_uid
        view._editing_named_view_item.setPlainText("   ")
        view._finish_named_view_rename(commit=True)
        self.assertEqual(emitted, [])
        self.assertEqual(view._draft_named_view_uid, uid)
        self.assertIn(uid, view._current_annotations)
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        view._finish_named_view_rename(commit=False)
        self.assertIsNone(view._draft_named_view_uid)
        self.assertNotIn(uid, view._current_annotations)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        view.cleanup()

    def test_named_view_draft_font_matches_final_renderer_font(self):
        from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
            create_named_view_label_font,
        )

        view = self._make_plan_view()
        view._selection_enabled = True
        self.assertTrue(
            view.begin_named_view_draft(
                [10.0, 20.0, 50.0, 20.0, 50.0, 60.0, 10.0, 60.0],
                "page-1",
            )
        )
        item = view._editing_named_view_item
        expected = create_named_view_label_font(
            view._scene_builder.get_coordinate_system()
        )
        self.assertEqual(item.font().family(), expected.family())
        self.assertEqual(item.font().pointSize(), expected.pointSize())
        self.assertEqual(item.font().bold(), expected.bold())
        # Independent oracle: the label the real renderer produces for a
        # committed named view must use the same font as the draft editor.
        final_view = self._make_plan_view(
            annotation_renderer=AnnotationItemRenderer(FakeCoordinateSystem())
        )
        page = Page(uid="page-1", name="Page 1", width_pts=612.0, height_pts=792.0)
        committed = self._named_view_annotation(uid="nv-final", page_uid="page-1")
        self.assertTrue(
            final_view.load_page(
                page,
                [],
                {},
                {},
                bid_ref=BidRef("bid.mdb", "bid-1"),
                annotations=[committed],
            )
        )
        final_label = final_view._named_view_label_item("nv-final")
        self.assertIsNotNone(final_label)
        self.assertEqual(item.font().family(), final_label.font().family())
        self.assertEqual(item.font().pointSize(), final_label.font().pointSize())
        self.assertEqual(item.font().bold(), final_label.font().bold())
        view._finish_named_view_rename(commit=False)
        view.cleanup()
        final_view.cleanup()

    def test_select_all_ignores_takeoffs_hidden_by_condition_layer(self):
        view = self._make_plan_view()
        conditions = {
            "visible-area": Condition(
                uid="visible-area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
            ),
            "hidden-area": Condition(
                uid="hidden-area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=False,
            ),
            "visible-linear": Condition(
                uid="visible-linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            ),
            "hidden-linear": Condition(
                uid="hidden-linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=False,
            ),
            "visible-count": Condition(
                uid="visible-count",
                condition_type=Condition.TYPE_COUNT,
                layer_visible=True,
            ),
            "hidden-count": Condition(
                uid="hidden-count",
                condition_type=Condition.TYPE_COUNT,
                layer_visible=False,
            ),
        }
        view._current_conditions = conditions
        view._current_takeoffs = {
            "visible-area": Takeoff(
                uid="visible-area",
                condition_uid="visible-area",
                position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0],
            ),
            "hidden-area": Takeoff(
                uid="hidden-area",
                condition_uid="hidden-area",
                position=[30.0, 0.0, 50.0, 0.0, 50.0, 20.0],
            ),
            "visible-linear": Takeoff(
                uid="visible-linear",
                condition_uid="visible-linear",
                position=[0.0, 30.0, 20.0, 30.0],
            ),
            "hidden-linear": Takeoff(
                uid="hidden-linear",
                condition_uid="hidden-linear",
                position=[30.0, 30.0, 50.0, 30.0],
            ),
            "visible-count": Takeoff(
                uid="visible-count",
                condition_uid="visible-count",
                position=[10.0, 50.0],
            ),
            "hidden-count": Takeoff(
                uid="hidden-count",
                condition_uid="hidden-count",
                position=[40.0, 50.0],
            ),
        }
        view._current_annotations = {}
        view._uid_to_items = {}
        view._selection_enabled = True
        view._cursor_mode = "select"
        for uid in ("visible-area", "visible-linear", "visible-count"):
            item = QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
            item.setData(0, uid)
            view._scene.addItem(item)
            view._uid_to_items[uid] = [item]
        view.select_all()
        self.assertEqual(
            view._selected_uids,
            {"visible-area", "visible-linear", "visible-count"},
        )
        self.assertTrue(view._selection_items)
        self.assertTrue(
            all(
                item.data(0) not in {"hidden-area", "hidden-linear", "hidden-count"}
                for item in view._selection_items
            )
        )
        view.cleanup()

    def test_select_all_ignores_hidden_annotations(self):
        view = self._make_plan_view()
        view._current_takeoffs = {}
        view._current_conditions = {}
        view._selection_enabled = True
        view._cursor_mode = "select"
        view._current_annotations = {
            "visible-ann": BidAnnotation(
                uid="visible-ann",
                annotation_type="rect",
                position=[0.0, 0.0, 20.0, 20.0],
                visible=True,
            ),
            "hidden-ann": BidAnnotation(
                uid="hidden-ann",
                annotation_type="rect",
                position=[30.0, 30.0, 50.0, 50.0],
                visible=False,
            ),
        }
        view._uid_to_items = {}
        visible_item = QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
        visible_item.setData(0, "visible-ann")
        view._scene.addItem(visible_item)
        view._uid_to_items["visible-ann"] = [visible_item]
        view.select_all()
        self.assertEqual(view._selected_uids, {"visible-ann"})
        self.assertTrue(
            all(item.data(0) != "hidden-ann" for item in view._selection_items)
        )
        view.cleanup()

    def test_hidden_annotation_layer_is_not_selectable_until_reenabled(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="text",
            position=[20.0, 20.0, 80.0, 24.0],
            properties={"Text": "Note"},
            layer_uid="annotation-layer",
            visible=True,
        )
        item = QGraphicsTextItem("Note")
        item.setData(0, "ann-1")
        view._scene.addItem(item)
        view._uid_to_items = {"ann-1": [item]}
        view._current_annotations = {"ann-1": annotation}
        view._current_takeoffs = {}
        view._current_conditions = {}
        view._current_bid_page_uid = "page-1"
        view._selection_enabled = True
        view._cursor_mode = "select"
        self.assertTrue(view.apply_layer_visibility("annotation-layer", False, {}))
        view.set_selected_uids({"ann-1"})
        self.assertEqual(view._selected_uids, set())
        view.select_all()
        self.assertEqual(view._selected_uids, set())
        self.assertTrue(view.apply_layer_visibility("annotation-layer", True, {}))
        view.set_selected_uids({"ann-1"})
        self.assertEqual(view._selected_uids, {"ann-1"})
        view.cleanup()

    def test_newly_registered_annotation_respects_hidden_layer_without_reload(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="rect",
            position=[1.0, 1.0, 10.0, 10.0],
            layer_uid="custom-notes-layer",
            visible=True,
        )
        item = QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
        item.setData(0, "ann-1")
        view._scene.addItem(item)
        view._current_bid_page_uid = "page-1"
        view._current_annotations = {"ann-1": annotation}
        view._current_takeoffs = {}
        view._hidden_layer_uids = {"custom-notes-layer"}
        view._register_uid_items("ann-1", [item])
        self.assertFalse(item.isVisible())
        self.assertFalse(view._is_selectable("ann-1"))
        view.cleanup()

    def test_newly_registered_takeoff_respects_hidden_condition_layer(self):
        view = self._make_plan_view()
        condition = Condition(
            uid="condition-1",
            name="Condition",
            layer_uid="custom-condition-layer",
            layer_visible=False,
        )
        takeoff = Takeoff(uid="takeoff-1", condition_uid=condition.uid)
        item = QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
        item.setData(0, "takeoff-1")
        view._scene.addItem(item)
        view._current_bid_page_uid = "page-1"
        view._current_conditions = {condition.uid: condition}
        view._current_takeoffs = {"takeoff-1": takeoff}
        view._current_annotations = {}
        view._hidden_layer_uids = {"custom-condition-layer"}
        view._register_uid_items("takeoff-1", [item])
        self.assertFalse(item.isVisible())
        self.assertFalse(view._is_selectable("takeoff-1"))
        view.cleanup()

    def test_clear_selection_signal_observes_fully_cleared_scene(self):
        view = self._make_plan_view()
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        background = ImageBackgroundItem(image, 100.0, 100.0)
        view._scene.addItem(background)
        view._background_item = background
        view._current_page = Page(uid="page-1", name="Page 1")
        view._current_bid_page_uid = "page-1"
        view._selected_uids = {"takeoff-1"}
        observations = []

        def refresh_editing_projection(_uids):
            view.set_editing_enabled(False)
            observations.append(
                (
                    "selection",
                    view._current_page,
                    view._background_item,
                    tuple(view._scene.items()),
                )
            )

        view.takeoff_selection_changed.connect(refresh_editing_projection)
        view.cursor_mode_change_requested.connect(
            lambda _mode: observations.append(
                (
                    "cursor",
                    view._current_page,
                    view._background_item,
                    tuple(view._scene.items()),
                )
            )
        )
        view.page_cleared.connect(
            lambda: observations.append(
                (
                    "page",
                    view._current_page,
                    view._background_item,
                    tuple(view._scene.items()),
                )
            )
        )
        view.clear()
        self.assertEqual([entry[0] for entry in observations].count("selection"), 1)
        self.assertEqual([entry[0] for entry in observations].count("page"), 1)
        self.assertGreaterEqual([entry[0] for entry in observations].count("cursor"), 1)
        self.assertTrue(all(entry[1:] == (None, None, ()) for entry in observations))
        view.cleanup()

    def test_inline_text_annotation_edit_respects_enabled_capability(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view.set_text_annotation_inline_edit_enabled(False)
        self.assertFalse(view._begin_text_annotation_edit("a1"))
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        view.set_text_annotation_inline_edit_enabled(True)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        view._finish_active_inline_text_edit(commit=False)
        view.cleanup()

    def test_inline_text_annotation_edit_respects_access_callback(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view.set_text_annotation_inline_edit_allowed_fn(lambda: False)
        self.assertFalse(view._begin_text_annotation_edit("a1"))
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        view.set_text_annotation_inline_edit_allowed_fn(lambda: True)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        view._finish_active_inline_text_edit(commit=False)
        view.cleanup()

    def test_same_page_active_area_change_refreshes_mutated_selection_snapshot(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        selections = {"page-1": "area-1"}
        view._current_page_area_selections = (
            TakeoffPlanView._snapshot_page_area_selections(selections)
        )
        self.assertIsNot(view._current_page_area_selections, selections)
        selections["page-1"] = "area-2"
        view._refresh_overlays = lambda *args: calls.append(
            ("refresh_overlays", args[5])
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections=selections,
            hidden_layer_uids=set(),
        )
        self.assertTrue(refreshed)
        self.assertEqual(
            [call for call in calls if call[0] == "refresh_overlays"],
            [("refresh_overlays", {"page-1": "area-2"})],
        )

    def test_dirty_positions_preserve_each_table_scoped_annotation_identity(self):
        view = SimpleNamespace(
            _dirty_ann_positions={
                "shared_text": (ANNOTATION_TYPE_TEXT, [10.0, 11.0]),
                "shared_hotlink": (ANNOTATION_TYPE_HOTLINK, [20.0, 21.0]),
            },
            _ann_db_uid_map={
                "shared_text": "shared",
                "shared_hotlink": "shared",
            },
        )
        annotations = [
            self._text_annotation(uid="shared", text="old"),
            self._hotlink_annotation(uid="shared"),
        ]
        refreshed = TakeoffPlanView._annotations_with_dirty_positions(
            view,
            annotations,
        )
        self.assertEqual(refreshed[0].position, [10.0, 11.0])
        self.assertEqual(refreshed[1].position, [20.0, 21.0])

    def test_layer_visibility_hides_loaded_items_and_clears_selection(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        condition = Condition(
            uid="c1",
            name="Condition",
            layer_uid="l1",
            layer_visible=True,
        )
        takeoff = Takeoff(uid="t1", condition_uid="c1", page_uid=page.uid)
        item = QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
        item.setData(0, "t1")
        view._scene.addItem(item)
        view._current_bid_page_uid = page.uid
        view._current_page = page
        view._current_takeoffs = {"t1": takeoff}
        view._current_conditions = {"c1": condition}
        view._uid_to_items = {"t1": [item]}
        view._selected_uids = {"t1"}
        condition.layer_visible = False
        try:
            self.assertTrue(view.apply_layer_visibility("l1", False, {"c1": condition}))
            self.assertFalse(item.isVisible())
            self.assertFalse(view._is_selectable("t1"))
            self.assertEqual(view._selected_uids, set())
        finally:
            view.cleanup()

    def test_scene_rect_update_keeps_existing_view_center_when_off_page_items_expand_origin(
        self,
    ):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        scene = FakeScene()
        calls = []
        view._scene = scene
        view._background_item = FakePageItem(
            scene, QtCore.QRectF(0.0, 0.0, 100.0, 200.0)
        )
        view._white_canvas_item = None
        view._takeoff_items = [
            FakePageItem(scene, QtCore.QRectF(-10000.0, -10000.0, 20.0, 20.0))
        ]
        view._hotlink_items = []
        view._cursor_mode = CURSOR_MODE_SELECT
        view._overlay_move_dragging = False
        view._overlay_move_handle_item = None
        view._load_view_applied = True
        view.get_precise_viewport_scene_center = lambda: QtCore.QPointF(25.0, 50.0)
        view.centerOn = lambda point: calls.append(point)
        view._update_scene_rect()
        self.assertTrue(scene.sceneRect().contains(QtCore.QPointF(0.0, 0.0)))
        self.assertTrue(scene.sceneRect().contains(QtCore.QPointF(-10000.0, -10000.0)))
        self.assertEqual(calls, [QtCore.QPointF(25.0, 50.0)])

    def test_same_page_overlay_refresh_does_not_recenter_when_scene_rect_is_unchanged(
        self,
    ):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        scene = FakeScene()
        scene._scene_rect = QtCore.QRectF(-50.0, -50.0, 200.0, 300.0)
        calls = []
        view._scene = scene
        view._background_item = FakePageItem(
            scene, QtCore.QRectF(0.0, 0.0, 100.0, 200.0)
        )
        view._white_canvas_item = None
        view._takeoff_items = []
        view._hotlink_items = []
        view._load_view_applied = True
        view.viewport = lambda: FakeSizedViewport()
        view.mapToScene = lambda _point: QtCore.QPointF(25.0, 50.0)
        view.centerOn = lambda point: calls.append(point)
        background_pos = view._background_item.pos()
        view._update_scene_rect()
        view._update_scene_rect()
        self.assertEqual(scene.set_scene_rect_calls, 0)
        self.assertEqual(calls, [])
        self.assertEqual(view._background_item.pos(), background_pos)


class TakeoffPlanViewLoadPageTests(_TakeoffPlanViewOverlayRefreshFixture):
    """TakeoffPlanView.load_page."""

    def test_current_page_render_starts_and_completes_loading_bar(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        self.assertTrue(view._render_loading_bar.is_loading)
        self.assertTrue(view._render_loading_bar.isHidden())
        request_id, request = view._rendering_service.page_requests[-1]
        request["callback"](
            RenderResult(
                request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        QApplication.processEvents()
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertTrue(view._render_loading_bar.isHidden())
        self.assertIsNone(view._pending_page_data)
        view.cleanup()

    def test_page_switch_updates_canvas_and_schedules_render_before_completion(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        self.assertEqual(view.current_page_uid, "p1")
        self.assertIsNotNone(view._white_canvas_item)
        self.assertIs(view._white_canvas_item.scene(), view._scene)
        self.assertIsNone(view._background_item)
        self.assertEqual(len(view._rendering_service.page_requests), 1)
        self.assertTrue(view._render_loading_bar.is_loading)
        view.cleanup()

    def test_missing_page_file_bar_appears_after_current_page_render_failure(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="missing.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        self.assertTrue(view._render_loading_bar.is_loading)
        self.assertFalse(view._missing_file_bar.is_active)
        request_id, request = view._rendering_service.page_requests[-1]
        request["callback"](RenderResult(request_id, False, None, "missing"))
        QApplication.processEvents()
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertTrue(view._missing_file_bar.is_active)
        self.assertFalse(view._missing_file_bar.isHidden())
        self.assertEqual(
            view._missing_file_bar.toolTip(),
            "Page image/PDF was not found or could not be loaded: missing.pdf."
            "\nmissing.pdf\nmissing",
        )
        view.cleanup()

    def test_missing_page_file_bar_hides_when_switching_to_valid_page(self):
        view = self._make_plan_view()
        missing = Page(
            uid="p1",
            name="P1",
            image_path="missing.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        valid = Page(
            uid="p2",
            name="P2",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(missing, [], {}, {}))
        request_id, request = view._rendering_service.page_requests[-1]
        request["callback"](RenderResult(request_id, False, None, "missing"))
        QApplication.processEvents()
        self.assertTrue(view._missing_file_bar.is_active)
        self.assertTrue(view.load_page(valid, [], {}, {}))
        self.assertFalse(view._missing_file_bar.is_active)
        valid_request_id, valid_request = view._rendering_service.page_requests[-1]
        valid_request["callback"](
            RenderResult(
                valid_request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        QApplication.processEvents()
        self.assertFalse(view._missing_file_bar.is_active)
        self.assertTrue(view._missing_file_bar.isHidden())
        view.cleanup()

    def test_stale_page_render_failure_does_not_show_missing_file_bar(self):
        view = self._make_plan_view()
        first = Page(
            uid="p1",
            name="P1",
            image_path="missing.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        second = Page(
            uid="p2",
            name="P2",
            image_path="second.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(first, [], {}, {}))
        first_request_id, first_request = view._rendering_service.page_requests[-1]
        self.assertTrue(view.load_page(second, [], {}, {}))
        first_request["callback"](
            RenderResult(first_request_id, False, None, "missing")
        )
        QApplication.processEvents()
        self.assertFalse(view._missing_file_bar.is_active)
        self.assertTrue(view._render_loading_bar.is_loading)
        view.cleanup()

    def test_composite_and_overlay_only_renders_start_loading_bar(self):
        view = self._make_plan_view()
        composite_page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(composite_page, [], {}, {}))
        self.assertTrue(view._render_loading_bar.is_loading)
        self.assertEqual(len(view._rendering_service.composite_requests), 1)
        view.clear()
        overlay_page = Page(
            uid="p2",
            name="P2",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(overlay_page, [], {}, {}))
        self.assertTrue(view._render_loading_bar.is_loading)
        self.assertEqual(len(view._rendering_service.overlay_requests), 1)
        view.cleanup()

    def test_main_page_plus_overlay_chain_hides_loading_after_overlay_completion(self):
        class ChainedOverlayLoadCoordinator(FakeLoadCoordinator):
            def determine_load_strategy(self, page):
                strategy = super().determine_load_strategy(page)
                return LoadStrategy(
                    needs_async_loading=True,
                    view_scale=strategy.view_scale,
                    show_canvas=True,
                    pdf_width_pts=strategy.pdf_width_pts,
                    pdf_height_pts=strategy.pdf_height_pts,
                    placeholder_width=strategy.placeholder_width,
                    placeholder_height=strategy.placeholder_height,
                    load_composite=False,
                    load_main=True,
                    load_overlay=False,
                    main_scale=strategy.main_scale,
                )

            def create_pending_page_data(
                self, page, strategy, pdf_width_pts, pdf_height_pts
            ):
                data = super().create_pending_page_data(
                    page, strategy, pdf_width_pts, pdf_height_pts
                )
                data["show_mode"] = 2
                data["show_overlay"] = True
                return data

        view = self._make_plan_view()
        view._load_coordinator = ChainedOverlayLoadCoordinator()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        page_request_id, page_request = view._rendering_service.page_requests[-1]
        page_request["callback"](
            RenderResult(
                page_request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        QApplication.processEvents()
        self.assertTrue(view._render_loading_bar.is_loading)
        self.assertIsNotNone(view._pending_page_data)
        overlay_request_id, overlay_request = view._rendering_service.overlay_requests[
            -1
        ]
        self.assertEqual(overlay_request["render_scale"], INTERACTIVE_PDF_RENDER_SCALE)
        overlay_request["callback"](
            RenderResult(
                overlay_request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        QApplication.processEvents()
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertIsNone(view._pending_page_data)
        view.cleanup()

    def test_invalid_overlay_geometry_completes_visual_load_without_an_item(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 0.0, 0.0),
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        request_id, request = view._rendering_service.overlay_requests[-1]
        with self.assertLogs(
            "ost_visualizer.presentation.components.plan_view.components.page_loader",
            level="WARNING",
        ):
            request["callback"](
                RenderResult(
                    request_id,
                    True,
                    QImage(1224, 1584, QImage.Format.Format_ARGB32),
                    None,
                )
            )
        QApplication.processEvents()
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertTrue(view._load_geometry_ready)
        self.assertIsNone(view._pending_page_data)
        self.assertEqual(view._overlay_items, [])
        view.cleanup()

    def test_page_switch_restarts_loading_and_stale_completion_does_not_hide_newer_bar(
        self,
    ):
        view = self._make_plan_view()
        first = Page(
            uid="p1",
            name="P1",
            image_path="first.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        second = Page(
            uid="p2",
            name="P2",
            image_path="second.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(first, [], {}, {}))
        first_request_id, first_request = view._rendering_service.page_requests[-1]
        self.assertTrue(view.load_page(second, [], {}, {}))
        first_request["callback"](
            RenderResult(
                first_request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        QApplication.processEvents()
        self.assertTrue(view._render_loading_bar.is_loading)
        second_request_id, second_request = view._rendering_service.page_requests[-1]
        second_request["callback"](
            RenderResult(
                second_request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        QApplication.processEvents()
        self.assertFalse(view._render_loading_bar.is_loading)
        view.cleanup()

    def test_fast_render_completion_before_reveal_keeps_loading_bar_hidden(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        request_id, request = view._rendering_service.page_requests[-1]
        request["callback"](
            RenderResult(
                request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertTrue(view._render_loading_bar.isHidden())
        # The pending reveal must be cancelled so the bar cannot flash later.
        self.assertFalse(view._render_loading_bar._reveal_timer.isActive())
        view.cleanup()

    def test_clear_resets_active_loading_bar(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        self.assertTrue(view._render_loading_bar.is_loading)
        view.clear()
        self.assertFalse(view._render_loading_bar.is_loading)
        self.assertTrue(view._render_loading_bar.isHidden())
        view.cleanup()

    def test_highlight_remains_observable_across_page_image_modes_and_layer_state(
        self,
    ):
        load_coordinator = PageLoadStrategyService(
            SimpleNamespace(get_page_size=lambda _path, _index: (72.0, 72.0))
        )
        view = self._make_plan_view(
            load_coordinator=load_coordinator,
            annotation_renderer=AnnotationItemRenderer(FakeCoordinateSystem()),
        )
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 1.0, 1.0),
            width_pts=72.0,
            height_pts=72.0,
        )
        highlight = BidAnnotation(
            uid="highlight-1",
            annotation_type="highlight",
            page_uid=page.uid,
            layer_uid="annotation-layer",
            position=[20.0, 20.0, 100.0, 20.0, 100.0, 100.0, 20.0, 100.0],
            color="#ffff00",
        )

        def complete_page_visual(mode):
            if mode == SHOW_ORIGINAL:
                request_id, request = view._rendering_service.page_requests[-1]
            elif mode == SHOW_OVERLAY:
                request_id, request = view._rendering_service.overlay_requests[-1]
            else:
                request_id, request = view._rendering_service.composite_requests[-1]
            image = QImage(216, 216, QImage.Format.Format_ARGB32)
            image.fill(QColor("white"))
            request["callback"](RenderResult(request_id, True, image, None))
            QApplication.processEvents()

        try:
            for mode in (
                SHOW_ORIGINAL,
                SHOW_OVERLAY,
                SHOW_BOTH,
                SHOW_OVERLAY,
                SHOW_ORIGINAL,
                SHOW_BOTH,
                SHOW_OVERLAY,
            ):
                current_page = replace(page, image_show_mode=mode)
                self.assertTrue(
                    view.load_page(
                        current_page,
                        [],
                        {},
                        {},
                        annotations=[highlight],
                        hidden_layer_uids=set(),
                    )
                )
                complete_page_visual(mode)
                highlight_item = view._uid_to_items[highlight.uid][0]
                self.assertIsInstance(highlight_item, HighlightGraphicsItem)
                self.assertTrue(highlight_item.isVisible())
                self.assertEqual(
                    self._render_scene_pixel(view, 60, 60), QColor("#ffff00")
                )
                if mode == SHOW_OVERLAY:
                    self.assertLess(
                        view._overlay_items[0].zValue(), highlight_item.zValue()
                    )
            view.set_selected_uids({highlight.uid})
            self.assertEqual(view._selected_uids, {highlight.uid})
            self.assertTrue(highlight_item.isVisible())
            self.assertEqual(self._render_scene_pixel(view, 60, 60), QColor("#ffff00"))
            self.assertTrue(view.apply_layer_visibility("annotation-layer", False, {}))
            self.assertFalse(highlight_item.isVisible())
            self.assertEqual(self._render_scene_pixel(view, 60, 60), QColor("white"))
            self.assertTrue(view.apply_layer_visibility("annotation-layer", True, {}))
            self.assertTrue(highlight_item.isVisible())
            self.assertEqual(self._render_scene_pixel(view, 60, 60), QColor("#ffff00"))
            blank_page = Page(
                uid="blank", name="Blank", width_pts=72.0, height_pts=72.0
            )
            self.assertTrue(view.load_page(blank_page, [], {}, {}))
            for move_mode in (SHOW_OVERLAY, SHOW_BOTH):
                move_page = replace(page, image_show_mode=move_mode)
                self.assertTrue(
                    view.load_page(
                        move_page,
                        [],
                        {},
                        {},
                        annotations=[highlight],
                        hidden_layer_uids=set(),
                    )
                )
                complete_page_visual(move_mode)
                highlight_item = view._uid_to_items[highlight.uid][0]
                self.assertEqual(
                    self._render_scene_pixel(view, 60, 60), QColor("#ffff00")
                )
                self.assertTrue(view.show_overlay_move_handle())
                base_request_id, base_request = view._rendering_service.page_requests[
                    -1
                ]
                overlay_request_id, overlay_request = (
                    view._rendering_service.overlay_requests[-1]
                )
                preview_image = QImage(216, 216, QImage.Format.Format_ARGB32)
                preview_image.fill(QColor("white"))
                base_request["callback"](
                    RenderResult(base_request_id, True, preview_image, None)
                )
                overlay_request["callback"](
                    RenderResult(overlay_request_id, True, preview_image, None)
                )
                QApplication.processEvents()
                self.assertLess(
                    view._overlay_move_preview_overlay_item.zValue(),
                    PAPER_HIGHLIGHT_Z,
                )
                self.assertTrue(highlight_item.isVisible())
                self.assertEqual(
                    self._render_scene_pixel(view, 60, 60), QColor("#ffff00")
                )
                view.cancel_overlay_move_mode(restore_preview=True)
        finally:
            view.cleanup()

    def test_show_both_loads_composite_instead_of_separate_layers(self):
        view = self._make_plan_view()
        rendering_service = FakeRenderingService()
        view._rendering_service = rendering_service
        view._load_coordinator = PageLoadStrategyService(FakePageSizeProvider())
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(
            view.load_page(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
            )
        )
        self.assertTrue(view._can_zoom_rerender)
        self.assertEqual(rendering_service.page_requests, [])
        self.assertEqual(len(rendering_service.composite_requests), 1)
        self.assertEqual(rendering_service.composite_requests[0][1]["page"], page)
        view.cleanup()

    def test_show_both_tif_overlay_loads_composite_instead_of_separate_layers(self):
        view = self._make_plan_view()
        rendering_service = FakeRenderingService()
        view._rendering_service = rendering_service
        view._load_coordinator = PageLoadStrategyService(FakePageSizeProvider())
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.tif",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(
            view.load_page(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
            )
        )
        self.assertTrue(view._can_zoom_rerender)
        self.assertEqual(rendering_service.page_requests, [])
        self.assertEqual(len(rendering_service.composite_requests), 1)
        self.assertEqual(rendering_service.composite_requests[0][1]["page"], page)
        self.assertEqual(
            rendering_service.composite_requests[0][1]["render_scale"],
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        view.cleanup()

    def test_overlay_only_raster_loads_native_pixels_independent_of_scene_scale(self):
        class DoubleSizeProvider:
            def get_page_size(self, _file_path, _page_index):
                return 1224.0, 1584.0

        view = self._make_plan_view()
        rendering_service = FakeRenderingService()
        view._rendering_service = rendering_service
        view._load_coordinator = PageLoadStrategyService(DoubleSizeProvider())
        page = Page(
            uid="p1",
            name="P1",
            overlay_image_path="overlay.tif",
            image_show_mode=1,
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        self.assertEqual(view._scene_scale, 2.0)
        self.assertEqual(len(rendering_service.overlay_requests), 1)
        self.assertEqual(
            rendering_service.overlay_requests[0][1]["render_scale"],
            RASTER_NATIVE_RENDER_SCALE,
        )
        view.cleanup()

    def test_composite_result_creates_one_canvas_when_dimensions_arrive_late(self):
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
            image_show_mode=2,
        )
        view = self._make_plan_view()
        view._load_coordinator = PageLoadStrategyService(FakePageSizeProvider())
        self.assertTrue(view.load_page(page, [], {}, {}))
        self.assertIsNone(view._white_canvas_item)
        request_id, request = view._rendering_service.composite_requests[-1]
        request["callback"](
            RenderResult(
                request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        try:
            canvas = view._white_canvas_item
            self.assertIsNotNone(canvas)
            self.assertTrue(
                view.apply_page_image_layer_visibility(
                    replace(page, layer_visible=False)
                )
            )
            self.assertTrue(canvas.isVisible())
            self.assertTrue(view._page_scene_rect().isValid())
            self.assertEqual(
                sum(item is canvas for item in view._scene.items()),
                1,
            )
        finally:
            view.cleanup()

    def test_hidden_both_mode_canvas_is_not_late_when_one_image_is_disabled(self):
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
        )
        view = self._make_plan_view()
        view._load_coordinator = PageLoadStrategyService(FakePageSizeProvider())
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        self.assertTrue(view.load_page(page, [], {}, {}))
        request_id, request = view._rendering_service.composite_requests[-1]
        request["callback"](
            RenderResult(
                request_id,
                True,
                QImage(1224, 1584, QImage.Format.Format_ARGB32),
                None,
            )
        )
        QApplication.processEvents()
        try:
            hidden_page = replace(page, layer_visible=False)
            self.assertTrue(view.apply_page_image_layer_visibility(hidden_page))
            self.assertIsNotNone(view._white_canvas_item)
            self.assertTrue(view._white_canvas_item.isVisible())
            view._capture_view_state_to_page(page, allow_pending_load=True)
            self.assertGreater(page.zoom_fac, 0.0)
            fit_calls = []
            view.fit_to_page = lambda: fit_calls.append("fit")
            original_only = replace(
                page,
                image_show_mode=0,
                layer_visible=False,
            )
            self.assertTrue(view.load_page(original_only, [], {}, {}))
            self.assertTrue(view._white_canvas_item.isVisible())
            self.assertTrue(view._page_scene_rect().isValid())
            self.assertTrue(view._scene.sceneRect().isValid())
            self.assertEqual(
                sum(item is view._white_canvas_item for item in view._scene.items()),
                1,
            )
            self.assertEqual(fit_calls, [])
        finally:
            view.cleanup()

    def test_user_zoom_during_async_page_load_survives_image_success(self):
        view = self._make_plan_view()
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        self.assertFalse(view._load_view_applied)
        loading_scale = view.transform().m11()
        view.zoom_in()
        zoomed_scale = view.transform().m11()
        self.assertNotAlmostEqual(zoomed_scale, loading_scale)
        request_id, request = view._rendering_service.page_requests[-1]
        result = RenderResult(
            request_id=request_id,
            success=True,
            image=QImage(1224, 1584, QImage.Format.Format_ARGB32),
            error=None,
        )
        request["callback"](result)
        QApplication.processEvents()
        self.assertTrue(view._load_view_applied)
        self.assertAlmostEqual(view.transform().m11(), zoomed_scale)
        view.cleanup()

    def test_user_zoom_percent_during_async_page_load_survives_image_success(self):
        view = self._make_plan_view()
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
            zoom_fac=1.332,
            current_x=408.0,
            current_y=528.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        view.set_zoom_percent(250.0)
        zoomed_scale = view.transform().m11()
        self.assertTrue(view._load_user_view_changed)
        request_id, request = view._rendering_service.page_requests[-1]
        result = RenderResult(
            request_id=request_id,
            success=True,
            image=QImage(1224, 1584, QImage.Format.Format_ARGB32),
            error=None,
        )
        request["callback"](result)
        QApplication.processEvents()
        self.assertTrue(view._load_view_applied)
        self.assertAlmostEqual(view.transform().m11(), zoomed_scale)
        view.cleanup()

    def test_reset_view_during_async_page_load_overrides_restored_zoom(self):
        view = self._make_plan_view()
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
            zoom_fac=1.332,
            current_x=408.0,
            current_y=528.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        restored_scale = view.transform().m11()
        view.reset_view()
        reset_scale = view.transform().m11()
        self.assertTrue(view._load_user_view_changed)
        self.assertNotAlmostEqual(reset_scale, restored_scale)
        self.assertAlmostEqual(page.zoom_fac, view.get_view_state()[0])
        request_id, request = view._rendering_service.page_requests[-1]
        result = RenderResult(
            request_id=request_id,
            success=True,
            image=QImage(1224, 1584, QImage.Format.Format_ARGB32),
            error=None,
        )
        request["callback"](result)
        QApplication.processEvents()
        self.assertTrue(view._load_view_applied)
        self.assertAlmostEqual(view.transform().m11(), reset_scale)
        view.cleanup()

    def test_pan_during_async_page_load_counts_as_user_view_change(self):
        view = self._make_plan_view()
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
            zoom_fac=1.332,
            current_x=408.0,
            current_y=528.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        center_before_pan = self._viewport_state(view)[1]
        view._panning = True
        view._last_pan_point = QtCore.QPoint(10, 10)
        self.assertTrue(view._apply_pan_update(QtCore.QPoint(20, 20)))
        self.assertTrue(view._load_user_view_changed)
        panned_center = self._viewport_state(view)[1]
        self.assertNotEqual(panned_center, center_before_pan)
        request_id, request = view._rendering_service.page_requests[-1]
        result = RenderResult(
            request_id=request_id,
            success=True,
            image=QImage(1224, 1584, QImage.Format.Format_ARGB32),
            error=None,
        )
        request["callback"](result)
        QApplication.processEvents()
        self.assertTrue(view._load_view_applied)
        self.assertAlmostEqual(
            self._viewport_state(view)[1].x(), panned_center.x(), delta=0.01
        )
        self.assertAlmostEqual(
            self._viewport_state(view)[1].y(), panned_center.y(), delta=0.01
        )
        view.cleanup()

    def test_async_page_load_still_fits_when_user_does_not_zoom(self):
        view = self._make_plan_view()
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        page = Page(
            uid="p1",
            name="P1",
            image_path="page.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        loading_scale = view.transform().m11()
        self.assertFalse(view._load_view_applied)
        # Resize while the render is in flight; the completed load must refit.
        view.resize(500, 450)
        QApplication.processEvents()
        request_id, request = view._rendering_service.page_requests[-1]
        result = RenderResult(
            request_id=request_id,
            success=True,
            image=QImage(1224, 1584, QImage.Format.Format_ARGB32),
            error=None,
        )
        request["callback"](result)
        QApplication.processEvents()
        self.assertTrue(view._load_view_applied)
        self.assertFalse(view._load_user_view_changed)
        fitted_scale = view.transform().m11()
        view.fit_to_page()
        self.assertAlmostEqual(fitted_scale, view.transform().m11(), delta=0.001)
        self.assertGreater(fitted_scale, loading_scale)
        view.cleanup()

    def test_user_zoom_during_failed_async_page_load_leaves_canvas_stable(self):
        view = self._make_plan_view()
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        page = Page(
            uid="p1",
            name="P1",
            image_path="missing.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        view.zoom_in()
        zoomed_scale = view.transform().m11()
        request_id, request = view._rendering_service.page_requests[-1]
        result = RenderResult(
            request_id=request_id,
            success=False,
            image=None,
            error="missing",
        )
        request["callback"](result)
        QApplication.processEvents()
        self.assertTrue(view._load_view_applied)
        self.assertIsNone(view._pending_page_data)
        self.assertAlmostEqual(view.transform().m11(), zoomed_scale)
        view._apply_pending_visible_view_state()
        self.assertAlmostEqual(view.transform().m11(), zoomed_scale)
        view.cleanup()

    def test_reset_view_during_failed_async_page_load_leaves_canvas_stable(self):
        view = self._make_plan_view()
        view.resize(300, 300)
        view.show()
        QApplication.processEvents()
        page = Page(
            uid="p1",
            name="P1",
            image_path="missing.pdf",
            width_pts=612.0,
            height_pts=792.0,
            zoom_fac=1.332,
            current_x=408.0,
            current_y=528.0,
        )
        self.assertTrue(view.load_page(page, [], {}, {}))
        view.reset_view()
        reset_scale = view.transform().m11()
        request_id, request = view._rendering_service.page_requests[-1]
        result = RenderResult(
            request_id=request_id,
            success=False,
            image=None,
            error="missing",
        )
        request["callback"](result)
        QApplication.processEvents()
        self.assertTrue(view._load_view_applied)
        self.assertIsNone(view._pending_page_data)
        self.assertAlmostEqual(view.transform().m11(), reset_scale)
        view._apply_pending_visible_view_state()
        self.assertAlmostEqual(view.transform().m11(), reset_scale)
        view.cleanup()

    def test_hidden_annotation_layer_from_page_data_controls_loaded_items(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1", width_pts=612.0, height_pts=792.0)
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="text",
            page_uid=page.uid,
            position=[20.0, 20.0, 80.0, 24.0],
            properties={"Text": "Note", "FontName": "Arial", "FontSize": 12},
            layer_uid="annotation-layer",
            visible=True,
        )
        self.assertTrue(
            view.load_page(
                page,
                [],
                {},
                {},
                annotations=[annotation],
                hidden_layer_uids={"annotation-layer"},
            )
        )
        self.assertFalse(view._uid_to_items["ann-1"][0].isVisible())
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                annotations=[annotation],
                hidden_layer_uids=set(),
            )
        )
        self.assertTrue(view._uid_to_items["ann-1"][0].isVisible())
        view.cleanup()

    def test_load_hidden_annotation_then_enable_reuses_one_scene_item(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1", width_pts=612.0, height_pts=792.0)
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="text",
            page_uid=page.uid,
            position=[20.0, 20.0, 80.0, 24.0],
            properties={"Text": "Note", "FontName": "Arial", "FontSize": 12},
            layer_uid="annotation-layer",
            visible=False,
        )
        self.assertTrue(
            view.load_page(
                page,
                [],
                {},
                {},
                annotations=[annotation],
                hidden_layer_uids={"annotation-layer"},
            )
        )
        original_items = list(view._uid_to_items["ann-1"])
        self.assertEqual(len(original_items), 1)
        self.assertFalse(original_items[0].isVisible())
        self.assertTrue(view.apply_layer_visibility("annotation-layer", True, {}))
        self.assertTrue(original_items[0].isVisible())
        self.assertTrue(view.apply_layer_visibility("annotation-layer", False, {}))
        self.assertFalse(original_items[0].isVisible())
        self.assertTrue(view.apply_layer_visibility("annotation-layer", True, {}))
        self.assertEqual(view._uid_to_items["ann-1"], original_items)
        self.assertTrue(original_items[0].isVisible())
        view.cleanup()

    def test_unassigned_annotation_reprojects_canonical_visibility_in_existing_items(
        self,
    ):
        view = self._make_plan_view()
        self.addCleanup(view.cleanup)
        page = Page(uid="page-1", name="Page", width_pts=612, height_pts=792)
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="text",
            page_uid=page.uid,
            position=[20, 20, 80, 24],
            properties={"Text": "Note"},
            layer_uid="",
            visible=True,
        )
        self.assertTrue(view.load_page(page, [], {}, {}, annotations=[annotation]))
        items = list(view._uid_to_items["ann-1"])
        self.assertTrue(items[0].isVisible())
        self.assertTrue(view._is_selectable("ann-1"))
        # ProjectDataService has already updated the authoritative annotation.
        annotation.visible = False
        view.apply_layer_visibility("2", False, {})
        self.assertFalse(items[0].isVisible())
        self.assertFalse(view._is_selectable("ann-1"))
        view.apply_layer_visibility("unrelated", True, {})
        self.assertFalse(items[0].isVisible())
        annotation.visible = True
        view.apply_layer_visibility("2", True, {})
        self.assertTrue(items[0].isVisible())
        self.assertTrue(view._is_selectable("ann-1"))
        self.assertEqual(view._uid_to_items["ann-1"], items)
        self.assertEqual(annotation.layer_uid, "")

    def test_hidden_annotation_layer_stays_hidden_after_overlay_refresh(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1", width_pts=612.0, height_pts=792.0)
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="text",
            page_uid=page.uid,
            position=[20.0, 20.0, 80.0, 24.0],
            properties={"Text": "Note", "FontName": "Arial", "FontSize": 12},
            layer_uid="annotation-layer",
            visible=True,
        )
        self.assertTrue(view.load_page(page, [], {}, {}, annotations=[annotation]))
        self.assertTrue(view._uid_to_items["ann-1"][0].isVisible())
        self.assertTrue(view.apply_layer_visibility("annotation-layer", False, {}))
        self.assertFalse(view._uid_to_items["ann-1"][0].isVisible())
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                annotations=[annotation],
            )
        )
        self.assertFalse(view._uid_to_items["ann-1"][0].isVisible())
        self.assertTrue(view.apply_layer_visibility("annotation-layer", True, {}))
        self.assertTrue(view._uid_to_items["ann-1"][0].isVisible())
        view.cleanup()

    def test_forced_page_reload_keeps_annotation_selection_by_typed_identity(self):
        view = self._make_plan_view()
        page = Page(
            uid="page-1",
            name="Page 1",
            width_pts=612.0,
            height_pts=792.0,
        )
        annotation = self._text_annotation(uid="2")
        condition = Condition(uid="c1", condition_type=Condition.TYPE_COUNT)
        self.assertTrue(
            view.load_page(
                page,
                [],
                {"c1": condition},
                {"c1": "#000000"},
                annotations=[annotation],
            )
        )
        view.set_selected_uids({"2"})
        self.assertTrue(
            view._load_page_impl(
                page,
                [
                    Takeoff(
                        uid="2",
                        condition_uid="c1",
                        page_uid=page.uid,
                        position=[3.0, 4.0],
                    )
                ],
                {"c1": condition},
                {"c1": "#000000"},
                annotations=[annotation],
                force_visual_reload=True,
            )
        )
        annotation_keys = view.find_annotation_keys_by_uid_type(
            {("2", ANNOTATION_TYPE_TEXT)}
        )
        self.assertEqual(len(annotation_keys), 1)
        self.assertEqual(view._selected_uids, annotation_keys)
        self.assertNotEqual(view._selected_uids, {"2"})
        view.cleanup()

    def test_forced_page_reload_keeps_pending_state_on_typed_annotation(self):
        view = self._make_plan_view()
        page = Page(
            uid="page-1",
            name="Page 1",
            width_pts=612.0,
            height_pts=792.0,
        )
        annotation = self._text_annotation(uid="2")
        condition = Condition(uid="c1", condition_type=Condition.TYPE_COUNT)
        self.assertTrue(
            view.load_page(
                page,
                [],
                {"c1": condition},
                {"c1": "#000000"},
                annotations=[annotation],
            )
        )
        view.set_pending_mutation_uids({"2"})
        self.assertTrue(
            view._load_page_impl(
                page,
                [
                    Takeoff(
                        uid="2",
                        condition_uid="c1",
                        page_uid=page.uid,
                        position=[3.0, 4.0],
                    )
                ],
                {"c1": condition},
                {"c1": "#000000"},
                annotations=[annotation],
                force_visual_reload=True,
            )
        )
        annotation_key = next(
            iter(view.find_annotation_keys_by_uid_type({("2", ANNOTATION_TYPE_TEXT)}))
        )
        self.assertEqual(view.get_pending_mutation_uids(), {annotation_key})
        self.assertTrue(
            all(item.opacity() == 0.35 for item in view._uid_to_items[annotation_key])
        )
        view.cleanup()


class TakeoffPlanViewApplyPageImageLayerVisibilityTests(
    _TakeoffPlanViewOverlayRefreshFixture
):
    """TakeoffPlanView.apply_page_image_layer_visibility."""

    def test_main_only_image_layer_disable_shows_existing_white_canvas(self):
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
        )
        view = self._load_completed_page_visual(page)
        canvas = view._white_canvas_item
        background = view._background_item
        fit_calls = []
        view.fit_to_page = lambda: fit_calls.append("fit")
        try:
            self.assertTrue(
                view.apply_page_image_layer_visibility(
                    replace(page, layer_visible=False)
                )
            )
            self.assertFalse(background.isVisible())
            self.assertTrue(canvas.isVisible())
            self.assertTrue(view._page_scene_rect().isValid())
            self.assertTrue(view._scene.sceneRect().isValid())
            self.assertEqual(fit_calls, [])
        finally:
            view.cleanup()

    def test_overlay_only_image_layer_disable_shows_existing_white_canvas(self):
        page = Page(
            uid="p1",
            name="P1",
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
            image_show_mode=1,
            width_pts=612.0,
            height_pts=792.0,
        )
        view = self._load_completed_page_visual(page)
        canvas = view._white_canvas_item
        overlay = view._overlay_items[0]
        fit_calls = []
        view.fit_to_page = lambda: fit_calls.append("fit")
        try:
            self.assertTrue(
                view.apply_page_image_layer_visibility(
                    replace(page, layer_visible=False)
                )
            )
            self.assertFalse(overlay.isVisible())
            self.assertTrue(canvas.isVisible())
            self.assertTrue(view._page_scene_rect().isValid())
            self.assertTrue(view._scene.sceneRect().isValid())
            self.assertEqual(fit_calls, [])
        finally:
            view.cleanup()

    def test_main_and_overlay_image_layer_disable_keeps_white_canvas(self):
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
        )
        view, canvas = self._load_completed_page_visual(
            page, return_initial_canvas=True
        )
        composite = view._background_item
        fit_calls = []
        view.fit_to_page = lambda: fit_calls.append("fit")
        try:
            self.assertIs(view._white_canvas_item, canvas)
            self.assertIs(canvas.scene(), view._scene)
            self.assertTrue(
                view.apply_page_image_layer_visibility(
                    replace(page, layer_visible=False)
                )
            )
            self.assertFalse(composite.isVisible())
            self.assertTrue(canvas.isVisible())
            self.assertTrue(view._page_scene_rect().isValid())
            self.assertTrue(view._scene.sceneRect().isValid())
            self.assertEqual(
                sum(item is canvas for item in view._scene.items()),
                1,
            )
            self.assertEqual(fit_calls, [])
        finally:
            view.cleanup()

    def test_image_layer_show_without_loaded_visual_items_requests_full_reload(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        hidden_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            layer_visible=False,
        )
        shown_page = replace(hidden_page, layer_visible=True)
        view._current_bid_page_uid = hidden_page.uid
        view._current_page = hidden_page
        view._background_item = None
        view._visible_frame_item = None
        view._overlay_items = []
        view._white_canvas_item = None
        view._update_scene_rect = lambda: None
        view.viewport = lambda: FakeViewport([])
        self.assertFalse(view.apply_page_image_layer_visibility(shown_page))


class TakeoffPlanViewShowOverlayMoveHandleTests(_TakeoffPlanViewOverlayRefreshFixture):
    """TakeoffPlanView.show_overlay_move_handle."""

    def test_move_overlay_hover_handle_uses_move_cursor(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        handle_pos = view.mapFromScene(view._overlay_move_handle_item.pos())
        self.assertEqual(view._resolve_cursor(handle_pos), view._move_overlay_cursor)
        self.assertEqual(
            view._resolve_cursor(handle_pos + QtCore.QPoint(80, 80)),
            QtCore.Qt.CursorShape.ArrowCursor,
        )
        view.cleanup()

    def test_move_overlay_handle_uses_white_fill_with_black_outline(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        with patch.object(
            view,
            "_outlined_icon_pixmap",
            wraps=view._outlined_icon_pixmap,
        ) as build_pixmap:
            self.assertTrue(view.show_overlay_move_handle())
        build_pixmap.assert_called_once_with(
            "recenter_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
            "#ffffff",
        )
        image = view._overlay_move_handle_item.pixmap().toImage()
        colors = {
            image.pixelColor(x, y).rgba()
            for y in range(image.height())
            for x in range(image.width())
        }
        self.assertIn(QColor(255, 255, 255).rgba(), colors)
        self.assertIn(QColor(0, 0, 0).rgba(), colors)
        view.cleanup()

    def test_move_overlay_handle_starts_at_scrolled_zoomed_viewport_center(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        view._load_view_applied = True
        view.show()
        view.scale(1.75, 1.75)
        view.horizontalScrollBar().setValue(225)
        view.verticalScrollBar().setValue(375)
        QApplication.processEvents()
        self.assertTrue(view.show_overlay_move_handle())
        viewport_center = view.viewport().rect().center()
        handle_viewport_pos = view.mapFromScene(view._overlay_move_handle_item.pos())
        expected_scene_pos = view.mapToScene(viewport_center)
        self.assertLessEqual(
            (handle_viewport_pos - viewport_center).manhattanLength(),
            1,
        )
        self.assertAlmostEqual(
            view._overlay_move_handle_item.pos().x(),
            expected_scene_pos.x(),
        )
        self.assertAlmostEqual(
            view._overlay_move_handle_item.pos().y(),
            expected_scene_pos.y(),
        )
        view.cleanup()

    def test_move_overlay_handle_centers_with_small_drawing_and_off_page_overlay(
        self,
    ):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=72.0,
            height_pts=72.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(5000.0, -3000.0, 64.0, 64.0),
        )
        self._install_page_canvas(view, page)
        view._load_view_applied = True
        view.show()
        QApplication.processEvents()
        self.assertTrue(view.show_overlay_move_handle())
        self.assertEqual(view.horizontalScrollBar().maximum(), 0)
        self.assertEqual(view.verticalScrollBar().maximum(), 0)
        self.assertLessEqual(
            (
                view.mapFromScene(view._overlay_move_handle_item.pos())
                - view.viewport().rect().center()
            ).manhattanLength(),
            1,
        )
        view.cleanup()

    def test_move_overlay_handle_follows_scroll_zoom_and_resize(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        view._load_view_applied = True
        view.show()
        view.scale(2.0, 2.0)
        QApplication.processEvents()
        self.assertGreater(view.horizontalScrollBar().maximum(), 0)
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        self.assertTrue(view.show_overlay_move_handle())
        initial_scene_pos = QtCore.QPointF(view._overlay_move_handle_item.pos())
        view.horizontalScrollBar().setValue(
            min(
                view.horizontalScrollBar().maximum(),
                view.horizontalScrollBar().value() + 100,
            )
        )
        view.verticalScrollBar().setValue(
            min(
                view.verticalScrollBar().maximum(),
                view.verticalScrollBar().value() + 125,
            )
        )
        QApplication.processEvents()
        scrolled_scene_pos = QtCore.QPointF(view._overlay_move_handle_item.pos())
        self.assertNotEqual(scrolled_scene_pos, initial_scene_pos)
        self.assertLessEqual(
            (
                view.mapFromScene(scrolled_scene_pos) - view.viewport().rect().center()
            ).manhattanLength(),
            1,
        )
        viewport_center = view.viewport().rect().center()
        before_pan_scene_pos = QtCore.QPointF(view._overlay_move_handle_item.pos())
        view.mousePressEvent(
            self._right_press_event(viewport_center.x(), viewport_center.y())
        )
        view.mouseMoveEvent(
            self._right_move_event(
                viewport_center.x() + 40,
                viewport_center.y() + 35,
            )
        )
        view.mouseReleaseEvent(
            self._right_release_event(
                viewport_center.x() + 40,
                viewport_center.y() + 35,
            )
        )
        self.assertFalse(view._panning)
        self.assertEqual(view._cursor_mode, "move_overlay_handle")
        self.assertNotEqual(
            view._overlay_move_handle_item.pos(),
            before_pan_scene_pos,
        )
        self.assertLessEqual(
            (
                view.mapFromScene(view._overlay_move_handle_item.pos())
                - view.viewport().rect().center()
            ).manhattanLength(),
            1,
        )
        for zoom_percent in (25.0, 800.0):
            view.set_zoom_percent(zoom_percent)
            QApplication.processEvents()
            self.assertLessEqual(
                (
                    view.mapFromScene(view._overlay_move_handle_item.pos())
                    - view.viewport().rect().center()
                ).manhattanLength(),
                1,
            )
        view.resize(420, 340)
        QApplication.processEvents()
        self.assertLessEqual(
            (
                view.mapFromScene(view._overlay_move_handle_item.pos())
                - view.viewport().rect().center()
            ).manhattanLength(),
            1,
        )
        view.cleanup()

    def test_move_overlay_handle_stops_tracking_after_mode_ends(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        view._load_view_applied = True
        view.show()
        QApplication.processEvents()
        self.assertTrue(view.show_overlay_move_handle())
        handle = view._overlay_move_handle_item
        view.cancel_overlay_move_mode(restore_preview=True)
        with patch.object(
            view,
            "_set_overlay_move_handle_pos",
            wraps=view._set_overlay_move_handle_pos,
        ) as set_handle_pos:
            view.horizontalScrollBar().setValue(
                max(0, view.horizontalScrollBar().value() - 75)
            )
            view.resize(360, 320)
            view.set_zoom_percent(175.0)
            QApplication.processEvents()
        set_handle_pos.assert_not_called()
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(handle.scene())
        view.cleanup()

    def test_move_overlay_preview_hides_stale_composite_after_base_ready(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        composite = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        view._scene.addItem(composite)
        view._background_item = composite
        view._loaded_visual_kind = VISUAL_KIND_COMPOSITE
        view._is_composite_mode = True
        view._base_raster_scale = 2.0
        self.assertTrue(view.show_overlay_move_handle())
        self.assertTrue(composite.isVisible())
        request_id, render_options = view._rendering_service.page_requests[-1]
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 80, 80).rgba())
        render_options["callback"](RenderResult(request_id, True, image, None))
        self.assertFalse(composite.isVisible())
        self.assertIsNotNone(view._white_canvas_item)
        self.assertIs(view._white_canvas_item.scene(), view._scene)
        self.assertIsNotNone(view._overlay_move_preview_base_item)
        self.assertTrue(view._overlay_move_preview_base_item.isVisible())
        self.assertLess(
            view._white_canvas_item.zValue(),
            view._overlay_move_preview_base_item.zValue(),
        )
        view.cleanup()

    def test_move_overlay_pdf_preview_uses_canonical_interactive_baseline(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        view._scene_scale = 7.0
        view._base_raster_scale = 3.0
        self.assertTrue(view.show_overlay_move_handle())
        _base_request_id, base_options = view._rendering_service.page_requests[-1]
        _overlay_request_id, overlay_options = view._rendering_service.overlay_requests[
            -1
        ]
        self.assertEqual(
            base_options["scale"],
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertEqual(
            overlay_options["render_scale"],
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        view.cleanup()

    def test_move_overlay_raster_preview_keeps_native_pixel_scale(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            overlay_image_path="overlay.png",
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        view._scene_scale = 7.0
        self.assertTrue(view.show_overlay_move_handle())
        _request_id, overlay_options = view._rendering_service.overlay_requests[-1]
        self.assertEqual(
            overlay_options["render_scale"],
            RASTER_NATIVE_RENDER_SCALE,
        )
        view.cleanup()

    def test_move_overlay_drag_before_base_ready_keeps_composite_visible(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        composite = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        view._scene.addItem(composite)
        view._background_item = composite
        view._loaded_visual_kind = VISUAL_KIND_COMPOSITE
        view._is_composite_mode = True
        view._base_raster_scale = 2.0
        self.assertTrue(view.show_overlay_move_handle())
        handle_pos = view.mapFromScene(view._overlay_move_handle_item.pos())
        self.assertTrue(view._begin_overlay_move(handle_pos))
        self.assertTrue(composite.isVisible())
        self.assertFalse(view._overlay_move_normal_visuals_hidden)
        self.assertIsNone(view._overlay_move_preview_base_item)
        view.cleanup()

    def test_move_overlay_bitonal_preview_keeps_tinted_paper_transparent(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            bitonal=True,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, base_options = view._rendering_service.page_requests[-1]
        overlay_request_id, overlay_options = view._rendering_service.overlay_requests[
            -1
        ]
        self.assertEqual(base_options["tint_rgb"], (255, 80, 80))
        self.assertTrue(base_options["bitonal"])
        self.assertTrue(base_options["apply_invert_effect"])
        self.assertFalse(base_options["apply_bitonal_effect"])
        self.assertEqual(overlay_options["show_mode"], 2)
        self.assertTrue(overlay_options["apply_invert_effect"])
        self.assertFalse(overlay_options["apply_bitonal_effect"])
        base_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        base_image.fill(QtCore.Qt.GlobalColor.transparent)
        base_image.setPixelColor(1, 1, QColor(255, 80, 80, 255))
        base_options["callback"](RenderResult(base_request_id, True, base_image, None))
        overlay_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        overlay_image.fill(QtCore.Qt.GlobalColor.transparent)
        overlay_image.setPixelColor(1, 1, QColor(80, 80, 255, 255))
        overlay_options["callback"](
            RenderResult(overlay_request_id, True, overlay_image, None)
        )
        base_item = view._overlay_move_preview_base_item
        overlay_item = view._overlay_move_preview_overlay_item
        self.assertIsNotNone(base_item)
        self.assertIsNotNone(overlay_item)
        self.assertTrue(base_item.isVisible())
        self.assertTrue(overlay_item.isVisible())
        self.assertLess(view._white_canvas_item.zValue(), base_item.zValue())
        self.assertLess(base_item.zValue(), overlay_item.zValue())
        self.assertEqual(overlay_item.opacity(), 1.0)
        self.assertEqual(
            overlay_item.pixmap().toImage().pixelColor(0, 0).alpha(),
            0,
        )
        view.cleanup()

    def test_move_overlay_invert_preview_applies_invert_without_bitonal(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            invert=True,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, base_options = view._rendering_service.page_requests[-1]
        overlay_request_id, overlay_options = view._rendering_service.overlay_requests[
            -1
        ]
        self.assertTrue(base_options["invert"])
        self.assertFalse(base_options["bitonal"])
        self.assertTrue(base_options["apply_invert_effect"])
        self.assertFalse(base_options["apply_bitonal_effect"])
        self.assertTrue(overlay_options["apply_invert_effect"])
        self.assertFalse(overlay_options["apply_bitonal_effect"])
        base_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        base_image.fill(QtCore.Qt.GlobalColor.transparent)
        base_image.setPixelColor(1, 1, QColor(0, 175, 175, 255))
        base_options["callback"](RenderResult(base_request_id, True, base_image, None))
        overlay_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        overlay_image.fill(QtCore.Qt.GlobalColor.transparent)
        overlay_image.setPixelColor(1, 1, QColor(175, 175, 0, 255))
        overlay_options["callback"](
            RenderResult(overlay_request_id, True, overlay_image, None)
        )
        base_item = view._overlay_move_preview_base_item
        overlay_item = view._overlay_move_preview_overlay_item
        self.assertIsNotNone(base_item)
        self.assertIsNotNone(overlay_item)
        self.assertEqual(
            base_item._image.pixelColor(1, 1),
            QColor(0, 175, 175, 255),
        )
        self.assertEqual(
            overlay_item.pixmap().toImage().pixelColor(1, 1),
            QColor(175, 175, 0, 255),
        )
        self.assertEqual(overlay_item.pixmap().toImage().pixelColor(0, 0).alpha(), 0)
        view.cleanup()

    def test_move_overlay_inverted_bitonal_preview_requests_invert_and_keeps_alpha(
        self,
    ):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            invert=True,
            bitonal=True,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, base_options = view._rendering_service.page_requests[-1]
        overlay_request_id, overlay_options = view._rendering_service.overlay_requests[
            -1
        ]
        self.assertTrue(base_options["invert"])
        self.assertTrue(base_options["bitonal"])
        self.assertTrue(base_options["apply_invert_effect"])
        self.assertFalse(base_options["apply_bitonal_effect"])
        self.assertTrue(overlay_options["apply_invert_effect"])
        self.assertFalse(overlay_options["apply_bitonal_effect"])
        base_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        base_image.fill(QtCore.Qt.GlobalColor.transparent)
        base_image.setPixelColor(1, 1, QColor(0, 175, 175, 255))
        base_options["callback"](RenderResult(base_request_id, True, base_image, None))
        overlay_image = QImage(2, 2, QImage.Format.Format_ARGB32)
        overlay_image.fill(QtCore.Qt.GlobalColor.transparent)
        overlay_image.setPixelColor(1, 1, QColor(175, 175, 0, 255))
        overlay_options["callback"](
            RenderResult(overlay_request_id, True, overlay_image, None)
        )
        overlay_pixels = view._overlay_move_preview_overlay_item.pixmap().toImage()
        self.assertEqual(overlay_pixels.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(overlay_pixels.pixelColor(1, 1), QColor(175, 175, 0, 255))
        view.cleanup()

    def test_move_overlay_enters_mode_from_handle_click(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        handle_pos = view.mapFromScene(view._overlay_move_handle_item.pos())
        view.mousePressEvent(self._left_press_event(handle_pos.x(), handle_pos.y()))
        self.assertEqual(view._cursor_mode, "move_overlay")
        self.assertIsNotNone(view._overlay_move_handle_item)
        self.assertEqual(view._overlay_move_original_rect, (0.0, 0.0, 544.0, 704.0))
        view.cleanup()

    def test_move_overlay_escape_hides_handle_and_restores_original_overlay_rect(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(64.0, 32.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view._overlay_move_original_rect = (0.0, 0.0, 544.0, 704.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Escape,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._cursor_mode, "select")
        self.assertIsNone(view._overlay_move_handle_item)
        view.cleanup()

    def test_place_mode_cancels_move_overlay_state(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(64.0, 32.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view._overlay_move_original_rect = (0.0, 0.0, 544.0, 704.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._current_conditions = {
            "c1": Condition(uid="c1", condition_type=Condition.TYPE_LINEAR)
        }
        view._annotation_place_type = "dimension"
        view._annotation_place_points = [(1.0, 1.0)]
        view._annotation_place_dragging = True
        self.assertTrue(view.activate_place_for_condition("c1"))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._cursor_mode, "place")
        self.assertEqual(view._place_session_uid, "c1")
        self.assertIsNone(view._annotation_place_type)
        self.assertEqual(view._annotation_place_points, [])
        self.assertFalse(view._annotation_place_dragging)
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        view.cleanup()

    def test_dimension_mode_cancels_move_overlay_state(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(64.0, 32.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view._overlay_move_original_rect = (0.0, 0.0, 544.0, 704.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view.set_selection_enabled(True)
        self.assertTrue(view.activate_annotation_placement("dimension"))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._cursor_mode, "annotation_place")
        self.assertEqual(view._annotation_place_type, "dimension")
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        view.cleanup()

    def test_paste_backout_cancels_move_overlay_state(self):
        view = self._make_plan_view()
        cursor_modes = []
        view.cursor_mode_change_requested.connect(cursor_modes.append)
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(64.0, 32.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view._overlay_move_original_rect = (0.0, 0.0, 544.0, 704.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._current_conditions = {
            "area-condition": Condition(
                uid="area-condition",
                condition_type=Condition.TYPE_AREA,
            )
        }
        view._current_takeoffs = {
            "host": Takeoff(
                uid="host",
                condition_uid="area-condition",
                position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
                parent_uid="0",
            )
        }
        view._place_session_uid = "area-condition"
        view._place_points = [(0.0, 0.0)]
        view._annotation_place_type = "dimension"
        view._annotation_place_points = [(1.0, 1.0)]
        view._annotation_place_dragging = True
        hole = Takeoff(
            uid="hole",
            condition_uid="area-condition",
            position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
            parent_uid="source-parent",
        )
        self.assertTrue(view.begin_paste_backout([hole], {}, "7"))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._cursor_mode, CURSOR_MODE_PASTE_BACKOUT)
        self.assertEqual(cursor_modes[-1], CURSOR_MODE_PASTE_BACKOUT)
        self.assertTrue(view._paste_backout_active)
        self.assertEqual(len(view._paste_backout_sources), 1)
        self.assertIsNone(view._place_session_uid)
        self.assertEqual(view._place_points, [])
        self.assertIsNone(view._annotation_place_type)
        self.assertEqual(view._annotation_place_points, [])
        self.assertFalse(view._annotation_place_dragging)
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        view.cleanup()

    def test_move_overlay_local_reload_failure_cancels_pending_preview_requests(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, base_options = view._rendering_service.page_requests[-1]
        overlay_request_id, overlay_options = view._rendering_service.overlay_requests[
            -1
        ]
        view.set_overlay_rect_save_handler(lambda _rect: True)
        preview_overlay = QGraphicsPixmapItem(QPixmap(10, 10))
        view._scene.addItem(preview_overlay)
        view._overlay_move_preview_overlay_item = preview_overlay
        view._overlay_move_preview_rect = (64.0, 32.0, 544.0, 704.0)
        view._force_reload_current_page_visuals = lambda: False
        with patch(
            "ost_visualizer.presentation.components.plan_view.view.show_warning"
        ):
            view._commit_overlay_move()
        self.assertIn(base_request_id, view._rendering_service.cancelled_requests)
        self.assertIn(overlay_request_id, view._rendering_service.cancelled_requests)
        self.assertIsNone(view._overlay_move_preview_base_request_id)
        self.assertIsNone(view._overlay_move_preview_overlay_request_id)
        self.assertEqual(view._overlay_move_preview_overlay_request_scale, 0.0)
        stale_image = QImage(8, 8, QImage.Format.Format_ARGB32)
        stale_image.fill(QColor(255, 255, 255).rgba())
        base_options["callback"](RenderResult(base_request_id, True, stale_image, None))
        overlay_options["callback"](
            RenderResult(overlay_request_id, True, stale_image, None)
        )
        self.assertIsNone(view._overlay_move_preview_base_item)
        self.assertIs(view._overlay_move_preview_overlay_item, preview_overlay)
        self.assertIs(preview_overlay.scene(), view._scene)
        self.assertTrue(preview_overlay.isVisible())
        view.cleanup()

    def test_move_overlay_cancel_clears_requests_and_ignores_stale_callbacks(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, base_options = view._rendering_service.page_requests[-1]
        overlay_request_id, overlay_options = view._rendering_service.overlay_requests[
            -1
        ]
        view.cancel_overlay_move_mode(restore_preview=True)
        self.assertIn(base_request_id, view._rendering_service.cancelled_requests)
        self.assertIn(overlay_request_id, view._rendering_service.cancelled_requests)
        self.assertIsNone(view._overlay_move_preview_base_request_id)
        self.assertIsNone(view._overlay_move_preview_overlay_request_id)
        self.assertIsNone(view._overlay_move_preview_base_item)
        self.assertIsNone(view._overlay_move_preview_overlay_item)
        self.assertIsNone(view._overlay_move_handle_item)
        stale_image = QImage(8, 8, QImage.Format.Format_ARGB32)
        stale_image.fill(QColor(255, 255, 255).rgba())
        base_options["callback"](RenderResult(base_request_id, True, stale_image, None))
        overlay_options["callback"](
            RenderResult(overlay_request_id, True, stale_image, None)
        )
        self.assertIsNone(view._overlay_move_preview_base_item)
        self.assertIsNone(view._overlay_move_preview_overlay_item)
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        view.cleanup()

    def test_move_overlay_page_reload_clears_preview_state_and_requests(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        base_request_id, _base_options = view._rendering_service.page_requests[-1]
        overlay_request_id, _overlay_options = view._rendering_service.overlay_requests[
            -1
        ]
        base_item = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        overlay_item = QGraphicsPixmapItem(QPixmap(10, 10))
        view._scene.addItem(base_item)
        view._scene.addItem(overlay_item)
        view._overlay_move_preview_base_item = base_item
        view._overlay_move_preview_overlay_item = overlay_item
        page.overlay_rect = (64.0, 32.0, 544.0, 704.0)
        view._overlay_move_preview_rect = page.overlay_rect
        self.assertTrue(view.load_page(page, [], {}, {}))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertIn(base_request_id, view._rendering_service.cancelled_requests)
        self.assertIn(overlay_request_id, view._rendering_service.cancelled_requests)
        self.assertIsNone(view._overlay_move_preview_base_request_id)
        self.assertIsNone(view._overlay_move_preview_overlay_request_id)
        self.assertIsNone(view._overlay_move_preview_base_item)
        self.assertIsNone(view._overlay_move_preview_overlay_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(base_item.scene())
        self.assertIsNone(overlay_item.scene())
        view.cleanup()

    def test_move_overlay_repeated_enter_cancel_does_not_reinstall_preview_items(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        for _ in range(2):
            self.assertTrue(view.show_overlay_move_handle())
            base_request_id, base_options = view._rendering_service.page_requests[-1]
            overlay_request_id, overlay_options = (
                view._rendering_service.overlay_requests[-1]
            )
            view.cancel_overlay_move_mode(restore_preview=True)
            stale_image = QImage(8, 8, QImage.Format.Format_ARGB32)
            stale_image.fill(QColor(255, 255, 255).rgba())
            base_options["callback"](
                RenderResult(base_request_id, True, stale_image, None)
            )
            overlay_options["callback"](
                RenderResult(overlay_request_id, True, stale_image, None)
            )
            self.assertIsNone(view._overlay_move_preview_base_item)
            self.assertIsNone(view._overlay_move_preview_overlay_item)
            self.assertIsNone(view._overlay_move_handle_item)
        view.cleanup()

    def test_move_overlay_commit_forces_normal_visual_reload(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view.set_overlay_rect_save_handler(lambda _rect: True)
        view._overlay_move_preview_rect = (64.0, 32.0, 544.0, 704.0)
        page_request_id, _page_options = view._rendering_service.page_requests[-1]
        overlay_request_id, _overlay_options = view._rendering_service.overlay_requests[
            -1
        ]
        view._commit_overlay_move()
        self.assertIn(page_request_id, view._rendering_service.cancelled_requests)
        self.assertIn(overlay_request_id, view._rendering_service.cancelled_requests)
        self.assertEqual(len(view._rendering_service.composite_requests), 1)
        composite_request_id, composite_options = (
            view._rendering_service.composite_requests[-1]
        )
        self.assertEqual(composite_options["page"].overlay_rect, page.overlay_rect)
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 255, 255).rgba())
        composite_options["callback"](
            RenderResult(composite_request_id, True, image, None)
        )
        self.assertIsNotNone(view._background_item)
        self.assertTrue(view._background_item.isVisible())
        self.assertEqual(view._loaded_visual_kind, "composite")
        self.assertIsNone(view._pending_page_data)
        self.assertEqual(page.overlay_rect, (64.0, 32.0, 544.0, 704.0))
        view.cleanup()

    def test_move_overlay_commit_next_composite_frame_uses_committed_overlay_rect(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        view.set_overlay_rect_save_handler(lambda _rect: True)
        view._overlay_move_preview_rect = (64.0, 32.0, 544.0, 704.0)
        view._commit_overlay_move()
        composite_request_id, composite_options = (
            view._rendering_service.composite_requests[-1]
        )
        image = QImage(200, 200, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 255, 255).rgba())
        composite_options["callback"](
            RenderResult(composite_request_id, True, image, None)
        )
        view._update_tile_coverage(4.0)
        self.assertEqual(len(view._rendering_service.composite_frame_requests), 1)
        _request_id, frame_options = view._rendering_service.composite_frame_requests[
            -1
        ]
        self.assertEqual(
            frame_options["page"].overlay_rect,
            (64.0, 32.0, 544.0, 704.0),
        )
        self.assertIn(
            (64.0, 32.0, 544.0, 704.0),
            view._visible_frame_key[-1],
        )
        view.cleanup()

    def test_move_overlay_handle_is_removed_on_clear(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        self.assertTrue(view.show_overlay_move_handle())
        handle = view._overlay_move_handle_item
        view.clear()
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(handle.scene())
        view.cleanup()


class TakeoffPlanViewPreviewOverlayMoveTests(_TakeoffPlanViewOverlayRefreshFixture):
    """TakeoffPlanView._preview_overlay_move."""

    def test_move_overlay_drag_keeps_preview_base_stable(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_image_path="overlay.png",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        base = ImageBackgroundItem(
            QImage(20, 20, QImage.Format.Format_ARGB32),
            1224.0,
            1584.0,
        )
        view._scene.addItem(base)
        view._overlay_move_preview_base_item = base
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = page.overlay_rect
        view._overlay_move_drag_start_rect = page.overlay_rect
        view._overlay_move_anchor_scene = QtCore.QPointF(0.0, 0.0)
        page_request_count = len(view._rendering_service.page_requests)
        view._preview_overlay_move(QtCore.QPointF(144.0, 72.0))
        self.assertIs(view._overlay_move_preview_base_item, base)
        self.assertEqual(len(view._rendering_service.page_requests), page_request_count)
        view.cleanup()

    def test_move_overlay_preview_translates_rect_in_calibrated_units(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_drag_start_rect = page.overlay_rect
        view._overlay_move_anchor_scene = QtCore.QPointF(0.0, 0.0)
        view._preview_overlay_move(QtCore.QPointF(144.0, 72.0))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._overlay_move_preview_rect, (64.0, 32.0, 544.0, 704.0))
        view.cleanup()

    def test_move_overlay_preview_updates_overlay_item_transform(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_image_path="overlay.png",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        pixmap = QPixmap(100, 100)
        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=1,
        )
        view._scene.addItem(item)
        view._overlay_move_preview_overlay_item = item
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_drag_start_rect = page.overlay_rect
        view._overlay_move_anchor_scene = QtCore.QPointF(0.0, 0.0)
        view._preview_overlay_move(QtCore.QPointF(144.0, 72.0))
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._overlay_move_preview_rect, (64.0, 32.0, 544.0, 704.0))
        self.assertAlmostEqual(item.transform().m31(), 144.0)
        self.assertAlmostEqual(item.transform().m32(), 72.0)
        view.cleanup()


class TakeoffPlanViewSetOverlayRectSaveHandlerTests(
    _TakeoffPlanViewOverlayRefreshFixture
):
    """TakeoffPlanView.set_overlay_rect_save_handler."""

    def test_move_overlay_release_keeps_preview_handle_without_saving(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        calls = []
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view.set_overlay_rect_save_handler(lambda rect: calls.append(rect) or True)
        low_res_item = QGraphicsPixmapItem(QPixmap(10, 10))
        low_res_item.setVisible(True)
        view._scene.addItem(low_res_item)
        view._overlay_move_preview_overlay_item = low_res_item
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = page.overlay_rect
        anchor_scene = view.mapToScene(QtCore.QPoint(0, 0))
        release_vp = view.mapFromScene(anchor_scene + QtCore.QPointF(144.0, 72.0))
        view._overlay_move_anchor_scene = anchor_scene
        view._overlay_move_drag_start_rect = page.overlay_rect
        view._overlay_move_dragging = True
        view._apply_cursor_mode("move_overlay")
        view.mouseMoveEvent(self._left_move_event(release_vp.x(), release_vp.y()))
        view.mouseReleaseEvent(self._left_release_event(release_vp.x(), release_vp.y()))
        self.assertEqual(calls, [])
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._cursor_mode, "move_overlay_handle")
        self.assertIsNotNone(view._overlay_move_handle_item)
        self.assertEqual(view._overlay_move_preview_rect, (64.0, 32.0, 544.0, 704.0))
        self.assertEqual(view._overlay_move_original_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertIs(view._overlay_move_preview_overlay_item, low_res_item)
        self.assertIs(low_res_item.scene(), view._scene)
        self.assertTrue(low_res_item.isVisible())
        self.assertEqual(view._rendering_service.overlay_requests, [])
        view.cleanup()

    def test_move_overlay_outside_click_commits_preview_and_exits_mode(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(64.0, 32.0, 544.0, 704.0),
        )
        calls = []
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view._scene_scale = 2.0
        view.set_overlay_rect_save_handler(lambda rect: calls.append(rect) or True)
        view._overlay_move_original_rect = (0.0, 0.0, 544.0, 704.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._set_overlay_move_handle_pos(QtCore.QPointF(144.0, 72.0))
        view._apply_cursor_mode("move_overlay_handle")
        view.mousePressEvent(self._left_press_event(300.0, 250.0))
        self.assertEqual(calls, [(64.0, 32.0, 544.0, 704.0)])
        self.assertEqual(page.overlay_rect, (64.0, 32.0, 544.0, 704.0))
        self.assertEqual(view._cursor_mode, "select")
        self.assertIsNone(view._overlay_move_handle_item)
        self.assertIsNone(view._overlay_move_original_rect)
        self.assertIsNone(view._overlay_move_preview_rect)
        view.cleanup()

    def test_move_overlay_commit_saves_preview_overlay_rect(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(64.0, 32.0, 544.0, 704.0),
        )
        calls = []
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view.set_overlay_rect_save_handler(lambda rect: calls.append(rect) or True)
        view._overlay_move_original_rect = (0.0, 0.0, 544.0, 704.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._commit_overlay_move()
        self.assertEqual(calls, [(64.0, 32.0, 544.0, 704.0)])
        self.assertEqual(page.overlay_rect, (64.0, 32.0, 544.0, 704.0))
        view.cleanup()

    def test_move_overlay_save_failure_rolls_back_and_exits_mode(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            overlay_rect=(64.0, 32.0, 544.0, 704.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view.set_overlay_rect_save_handler(lambda _rect: False)
        view._overlay_move_original_rect = (0.0, 0.0, 544.0, 704.0)
        view._overlay_move_preview_rect = page.overlay_rect
        view._set_overlay_move_handle_pos(QtCore.QPointF(144.0, 72.0))
        view._apply_cursor_mode("move_overlay_handle")
        with patch(
            "ost_visualizer.presentation.components.plan_view.view.show_warning"
        ) as warning:
            event = self._left_press_event(300.0, 250.0)
            view.mousePressEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(page.overlay_rect, (0.0, 0.0, 544.0, 704.0))
        self.assertEqual(view._cursor_mode, "select")
        self.assertIsNone(view._overlay_move_handle_item)
        warning.assert_called_once()
        view.cleanup()

    def test_move_overlay_local_reload_failure_keeps_accepted_preview_visible(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            width_pts=612.0,
            height_pts=792.0,
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        view._current_page = page
        view._current_bid_page_uid = "p1"
        view.set_overlay_rect_save_handler(lambda _rect: True)
        preview_overlay = QGraphicsPixmapItem(QPixmap(10, 10))
        view._scene.addItem(preview_overlay)
        view._overlay_move_preview_overlay_item = preview_overlay
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = (64.0, 32.0, 544.0, 704.0)
        view._force_reload_current_page_visuals = lambda: False
        with patch(
            "ost_visualizer.presentation.components.plan_view.view.show_warning"
        ) as warning:
            view._commit_overlay_move()
        self.assertEqual(page.overlay_rect, (64.0, 32.0, 544.0, 704.0))
        self.assertIs(preview_overlay.scene(), view._scene)
        self.assertTrue(preview_overlay.isVisible())
        self.assertEqual(view._rendering_service.composite_requests, [])
        self.assertEqual(view._cursor_mode, "select")
        warning.assert_called_once()
        view.cleanup()

    def test_move_overlay_commit_invalidates_stale_visible_frame(self):
        view = self._make_plan_view()
        page = Page(
            uid="p1",
            name="P1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=2,
            width_pts=612.0,
            height_pts=792.0,
            overlay_rect=(0.0, 0.0, 544.0, 704.0),
        )
        self._install_page_canvas(view, page)
        stale_image = QImage(20, 20, QImage.Format.Format_ARGB32)
        stale_image.fill(QColor(255, 255, 255).rgba())
        stale_frame = TileGraphicsItem(
            stale_image,
            QtCore.QRectF(0.0, 0.0, 20.0, 20.0),
            QtCore.QRectF(0.0, 0.0, 20.0, 20.0),
        )
        view._scene.addItem(stale_frame)
        view._visible_frame_item = stale_frame
        view._visible_frame_key = ("composite", "old-overlay-rect")
        view._visible_frame_kind = "composite"
        view._visible_frame_scale = 8.0
        view._visible_frame_request_id = "old-frame-request"
        preview_overlay = QGraphicsPixmapItem(QPixmap(10, 10))
        view._scene.addItem(preview_overlay)
        view._overlay_move_preview_overlay_item = preview_overlay
        view._overlay_move_original_rect = page.overlay_rect
        view._overlay_move_preview_rect = (64.0, 32.0, 544.0, 704.0)
        view.set_overlay_rect_save_handler(lambda _rect: True)
        view._force_reload_current_page_visuals = lambda: False
        with patch(
            "ost_visualizer.presentation.components.plan_view.view.show_warning"
        ):
            view._commit_overlay_move()
        self.assertEqual(page.overlay_rect, (64.0, 32.0, 544.0, 704.0))
        self.assertIn("old-frame-request", view._rendering_service.cancelled_requests)
        self.assertIsNone(stale_frame.scene())
        self.assertIsNone(view._visible_frame_item)
        self.assertIsNone(view._visible_frame_key)
        self.assertEqual(view._visible_frame_scale, 0.0)
        self.assertIs(preview_overlay.scene(), view._scene)
        view.cleanup()


class TakeoffPlanViewSetSelectionEnabledTests(_TakeoffPlanViewOverlayRefreshFixture):
    """TakeoffPlanView.set_selection_enabled."""

    def test_annotation_placement_allowed_callback_blocks_direct_activation(self):
        view = self._make_plan_view()
        page = Page(uid="p1", name="P1", width_pts=612.0, height_pts=792.0)
        self._install_page_canvas(view, page)
        view.set_selection_enabled(True)
        view.set_annotation_placement_allowed_fn(lambda: False)
        self.assertFalse(view.activate_annotation_placement("dimension"))
        self.assertNotEqual(view._cursor_mode, "annotation_place")
        self.assertIsNone(view._annotation_place_type)
        view.set_annotation_placement_allowed_fn(lambda: True)
        self.assertTrue(view.activate_annotation_placement("dimension"))
        self.assertEqual(view._cursor_mode, "annotation_place")
        view.cleanup()

    def test_annotation_placement_does_not_require_general_editing_or_selection(self):
        view = self._make_plan_view()
        page = Page(uid="p1", name="P1", width_pts=612.0, height_pts=792.0)
        self._install_page_canvas(view, page)
        view.set_selection_enabled(False)
        view.set_editing_enabled(False)
        view.set_annotation_placement_allowed_fn(lambda: True)
        self.assertTrue(view.activate_annotation_placement("dimension"))
        self.assertEqual(view._cursor_mode, "annotation_place")
        self.assertTrue(view._editing_cursor_mode_allowed())
        view.cleanup()

    def test_dimension_drag_over_condition_label_creates_dimension(self):
        view = self._make_plan_view()
        page = Page(uid="p1", name="P1", width_pts=612.0, height_pts=792.0)
        self._install_page_canvas(view, page)
        view.set_selection_enabled(True)
        created = []
        view.annotation_created.connect(
            lambda annotation_type, position, page_uid: created.append(
                (annotation_type, list(position), page_uid)
            )
        )
        label = QGraphicsTextItem("Condition")
        label.setData(2, "condition_label")
        self.assertTrue(view.activate_annotation_placement(ANNOTATION_TYPE_DIMENSION))
        with patch.object(
            view, "_condition_text_label_at", return_value=label
        ), patch.object(
            view,
            "_select_condition_text_label",
            side_effect=AssertionError(
                "active dimension placement must precede condition-label selection"
            ),
        ):
            press = self._left_press_event(80.0, 80.0)
            release = self._left_release_event(140.0, 80.0)
            view.mousePressEvent(press)
            view.mouseReleaseEvent(release)
        self.assertTrue(press.isAccepted())
        self.assertTrue(release.isAccepted())
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][0], ANNOTATION_TYPE_DIMENSION)
        self.assertEqual(created[0][2], page.uid)
        position = created[0][1]
        self.assertEqual(len(position), 4)
        self.assertGreater(position[2], position[0])
        self.assertAlmostEqual(position[1], position[3])
        view._current_conditions = {
            "c1": Condition(uid="c1", condition_type=Condition.TYPE_LINEAR)
        }
        self.assertTrue(view.activate_place_for_condition("c1"))
        self.assertEqual(view.cursor_mode, CURSOR_MODE_PLACE)
        self.assertIsNone(view.annotation_place_type)
        view.cleanup()

    def test_dimension_drag_over_dimension_label_creates_dimension(self):
        view = self._make_plan_view()
        page = Page(uid="p1", name="P1", width_pts=612.0, height_pts=792.0)
        self._install_page_canvas(view, page)
        view.set_selection_enabled(True)
        created = []
        view.annotation_created.connect(
            lambda annotation_type, position, page_uid: created.append(
                (annotation_type, list(position), page_uid)
            )
        )
        label = QGraphicsTextItem("12' - 0\"")
        label.setData(2, DIMENSION_LABEL_ITEM_KIND)
        self.assertTrue(view.activate_annotation_placement(ANNOTATION_TYPE_DIMENSION))
        with patch.object(
            view, "_dimension_text_label_at", return_value=label
        ), patch.object(
            view,
            "_select_dimension_text_label",
            side_effect=AssertionError(
                "active dimension placement must precede dimension-label selection"
            ),
        ):
            press = self._left_press_event(80.0, 80.0)
            release = self._left_release_event(140.0, 80.0)
            view.mousePressEvent(press)
            view.mouseReleaseEvent(release)
        self.assertTrue(press.isAccepted())
        self.assertTrue(release.isAccepted())
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][0], ANNOTATION_TYPE_DIMENSION)
        self.assertEqual(created[0][2], page.uid)
        position = created[0][1]
        self.assertEqual(len(position), 4)
        self.assertGreater(position[2], position[0])
        self.assertAlmostEqual(position[1], position[3])
        view._current_conditions = {
            "c1": Condition(uid="c1", condition_type=Condition.TYPE_LINEAR)
        }
        self.assertTrue(view.activate_place_for_condition("c1"))
        self.assertEqual(view.cursor_mode, CURSOR_MODE_PLACE)
        self.assertIsNone(view.annotation_place_type)
        view.cleanup()

    def test_failed_paste_backout_preserves_dimension_tool_and_toolbar_state(self):
        view = self._make_plan_view()
        page = Page(uid="p1", name="P1", width_pts=612.0, height_pts=792.0)
        self._install_page_canvas(view, page)
        view.set_selection_enabled(True)
        view._current_conditions = {
            "area-condition": Condition(
                uid="area-condition",
                condition_type=Condition.TYPE_AREA,
            )
        }
        select_action = QAction()
        select_action.setCheckable(True)
        dimension_action = QAction()
        dimension_action.setCheckable(True)
        place_action = QAction()
        place_action.setCheckable(True)
        action_group = QActionGroup(view)
        action_group.setExclusive(True)
        for action in (select_action, dimension_action, place_action):
            action_group.addAction(action)
        select_action.toggled.connect(
            lambda checked: (
                view.set_cursor_mode(CURSOR_MODE_SELECT) if checked else None
            )
        )
        dimension_action.toggled.connect(
            lambda checked: (
                view.activate_annotation_placement(ANNOTATION_TYPE_DIMENSION)
                if checked
                else None
            )
        )
        place_action.toggled.connect(
            lambda checked: (
                view.activate_place_for_condition("area-condition") if checked else None
            )
        )

        def project_cursor_mode(mode):
            action = {
                CURSOR_MODE_SELECT: select_action,
                CURSOR_MODE_PLACE: place_action,
                CURSOR_MODE_ANNOTATION_PLACE: dimension_action,
            }.get(mode)
            if action is not None and not action.isChecked():
                action.setChecked(True)

        view.cursor_mode_change_requested.connect(project_cursor_mode)
        select_action.setChecked(True)
        dimension_action.setChecked(True)
        self.assertTrue(dimension_action.isChecked())
        self.assertEqual(view.cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
        self.assertEqual(view.annotation_place_type, ANNOTATION_TYPE_DIMENSION)
        self.assertTrue(view._editing_cursor_mode_allowed())
        hole = Takeoff(
            uid="hole",
            condition_uid="area-condition",
            position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
            parent_uid="source-parent",
        )
        self.assertFalse(view.begin_paste_backout([hole], {}, "7"))
        self.assertTrue(dimension_action.isChecked())
        self.assertFalse(select_action.isChecked())
        self.assertFalse(place_action.isChecked())
        self.assertEqual(view.cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
        self.assertEqual(view.annotation_place_type, ANNOTATION_TYPE_DIMENSION)
        self.assertTrue(view._editing_cursor_mode_allowed())
        created = []
        view.annotation_created.connect(
            lambda annotation_type, position, page_uid: created.append(
                (annotation_type, list(position), page_uid)
            )
        )
        view.mousePressEvent(self._left_press_event(80.0, 80.0))
        view.mouseReleaseEvent(self._left_release_event(140.0, 80.0))
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][0], ANNOTATION_TYPE_DIMENSION)
        self.assertTrue(dimension_action.isChecked())
        self.assertEqual(view.cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
        self.assertEqual(view.annotation_place_type, ANNOTATION_TYPE_DIMENSION)
        place_action.setChecked(True)
        self.assertTrue(place_action.isChecked())
        self.assertFalse(dimension_action.isChecked())
        self.assertEqual(view.cursor_mode, CURSOR_MODE_PLACE)
        self.assertEqual(view.place_condition_uid, "area-condition")
        self.assertIsNone(view.annotation_place_type)
        view.cleanup()


class TakeoffPlanViewSelectConditionTextLabelTests(
    _TakeoffPlanViewOverlayRefreshFixture
):
    """TakeoffPlanView._select_condition_text_label."""

    def test_condition_text_color_swatch_updates_from_selected_text_color(self):
        view = self._make_plan_view()
        label = QGraphicsTextItem("Condition")
        label.setData(2, "condition_label")
        label.setDefaultTextColor(QColor("#123456"))
        view._select_condition_text_label(label)
        image = view._condition_text_color_btn.icon().pixmap(20, 20).toImage()
        center_color = QColor.fromRgba(image.pixel(10, 10))
        self.assertEqual(center_color.name(), "#123456")
        self.assertEqual(
            view._condition_text_color_btn.toolTip(), "Text color (#123456)"
        )
        view.cleanup()

    def test_condition_text_toolbar_shows_for_label_and_clears_selection(self):
        view = self._make_plan_view()
        label = QGraphicsTextItem("Condition")
        label.setData(2, "condition_label")
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        view._select_condition_text_label(label)
        view._condition_text_bold_btn.setChecked(True)
        self.assertIs(view._selected_text_item, label)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(emitted, [])
        self.assertFalse(view._condition_text_align_left_btn.isEnabled())
        self.assertFalse(view._condition_text_align_center_btn.isEnabled())
        self.assertFalse(view._condition_text_align_right_btn.isEnabled())
        view._clear_text_selection()
        self.assertFalse(label.isSelected())
        self.assertIsNone(view._selected_text_item)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_condition_label_alignment_buttons_are_disabled_and_noop(self):
        view = self._make_plan_view()
        label = QGraphicsTextItem("Condition")
        label.setData(0, "t1")
        label.setData(2, "condition_label")
        label.setData(3, "display_name")
        option = QTextOption(label.document().defaultTextOption())
        option.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        label.document().setDefaultTextOption(option)
        emitted = []
        view.condition_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        view._select_condition_text_label(label)
        view._set_condition_text_alignment(QtCore.Qt.AlignmentFlag.AlignRight)
        alignment = label.document().defaultTextOption().alignment()
        self.assertTrue(alignment & QtCore.Qt.AlignmentFlag.AlignLeft)
        self.assertFalse(alignment & QtCore.Qt.AlignmentFlag.AlignRight)
        self.assertEqual(emitted, [])
        self.assertFalse(view._condition_text_align_center_btn.isEnabled())
        self.assertFalse(view._condition_text_align_right_btn.isEnabled())
        view.cleanup()

    def test_selecting_condition_label_clears_previous_label_outline(self):
        view = self._make_plan_view()
        name_label = QGraphicsTextItem("Display Name")
        name_label.setData(2, "condition_label")
        name_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        dimension_label = QGraphicsTextItem("12 SF")
        dimension_label.setData(2, "condition_label")
        dimension_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(name_label)
        view._scene.addItem(dimension_label)
        view._select_condition_text_label(name_label)
        self.assertTrue(name_label.isSelected())
        view._select_condition_text_label(dimension_label)
        self.assertFalse(name_label.isSelected())
        self.assertTrue(dimension_label.isSelected())
        self.assertIs(view._selected_text_item, dimension_label)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_selecting_text_annotation_clears_condition_label_outline(self):
        view = self._make_plan_view()
        label = QGraphicsTextItem("Display Dimension")
        label.setData(2, "condition_label")
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(label)
        annotation = BidAnnotation(uid="a1", annotation_type="text")
        annotation_item = QGraphicsTextItem("Note")
        annotation_item.setData(0, "a1")
        view._scene.addItem(annotation_item)
        view._uid_to_items = {"a1": [annotation_item]}
        view._current_annotations = {"a1": annotation}
        view._select_condition_text_label(label)
        self.assertTrue(label.isSelected())
        self.assertTrue(view._select_text_annotation_label("a1"))
        self.assertFalse(label.isSelected())
        self.assertIs(view._selected_text_item, annotation_item)
        self.assertEqual(view._selected_text_annotation_uid, "a1")
        view.cleanup()

    def test_deleting_selected_takeoff_clears_its_condition_text_toolbar_target(self):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        label = QGraphicsTextItem("Area")
        label.setData(0, "t1")
        label.setData(1, "c1")
        label.setData(2, "condition_label")
        label.setData(3, "display_name")
        view._scene.addItem(path_item)
        view._scene.addItem(label)
        view._uid_to_items = {"t1": [path_item, label]}
        view._current_takeoffs = {"t1": Takeoff(uid="t1", condition_uid="c1")}
        view._current_conditions = {
            "c1": Condition(uid="c1", name="Area", condition_type=Condition.TYPE_AREA)
        }
        view._editing_enabled = True
        view._selected_uids = {"t1"}
        view._select_condition_text_label(label)
        states = []
        view.elements_deleted.connect(
            lambda _uids: states.append(
                (
                    view._selected_text_item,
                    view._condition_text_toolbar.isHidden(),
                )
            )
        )
        view.delete_selected()
        self.assertEqual(states, [(None, True)])
        self.assertIsNone(view._selected_text_annotation_uid)
        view.cleanup()

    def test_selected_display_name_toolbar_restores_after_label_rebuild(self):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        old_label = QGraphicsTextItem("Display Name")
        old_label.setData(0, "t1")
        old_label.setData(1, "c1")
        old_label.setData(2, "condition_label")
        old_label.setData(3, "display_name")
        old_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(old_label)
        view._uid_to_items = {"t1": [path_item, old_label]}
        view._current_takeoffs = {"t1": Takeoff(uid="t1", condition_uid="c1")}
        view._current_conditions = {
            "c1": Condition(uid="c1", name="Area", condition_type=Condition.TYPE_AREA)
        }
        view._select_condition_text_label(old_label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        saved_target = view._selected_condition_text_label_target()
        view._clear_text_selection()
        new_label = QGraphicsTextItem("Display Name")
        new_label.setData(0, "t1")
        new_label.setData(1, "c1")
        new_label.setData(2, "condition_label")
        new_label.setData(3, "display_name")
        new_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        new_label.setFont(QFont("Arial", 24))
        view._scene.addItem(new_label)
        view._uid_to_items = {"t1": [path_item, new_label]}
        view._restore_selected_condition_text_label_toolbar(saved_target)
        self.assertIs(view._selected_text_item, new_label)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(new_label.isSelected())
        self.assertFalse(old_label.isSelected())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(view._condition_text_size_combo.currentData(), 24)
        view.cleanup()

    def test_selected_display_dimension_toolbar_restores_after_color_rebuild(self):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        old_label = QGraphicsTextItem("100.00 SF")
        old_label.setData(0, "t1")
        old_label.setData(1, "c1")
        old_label.setData(2, "condition_label")
        old_label.setData(3, "display_dimension")
        old_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(old_label)
        view._uid_to_items = {"t1": [path_item, old_label]}
        takeoff = Takeoff(uid="t1", condition_uid="c1")
        view._current_takeoffs = {"t1": takeoff}
        view._current_conditions = {
            "c1": Condition(uid="c1", name="Area", condition_type=Condition.TYPE_AREA)
        }
        view._select_condition_text_label(old_label)
        old_label.setDefaultTextColor(QColor("#112233"))
        view._persist_selected_text_annotation()
        saved_target = view._selected_condition_text_label_target()
        view._clear_text_selection()
        new_label = QGraphicsTextItem("100.00 SF")
        new_label.setData(0, "t1")
        new_label.setData(1, "c1")
        new_label.setData(2, "condition_label")
        new_label.setData(3, "display_dimension")
        new_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        new_label.setDefaultTextColor(QColor("#112233"))
        view._scene.addItem(new_label)
        view._uid_to_items = {"t1": [path_item, new_label]}
        view._restore_selected_condition_text_label_toolbar(saved_target)
        self.assertIs(view._selected_text_item, new_label)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(new_label.isSelected())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(takeoff.dimension_font_color, 0x332211)
        self.assertIn("#112233", view._condition_text_color_btn.toolTip())
        view.cleanup()


class TakeoffPlanViewRefreshConditionTextLabelLayoutTests(
    _TakeoffPlanViewOverlayRefreshFixture
):
    """TakeoffPlanView._refresh_condition_text_label_layout."""

    def test_display_name_label_font_size_recomputes_box_immediately(self):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        label = QGraphicsTextItem("Display Name")
        label.setData(0, "t1")
        label.setData(1, "c1")
        label.setData(2, "condition_label")
        label.setData(3, "display_name")
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(label)
        view._uid_to_items = {"t1": [path_item, label]}
        view._current_takeoffs = {"t1": Takeoff(uid="t1", condition_uid="c1")}
        view._current_conditions = {"c1": Condition(uid="c1", name="Area")}
        view._refresh_condition_text_label_layout(label)
        initial_rect = label.mapToScene(label.boundingRect()).boundingRect()
        view._select_condition_text_label(label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        updated_rect = label.mapToScene(label.boundingRect()).boundingRect()
        self.assertGreater(updated_rect.height(), initial_rect.height())
        self.assertAlmostEqual(updated_rect.center().x(), 50.0, places=3)
        self.assertGreater(updated_rect.top(), 100.0)
        self.assertTrue(label.isSelected())
        self.assertIs(view._selected_text_item, label)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(view._current_takeoffs["t1"].name_font_size, 24)
        view.cleanup()

    def test_display_dimension_label_font_size_recomputes_center_immediately(self):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        label = QGraphicsTextItem("100.00 SF\n40.00 LF\n0.00 CY")
        label.setData(0, "t1")
        label.setData(1, "c1")
        label.setData(2, "condition_label")
        label.setData(3, "display_dimension")
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(label)
        view._uid_to_items = {"t1": [path_item, label]}
        view._current_takeoffs = {"t1": Takeoff(uid="t1", condition_uid="c1")}
        view._current_conditions = {"c1": Condition(uid="c1", name="Area")}
        view._refresh_condition_text_label_layout(label)
        initial_rect = label.mapToScene(label.boundingRect()).boundingRect()
        view._select_condition_text_label(label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        updated_rect = label.mapToScene(label.boundingRect()).boundingRect()
        self.assertGreater(updated_rect.height(), initial_rect.height())
        self.assertAlmostEqual(updated_rect.center().x(), 50.0, places=3)
        self.assertAlmostEqual(updated_rect.center().y(), 50.0, places=3)
        self.assertTrue(label.isSelected())
        self.assertIs(view._selected_text_item, label)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(view._current_takeoffs["t1"].dimension_font_size, 24)
        view.cleanup()

    def test_area_display_name_stays_below_dimension_after_live_dimension_recompute(
        self,
    ):
        view = self._make_plan_view()
        path_item = self._make_condition_label_path_item("t1")
        dimension_label = QGraphicsTextItem("100.00 SF\n40.00 LF\n0.00 CY")
        dimension_label.setData(0, "t1")
        dimension_label.setData(1, "c1")
        dimension_label.setData(2, "condition_label")
        dimension_label.setData(3, "display_dimension")
        dimension_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        name_label = QGraphicsTextItem("Display Name")
        name_label.setData(0, "t1")
        name_label.setData(1, "c1")
        name_label.setData(2, "condition_label")
        name_label.setData(3, "display_name")
        name_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(path_item)
        view._scene.addItem(dimension_label)
        view._scene.addItem(name_label)
        view._uid_to_items = {"t1": [path_item, dimension_label, name_label]}
        view._current_takeoffs = {"t1": Takeoff(uid="t1", condition_uid="c1")}
        view._current_conditions = {
            "c1": Condition(
                uid="c1",
                name="Area",
                condition_type=Condition.TYPE_AREA,
                display_dimension=True,
                display_name=True,
            )
        }
        view._refresh_condition_text_label_layout(dimension_label)
        view._refresh_condition_text_label_layout(name_label)
        view._select_condition_text_label(dimension_label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        dimension_rect = dimension_label.mapToScene(
            dimension_label.boundingRect()
        ).boundingRect()
        name_rect = name_label.mapToScene(name_label.boundingRect()).boundingRect()
        self.assertAlmostEqual(name_rect.center().x(), dimension_rect.center().x())
        self.assertGreater(name_rect.top(), dimension_rect.bottom())
        self.assertTrue(dimension_label.isSelected())
        self.assertIs(view._selected_text_item, dimension_label)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.cleanup()


class TakeoffPlanViewSelectTextAnnotationLabelTests(
    _TakeoffPlanViewOverlayRefreshFixture
):
    """TakeoffPlanView._select_text_annotation_label."""

    def test_text_annotation_uses_shared_toolbar_and_persists_style_changes(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=ANNOTATION_TYPE_TEXT,
            properties={
                "Text": "Note",
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": 12,
                "FontBold": False,
                "FontItalic": False,
                "FontUnderline": False,
                "TextAlign": 0,
            },
        )
        item = QGraphicsTextItem("Note")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._select_text_annotation_label("a1"))
        self.assertTrue(view._condition_text_align_left_btn.isEnabled())
        self.assertTrue(view._condition_text_align_center_btn.isEnabled())
        self.assertTrue(view._condition_text_align_right_btn.isEnabled())
        size_index = view._condition_text_size_combo.findData(18)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        view._condition_text_bold_btn.setChecked(True)
        view._condition_text_italic_btn.setChecked(True)
        view._condition_text_underline_btn.setChecked(True)
        view._set_condition_text_alignment(QtCore.Qt.AlignmentFlag.AlignRight)
        item.setDefaultTextColor(QColor("#112233"))
        view._persist_selected_text_annotation()
        self.assertEqual(view._selected_text_annotation_uid, "a1")
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertTrue(annotation.properties["FontBold"])
        self.assertTrue(annotation.properties["FontItalic"])
        self.assertTrue(annotation.properties["FontUnderline"])
        self.assertEqual(annotation.properties["FontSize"], 18)
        self.assertEqual(annotation.properties["TextAlign"], 2)
        self.assertTrue(view._condition_text_align_right_btn.isChecked())
        self.assertFalse(view._condition_text_align_left_btn.isChecked())
        self.assertFalse(view._condition_text_align_center_btn.isChecked())
        self.assertEqual(annotation.properties["FontColor"], 0x332211)
        self.assertEqual(emitted[-1][0], "a1")
        self.assertEqual(emitted[-1][3]["FontColor"], 0x332211)
        view.cleanup()

    def test_text_annotation_color_change_does_not_resize_box(self):
        view = self._make_plan_view()
        annotation, _item = self._add_text_annotation(
            view,
            text="Color text",
            position=[100.0, 120.0, 90.0, 25.0],
        )
        emitted_text, emitted_positions = self._capture_annotation_flushes(view)
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        with patch.object(QColorDialog, "getColor", return_value=QColor("#445566")):
            view._pick_condition_text_color()
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(emitted_positions, [])
        self.assertEqual(annotation.properties["FontColor"], 0x665544)
        self.assertEqual(emitted_text[-1][3]["FontColor"], 0x665544)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_text_annotation_toolbar_clears_before_delete_signal(self):
        view = self._make_plan_view()
        _annotation, item = self._add_text_annotation(view, text="Before")
        view._editing_enabled = True
        view._selected_uids = {"a1"}
        self.assertTrue(view._select_text_annotation_label("a1"))
        event_order = []

        def remove_annotation(uids):
            event_order.append(
                (
                    "deleted",
                    list(uids),
                    view.get_selected_uids(),
                    view._selected_text_item,
                    view._selected_text_annotation_uid,
                    view._condition_text_toolbar.isHidden(),
                )
            )
            view._current_annotations.pop("a1")
            view._uid_to_items.pop("a1")
            view._scene.removeItem(item)

        view.takeoff_selection_changed.connect(
            lambda uids: event_order.append(("selection", list(uids)))
        )
        view.elements_deleted.connect(remove_annotation)
        view.delete_selected()
        self.assertEqual(
            event_order,
            [
                ("selection", []),
                ("deleted", ["a1"], [], None, None, True),
            ],
        )
        self.assertIsNone(item.scene())
        self.assertIsNone(view._selected_text_item)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_multi_selection_delete_clears_text_toolbar_once_before_delete_signal(self):
        view = self._make_plan_view()
        annotation_1, item_1 = self._add_text_annotation(view, uid="a1", text="First")
        annotation_2, item_2 = self._add_text_annotation(view, uid="a2", text="Second")
        view._current_annotations = {"a1": annotation_1, "a2": annotation_2}
        view._uid_to_items = {"a1": [item_1], "a2": [item_2]}
        view._editing_enabled = True
        view._selected_uids = {"a1", "a2"}
        self.assertTrue(view._select_text_annotation_label("a1"))
        events = []
        view.takeoff_selection_changed.connect(
            lambda uids: events.append(("selection", list(uids)))
        )
        view.elements_deleted.connect(
            lambda uids: events.append(("deleted", sorted(uids)))
        )
        view.delete_selected()
        self.assertEqual(
            events,
            [("selection", []), ("deleted", ["a1", "a2"])],
        )
        self.assertIsNone(view._selected_text_item)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_disabling_selection_clears_text_toolbar_without_extra_interaction(self):
        view = self._make_plan_view()
        self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._select_text_annotation_label("a1"))
        view.set_selection_enabled(False)
        self.assertEqual(view.get_selected_uids(), [])
        self.assertIsNone(view._selected_text_item)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_selected_text_annotation_toolbar_restores_after_overlay_rebuild(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        old_item = QGraphicsTextItem("Before")
        old_item.setData(0, "a1")
        view._scene.addItem(old_item)
        view._uid_to_items = {"a1": [old_item]}
        view._current_annotations = {"a1": annotation}
        view._selected_uids = {"a1"}
        self.assertTrue(view._select_text_annotation_label("a1"))
        view._clear_text_selection()
        new_item = QGraphicsTextItem("Before")
        new_item.setData(0, "a1")
        new_item.setPos(25, 40)
        view._scene.addItem(new_item)
        view._uid_to_items = {"a1": [new_item]}
        view._restore_selected_text_annotation_toolbar("a1")
        self.assertIs(view._selected_text_item, new_item)
        self.assertEqual(view._selected_text_annotation_uid, "a1")
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_text_annotation_font_size_increase_preserves_box_geometry(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 40.0, 15.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setTextWidth(40)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        emitted_text = []
        separate_position_changes = []
        view.annotation_text_properties_flushed.connect(emitted_text.extend)
        view.positions_flushed.connect(
            lambda _takeoffs, annotations: separate_position_changes.extend(annotations)
        )
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(annotation.position, old_position)
        outline = self._first_selection_outline(view).polygon().boundingRect()
        self.assertEqual(outline.center(), QtCore.QPointF(100.0, 100.0))
        self.assertEqual(outline.width(), old_position[2])
        self.assertEqual(outline.height(), old_position[3])
        self.assertEqual(
            item.pos(),
            QtCore.QPointF(
                100.0 - old_position[2] / 2.0,
                100.0 - old_position[3] / 2.0,
            ),
        )
        self.assertEqual(separate_position_changes, [])
        self.assertEqual(emitted_text[-1][3]["FontSize"], 24)
        view.cleanup()

    def test_text_annotation_style_change_flushes_without_box_change(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 40.0, 15.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setTextWidth(40)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        emitted_text = []
        emitted_positions = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted_text.extend(changes)
        )
        view.positions_flushed.connect(
            lambda _takeoffs, annotations: emitted_positions.extend(annotations)
        )
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(len(emitted_text), 1)
        self.assertEqual(emitted_positions, [])
        self.assertEqual(emitted_text[0][2]["FontSize"], 12)
        self.assertEqual(emitted_text[0][3]["FontSize"], 24)
        self.assertEqual(annotation.position, old_position)
        view.cleanup()

    def test_new_text_annotation_font_sizes_update_through_toolbar_workflow(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 40.0, 15.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setTextWidth(40)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        emitted = []
        view.annotation_text_properties_flushed.connect(emitted.extend)
        self.assertTrue(view._select_text_annotation_label("a1"))
        self.assertEqual(
            [
                view._condition_text_size_combo.itemData(index)
                for index in range(view._condition_text_size_combo.count())
            ],
            [8, 9, 10, 11, 12, 14, 16, 18, 24, 36, 48, 72],
        )
        for size in (48, 72):
            with self.subTest(size=size):
                size_index = view._condition_text_size_combo.findData(size)
                self.assertGreaterEqual(size_index, 0)
                view._condition_text_size_combo.setCurrentIndex(size_index)
                self.assertEqual(annotation.properties["FontSize"], size)
                self.assertEqual(emitted[-1][3]["FontSize"], size)
        view.cleanup()

    def test_text_annotation_font_size_decrease_preserves_box_geometry(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 180.0, 60.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 24},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setFont(QFont("Arial", 24))
        item.setTextWidth(180)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        size_index = view._condition_text_size_combo.findData(8)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(annotation.position, old_position)
        outline = self._first_selection_outline(view).polygon().boundingRect()
        self.assertEqual(outline.center(), QtCore.QPointF(100.0, 100.0))
        self.assertEqual(outline.width(), old_position[2])
        self.assertEqual(outline.height(), old_position[3])
        view.cleanup()

    def test_text_annotation_font_size_change_keeps_clip_rect_on_stored_box(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 40.0, 15.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 40.0, 15.0))
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        self.assertTrue(view._select_text_annotation_label("a1"))
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(
            item.clip_rect(),
            QtCore.QRectF(0.0, 0.0, annotation.position[2], annotation.position[3]),
        )
        self.assertEqual(item.boundingRect(), item.clip_rect())
        self.assertEqual(item.pos().x(), 100.0 - annotation.position[2] / 2.0)
        self.assertEqual(item.pos().y(), 100.0 - annotation.position[3] / 2.0)
        view.cleanup()


class TakeoffPlanViewSelectDimensionTextLabelTests(
    _TakeoffPlanViewOverlayRefreshFixture
):
    """TakeoffPlanView._select_dimension_text_label."""

    def test_bid_dimension_label_uses_toolbar_without_alignment_or_bidtext_target(self):
        view = self._make_plan_view()
        annotation, label = self._add_dimension_label_annotation(view)
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._select_dimension_text_label(label))
        self.assertIs(view._selected_text_item, label)
        self.assertEqual(view._selected_text_annotation_uid, "d1")
        self.assertFalse(annotation.is_text)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertTrue(label.isSelected())
        self.assertFalse(view._condition_text_align_left_btn.isEnabled())
        self.assertFalse(view._condition_text_align_center_btn.isEnabled())
        self.assertFalse(view._condition_text_align_right_btn.isEnabled())
        old_rect = label.mapToScene(label.boundingRect()).boundingRect()
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        new_rect = label.mapToScene(label.boundingRect()).boundingRect()
        self.assertGreater(new_rect.height(), old_rect.height())
        self.assertEqual(label.toPlainText(), "21' - 3\"")
        self.assertEqual(annotation.properties["FontSize"], 24)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[-1][1], "dimension")
        self.assertNotIn("Text", emitted[-1][3])
        self.assertNotIn("TextAlign", emitted[-1][3])
        view.cleanup()

    def test_bid_dimension_label_color_change_persists_and_toolbar_stays_visible(self):
        view = self._make_plan_view()
        annotation, label = self._add_dimension_label_annotation(
            view, {"FontName": "Arial", "FontColor": 0, "FontSize": 10}
        )
        label.setDefaultTextColor(QColor("#000000"))
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._select_dimension_text_label(label))
        with patch.object(QColorDialog, "getColor", return_value=QColor("#445566")):
            view._pick_condition_text_color()
        self.assertEqual(annotation.properties["FontColor"], 0x665544)
        self.assertEqual(annotation.color, "#445566")
        self.assertEqual(label.defaultTextColor().name(), "#445566")
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[-1][1], "dimension")
        self.assertEqual(emitted[-1][3]["FontColor"], 0x665544)
        self.assertNotIn("TextAlign", emitted[-1][3])
        view.cleanup()

    def test_text_color_picker_drops_result_after_toolbar_target_is_cleared(self):
        view = self._make_plan_view()
        annotation, label = self._add_dimension_label_annotation(
            view, {"FontName": "Arial", "FontColor": 0, "FontSize": 10}
        )
        label.setDefaultTextColor(QColor("#000000"))
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._select_dimension_text_label(label))

        def clear_target(*_args, **_kwargs):
            view._clear_text_toolbar_target()
            return QColor("#445566")

        with patch.object(QColorDialog, "getColor", side_effect=clear_target):
            view._pick_condition_text_color()
        self.assertEqual(label.defaultTextColor().name(), "#000000")
        self.assertEqual(annotation.properties["FontColor"], 0)
        self.assertEqual(emitted, [])
        view.cleanup()

    def test_selected_bid_dimension_label_toolbar_restores_after_overlay_rebuild(self):
        view = self._make_plan_view()
        _annotation, old_label = self._add_dimension_label_annotation(
            view, {"FontName": "Arial", "FontColor": 0, "FontSize": 10}
        )
        self.assertTrue(view._select_dimension_text_label(old_label))
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        saved_uid = view._selected_dimension_text_label_target()
        view._clear_text_selection()
        new_label = QGraphicsTextItem("21' - 3\"")
        new_label.setData(0, "d1")
        new_label.setData(2, DIMENSION_LABEL_ITEM_KIND)
        new_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        new_label.setFont(QFont("Arial", 24))
        view._scene.addItem(new_label)
        view._uid_to_items = {"d1": [new_label]}
        view._restore_selected_dimension_text_label_toolbar(saved_uid)
        self.assertIs(view._selected_text_item, new_label)
        self.assertEqual(view._selected_text_annotation_uid, "d1")
        self.assertTrue(new_label.isSelected())
        self.assertFalse(old_label.isSelected())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertFalse(view._condition_text_align_left_btn.isEnabled())
        self.assertFalse(view._condition_text_align_center_btn.isEnabled())
        self.assertFalse(view._condition_text_align_right_btn.isEnabled())
        self.assertEqual(view._condition_text_size_combo.currentData(), 24)
        view.cleanup()


class TakeoffPlanViewBuildRenderIdentityTests(_TakeoffPlanViewOverlayRefreshFixture):
    """TakeoffPlanView._build_render_identity."""

    def test_text_annotation_alignment_changes_do_not_resize_box(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        annotation, _item = self._add_text_annotation(
            view,
            text="Aligned text",
            page_uid=page.uid,
            position=[100.0, 120.0, 90.0, 25.0],
        )
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        emitted_text, emitted_positions = self._capture_annotation_flushes(view)
        self.assertTrue(view._select_text_annotation_label("a1"))
        old_position = list(annotation.position)
        view._set_condition_text_alignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        view._set_condition_text_alignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(emitted_positions, [])
        self.assertEqual(annotation.properties["TextAlign"], 2)
        self.assertEqual(emitted_text[-1][3]["TextAlign"], 2)
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertTrue(view._condition_text_align_right_btn.isChecked())
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[annotation],
                page_area_selections={},
            )
        )
        rebuilt = view._text_annotation_item("a1")
        self.assertIsInstance(rebuilt, ClippedTextGraphicsItem)
        alignment = rebuilt.document().defaultTextOption().alignment()
        self.assertTrue(alignment & QtCore.Qt.AlignmentFlag.AlignRight)
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(rebuilt.clip_rect().width(), old_position[2])
        self.assertEqual(rebuilt.clip_rect().height(), old_position[3])
        view.cleanup()

    def test_selected_condition_label_toolbar_restores_after_overlay_refresh(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        takeoff = Takeoff(uid="t1", condition_uid="c1")
        condition = Condition(
            uid="c1",
            name="Area",
            condition_type=Condition.TYPE_AREA,
            display_name=True,
        )
        old_path = self._make_condition_label_path_item("t1")
        old_label = QGraphicsTextItem("Area")
        old_label.setData(0, "t1")
        old_label.setData(1, "c1")
        old_label.setData(2, "condition_label")
        old_label.setData(3, "display_name")
        old_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        view._scene.addItem(old_path)
        view._scene.addItem(old_label)
        view._uid_to_items = {"t1": [old_path, old_label]}
        view._current_takeoffs = {"t1": takeoff}
        view._current_conditions = {"c1": condition}
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)

        def add_takeoff_overlays(
            scene,
            _takeoffs,
            _conditions,
            _color_map,
            _page_info,
            _area_selections,
            *,
            inactive_object_color,
        ):
            self.assertEqual(
                inactive_object_color, Config.DEFAULT_INACTIVE_OBJECT_COLOR
            )
            new_path = self._make_condition_label_path_item("t1")
            new_label = QGraphicsTextItem("Area")
            new_label.setData(0, "t1")
            new_label.setData(1, "c1")
            new_label.setData(2, "condition_label")
            new_label.setData(3, "display_name")
            new_label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
            new_label.setFont(QFont("Arial", 24))
            scene.addItem(new_path)
            scene.addItem(new_label)
            return [new_path, new_label], {"t1": [new_path, new_label]}

        view._scene_builder.add_takeoff_overlays = add_takeoff_overlays
        view._select_condition_text_label(old_label)
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[takeoff],
                conditions={"c1": condition},
                color_map={"c1": "#123456"},
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
            )
        )
        rebuilt_label = view._condition_label_text_item("t1", "display_name")
        self.assertIs(view._selected_text_item, rebuilt_label)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(rebuilt_label.isSelected())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(view._condition_text_size_combo.currentData(), 24)
        view.cleanup()

    def test_text_annotation_style_and_centered_box_survive_overlay_refresh(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="page-1",
            position=[100.0, 100.0, 40.0, 15.0],
            properties={
                "Text": "Before",
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": 12,
            },
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 40.0, 15.0))
        item.setData(0, "a1")
        item.setTextWidth(40.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._selection_enabled = True
        self.assertTrue(view._select_text_annotation_label("a1"))
        size_index = view._condition_text_size_combo.findData(72)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        item.setDefaultTextColor(QColor("#112233"))
        view._persist_selected_text_annotation()
        updated_position = list(annotation.position)
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[annotation],
                page_area_selections={},
            )
        )
        rebuilt = view._text_annotation_item("a1")
        self.assertIsInstance(rebuilt, ClippedTextGraphicsItem)
        self.assertEqual(rebuilt.font().pointSize(), 72)
        self.assertEqual(rebuilt.defaultTextColor().name(), "#112233")
        self.assertEqual(annotation.properties["FontSize"], 72)
        self.assertEqual(annotation.properties["FontColor"], 0x332211)
        self.assertEqual(annotation.position, updated_position)
        self.assertEqual(
            rebuilt.pos(),
            QtCore.QPointF(
                annotation.position[0] - annotation.position[2] / 2.0,
                annotation.position[1] - annotation.position[3] / 2.0,
            ),
        )
        self.assertEqual(rebuilt.clip_rect().width(), annotation.position[2])
        self.assertEqual(rebuilt.clip_rect().height(), annotation.position[3])
        view.cleanup()

    def test_full_overlay_refresh_removes_text_draft_and_releases_edit_mode(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1", width_pts=100.0, height_pts=100.0)
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view._current_page = page
        view._current_bid_page_uid = page.uid
        view._current_bid_ref = bid_ref
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._selection_enabled = True
        edit_states = []
        view.text_annotation_edit_mode_changed.connect(edit_states.append)
        self.assertTrue(
            view.begin_text_annotation_draft([100.0, 100.0, 80.0, 24.0], page.uid)
        )
        uid = view._draft_text_annotation_uid
        item = view._text_annotation_item(uid)
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        view._refresh_overlays(page, [], {}, {}, [], {}, bid_ref)
        self.assertIsNone(view._draft_text_annotation_uid)
        self.assertIsNone(view._editing_text_annotation_uid)
        self.assertNotIn(uid, view._current_annotations)
        self.assertIsNone(item.scene())
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        self.assertEqual(edit_states, [True, False])
        view.cleanup()

    def test_overlay_refresh_after_inline_text_edit_keeps_textbox_width(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        annotation, item = self._add_text_annotation(
            view,
            text="Short",
            page_uid=page.uid,
            position=[100.0, 100.0, 52.0, 22.0],
        )
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._selected_uids = {"a1"}
        old_position = list(annotation.position)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("Long text that must wrap after refresh too")
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(annotation.position, old_position)
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[annotation],
                page_area_selections={},
            )
        )
        rebuilt = view._text_annotation_item("a1")
        self.assertIsInstance(rebuilt, ClippedTextGraphicsItem)
        self.assertEqual(
            rebuilt.toPlainText(),
            "Long text that must wrap after refresh too",
        )
        self.assertEqual(rebuilt.textWidth(), old_position[2])
        self.assertEqual(rebuilt.clip_rect().width(), old_position[2])
        self.assertEqual(rebuilt.clip_rect().height(), old_position[3])
        self.assertEqual(annotation.position, old_position)
        view.cleanup()

    def test_overlay_refresh_does_not_enter_load_view_state_path(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view._current_bid_page_uid = "page-1"
        view._current_render_identity = TakeoffPlanView._build_render_identity(
            view, page, bid_ref
        )
        view._current_page = page
        view._background_item = None
        view._visible_frame_item = None
        view._overlay_items = []
        view._white_canvas_item = None
        view._overlay_move_normal_visuals_hidden = False
        view._load_coordinator = FakeLoadCoordinator()
        calls = []
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        view._update_scene_rect = lambda: calls.append("update_scene_rect")
        view.viewport = lambda: FakeViewport(calls)
        view._begin_load_cycle = lambda *_args: calls.append("begin_load_cycle")
        view.restore_view_state = lambda *_args: calls.append("restore_view_state")
        view.fit_to_page = lambda: calls.append("fit_to_page")
        view.resetTransform = lambda: calls.append("reset_transform")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
        )
        self.assertTrue(refreshed)
        self.assertEqual(
            calls,
            ["refresh_overlays", "update_scene_rect", "viewport.update"],
        )

    def test_annotation_delete_full_refresh_releases_active_text_edit(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1", width_pts=100.0, height_pts=100.0)
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        annotation, item = self._add_text_annotation(
            view,
            uid="ann-1",
            text="old",
            page_uid=page.uid,
            position=[20.0, 20.0, 80.0, 24.0],
        )
        view._current_page = page
        view._current_bid_page_uid = page.uid
        view._current_bid_ref = bid_ref
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._current_takeoffs = {}
        view._current_conditions = {}
        view._current_color_map = {}
        view._current_page_area_selections = {}
        view._ann_db_uid_map = {}
        view._takeoff_items = [item]
        view._selected_uids = {annotation.uid}
        edit_states = []
        view.text_annotation_edit_mode_changed.connect(edit_states.append)
        self.assertTrue(view._begin_text_annotation_edit(annotation.uid))
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[],
            conditions={},
            color_map={},
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=[annotation.uid],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertTrue(refreshed)
        self.assertIsNone(item.scene())
        self.assertIsNone(view._editing_text_annotation_uid)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        self.assertEqual(edit_states, [True, False])
        view.cleanup()

    def test_overlay_refresh_rejects_render_identity_change(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view._current_bid_page_uid = "page-1"
        view._current_render_identity = TakeoffPlanView._build_render_identity(
            view, page, bid_ref
        )
        page.rotation = 90
        view._refresh_overlays = lambda *_args: self.fail(
            "overlay refresh should not run when render identity changes"
        )
        self.assertFalse(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
            )
        )

    def test_overlay_refresh_rejects_page_calibration_change(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            scale_factor1=0.1875,
            scale_factor2=12.0,
        )
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view._current_bid_page_uid = page.uid
        view._current_render_identity = TakeoffPlanView._build_render_identity(
            view, page, bid_ref
        )
        page.scale_factor1 = 0.125
        view._refresh_overlays = lambda *_args: self.fail(
            "overlay refresh should not reuse a render from another calibration"
        )
        self.assertFalse(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
            )
        )

    def test_image_layer_show_without_loaded_image_rejects_overlay_refresh(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        hidden_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            layer_visible=False,
        )
        shown_page = replace(hidden_page, layer_visible=True)
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        view._current_bid_page_uid = hidden_page.uid
        view._current_page = hidden_page
        view._current_render_identity = TakeoffPlanView._build_render_identity(
            view, hidden_page, bid_ref
        )
        view._background_item = None
        view._visible_frame_item = None
        view._overlay_items = []
        view._load_coordinator = FakeLoadCoordinator()
        view._refresh_overlays = lambda *_args: self.fail(
            "overlay refresh should not run before the image is loaded"
        )
        self.assertFalse(
            view.refresh_current_page_overlays(
                page=shown_page,
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
            )
        )

    def test_image_layer_toggle_refresh_preserves_page_visual_geometry(self):
        view = self._make_plan_view()
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            layer_visible=True,
            width_pts=100.0,
            height_pts=150.0,
        )
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        background = ImageBackgroundItem(image, 200.0, 300.0)
        frame = TileGraphicsItem(
            image,
            QtCore.QRectF(12.25, 18.5, 80.0, 120.0),
            QtCore.QRectF(0.0, 0.0, 20.0, 20.0),
        )
        frame_transform = QTransform()
        frame_transform.translate(0.375, 0.625)
        frame.setTransform(frame_transform)
        overlay = QGraphicsPixmapItem(QPixmap.fromImage(image))
        overlay_transform = QTransform()
        overlay_transform.translate(3.5, 4.25)
        overlay_transform.scale(1.2, 1.1)
        overlay.setTransform(overlay_transform)
        canvas = QGraphicsRectItem(0.0, 0.0, 200.0, 300.0)
        view._scene.addItem(background)
        view._scene.addItem(frame)
        view._scene.addItem(overlay)
        view._scene.addItem(canvas)
        view._background_item = background
        view._visible_frame_item = frame
        view._overlay_items = [overlay]
        view._white_canvas_item = canvas
        view._current_bid_page_uid = page.uid
        view._current_page = page
        view._current_bid_ref = bid_ref
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._loaded_visual_kind = VISUAL_KIND_PAGE
        view._pdf_width_pts = page.width_pts
        view._pdf_height_pts = page.height_pts
        view._scene_scale = 2.0
        initial_items = (view._background_item, view._visible_frame_item, overlay)
        initial_background_rect = background.sceneBoundingRect()
        initial_frame_rect = frame.sceneBoundingRect()
        initial_overlay_rect = overlay.sceneBoundingRect()
        initial_frame_transform = frame.transform()
        initial_view_transform = view.transform()
        try:
            for visible in (False, True, False, True, False, True):
                refreshed = view.refresh_current_page_overlays(
                    page=replace(page, layer_visible=visible),
                    takeoffs=[],
                    conditions={},
                    color_map={},
                    bid_ref=bid_ref,
                    annotations=[],
                    page_area_selections={},
                )
                self.assertTrue(refreshed)
                self.assertIs(view._background_item, initial_items[0])
                self.assertIs(view._visible_frame_item, initial_items[1])
                self.assertIs(view._overlay_items[0], initial_items[2])
                self.assertEqual(
                    background.sceneBoundingRect(), initial_background_rect
                )
                self.assertEqual(frame.sceneBoundingRect(), initial_frame_rect)
                self.assertEqual(overlay.sceneBoundingRect(), initial_overlay_rect)
                self.assertEqual(frame.transform(), initial_frame_transform)
                self.assertEqual(view.transform(), initial_view_transform)
                self.assertEqual(background.isVisible(), visible)
                self.assertEqual(frame.isVisible(), visible)
                self.assertEqual(overlay.isVisible(), visible)
                self.assertTrue(canvas.isVisible())
        finally:
            view.cleanup()

    def test_overlay_refresh_preserves_dirty_takeoff_position_without_flushing(self):
        view = self._make_plan_view()
        page = Page(uid="page-1", name="Page 1")
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="bid-1")
        condition = Condition(uid="c1", name="Condition", layer_visible=True)
        stale_takeoff = Takeoff(
            uid="1",
            condition_uid="c1",
            page_uid="page-1",
            position=[0.0, 0.0, 10.0, 10.0],
        )
        dirty_position = [50.0, 60.0, 70.0, 80.0]
        view._current_bid_page_uid = page.uid
        view._current_render_identity = view._build_render_identity(page, bid_ref)
        view._dirty_positions = {"1": list(dirty_position)}
        view._position_before_edit = {"1": list(stale_takeoff.position)}
        emitted = []
        view.positions_flushed.connect(
            lambda takeoffs, annotations: emitted.append((takeoffs, annotations))
        )
        try:
            refreshed = view.refresh_current_page_overlays(
                page=page,
                takeoffs=[stale_takeoff],
                conditions={"c1": condition},
                color_map={},
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
            )
            self.assertTrue(refreshed)
            self.assertEqual(view.get_takeoff("1").position, dirty_position)
            self.assertEqual(view._dirty_positions, {"1": dirty_position})
            self.assertEqual(emitted, [])
        finally:
            view.cleanup()


class TakeoffPlanViewBeginTextAnnotationEditTests(
    _TakeoffPlanViewOverlayRefreshFixture
):
    """TakeoffPlanView._begin_text_annotation_edit."""

    def test_inline_text_annotation_edit_commits_text_property(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(
            view,
            text="Before",
            position=[0.0, 0.0, 80.0, 24.0],
        )
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0], "a1")
        self.assertEqual(emitted[0][1], "text")
        self.assertEqual(emitted[0][2]["Text"], "Before")
        self.assertEqual(emitted[0][3]["Text"], "After")
        view.cleanup()

    def test_inline_text_annotation_commit_clears_text_cursor_selection(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(
            view,
            text="Before",
            position=[0.0, 0.0, 80.0, 24.0],
        )
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        self._select_document_text(item)
        self.assertTrue(item.textCursor().hasSelection())
        view._finish_text_annotation_edit(commit=True)
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_text_annotation_toolbar_hides_when_inline_edit_commits(self):
        view = self._make_plan_view()
        _annotation, _item = self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view._finish_text_annotation_edit(commit=True)
        self.assertIsNone(view._selected_text_item)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_text_annotation_toolbar_action_ignores_stale_target_after_edit(self):
        view = self._make_plan_view()
        annotation, _item = self._add_text_annotation(
            view,
            text="Before",
        )
        emitted = []
        view.annotation_text_properties_flushed.connect(emitted.extend)
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        view._finish_text_annotation_edit(commit=True)
        emitted.clear()
        size_index = view._condition_text_size_combo.findData(24)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        view._condition_text_bold_btn.setChecked(True)
        view._set_condition_text_alignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.assertEqual(annotation.properties["FontSize"], 12)
        self.assertFalse(annotation.properties["FontBold"])
        self.assertEqual(annotation.properties["TextAlign"], 0)
        self.assertEqual(emitted, [])
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_reenter_inline_text_annotation_edit_has_no_stale_text_selection(self):
        view = self._make_plan_view()
        _annotation, item = self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self._select_document_text(item)
        view._finish_text_annotation_edit(commit=True)
        self.assertFalse(item.textCursor().hasSelection())
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_inline_text_annotation_edit_immediately_uses_ibeam_cursor(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 80.0, 40.0))
        item.setData(0, "a1")
        item.setPos(60.0, 80.0)
        item.setTextWidth(80.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view._last_mouse_vp_pos = view.mapFromScene(QtCore.QPointF(70.0, 90.0))
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertEqual(
            view.viewport().cursor().shape(),
            QtCore.Qt.CursorShape.IBeamCursor,
        )
        view.cleanup()

    def test_text_toolbar_focus_does_not_exit_inline_text_edit(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        edit_active_states = []
        view.text_annotation_edit_mode_changed.connect(edit_active_states.append)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        view._condition_text_size_combo.setFocus()
        QApplication.processEvents()
        view._on_scene_focus_item_changed(
            None, item, QtCore.Qt.FocusReason.MouseFocusReason
        )
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertFalse(view._condition_text_toolbar.isHidden())
        self.assertEqual(edit_active_states, [True])
        view.cleanup()

    def test_annotation_font_size_toolbar_uses_model_size_once(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={
                "Text": "Before",
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": 12,
            },
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setFont(QFont("Arial", 36))
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertEqual(view._condition_text_size_combo.currentData(), 12)
        self.assertEqual(emitted, [])
        size_index = view._condition_text_size_combo.findData(18)
        self.assertGreaterEqual(size_index, 0)
        view._condition_text_size_combo.setCurrentIndex(size_index)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[-1][3]["FontSize"], 18)
        view._condition_text_size_combo.setFocus()
        QApplication.processEvents()
        view._on_scene_focus_item_changed(
            None, item, QtCore.Qt.FocusReason.MouseFocusReason
        )
        view._condition_text_bold_btn.setChecked(True)
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertEqual(annotation.properties["FontSize"], 18)
        self.assertEqual(item.font().pointSize(), 54)
        self.assertTrue(annotation.properties["FontBold"])
        self.assertEqual(len(emitted), 2)
        self.assertEqual(emitted[-1][3]["FontBold"], True)
        view.cleanup()

    def test_text_annotation_text_edit_preserves_box_and_wrapping(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 45.0, 18.0],
            properties={"Text": "Short", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Short")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        emitted_text, emitted_positions = self._capture_annotation_flushes(view)
        old_position = list(annotation.position)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("A much longer annotation that should wrap inside the box")
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(item.textWidth(), old_position[2])
        self.assertEqual(
            annotation.properties["Text"],
            "A much longer annotation that should wrap inside the box",
        )
        self.assertEqual(emitted_positions, [])
        self.assertEqual(emitted_text[-1][2]["Text"], "Short")
        self.assertEqual(
            emitted_text[-1][3]["Text"],
            "A much longer annotation that should wrap inside the box",
        )
        outline = self._first_selection_outline(view).polygon().boundingRect()
        self.assertEqual(outline.center(), QtCore.QPointF(100.0, 100.0))
        self.assertEqual(outline.width(), old_position[2])
        self.assertEqual(outline.height(), old_position[3])
        self.assertLess(item.boundingRect().width(), 100.0)
        view.cleanup()

    def test_inline_text_shortcut_handler_selects_text_not_scene_items(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertTrue(view.handle_inline_text_shortcut("select_all"))
        self.assertEqual(item.textCursor().selectedText(), "Before")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_cancel_inline_text_annotation_edit_restores_original_text(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 24.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setTextWidth(80.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        old_position = list(annotation.position)
        old_text_width = item.textWidth()
        emitted = []
        view.annotation_text_properties_flushed.connect(
            lambda changes: emitted.extend(changes)
        )
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        view._finish_text_annotation_edit(commit=False)
        self.assertEqual(item.toPlainText(), "Before")
        self.assertEqual(annotation.properties["Text"], "Before")
        self.assertEqual(annotation.position, old_position)
        self.assertEqual(item.textWidth(), old_text_width)
        self.assertEqual(emitted, [])
        view.cleanup()

    def test_direct_cancel_inline_text_annotation_clears_text_cursor_selection(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        self._select_document_text(item)
        view._finish_text_annotation_edit(commit=False)
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(item.toPlainText(), "Before")
        self.assertEqual(annotation.properties["Text"], "Before")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_disabling_inline_text_edit_cancels_uncommitted_changes(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(view, text="Before")
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        view.set_text_annotation_inline_edit_enabled(False)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        self.assertEqual(item.toPlainText(), "Before")
        self.assertEqual(annotation.properties["Text"], "Before")
        view.cleanup()


class TakeoffPlanViewBeginTextAnnotationDraftTests(
    _TakeoffPlanViewOverlayRefreshFixture
):
    """TakeoffPlanView.begin_text_annotation_draft."""

    def test_text_annotation_draft_enters_inline_edit_without_flushing(self):
        view = self._make_plan_view()
        view._selection_enabled = True
        emitted = []
        flushed = []
        view.text_annotation_created.connect(
            lambda position, page_uid, properties: emitted.append(
                (list(position), page_uid, dict(properties))
            )
        )
        view.annotation_text_properties_flushed.connect(
            lambda changes: flushed.extend(changes)
        )
        self.assertTrue(
            view.begin_text_annotation_draft([100.0, 100.0, 80.0, 24.0], "page-1")
        )
        uid = view._draft_text_annotation_uid
        self.assertIsNotNone(uid)
        item = view._text_annotation_item(uid)
        self.assertIsInstance(item, ClippedTextGraphicsItem)
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertEqual(
            item.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.TextEditorInteraction,
        )
        self.assertEqual(item.toPlainText(), "")
        self.assertEqual(emitted, [])
        self.assertEqual(flushed, [])
        view.cleanup()

    def test_empty_text_annotation_draft_commit_keeps_editor_active(self):
        view = self._make_plan_view()
        view._selection_enabled = True
        emitted = []
        view.text_annotation_created.connect(
            lambda position, page_uid, properties: emitted.append(
                (list(position), page_uid, dict(properties))
            )
        )
        self.assertTrue(
            view.begin_text_annotation_draft([100.0, 100.0, 80.0, 24.0], "page-1")
        )
        uid = view._draft_text_annotation_uid
        item = view._text_annotation_item(uid)
        item.setPlainText("   ")
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(emitted, [])
        self.assertEqual(view._draft_text_annotation_uid, uid)
        self.assertIn(uid, view._current_annotations)
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertEqual(
            item.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.TextEditorInteraction,
        )
        view._finish_text_annotation_edit(commit=False)
        self.assertIsNone(view._draft_text_annotation_uid)
        self.assertNotIn(uid, view._current_annotations)
        self.assertIsNone(view._text_annotation_item(uid))
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        view.cleanup()

    def test_non_empty_text_annotation_draft_commit_emits_create_once(self):
        view = self._make_plan_view()
        view._selection_enabled = True
        emitted = []
        view.text_annotation_created.connect(
            lambda position, page_uid, properties: emitted.append(
                (list(position), page_uid, dict(properties))
            )
        )
        self.assertTrue(
            view.begin_text_annotation_draft([100.0, 100.0, 80.0, 24.0], "page-1")
        )
        uid = view._draft_text_annotation_uid
        item = view._text_annotation_item(uid)
        item.setPlainText("Hello")
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(len(emitted), 1)
        position, page_uid, properties = emitted[0]
        self.assertEqual(position, [100.0, 100.0, 80.0, 24.0])
        self.assertEqual(page_uid, "page-1")
        self.assertEqual(properties["Text"], "Hello")
        self.assertIsNone(view._draft_text_annotation_uid)
        self.assertNotIn(uid, view._current_annotations)
        self.assertIsNone(view._text_annotation_item(uid))
        view.cleanup()


class TakeoffPlanViewRefreshCurrentPageOverlaysTests(
    _TakeoffPlanViewOverlayRefreshFixture
):
    """TakeoffPlanView.refresh_current_page_overlays."""

    def test_takeoff_insert_appends_new_primary_without_full_overlay_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        view._refresh_overlays = lambda *_args: self.fail(
            "primary insert should append without full refresh"
        )
        incoming = [
            view._current_takeoffs["1"],
            Takeoff(
                uid="2",
                condition_uid="c1",
                page_uid=page.uid,
                position=[3.0, 4.0],
            ),
        ]
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=incoming,
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_takeoff_uids=["2"],
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [["2"]])
        self.assertIn("2", view._current_takeoffs)
        self.assertIn("2", view._uid_to_items)
        self.assertEqual(calls, ["sync", "scene_rect", "viewport.update"])

    def test_pending_takeoff_insert_refreshes_the_active_plan(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        pending_uid = "pending:takeoff-placement:operation-1:0"
        incoming = [
            view._current_takeoffs["1"],
            Takeoff(
                uid=pending_uid,
                condition_uid="c1",
                page_uid=page.uid,
                position=[3.0, 4.0],
            ),
        ]
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=incoming,
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_takeoff_uids=[pending_uid],
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [[pending_uid]])
        self.assertIn(pending_uid, view._current_takeoffs)
        self.assertIn(pending_uid, view._uid_to_items)
        view.set_pending_mutation_uids({pending_uid})
        self.assertFalse(view._is_selectable(pending_uid))
        self.assertEqual(view._uid_to_items[pending_uid][0].opacity(), 0.35)
        self.assertEqual(calls, ["sync", "scene_rect", "viewport.update"])

    def test_committed_takeoff_replaces_pending_identity_without_full_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        pending_uid = "pending:takeoff-placement:operation-1:0"
        pending = Takeoff(
            uid=pending_uid,
            condition_uid="c1",
            page_uid=page.uid,
            position=[3.0, 4.0],
        )
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=[view._current_takeoffs["1"], pending],
                conditions=view._current_conditions,
                color_map=view._current_color_map,
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
                hidden_layer_uids=set(),
                changed_takeoff_uids=[pending_uid],
            )
        )
        calls.clear()
        renderer.calls.clear()
        view._refresh_overlays = lambda *_args: self.fail(
            "authoritative identity replacement should be targeted"
        )
        committed = replace(pending, uid="501")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"], committed],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_takeoff_uids=[pending_uid, "501"],
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [["501"]])
        self.assertNotIn(pending_uid, view._current_takeoffs)
        self.assertNotIn(pending_uid, view._uid_to_items)
        self.assertIn("501", view._current_takeoffs)
        self.assertIn("501", view._uid_to_items)
        self.assertEqual(calls, ["sync", "scene_rect", "viewport.update"])

    def test_takeoff_insert_reorders_existing_overlay_z_values(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, _calls = self._make_incremental_refresh_view(renderer)
        existing = replace(view._current_takeoffs["1"], uid="2")
        view._current_takeoffs = {"2": existing}
        existing_item = QGraphicsPathItem()
        view._scene.addItem(existing_item)
        view._uid_to_items = {"2": [existing_item]}
        view._takeoff_items = [existing_item]
        inserted = replace(existing, uid="1")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[inserted, existing],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_takeoff_uids=["1"],
        )
        self.assertTrue(refreshed)
        inserted_item = view._uid_to_items["1"][0]
        self.assertGreater(existing_item.zValue(), inserted_item.zValue())

    def test_takeoff_update_replaces_only_changed_primary_overlay(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        old_item = QGraphicsPathItem()
        view._scene.addItem(old_item)
        view._uid_to_items["1"] = [old_item]
        view._takeoff_items = [old_item]
        old_items = [old_item]
        view._refresh_overlays = lambda *_args: self.fail(
            "primary update should not rebuild every overlay"
        )
        updated = Takeoff(
            uid="1",
            condition_uid="c1",
            page_uid=page.uid,
            position=[9.0, 10.0],
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[updated],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_takeoff_uids=["1"],
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [["1"]])
        self.assertEqual(view._current_takeoffs["1"], updated)
        self.assertTrue(all(item.scene() is None for item in old_items))
        self.assertEqual(calls, ["sync", "scene_rect", "viewport.update"])

    def test_takeoff_parent_with_hole_refreshes_only_dependency_graph(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        parent = replace(
            view._current_takeoffs["1"],
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        hole = Takeoff(
            uid="2",
            condition_uid="c1",
            page_uid=page.uid,
            parent_uid="1",
            position=[5.0, 5.0, 10.0, 5.0, 10.0, 10.0, 5.0, 10.0],
        )
        view._current_takeoffs = {"1": parent, "2": hole}
        updated_parent = replace(parent, position=[1.0, 0.0, 21.0, 0.0, 21.0, 20.0])
        view._refresh_overlays = lambda *_args: self.fail(
            "parent and hole graph should refresh without rebuilding all overlays"
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[updated_parent, hole],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_takeoff_uids=["1"],
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [["1", "2"]])
        self.assertEqual(calls, ["sync", "scene_rect", "viewport.update"])

    def test_takeoff_delete_removes_only_changed_primary_overlay(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        old_item = QGraphicsPathItem()
        view._scene.addItem(old_item)
        view._uid_to_items["1"] = [old_item]
        view._takeoff_items = [old_item]
        old_items = [old_item]
        view._selected_uids = {"1"}
        view._refresh_overlays = lambda *_args: self.fail(
            "primary delete should not rebuild every overlay"
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_takeoff_uids=["1"],
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [])
        self.assertNotIn("1", view._current_takeoffs)
        self.assertNotIn("1", view._uid_to_items)
        self.assertEqual(view._selected_uids, set())
        self.assertTrue(all(item.scene() is None for item in old_items))
        self.assertEqual(calls, ["selection", "sync", "scene_rect", "viewport.update"])

    def test_metadata_less_same_page_unchanged_state_skips_full_overlay_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        view._refresh_overlays = lambda *_args: self.fail(
            "unchanged metadata-less refresh should be a no-op"
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [])
        self.assertEqual(calls, [])

    def test_metadata_less_same_page_changed_takeoffs_uses_full_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[
                view._current_takeoffs["1"],
                Takeoff(
                    uid="2",
                    condition_uid="c1",
                    page_uid=page.uid,
                    position=[3.0, 4.0],
                ),
            ],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
        )
        self.assertTrue(refreshed)
        self.assertIn("refresh_overlays", calls)

    def test_metadata_less_same_page_changed_annotations_uses_full_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        self._install_annotation_item(view, self._text_annotation(text="old"))
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[self._text_annotation(text="new")],
            page_area_selections={},
            hidden_layer_uids=set(),
        )
        self.assertTrue(refreshed)
        self.assertIn("refresh_overlays", calls)

    def test_metadata_less_same_page_hidden_layer_change_uses_full_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        view._hidden_layer_uids = {"hidden-layer"}
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
        )
        self.assertTrue(refreshed)
        self.assertIn("refresh_overlays", calls)

    def test_native_scene_generic_refresh_after_fast_append_is_noop(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        view._refresh_overlays = lambda *_args: self.fail(
            "native-scene generic refresh should not rebuild unchanged overlays"
        )
        incoming = [
            view._current_takeoffs["1"],
            Takeoff(
                uid="2",
                condition_uid="c1",
                page_uid=page.uid,
                position=[3.0, 4.0],
            ),
        ]
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=incoming,
                conditions=view._current_conditions,
                color_map=view._current_color_map,
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
                hidden_layer_uids=set(),
                changed_takeoff_uids=["2"],
            )
        )
        self.assertEqual(renderer.calls, [["2"]])
        calls.clear()
        renderer.calls.clear()
        self.assertTrue(
            view.refresh_current_page_overlays(
                page=page,
                takeoffs=incoming,
                conditions=view._current_conditions,
                color_map=view._current_color_map,
                bid_ref=bid_ref,
                annotations=[],
                page_area_selections={},
                hidden_layer_uids=set(),
            )
        )
        self.assertEqual(renderer.calls, [])
        self.assertEqual(calls, [])

    def test_hole_insert_refreshes_only_parent_dependency_graph(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        view._refresh_overlays = lambda *_args: self.fail(
            "hole insertion should refresh its dependency graph directly"
        )
        incoming = [
            view._current_takeoffs["1"],
            Takeoff(
                uid="2",
                condition_uid="c1",
                page_uid=page.uid,
                position=[3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
                parent_uid="1",
            ),
        ]
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=incoming,
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_takeoff_uids=["2"],
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [["1", "2"]])
        self.assertNotIn("refresh_overlays", calls)

    def test_annotation_insert_refreshes_only_annotation_graphics(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        view._refresh_overlays = lambda *_args: self.fail(
            "safe annotation insert should not rebuild all overlays"
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[self._text_annotation(text="new")],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["ann-1"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [])
        self.assertIn("ann-1", view._current_annotations)
        self.assertIn("ann-1", view._uid_to_items)
        self.assertNotIn("refresh_overlays", calls)
        self.assertIn("sync", calls)
        self.assertIn("scene_rect", calls)
        self.assertIn("viewport.update", calls)

    def test_named_view_insert_refreshes_visible_selectable_overlay(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        view._refresh_overlays = lambda *_args: self.fail(
            "named view insert should refresh annotation graphics directly"
        )
        named_view = self._named_view_annotation()
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[named_view],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["view-1"],
            changed_annotation_types=[ANNOTATION_TYPE_NAMED_VIEW],
        )
        self.assertTrue(refreshed)
        self.assertIn("view-1", view._current_annotations)
        self.assertIn("view-1", view._uid_to_items)
        self.assertEqual(len(view._uid_to_items["view-1"]), 3)
        self.assertTrue(
            all(item.scene() is view._scene for item in view._uid_to_items["view-1"])
        )
        self.assertNotIn("refresh_overlays", calls)
        self.assertIn("sync", calls)
        self.assertIn("scene_rect", calls)
        self.assertIn("viewport.update", calls)

    def test_annotation_update_replaces_only_changed_annotation_item(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        old_item = self._install_annotation_item(
            view, self._text_annotation(text="old")
        )
        view._selected_uids = {"ann-1"}
        view._refresh_overlays = lambda *_args: self.fail(
            "safe annotation update should not rebuild all overlays"
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[self._text_annotation(text="new")],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["ann-1"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertTrue(refreshed)
        self.assertIsNone(old_item.scene())
        self.assertEqual(renderer.calls, [])
        self.assertEqual(view._selected_uids, {"ann-1"})
        self.assertIn("selection", calls)
        (new_item,) = view._uid_to_items["ann-1"]
        self.assertIsNot(new_item, old_item)
        self.assertIs(new_item.scene(), view._scene)
        self.assertEqual(new_item.toPlainText(), "new")
        self.assertEqual(view._current_annotations["ann-1"].properties["Text"], "new")

    def test_annotation_delete_removes_only_annotation_item_and_selection(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        old_item = self._install_annotation_item(
            view, self._text_annotation(text="old")
        )
        view._selected_uids = {"ann-1"}
        view._refresh_overlays = lambda *_args: self.fail(
            "safe annotation delete should not rebuild all overlays"
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["ann-1"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertTrue(refreshed)
        self.assertIsNone(old_item.scene())
        self.assertEqual(renderer.calls, [])
        self.assertNotIn("ann-1", view._current_annotations)
        self.assertNotIn("ann-1", view._uid_to_items)
        self.assertEqual(view._selected_uids, set())
        self.assertIn("selection", calls)

    def test_hotlink_annotation_update_replaces_hotlink_target(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, _calls = self._make_incremental_refresh_view(renderer)
        old_item = self._install_annotation_item(
            view, self._hotlink_annotation(), hotlink=True
        )
        old_hotlink_item = view._hotlink_items[0][0]
        view._refresh_overlays = lambda *_args: self.fail(
            "safe hotlink update should not rebuild all overlays"
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[self._hotlink_annotation()],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["hot-1"],
            changed_annotation_types=[ANNOTATION_TYPE_HOTLINK],
        )
        self.assertTrue(refreshed)
        self.assertIsNone(old_item.scene())
        self.assertEqual(renderer.calls, [])
        self.assertEqual(len(view._hotlink_items), 1)
        self.assertIsNot(view._hotlink_items[0][0], old_hotlink_item)
        self.assertEqual(view._hotlink_items[0][1].uid, "hot-1")

    def test_annotation_change_without_aligned_metadata_uses_full_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[self._text_annotation(text="new")],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["ann-1"],
            changed_annotation_types=[],
        )
        self.assertTrue(refreshed)
        self.assertEqual(renderer.calls, [])
        self.assertIn("refresh_overlays", calls)

    def test_annotation_change_with_hidden_layer_mismatch_uses_full_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        old_item = self._install_annotation_item(
            view, self._text_annotation(text="old")
        )
        view._hidden_layer_uids = {"notes-layer"}
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[self._text_annotation(text="new")],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["ann-1"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertTrue(refreshed)
        self.assertIs(old_item.scene(), view._scene)
        self.assertEqual(renderer.calls, [])
        self.assertIn("refresh_overlays", calls)

    def test_duplicate_same_page_annotation_identity_uses_full_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        first_item = self._install_annotation_item(
            view, self._text_annotation(uid="dup", text="first")
        )
        second_item = self._install_annotation_item(
            view,
            self._text_annotation(uid="dup", text="second"),
            key="dup_text",
        )
        view._ann_db_uid_map["dup_text"] = "dup"
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[self._text_annotation(uid="dup", text="new")],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["dup"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertTrue(refreshed)
        self.assertIs(first_item.scene(), view._scene)
        self.assertIs(second_item.scene(), view._scene)
        self.assertEqual(renderer.calls, [])
        self.assertIn("refresh_overlays", calls)

    def test_same_annotation_uid_with_different_types_can_refresh_targeted_item(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        text_item = self._install_annotation_item(
            view, self._text_annotation(uid="shared", text="old")
        )
        hotlink = self._hotlink_annotation(uid="shared")
        hotlink_item = self._install_annotation_item(
            view,
            hotlink,
            key="shared_hotlink",
            hotlink=True,
        )
        view._ann_db_uid_map["shared_hotlink"] = "shared"
        view._refresh_overlays = lambda *_args: self.fail(
            "same UID with different annotation types should not force full refresh"
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[
                self._text_annotation(uid="shared", text="new"),
                hotlink,
            ],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["shared"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertTrue(refreshed)
        self.assertIsNone(text_item.scene())
        self.assertIs(hotlink_item.scene(), view._scene)
        self.assertEqual(renderer.calls, [])
        self.assertNotIn("refresh_overlays", calls)
        self.assertEqual(view._current_annotations["shared"].properties["Text"], "new")
        self.assertEqual(
            view._current_annotations["shared_hotlink"].annotation_type,
            ANNOTATION_TYPE_HOTLINK,
        )
        self.assertEqual(view._uid_to_items["shared_hotlink"], [hotlink_item])

    def test_full_refresh_keeps_annotation_selected_when_takeoff_claims_raw_uid(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, _calls = self._make_incremental_refresh_view(renderer)
        annotation = self._text_annotation(uid="2")
        self._install_annotation_item(view, annotation)
        view._selected_uids = {"2"}
        view._clear_text_selection = lambda: None
        view._remove_text_annotation_draft = lambda: None
        view._remove_named_view_draft = lambda: None
        view.clear_selection_items = lambda: view._selection_items.clear()
        view._remove_rotate_handle = lambda: None
        view._apply_page_transform_to_items = lambda: None
        view._cancel_backout_if_invalid = lambda: None
        view._cursor_mode = "select"
        takeoffs = [
            view._current_takeoffs["1"],
            Takeoff(
                uid="2",
                condition_uid="c1",
                page_uid=page.uid,
                position=[3.0, 4.0],
            ),
        ]
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=takeoffs,
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[annotation],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_takeoff_uids=["2"],
        )
        annotation_keys = view.find_annotation_keys_by_uid_type(
            {("2", ANNOTATION_TYPE_TEXT)}
        )
        self.assertTrue(refreshed)
        self.assertEqual(len(annotation_keys), 1)
        self.assertEqual(view._selected_uids, annotation_keys)
        self.assertNotEqual(view._selected_uids, {"2"})

    def test_full_refresh_keeps_surviving_same_uid_annotation_selected(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, _calls = self._make_incremental_refresh_view(renderer)
        text = self._text_annotation(uid="shared")
        hotlink = self._hotlink_annotation(uid="shared")
        self._install_annotation_item(view, text)
        self._install_annotation_item(
            view,
            hotlink,
            key="shared_hotlink",
            hotlink=True,
        )
        view._ann_db_uid_map["shared_hotlink"] = "shared"
        view._selected_uids = {"shared_hotlink"}
        view._clear_text_selection = lambda: None
        view._remove_text_annotation_draft = lambda: None
        view._remove_named_view_draft = lambda: None
        view.clear_selection_items = lambda: view._selection_items.clear()
        view._remove_rotate_handle = lambda: None
        view._apply_page_transform_to_items = lambda: None
        view._cancel_backout_if_invalid = lambda: None
        view._cursor_mode = "select"
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[hotlink],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["shared"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        annotation_keys = view.find_annotation_keys_by_uid_type(
            {("shared", ANNOTATION_TYPE_HOTLINK)}
        )
        self.assertTrue(refreshed)
        self.assertEqual(view._selected_uids, annotation_keys)
        self.assertEqual(annotation_keys, {"shared"})

    def test_multi_page_annotation_metadata_uses_full_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        old_item = self._install_annotation_item(
            view, self._text_annotation(text="old")
        )
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[self._text_annotation(text="new")],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["ann-1", "off-page-ann"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT, ANNOTATION_TYPE_TEXT],
        )
        self.assertTrue(refreshed)
        self.assertIs(old_item.scene(), view._scene)
        self.assertEqual(renderer.calls, [])
        self.assertIn("refresh_overlays", calls)

    def test_unreported_same_page_annotation_change_uses_full_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, calls = self._make_incremental_refresh_view(renderer)
        first_item = self._install_annotation_item(
            view, self._text_annotation(uid="ann-1", text="old-1")
        )
        second_item = self._install_annotation_item(
            view, self._text_annotation(uid="ann-2", text="old-2")
        )
        view._refresh_overlays = lambda *_args: calls.append("refresh_overlays")
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[
                self._text_annotation(uid="ann-1", text="new-1"),
                self._text_annotation(uid="ann-2", text="new-2"),
            ],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["ann-1"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertTrue(refreshed)
        self.assertIs(first_item.scene(), view._scene)
        self.assertIs(second_item.scene(), view._scene)
        self.assertEqual(renderer.calls, [])
        self.assertIn("refresh_overlays", calls)

    def test_annotation_change_with_render_identity_mismatch_rejects_refresh(self):
        renderer = RecordingPathTakeoffRenderer()
        view, page, bid_ref, _calls = self._make_incremental_refresh_view(renderer)
        page.rotation = 90
        view._refresh_overlays = lambda *_args: self.fail(
            "render identity mismatch should not refresh overlays"
        )
        refreshed = view.refresh_current_page_overlays(
            page=page,
            takeoffs=[view._current_takeoffs["1"]],
            conditions=view._current_conditions,
            color_map=view._current_color_map,
            bid_ref=bid_ref,
            annotations=[self._text_annotation(text="new")],
            page_area_selections={},
            hidden_layer_uids=set(),
            changed_annotation_uids=["ann-1"],
            changed_annotation_types=[ANNOTATION_TYPE_TEXT],
        )
        self.assertFalse(refreshed)


class ViewPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_roping_preference_changes_selection_mode(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view.set_roping_selection_method("inclusive")
        self.assertEqual(
            view._roping_item_selection_mode(),
            QtCore.Qt.ItemSelectionMode.ContainsItemShape,
        )
        view.set_roping_selection_method("touching")
        self.assertEqual(
            view._roping_item_selection_mode(),
            QtCore.Qt.ItemSelectionMode.IntersectsItemShape,
        )

    def test_unknown_roping_preference_falls_back_to_touching(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view.set_roping_selection_method("inclusive")
        view.set_roping_selection_method("bogus")
        self.assertEqual(
            view._roping_item_selection_mode(),
            QtCore.Qt.ItemSelectionMode.IntersectsItemShape,
        )

    def test_crosshair_preference_updates_plan_view_overlay_state(self):
        view, viewport = _preferences_support__plan_view_with_tracking_viewport()
        TakeoffPlanView.set_full_window_crosshairs(view, True, "#123456", 4)
        self.assertTrue(view._use_full_window_crosshairs)
        self.assertEqual(view._crosshair_color, "#123456")
        self.assertEqual(view._crosshair_line_thickness, 4)
        self.assertEqual(viewport.tracking, [True])
        self.assertEqual(viewport.updates, 1)
        TakeoffPlanView.set_full_window_crosshairs(view, False, "#654321", 2)
        self.assertFalse(view._use_full_window_crosshairs)
        self.assertEqual(viewport.tracking, [True, True])
        self.assertEqual(viewport.updates, 2)

    def test_crosshair_disabled_keeps_mouse_tracking_on_during_placement(self):
        view, viewport = _preferences_support__plan_view_with_tracking_viewport("place")
        TakeoffPlanView.set_full_window_crosshairs(view, False, "#123456", 4)
        self.assertFalse(view._use_full_window_crosshairs)
        self.assertEqual(viewport.tracking, [True])
        self.assertEqual(viewport.updates, 1)

    def test_crosshair_preference_controls_mouse_tracking_outside_passive_modes(self):
        view, viewport = _preferences_support__plan_view_with_tracking_viewport("pan")
        TakeoffPlanView.set_full_window_crosshairs(view, True, "#123456", 4)
        TakeoffPlanView.set_full_window_crosshairs(view, False, "#123456", 4)
        self.assertEqual(viewport.tracking, [True, False])
        self.assertEqual(viewport.updates, 2)

    def test_cursor_mode_changes_refresh_preview_mouse_tracking(self):
        view, viewport = _preferences_support__plan_view_with_tracking_viewport()
        TakeoffPlanView._apply_cursor_mode(view, "place")
        TakeoffPlanView._apply_cursor_mode(view, "paste_backout")
        TakeoffPlanView._apply_cursor_mode(view, "rotate")
        TakeoffPlanView._apply_cursor_mode(view, "select")
        self.assertEqual(viewport.tracking, [True, True, True, True])
        self.assertEqual(viewport.updates, 4)

    def test_begin_paste_backout_requires_host_area(self):
        class FakeSignal:
            def __init__(self):
                self.emitted = []

            def emit(self, value):
                self.emitted.append(value)

        class FakePasteBackoutView:
            def __init__(self):
                self._editing_enabled = True
                self._current_conditions = {
                    "area-condition": Condition(
                        uid="area-condition",
                        condition_type=Condition.TYPE_AREA,
                    )
                }
                self._current_takeoffs = {}
                self._paste_backout_active = False
                self._paste_backout_sources = []
                self._paste_backout_source_bid_uid = None
                self._paste_backout_group_centroid = (0.0, 0.0)
                self._last_mouse_vp_pos = None
                self.cursor_mode_change_requested = FakeSignal()
                self.finished_intelligent_paste = 0
                self.cursor_modes = []

            def finish_intelligent_paste_placement(self):
                self.finished_intelligent_paste += 1

            def cancel_overlay_move_mode(self, restore_preview=True):
                pass

            def _remove_rotate_handle(self):
                pass

            def _exit_place_mode(self):
                pass

            def _exit_annotation_place_mode(self):
                pass

            def _clear_backout_state(self):
                pass

            def _apply_cursor_mode(self, mode):
                self.cursor_modes.append(mode)

        view = FakePasteBackoutView()
        hole = Takeoff(
            uid="hole",
            condition_uid="area-condition",
            position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
            parent_uid="source-parent",
        )
        self.assertFalse(TakeoffPlanView.begin_paste_backout(view, [hole], {}, "7"))
        self.assertFalse(view._paste_backout_active)
        self.assertEqual(view.cursor_modes, [])
        self.assertEqual(view.finished_intelligent_paste, 0)
        view._current_takeoffs["host"] = Takeoff(
            uid="host",
            condition_uid="area-condition",
            position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0],
            parent_uid="0",
        )
        self.assertTrue(TakeoffPlanView.begin_paste_backout(view, [hole], {}, "7"))
        self.assertTrue(view._paste_backout_active)
        self.assertEqual(view.finished_intelligent_paste, 1)
        self.assertEqual(view.cursor_modes, ["paste_backout"])
        self.assertEqual(view.cursor_mode_change_requested.emitted, ["paste_backout"])

    def test_finalized_page_load_requests_current_high_resolution_tiles(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._load_geometry_ready = True
        view._load_view_applied = False
        view._load_user_view_changed = False
        view._load_waiting_for_visibility = True
        view._saved_scroll_state = object()
        view.isVisible = lambda: True
        view._apply_current_view_contract = lambda consume_scroll_state: calls.append(
            ("view", consume_scroll_state)
        )
        view._uses_dynamic_tile_coverage = lambda: True
        view.transform = lambda: SimpleNamespace(m11=lambda: 3.5)
        view._update_tile_coverage = lambda scale: calls.append(("tiles", scale))
        view.page_fully_loaded = SimpleNamespace(emit=lambda: calls.append(("loaded",)))
        self.assertTrue(view._finalize_page_load_if_ready())
        self.assertTrue(view._load_view_applied)
        self.assertFalse(view._load_waiting_for_visibility)
        self.assertIsNone(view._saved_scroll_state)
        self.assertEqual(
            calls,
            [("view", True), ("tiles", 3.5), ("loaded",)],
        )
        # A second finalize must not re-apply the view or re-emit the signal.
        self.assertFalse(view._finalize_page_load_if_ready())
        self.assertEqual(len(calls), 3)

    def test_finalized_page_load_preserves_user_changed_loading_zoom(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._load_geometry_ready = True
        view._load_view_applied = False
        view._load_user_view_changed = True
        view._load_waiting_for_visibility = True
        view._saved_scroll_state = object()
        view.isVisible = lambda: True
        view._apply_current_view_contract = lambda consume_scroll_state: calls.append(
            ("view", consume_scroll_state)
        )
        view._uses_dynamic_tile_coverage = lambda: False
        view.page_fully_loaded = SimpleNamespace(emit=lambda: calls.append(("loaded",)))
        self.assertTrue(view._finalize_page_load_if_ready())
        self.assertTrue(view._load_view_applied)
        self.assertIsNone(view._saved_scroll_state)
        self.assertEqual(calls, [("loaded",)])

    def test_high_resolution_preference_change_refreshes_current_page_immediately(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = object()
        view._loaded_visual_kind = None
        view._disable_high_resolution_images = False
        view._can_zoom_rerender = True
        view._is_composite_mode = False
        view._background_item = object()
        view._base_raster_scale = INTERACTIVE_PDF_RENDER_SCALE - 1.0
        view._scene_scale = 2.0
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._advance_render_generation = lambda: 7
        view._request_optional_base_correction = lambda scale, generation: calls.append(
            ("base", scale, generation)
        )
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(True)
        self.assertEqual(
            calls,
            [
                "clear",
                "cancel",
                ("base", INTERACTIVE_PDF_RENDER_SCALE, 7),
                "viewport",
            ],
        )

    def test_high_resolution_preference_unchanged_value_does_not_refresh(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = object()
        view._disable_high_resolution_images = True
        view._clear_tiles = lambda: calls.append("clear")
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(True)
        self.assertEqual(calls, [])

    def test_page_view_state_uses_ost_page_pixel_coordinates(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene_scale = 3.0
        view._pdf_width_pts = 0.0
        view._pdf_height_pts = 0.0
        view._current_rotation = 0
        view._current_page = Page(
            uid="6420",
            name="S3.0.pdf",
            width_pts=42.0 * 72.0,
            height_pts=30.0 * 72.0,
        )
        current_x, current_y = view._scene_center_to_persisted_coords(
            QtCore.QPointF(1512.0, 1080.0)
        )
        restored = view._persisted_coords_to_scene_center(current_x, current_y)
        self.assertAlmostEqual(current_x, 672.0)
        self.assertAlmostEqual(current_y, 480.0)
        self.assertAlmostEqual(restored.x(), 1512.0)
        self.assertAlmostEqual(restored.y(), 1080.0)

    def test_high_resolution_reenabled_requests_current_tile_coverage(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = object()
        view._disable_high_resolution_images = True
        view._can_zoom_rerender = True
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._update_tile_coverage = lambda scale: calls.append(("tiles", scale))
        view.transform = lambda: SimpleNamespace(m11=lambda: 4.0)
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(False)
        self.assertEqual(calls, ["clear", "cancel", ("tiles", 4.0), "viewport"])

    def test_high_resolution_refresh_on_blank_page_does_not_error(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = Page(uid="blank", name="Blank")
        view._loaded_visual_kind = None
        view._disable_high_resolution_images = False
        view._can_zoom_rerender = False
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(True)
        self.assertEqual(calls, ["clear", "cancel", "viewport"])

    def test_advanced_mouse_controls_preference_toggles_shortcuts(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        cursor_updates = []
        view._update_cursor = lambda: cursor_updates.append("cursor")
        view._ctrl_held = True
        view._zoom_press_ctrl = True
        view._advanced_mouse_controls_enabled = True
        self.assertTrue(view._advanced_mouse_controls_active())
        view.set_advanced_mouse_controls_enabled(False)
        self.assertFalse(view._advanced_mouse_controls_active())
        self.assertFalse(view._ctrl_held)
        self.assertFalse(view._zoom_press_ctrl)
        self.assertEqual(cursor_updates, ["cursor"])
        view.set_advanced_mouse_controls_enabled(True)
        self.assertTrue(view._advanced_mouse_controls_active())

    def test_auto_zoom_preference_applies_only_without_saved_page_zoom(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._default_auto_zoom_level = 125
        page = Page(uid="p1", name="A101")
        view._begin_load_cycle(page, preserve_current_view=False)
        self.assertEqual(view._load_initial_view_mode, "auto_zoom")
        page.zoom_fac = 300.0
        view._begin_load_cycle(page, preserve_current_view=False)
        self.assertEqual(view._load_initial_view_mode, "restore")
        view._default_auto_zoom_level = 0
        page.zoom_fac = 0.0
        view._begin_load_cycle(page, preserve_current_view=False)
        self.assertEqual(view._load_initial_view_mode, "fit")

    def _make_intelligent_paste_snap_view(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._editing_enabled = True
        view._scene = QtWidgets.QGraphicsScene()
        view._scene_builder = SimpleNamespace(
            get_coordinate_system=lambda: SimpleNamespace(
                scale_ratio=72.0,
                view_scale=1.0,
            )
        )
        view._current_page_transform = lambda: None
        view._page_scene_rect = lambda: QtCore.QRectF(0.0, 0.0, 200.0, 200.0)
        view.mapFromScene = lambda point: QtCore.QPoint(
            int(round(point.x())),
            int(round(point.y())),
        )
        view._intelligent_paste_enabled = True
        view._intelligent_paste_pending_uids = []
        view._intelligent_paste_pending_source_anchor_ost = None
        view._intelligent_paste_active = True
        view._intelligent_paste_source_anchor_ost = (10.0, 20.0)
        view._intelligent_paste_anchor_start_ost = (50.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted": [50.0, 75.0, 54.0, 79.0]
        }
        view._intelligent_paste_guide_items = []
        view._current_takeoffs = {}
        view._current_conditions = {}
        view._current_annotations = {}
        view._snap_increments = 0.0
        return view

    def _guide_lines(self, view):
        return [item.line() for item in view._intelligent_paste_guide_items]

    def test_intelligent_paste_pending_state_does_not_start_drag_or_rubber_band(self):
        view = self._make_intelligent_paste_snap_view()
        view._intelligent_paste_active = False
        view._intelligent_paste_source_anchor_ost = None
        view._intelligent_paste_anchor_start_ost = None
        view._selected_uids = {"pasted"}
        view._select_band_origin = None
        view._select_band_dragged = False
        view._drag_multi_orig_positions = {}
        self.assertTrue(
            view.mark_intelligent_paste_drag_pending(["pasted"], (10.0, 20.0))
        )
        self.assertFalse(view._intelligent_paste_active)
        self.assertIsNone(view._select_band_origin)
        self.assertFalse(view._select_band_dragged)
        self.assertEqual(view._drag_multi_orig_positions, {})

    def test_intelligent_paste_pending_state_only_snaps_during_first_drag(self):
        view = self._make_intelligent_paste_snap_view()
        view._intelligent_paste_active = False
        view._intelligent_paste_source_anchor_ost = None
        view._intelligent_paste_anchor_start_ost = None
        view.mark_intelligent_paste_drag_pending(["pasted"], (10.0, 20.0))
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -50.0))
        self.assertEqual(view._intelligent_paste_guide_items, [])
        self.assertTrue(
            view.begin_intelligent_paste_drag_if_pending(
                {"pasted": [50.0, 75.0, 54.0, 79.0]}
            )
        )
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        view.finish_intelligent_paste_placement()
        self.assertEqual(view._intelligent_paste_pending_uids, [])
        self.assertFalse(view._intelligent_paste_active)

    def test_intelligent_paste_pending_state_clears_on_other_selection_drag(self):
        view = self._make_intelligent_paste_snap_view()
        view._intelligent_paste_active = False
        view.mark_intelligent_paste_drag_pending(["pasted"], (10.0, 20.0))
        self.assertFalse(
            view.begin_intelligent_paste_drag_if_pending(
                {"other": [50.0, 75.0, 54.0, 79.0]}
            )
        )
        self.assertEqual(view._intelligent_paste_pending_uids, [])
        self.assertFalse(view._intelligent_paste_active)

    def test_intelligent_paste_snaps_to_original_x_axis_and_shows_edge_guides(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 2)
        lines = self._guide_lines(view)
        self.assertTrue(all(line.y1() == line.y2() for line in lines))
        self.assertEqual([line.y1() for line in lines], [20.0, 24.0])
        pen = view._intelligent_paste_guide_items[0].pen()
        self.assertEqual(pen.style(), QtCore.Qt.PenStyle.DashLine)
        self.assertEqual(pen.color().name(), "#1f9d45")
        view.finish_intelligent_paste_placement()
        self.assertEqual(view._intelligent_paste_guide_items, [])

    def test_intelligent_paste_axis_snap_threshold_boundary(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -47.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 2)
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -46.0)
        self.assertEqual((dx, dy), (0.0, -46.0))
        self.assertEqual(view._intelligent_paste_guide_items, [])

    def test_intelligent_paste_snaps_to_original_y_axis_and_shows_edge_guides(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, 0.0)
        self.assertEqual((dx, dy), (-40.0, 0.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 2)
        lines = self._guide_lines(view)
        self.assertTrue(all(line.x1() == line.x2() for line in lines))
        self.assertEqual([line.x1() for line in lines], [10.0, 14.0])
        view.finish_intelligent_paste_placement()
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, 0.0)
        self.assertEqual((dx, dy), (-35.0, 0.0))
        self.assertEqual(view._intelligent_paste_guide_items, [])

    def test_intelligent_paste_snaps_to_both_axes_and_shows_four_edge_guides(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, -50.0)
        self.assertEqual((dx, dy), (-40.0, -55.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 4)
        lines = self._guide_lines(view)
        horizontal = [line for line in lines if line.y1() == line.y2()]
        vertical = [line for line in lines if line.x1() == line.x2()]
        self.assertEqual([line.y1() for line in horizontal], [20.0, 24.0])
        self.assertEqual([line.x1() for line in vertical], [10.0, 14.0])

    def test_intelligent_paste_multi_object_y_axis_guides_use_preview_union_bounds(
        self,
    ):
        view = self._make_intelligent_paste_snap_view()
        view._snap_increments = 10.0
        view._intelligent_paste_anchor_start_ost = (51.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted-a": [51.0, 75.0, 55.0, 79.0],
            "pasted-b": [85.0, 100.0, 89.0, 104.0],
        }
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, 0.0)
        self.assertEqual((dx, dy), (-41.0, 0.0))
        lines = self._guide_lines(view)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.x1() == line.x2() for line in lines))
        self.assertEqual([line.x1() for line in lines], [11.0, 49.0])

    def test_intelligent_paste_multi_object_x_axis_guides_use_preview_union_bounds(
        self,
    ):
        view = self._make_intelligent_paste_snap_view()
        view._snap_increments = 10.0
        view._intelligent_paste_anchor_start_ost = (51.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted-a": [51.0, 75.0, 55.0, 79.0],
            "pasted-b": [85.0, 100.0, 89.0, 104.0],
        }
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        lines = self._guide_lines(view)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.y1() == line.y2() for line in lines))
        self.assertEqual([line.y1() for line in lines], [15.0, 44.0])

    def test_intelligent_paste_multi_object_both_axis_guides_use_preview_union_bounds(
        self,
    ):
        view = self._make_intelligent_paste_snap_view()
        view._snap_increments = 10.0
        view._intelligent_paste_anchor_start_ost = (51.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted-a": [51.0, 75.0, 55.0, 79.0],
            "pasted-b": [85.0, 100.0, 89.0, 104.0],
        }
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, -50.0)
        self.assertEqual((dx, dy), (-41.0, -55.0))
        lines = self._guide_lines(view)
        self.assertEqual(len(lines), 4)
        horizontal = [line for line in lines if line.y1() == line.y2()]
        vertical = [line for line in lines if line.x1() == line.x2()]
        self.assertEqual([line.y1() for line in horizontal], [15.0, 44.0])
        self.assertEqual([line.x1() for line in vertical], [11.0, 49.0])


class PdfTextSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        # Start every test from an empty clipboard so copy assertions prove that
        # the view wrote the text, not that a previous test left it behind.
        QtWidgets.QApplication.clipboard().setText("")
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "")

    def _make_view(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene = QGraphicsScene()
        view._current_bid_ref = None
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="drawing.pdf",
            width_pts=200.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            page_index=0,
        )
        view._pdf_width_pts = 200.0
        view._pdf_height_pts = 100.0
        view._scene_scale = 2.0
        view._pdf_text_runs = []
        view._pdf_text_cache_key = None
        view._pdf_text_request_id = None
        view._pdf_text_request_source = None
        view._pdf_text_highlight_items = []
        view._selected_pdf_text_selection = None
        view._pdf_text_drag_anchor = None
        view._pdf_text_drag_focus = None
        view._selection_enabled = True
        view._cursor_mode = "select"
        view._panning = False
        view._right_pan_active = False
        view._ctrl_held = False
        view._rotation_drag_active = False
        view._select_band_origin = None
        view._drag_handle_index = -2
        view._handle_infos = []
        view._zoom_press_ctrl = False
        view._current_annotations = {}
        view._editing_text_annotation_uid = None
        view._editing_named_view_uid = None
        view._takeoff_items = []
        view._hotlink_items = []
        view._uid_to_items = {}
        view._selected_uids = set()
        view._current_page_transform = lambda: None
        view.mapToScene = lambda point: QtCore.QPointF(point.x(), point.y())
        view.viewport = lambda: _pdf_text_support_FakeTrackingViewport()
        view._rendering_service = _pdf_text_support_FakeRenderingService()
        view._context_menu_command_trigger = lambda _action_key: None
        view._context_menu_action_state = lambda action_key: {
            "text": action_key.replace("_", " ").title(),
            "enabled": False,
        }
        view._use_full_window_crosshairs = False
        return view

    def test_maps_pdfium_text_box_to_plan_view_page_coordinates(self):
        view = self._make_view()
        raw_runs = [
            _pdf_text_support__raw_run(
                "Hello",
                10.0,
                20.0,
                70.0,
                80.0,
                [_pdf_text_support__raw_char("H", 10.0, 12.0, 70.0, 80.0)],
            )
        ]
        mapped = view._map_pdf_text_runs(raw_runs, _pdf_text_support__page_info())
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0].text, "Hello")
        self.assertEqual(
            (mapped[0].left, mapped[0].top, mapped[0].right, mapped[0].bottom),
            (20.0, 40.0, 40.0, 60.0),
        )
        self.assertEqual(
            (
                mapped[0].chars[0].left,
                mapped[0].chars[0].top,
                mapped[0].chars[0].right,
                mapped[0].chars[0].bottom,
            ),
            (20.0, 40.0, 24.0, 60.0),
        )

    def test_pdf_text_click_selects_character_and_copies_text(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        selected = view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0))
        copied = view.copy_selected_pdf_text()
        self.assertTrue(selected)
        self.assertTrue(copied)
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "B")
        self.assertEqual(len(view._pdf_text_highlight_items), 1)
        self.assertIs(view._pdf_text_highlight_items[0].scene(), view._scene)

    def test_dragging_within_pdf_text_selects_partial_range(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    18.0,
                    70.0,
                    80.0,
                    [
                        _pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0),
                        _pdf_text_support__raw_char("e", 12.0, 14.0, 70.0, 80.0),
                        _pdf_text_support__raw_char("a", 14.0, 16.0, 70.0, 80.0),
                        _pdf_text_support__raw_char("m", 16.0, 18.0, 70.0, 80.0),
                    ],
                )
            ],
            _pdf_text_support__page_info(),
        )
        self.assertTrue(view._begin_pdf_text_selection(QtCore.QPointF(21.0, 45.0)))
        self.assertTrue(
            view._update_pdf_text_selection_drag(QtCore.QPointF(31.0, 45.0))
        )
        self.assertTrue(view._finish_pdf_text_selection_drag())
        self.assertTrue(view.copy_selected_pdf_text())
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "Bea")
        self.assertEqual(len(view._pdf_text_highlight_items), 1)

    def test_dragging_across_pdf_text_runs_copies_reading_order(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    14.0,
                    70.0,
                    80.0,
                    [
                        _pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0),
                        _pdf_text_support__raw_char("e", 12.0, 14.0, 70.0, 80.0),
                    ],
                ),
                _pdf_text_support__raw_run(
                    "Tag",
                    20.0,
                    26.0,
                    70.0,
                    80.0,
                    [
                        _pdf_text_support__raw_char("T", 20.0, 22.0, 70.0, 80.0),
                        _pdf_text_support__raw_char("a", 22.0, 24.0, 70.0, 80.0),
                        _pdf_text_support__raw_char("g", 24.0, 26.0, 70.0, 80.0),
                    ],
                ),
            ],
            _pdf_text_support__page_info(),
        )
        self.assertTrue(view._begin_pdf_text_selection(QtCore.QPointF(21.0, 45.0)))
        self.assertTrue(
            view._update_pdf_text_selection_drag(QtCore.QPointF(51.0, 45.0))
        )
        self.assertTrue(view.copy_selected_pdf_text())
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "Be Tag")
        self.assertEqual(len(view._pdf_text_highlight_items), 2)

    def test_copy_selected_uses_pdf_text_when_no_takeoffs_are_selected(self):
        view = self._make_view()
        view._selected_uids = set()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0))
        view.copy_selected()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "B")

    def test_pdf_text_selection_is_ignored_outside_select_mode(self):
        view = self._make_view()
        view._cursor_mode = "place"
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        self.assertFalse(view.select_pdf_text_at(QtCore.QPointF(25.0, 45.0)))
        self.assertIsNone(view._selected_pdf_text_selection)

    def test_pdf_text_hover_uses_text_cursor_in_select_mode(self):
        view = self._make_view()
        view._selected_uids = set()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        cursor = view._resolve_select_cursor(QtCore.QPoint(25, 45))
        self.assertEqual(cursor, Qt.CursorShape.IBeamCursor)

    def test_pdf_text_hover_cursor_resets_when_mouse_moves_away(self):
        view = self._make_view()
        viewport = _pdf_text_support_FakeTrackingViewport()
        view.viewport = lambda: viewport
        view._last_mouse_vp_pos = QtCore.QPoint(25, 45)
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        view._update_cursor(QtCore.QPoint(25, 45))
        self.assertEqual(viewport.cursor, Qt.CursorShape.IBeamCursor)
        view._update_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)

    def test_selected_pdf_text_does_not_force_hover_ibeam_elsewhere(self):
        view = self._make_view()
        viewport = _pdf_text_support_FakeTrackingViewport()
        view.viewport = lambda: viewport
        view._last_mouse_vp_pos = QtCore.QPoint(25, 45)
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        self.assertTrue(view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0)))
        view._update_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)

    def test_select_mode_enables_passive_mouse_tracking_for_pdf_text_hover(self):
        view = self._make_view()
        viewport = _pdf_text_support_FakeTrackingViewport()
        view.viewport = lambda: viewport
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        view._update_viewport_mouse_tracking()
        self.assertEqual(viewport.tracking, [True])

    def test_select_mode_enables_passive_mouse_tracking_without_pdf_text(self):
        view = self._make_view()
        viewport = _pdf_text_support_FakeTrackingViewport()
        view.viewport = lambda: viewport
        view._update_viewport_mouse_tracking()
        self.assertEqual(viewport.tracking, [True])

    def test_takeoff_hover_priority_beats_pdf_text_cursor(self):
        view = self._make_view()
        view._selected_uids = {"takeoff-1"}
        view._handle_infos = []
        view.find_selected_movable_at = lambda _scene_pos: "takeoff-1"
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        cursor = view._resolve_select_cursor(QtCore.QPoint(25, 45))
        self.assertEqual(cursor, Qt.CursorShape.SizeAllCursor)

    def test_pdf_text_context_menu_copy_is_enabled_for_selection(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        empty_menu = QtWidgets.QMenu()
        view._add_pdf_text_context_clipboard_actions(empty_menu)
        self.assertEqual(empty_menu.actions()[0].text().replace("&", ""), "Copy")
        self.assertFalse(empty_menu.actions()[0].isEnabled())
        view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0))
        menu = QtWidgets.QMenu()
        view._add_pdf_text_context_clipboard_actions(menu)
        actions = menu.actions()
        self.assertEqual(actions[0].text().replace("&", ""), "Copy")
        self.assertTrue(actions[0].isEnabled())

    def test_pdf_text_context_menu_copy_action_copies_selected_text(self):
        view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=FakeTakeoffRenderer(),
            annotation_renderer=FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        self.addCleanup(lambda: delete(view) if isValid(view) else None)
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="drawing.pdf",
            width_pts=200.0,
            height_pts=100.0,
        )
        view._pdf_width_pts = 200.0
        view._pdf_height_pts = 100.0
        view._scene_scale = 2.0
        view._selection_enabled = True
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        self.assertTrue(view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0)))
        menu = QtWidgets.QMenu()
        view._add_pdf_text_context_clipboard_actions(menu)
        copy_action = menu.actions()[0]
        self.assertTrue(copy_action.isEnabled())
        copy_action.trigger()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "B")
        # The captured command is invalidated by clearing or replacing the
        # selection, and by replacing the owning Page.
        QtWidgets.QApplication.clipboard().setText("")
        view._clear_pdf_text_selection()
        copy_action.trigger()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "")
        self.assertTrue(view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0)))
        stale_menu = QtWidgets.QMenu()
        view._add_pdf_text_context_clipboard_actions(stale_menu)
        view._current_page = replace(view._current_page)
        stale_menu.actions()[0].trigger()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "")
        view.cleanup()

    def test_pdf_text_extraction_runs_through_rendering_worker_service(self):
        view = self._make_view()
        view._request_pdf_text_extraction()
        self.assertEqual(
            view._rendering_service.requests[0][:2],
            ("drawing.pdf", 0),
        )
        self.assertEqual(
            view._rendering_service.requests[0][3], RenderPriority.PDF_TEXT
        )
        self.assertEqual(len(view._rendering_service.requests), 1)
        self.assertEqual(view._pdf_text_request_id, "text-request-1")
        view._request_pdf_text_extraction()
        self.assertEqual(len(view._rendering_service.requests), 1)

    def test_composite_pdf_text_extraction_uses_overlay_source(self):
        view = self._make_view()
        view._current_page.overlay_image_path = "overlay.pdf"
        view._current_page.image_show_mode = 2
        view._request_pdf_text_extraction()
        self.assertEqual(
            view._rendering_service.requests[0][:2],
            ("overlay.pdf", 0),
        )
        self.assertEqual(view._pdf_text_cache_key[1], "overlay")

    def test_raster_overlay_falls_back_to_main_pdf_text_source(self):
        view = self._make_view()
        view._current_page.overlay_image_path = "overlay.tif"
        view._current_page.image_show_mode = 2
        view._request_pdf_text_extraction()
        self.assertEqual(
            view._rendering_service.requests[0][:2],
            ("drawing.pdf", 0),
        )
        self.assertEqual(view._pdf_text_cache_key[1], "main")

    def test_pdf_text_cache_changes_with_overlay_coordinate_calibration(self):
        view = self._make_view()
        view._current_page.overlay_image_path = "overlay.pdf"
        view._current_page.image_show_mode = 1
        first_key = view._pdf_text_extraction_cache_key()
        self.assertEqual(first_key, view._pdf_text_extraction_cache_key())
        view._current_page.scale_factor1 = 0.125
        second_key = view._pdf_text_extraction_cache_key()
        self.assertNotEqual(first_key, second_key)

    def test_overlay_pdf_text_boxes_map_through_overlay_rect_position(self):
        view = self._make_view()
        view._current_page.overlay_image_path = "overlay.pdf"
        view._current_page.image_show_mode = 2
        view._current_page.overlay_offset_x = 999.0
        view._current_page.overlay_offset_y = -999.0
        view._current_page.overlay_rect = (
            64.0,
            32.0,
            200.0 / 72.0 * 64.0,
            100.0 / 72.0 * 64.0,
        )
        raw_runs = [
            _pdf_text_support__raw_run(
                "B",
                10.0,
                20.0,
                70.0,
                80.0,
                [_pdf_text_support__raw_char("B", 10.0, 12.0, 70.0, 80.0)],
            )
        ]
        mapped = view._map_pdf_text_runs(
            raw_runs,
            _pdf_text_support__page_info(),
            ("overlay", "overlay.pdf", 0),
        )
        self.assertEqual(len(mapped), 1)
        bounds = (mapped[0].left, mapped[0].top, mapped[0].right, mapped[0].bottom)
        for actual, expected in zip(bounds, (164.0, 112.0, 184.0, 132.0)):
            self.assertAlmostEqual(actual, expected)

    def test_overlay_pdf_text_boxes_map_through_overlay_rect_scale_and_rotation(self):
        view = self._make_view()
        view._current_page.overlay_image_path = "overlay.pdf"
        view._current_page.image_show_mode = 2
        view._current_page.overlay_offset_x = 999.0
        view._current_page.overlay_offset_y = -999.0
        view._current_page.overlay_rotation = math.pi / 2.0
        view._current_page.overlay_rect = (
            64.0,
            32.0,
            200.0 / 72.0 * 64.0,
            100.0 / 72.0 * 64.0,
        )
        raw_runs = [
            _pdf_text_support__raw_run(
                "R",
                10.0,
                20.0,
                30.0,
                40.0,
                [_pdf_text_support__raw_char("R", 10.0, 20.0, 30.0, 40.0)],
            )
        ]
        mapped = view._map_pdf_text_runs(
            raw_runs,
            _pdf_text_support__page_info(
                pdf_width=100.0,
                pdf_height=50.0,
                media_width=100.0,
                media_height=50.0,
            ),
            ("overlay", "overlay.pdf", 0),
        )
        self.assertEqual(len(mapped), 1)
        bounds = (mapped[0].left, mapped[0].top, mapped[0].right, mapped[0].bottom)
        for actual, expected in zip(bounds, (64.0, 112.0, 104.0, 152.0)):
            self.assertAlmostEqual(actual, expected)

    def test_pdf_text_request_is_cancelled_when_page_clears(self):
        view = self._make_view()
        view._pdf_text_request_id = "old-text-request"
        view._clear_pdf_text_cache()
        self.assertEqual(view._rendering_service.cancelled, ["old-text-request"])
        self.assertEqual(view._pdf_text_runs, [])

    def test_pdf_text_cache_clear_tolerates_scene_deleted_highlights(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _pdf_text_support__raw_run(
                    "A",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_pdf_text_support__raw_char("A", 10.0, 20.0, 70.0, 80.0)],
                )
            ],
            _pdf_text_support__page_info(),
        )
        self.assertTrue(view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0)))
        self.assertEqual(len(view._pdf_text_highlight_items), 1)
        view._scene.clear()
        view._clear_pdf_text_cache()
        self.assertEqual(view._pdf_text_highlight_items, [])
        self.assertIsNone(view._selected_pdf_text_selection)

    def test_pdf_text_extraction_result_ignores_stale_request(self):
        view = self._make_view()
        view._pdf_text_request_id = "current"
        view._on_pdf_text_extracted(
            RenderResult(
                "stale",
                True,
                {"text_runs": [], "page_info": _pdf_text_support__page_info()},
                None,
            )
        )
        self.assertEqual(view._pdf_text_request_id, "current")
        self.assertEqual(view._pdf_text_runs, [])

    def test_pdf_text_extraction_result_maps_current_request(self):
        view = self._make_view()
        view._pdf_text_request_id = "current"
        view._on_pdf_text_extracted(
            RenderResult(
                "current",
                True,
                {
                    "text_runs": [
                        _pdf_text_support__raw_run(
                            "Hello",
                            10.0,
                            20.0,
                            70.0,
                            80.0,
                            [_pdf_text_support__raw_char("H", 10.0, 12.0, 70.0, 80.0)],
                        )
                    ],
                    "page_info": _pdf_text_support__page_info(),
                },
                None,
            )
        )
        self.assertIsNone(view._pdf_text_request_id)
        self.assertEqual([run.text for run in view._pdf_text_runs], ["Hello"])

    def test_pdf_text_extraction_failure_clears_runs_and_request(self):
        view = self._make_view()
        view._pdf_text_request_id = "current"
        view._pdf_text_runs = ["stale"]
        view._on_pdf_text_extracted(RenderResult("current", False, None, "boom"))
        self.assertIsNone(view._pdf_text_request_id)
        self.assertEqual(view._pdf_text_runs, [])


class NamedViewInlineLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.qt_errors = []
        exception_hook = patch(
            "sys.excepthook", side_effect=lambda *error: self.qt_errors.append(error)
        )
        exception_hook.start()
        self.addCleanup(exception_hook.stop)
        self.addCleanup(lambda: self.assertEqual(self.qt_errors, []))
        self.view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=FakeTakeoffRenderer(),
            annotation_renderer=FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        self.addCleanup(lambda: delete(self.view) if isValid(self.view) else None)
        self.view.set_editing_enabled(True)
        self.view.set_selection_enabled(True)
        self.changes = []
        self.view.annotation_text_properties_flushed.connect(self.changes.extend)
        self.label = self.add_named_view()
        self.assertTrue(self.view._begin_named_view_rename("nv1"))

    def add_named_view(self):
        annotation = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            page_uid="p1",
            properties={"Text": "Before"},
        )
        label = QtWidgets.QGraphicsTextItem("Before")
        label.setData(0, "nv1")
        label.setData(2, NAMED_VIEW_LABEL_ITEM_KIND)
        self.view._scene.addItem(label)
        self.view._uid_to_items = {"nv1": [label]}
        self.view._takeoff_items = [label]
        self.view._current_annotations = {"nv1": annotation}
        return label

    def click_away(self):
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(900, 900),
            QtCore.QPointF(900, 900),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        self.view.mousePressEvent(event)

    def assert_edit_cleared(self):
        self.assertFalse(self.view.is_text_annotation_inline_edit_active())
        self.assertIsNone(self.view._editing_named_view_item)
        self.assertIsNone(self.view._editing_text_document)

    def test_normal_rename_and_repeated_cleanup_preserve_scene_selection(self):
        self.view._selected_uids = {"nv1"}
        self.label.setPlainText("After")
        cursor = self.label.textCursor()
        cursor.select(QtGui.QTextCursor.SelectionType.Document)
        self.label.setTextCursor(cursor)
        self.view._finish_active_inline_text_edit(commit=True)
        self.view._finish_active_inline_text_edit(commit=True)
        self.view._clear_inline_text_edit_state()
        self.assert_edit_cleared()
        self.assertEqual(len(self.changes), 1)
        self.assertEqual(self.changes[0][3], {"Text": "After"})
        self.assertFalse(self.label.textCursor().hasSelection())
        self.assertEqual(self.view._selected_uids, {"nv1"})
        self.assertEqual(
            self.label.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.NoTextInteraction,
        )

    def test_escape_restores_original_text_without_persistence(self):
        self.label.setPlainText("After")
        self.view.keyPressEvent(
            QtGui.QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Escape,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assert_edit_cleared()
        self.assertEqual(self.label.toPlainText(), "Before")
        self.assertEqual(self.changes, [])

    def test_scene_clear_while_empty_draft_refuses_commit(self):
        self.view._finish_active_inline_text_edit(commit=False)
        self.assertTrue(
            self.view.begin_named_view_draft([0, 0, 40, 0, 40, 40, 0, 40], "p1")
        )
        item = self.view._editing_named_view_item
        self.view.clear()
        self.assert_edit_cleared()
        self.assertIsNone(self.view._draft_named_view_uid)
        # Draft removal transfers ownership out of the scene before clearing.
        self.assertTrue(not isValid(item) or item.scene() is None)

    def test_scene_clear_while_validation_rejects_commit(self):
        self.view.set_named_view_name_validator(lambda _name, _uid: False)
        self.view.clear()
        self.assertFalse(isValid(self.label))
        self.assert_edit_cleared()
        self.view._clear_inline_text_edit_state()
        self.assertEqual(self.changes, [])

    def test_validator_replaces_same_uid_target(self):
        replacement = []

        def validate(_name, _uid):
            self.view.clear()
            replacement.append(self.add_named_view())
            return True

        self.label.setPlainText("Old draft")
        self.view.set_named_view_name_validator(validate)
        self.view._finish_active_inline_text_edit(commit=True)
        self.assert_edit_cleared()
        self.assertEqual(self.changes, [])
        self.assertEqual(replacement[0].toPlainText(), "Before")

    def test_edit_mode_notification_cannot_redirect_commit_to_replacement(self):
        replacement = []

        def replace_on_finish(active):
            if not active:
                self.view.clear()
                replacement.append(self.add_named_view())

        self.view.text_annotation_edit_mode_changed.connect(replace_on_finish)
        self.label.setPlainText("Old draft")
        self.view._finish_active_inline_text_edit(commit=True)
        self.assert_edit_cleared()
        self.assertEqual(self.changes, [])
        self.assertEqual(replacement[0].toPlainText(), "Before")

    def test_overlay_rebuild_releases_removed_target(self):
        page = Page(uid="p1", name="Page")
        annotation = self.view._current_annotations["nv1"]
        self.view._refresh_overlays_impl_unflushed(
            page, [], {}, {}, [annotation], None, None
        )
        self.assert_edit_cleared()
        self.assertIsNone(self.label.scene())
        self.assertIsNot(self.view._named_view_label_item("nv1"), self.label)
        self.click_away()

    def test_destroyed_target_then_press_double_click_starts_one_connection(self):
        self.label.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            self.label, QtCore.QEvent.Type.DeferredDelete
        )
        self.assert_edit_cleared()
        self.click_away()
        replacement = self.add_named_view()
        point = QtCore.QPointF(
            self.view.mapFromScene(
                replacement.mapToScene(replacement.boundingRect().center())
            )
        )
        with patch.object(
            self.view,
            "_refresh_active_inline_text_visuals",
            wraps=self.view._refresh_active_inline_text_visuals,
        ) as refresh:
            self.view.mouseDoubleClickEvent(
                QtGui.QMouseEvent(
                    QtCore.QEvent.Type.MouseButtonDblClick,
                    point,
                    point,
                    QtCore.Qt.MouseButton.LeftButton,
                    QtCore.Qt.MouseButton.LeftButton,
                    QtCore.Qt.KeyboardModifier.NoModifier,
                )
            )
            self.assertIs(self.view._editing_named_view_item, replacement)
            self.assertTrue(self.view._begin_named_view_rename("nv1"))
            refresh.reset_mock()
            replacement.setPlainText("New")
            refresh.assert_called_once_with()
            self.view._finish_active_inline_text_edit(commit=True)
        self.assert_edit_cleared()
        self.assertEqual(len(self.changes), 1)

    def test_document_replacement_releases_destroyed_signal_source(self):
        document = self.label.document()
        replacement = QtGui.QTextDocument(self.label)
        self.label.setDocument(replacement)
        self.assertFalse(isValid(document))
        self.assert_edit_cleared()
        self.view._clear_inline_text_document()
        self.view._clear_inline_text_document()
        self.assertTrue(self.view._begin_named_view_rename("nv1"))
        self.assertIs(self.view._editing_text_document, replacement)
        self.view._finish_active_inline_text_edit(commit=False)
        self.assert_edit_cleared()

    def test_start_rename_after_native_document_replacement(self):
        document = self.label.document()
        self.label.setDocument(QtGui.QTextDocument(self.label))
        self.assertFalse(isValid(document))
        self.assertTrue(self.view._begin_named_view_rename("nv1"))
        self.view._finish_active_inline_text_edit(commit=False)
        self.assert_edit_cleared()

    def test_annotation_removal_releases_edit_before_same_uid_replacement(self):
        self.label.setPlainText("Obsolete draft")
        self.view._remove_annotation_overlay_items({"nv1"})
        self.assert_edit_cleared()
        self.assertIsNone(self.label.scene())
        replacement = self.add_named_view()
        self.click_away()
        self.assertEqual(self.changes, [])
        self.assertEqual(replacement.toPlainText(), "Before")

    def test_view_native_teardown_releases_inline_ownership(self):
        document = self.label.document()
        delete(self.view)
        self.assertFalse(isValid(self.label))
        self.assertFalse(isValid(document))
        self.assert_edit_cleared()

    def test_cleanup_during_rename_is_idempotent(self):
        self.view.cleanup()
        self.view.cleanup()
        self.assert_edit_cleared()

    def test_commit_rebuilds_scene_before_returning_to_click_cleanup(self):
        document = self.label.document()
        self.label.setPlainText("After")
        replacement = []

        def rebuild(_changes):
            self.view.clear()
            replacement.append(self.add_named_view())

        self.view.annotation_text_properties_flushed.connect(rebuild)
        self.click_away()
        self.assertFalse(isValid(self.label))
        self.assertFalse(isValid(document))
        self.assert_edit_cleared()
        self.assertIs(self.view._named_view_label_item("nv1"), replacement[0])
        self.assertEqual(replacement[0].toPlainText(), "Before")
        self.assertEqual(len(self.changes), 1)
        self.click_away()

    def test_deferred_target_deletion_before_finish(self):
        document = self.label.document()
        self.label.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            self.label, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertFalse(isValid(self.label))
        self.assertFalse(isValid(document))
        self.view._finish_active_inline_text_edit(commit=True)
        self.assert_edit_cleared()
        self.assertEqual(self.changes, [])


class UIAccessPlanEditingTests(unittest.TestCase):
    def test_revoking_plan_editing_cancels_every_active_mutation_mode(self):
        cancellations = []

        def cancel_rotation_drag():
            cancellations.append(("rotation-drag", True))
            return False

        def discard_unflushed_geometry_edits():
            TakeoffPlanView._discard_unflushed_geometry_edits(view)

        view = SimpleNamespace(
            _editing_enabled=True,
            _rotation_drag_active=False,
            _position_before_edit={},
            _rotation_before_edit={},
            _current_takeoffs={},
            _current_annotations={},
            _dirty_positions={},
            _dirty_ann_positions={},
            _dirty_rotations={},
            _keyboard_move_dirty=False,
            _cancel_active_drag_interaction=lambda restore_preview: cancellations.append(
                ("drag", restore_preview)
            ),
            _cancel_rotation_drag_interaction=cancel_rotation_drag,
            _discard_unflushed_geometry_edits=discard_unflushed_geometry_edits,
            cancel_overlay_move_mode=lambda restore_preview: cancellations.append(
                ("overlay", restore_preview)
            ),
            finish_intelligent_paste_placement=lambda: cancellations.append(
                ("intelligent-paste", True)
            ),
            cancel_paste_backout=lambda: cancellations.append(("paste-backout", True)),
            cancel_place_mode=lambda: cancellations.append(("placement", True)),
            _finish_active_inline_text_edit=lambda commit: cancellations.append(
                ("inline-text", commit)
            ),
            _remove_rotate_handle=lambda: cancellations.append(("rotate", True)),
            _rebuild_current_overlays_from_model=lambda: None,
        )
        TakeoffPlanView.set_editing_enabled(view, False)
        self.assertFalse(view._editing_enabled)
        self.assertEqual(
            cancellations,
            [
                ("inline-text", False),
                ("overlay", True),
                ("intelligent-paste", True),
                ("paste-backout", True),
                ("placement", True),
                ("drag", True),
                ("rotation-drag", True),
                ("rotate", True),
            ],
        )
        cancellations.clear()
        TakeoffPlanView.set_editing_enabled(view, True)
        self.assertTrue(view._editing_enabled)
        self.assertEqual(cancellations, [])

    def test_read_only_plan_rejects_direct_mutation_mode_activation(self):
        calls = []
        view = SimpleNamespace(
            _editing_enabled=False,
            _finish_inline_text_edit_before_tool_change=lambda: calls.append(
                "finish-text"
            )
            or True,
            cancel_overlay_move_mode=lambda restore_preview: calls.append(
                ("overlay", restore_preview)
            ),
            _remove_rotate_handle=lambda: calls.append("remove-rotate"),
            finish_intelligent_paste_placement=lambda: calls.append("finish-paste"),
            _exit_annotation_place_mode=lambda: calls.append("exit-annotation"),
            enter_place_mode=lambda: calls.append("enter-place") or True,
            _exit_place_mode=lambda: calls.append("exit-place"),
            _clear_backout_state=lambda: calls.append("clear-backout"),
            _apply_cursor_mode=lambda mode: calls.append(("cursor", mode)),
            cursor_mode_change_requested=SimpleNamespace(
                emit=lambda mode: calls.append(("emit", mode))
            ),
        )
        TakeoffPlanView.set_cursor_mode(view, CURSOR_MODE_PLACE)
        self.assertEqual(calls, [])
        view._editing_enabled = True
        TakeoffPlanView.set_cursor_mode(view, CURSOR_MODE_PLACE)
        self.assertEqual(
            calls,
            [
                "finish-text",
                ("overlay", True),
                "remove-rotate",
                "finish-paste",
                "exit-annotation",
                "enter-place",
                ("cursor", CURSOR_MODE_PLACE),
                ("emit", CURSOR_MODE_PLACE),
            ],
        )

    def test_read_only_plan_rejects_direct_annotation_style_mutation(self):
        annotation = SimpleNamespace(
            color="#112233",
            width=2.0,
            is_text=False,
            is_dimension=False,
            is_highlight=False,
            annotation_type="rectangle",
            properties={},
        )
        emissions = []
        view = SimpleNamespace(
            _editing_enabled=False,
            _selected_uids={"annotation-1"},
            _current_annotations={"annotation-1": annotation},
            _ann_db_uid_map={"annotation-1": 41},
            _rebuild_current_overlays_from_model=lambda: emissions.append("rebuild"),
            annotation_styles_flushed=SimpleNamespace(
                emit=lambda changes: emissions.append(changes)
            ),
        )
        TakeoffPlanView.apply_annotation_style_to_selection(
            view, color="#445566", width=4.0
        )
        self.assertEqual(annotation.color, "#112233")
        self.assertEqual(annotation.width, 2.0)
        self.assertEqual(emissions, [])
        view._editing_enabled = True
        TakeoffPlanView.apply_annotation_style_to_selection(
            view, color="#445566", width=4.0
        )
        self.assertEqual(annotation.color, "#445566")
        self.assertEqual(annotation.width, 4.0)
        self.assertEqual(
            emissions,
            [
                "rebuild",
                [
                    (
                        41,
                        "rectangle",
                        {"Color": "#112233", "Width": 2.0},
                        {"Color": "#445566", "Width": 4.0},
                    )
                ],
            ],
        )


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    def test_pending_visible_view_state_ignores_reentrant_resize_apply(self):
        calls = []
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._applying_pending_visible_view_state = False
        view._load_view_applied = False
        view.isVisible = lambda: True
        view.viewport = lambda: SimpleNamespace(
            size=lambda: SimpleNamespace(isValid=lambda: True)
        )

        def apply_loading_view_contract():
            calls.append("loading")
            TakeoffPlanView._apply_pending_visible_view_state(view)

        view._apply_loading_view_contract = apply_loading_view_contract
        view._finalize_page_load_if_ready = lambda: calls.append("finalize")
        TakeoffPlanView._apply_pending_visible_view_state(view)
        self.assertEqual(calls, ["loading", "finalize"])
        self.assertFalse(view._applying_pending_visible_view_state)


class TextAnnotationNativeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.errors = []
        hook = patch(
            "sys.excepthook", side_effect=lambda *args: self.errors.append(args)
        )
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(self.errors, []))
        fixture = view_fixtures.TakeoffPlanViewOverlayRefreshTests()
        self.addCleanup(fixture.doCleanups)
        self.view = fixture._make_plan_view()
        self.annotation, self.item = fixture._add_text_annotation(
            self.view, text="Before", page_uid="p1"
        )
        self.changes = []
        self.view.annotation_text_properties_flushed.connect(self.changes.extend)

    def test_edit_completion_tolerates_synchronous_scene_clear(self):
        self.assertTrue(self.view._begin_text_annotation_edit("a1"))
        self.item.setPlainText("After")
        self.view.annotation_text_properties_flushed.connect(
            lambda _changes: self.view.clear()
        )
        self.view._finish_text_annotation_edit(True)
        self.assertEqual(len(self.changes), 1)
        self.assertFalse(self.view.is_text_annotation_inline_edit_active())
        self.assertIsNone(self.view._editing_text_document)

    def test_destroyed_item_releases_edit_and_allows_new_draft(self):
        self.assertTrue(self.view._begin_text_annotation_edit("a1"))
        delete(self.item)
        self.assertFalse(isValid(self.item))
        self.assertFalse(self.view.is_text_annotation_inline_edit_active())
        self.view._finish_text_annotation_edit(True)
        self.assertTrue(self.view.begin_text_annotation_draft([10, 10, 80, 24], "p1"))
        self.view._finish_text_annotation_edit(False)
        self.assertEqual(self.changes, [])


class RemoteProjectionBlockerTests(unittest.TestCase):
    @staticmethod
    def _plan_state(**overrides):
        state = {
            "_editing_annotation_uids": lambda: set(),
            "_has_active_drag_interaction": lambda: False,
            "_drag_plan_item_uid": None,
            "_rotation_drag_active": False,
            "_overlay_move_dragging": False,
            "_annotation_place_dragging": False,
            "_annotation_area_rect_dragging": False,
            "_place_linear_dragging": False,
            "_place_area_rect_dragging": False,
            "_dirty_positions": {},
            "_dirty_ann_positions": {},
            "_place_preview_items": [],
            "_paste_backout_preview_items": [],
        }
        state.update(overrides)
        return SimpleNamespace(**state)

    def test_passive_placement_hover_preview_does_not_block_projection(self):
        view = self._plan_state(_place_preview_items=[object()])
        self.assertFalse(TakeoffPlanView.has_active_remote_projection_blocker(view))

    def test_active_placement_gesture_still_blocks_projection(self):
        view = self._plan_state(
            _place_preview_items=[object()],
            _place_linear_dragging=True,
        )
        self.assertTrue(TakeoffPlanView.has_active_remote_projection_blocker(view))

    def test_active_selection_box_blocks_projection(self):
        view = self._plan_state(_has_active_drag_interaction=lambda: True)
        self.assertTrue(TakeoffPlanView.has_active_remote_projection_blocker(view))

    def test_idle_plan_does_not_block_projection(self):
        view = self._plan_state()
        self.assertFalse(TakeoffPlanView.has_active_remote_projection_blocker(view))

    def test_each_active_edit_state_blocks_projection(self):
        blockers = {
            "editing-annotation": {"_editing_annotation_uids": lambda: {"a1"}},
            "rotation-drag": {"_rotation_drag_active": True},
            "overlay-move-drag": {"_overlay_move_dragging": True},
            "annotation-place-drag": {"_annotation_place_dragging": True},
            "annotation-area-drag": {"_annotation_area_rect_dragging": True},
            "place-area-drag": {"_place_area_rect_dragging": True},
            "dirty-takeoff-position": {"_dirty_positions": {"t1": [1.0, 2.0]}},
            "dirty-annotation-position": {
                "_dirty_ann_positions": {"a1": (ANNOTATION_TYPE_TEXT, [1.0, 2.0])}
            },
            "paste-backout-preview": {"_paste_backout_preview_items": [object()]},
        }
        for name, overrides in blockers.items():
            with self.subTest(blocker=name):
                view = self._plan_state(**overrides)
                self.assertTrue(
                    TakeoffPlanView.has_active_remote_projection_blocker(view)
                )


class CtrlDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _make_view(self, selected_uids=None):
        view = _interaction_support_InputHandlerHarness()
        view._scene_builder = _interaction_support_FakeSceneBuilder()
        view._current_bid_ref = None
        view._current_page = None
        view._cursor_mode = "select"
        view._selection_enabled = True
        view._ctrl_held = False
        view._use_full_window_crosshairs = False
        view._zoom_press_ctrl = False
        view._select_band_origin = None
        view._select_band_active = False
        view._select_band_dragged = False
        view._press_changed_selection = False
        view._rotation_drag_active = False
        view._rotate_cursor = Qt.CursorShape.CrossCursor
        view._rotate_handle_item = None
        view._panning = False
        view._right_pan_active = False
        view._point_annotation_release_pending = False
        view._last_pan_point = None
        view._drag_plan_item_uid = None
        view._drag_handle_index = -2
        view._drag_orig_position = []
        view._drag_handle_corner_count = 0
        view._drag_item_orig_positions = {}
        view._drag_item_orig_paths = {}
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {}
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._keyboard_move_dirty = False
        view._selected_uids = set({"t1"} if selected_uids is None else selected_uids)
        view.plan_item_selection_changed = _interaction_support__FakeSignal()
        view.takeoff_selection_changed = _interaction_support__FakeSignal()
        view._handle_infos = []
        view._selection_items = []
        view._current_takeoffs = {
            "t1": Takeoff(
                uid="t1",
                position=[0.0, 0.0, 10.0, 0.0],
                condition_uid="c",
            ),
            "t2": Takeoff(
                uid="t2",
                position=[20.0, 0.0, 30.0, 0.0],
                condition_uid="c",
            ),
        }
        view._current_annotations = {}
        view._hotlink_items = []
        view._current_conditions = {}
        view._scene = None
        view._uid_to_items = {
            "t1": [_interaction_support_FakeItem(1.0, 2.0)],
            "t2": [_interaction_support_FakeItem(3.0, 4.0)],
        }
        view._takeoff_items = []
        view.mapToScene = lambda _point: QtCore.QPointF(10.0, 10.0)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        view.find_takeoff_at = lambda _scene_pos: "t1"
        view.find_takeoffs_at = lambda _scene_pos: ["t1"]
        view._flush_dirty_positions = lambda: None
        view.update_selection_visuals = lambda *args, **_call_options: None
        view._rubber_band_origin = None
        view._rubber_band = None
        view._update_cursor = lambda *args, **_call_options: None
        view._snap_increments = 1.0
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        return view

    def _make_tool_change_commit_view(self):
        view = SimpleNamespace()
        view._editing_enabled = True
        view._cursor_mode = CURSOR_MODE_ANNOTATION_PLACE
        view._editing_named_view_uid = "draft"
        view._editing_text_annotation_uid = None
        view._annotation_place_type = ANNOTATION_TYPE_NAMED_VIEW
        view._current_bid_page_uid = "page-1"
        view.finished_inline_edits = []
        view.exited_annotation_place = 0
        view.entered_annotation_place = []
        view.cursor_mode_change_requested = _interaction_support__FakeSignal()

        def is_text_annotation_inline_edit_active():
            return (
                view._editing_named_view_uid is not None
                or view._editing_text_annotation_uid is not None
            )

        def finish_inline_edit(commit):
            view.finished_inline_edits.append(commit)
            view._editing_named_view_uid = None
            view._editing_text_annotation_uid = None
            view._annotation_place_type = ANNOTATION_TYPE_NAMED_VIEW

        def exit_annotation_place_mode():
            view.exited_annotation_place += 1
            view._annotation_place_type = None

        def enter_annotation_place_mode(annotation_type):
            view.entered_annotation_place.append(annotation_type)
            view._annotation_place_type = annotation_type
            return True

        view.is_text_annotation_inline_edit_active = (
            is_text_annotation_inline_edit_active
        )
        view._finish_active_inline_text_edit = finish_inline_edit
        view._finish_inline_text_edit_before_tool_change = lambda: (
            TakeoffPlanView._finish_inline_text_edit_before_tool_change(view)
        )
        view.cancel_overlay_move_mode = lambda restore_preview=True: None
        view._remove_rotate_handle = lambda: None
        view.finish_intelligent_paste_placement = lambda: None
        view._exit_annotation_place_mode = exit_annotation_place_mode
        view.enter_place_mode = lambda: True
        view._exit_place_mode = lambda: None
        view._clear_backout_state = lambda: None

        def apply_cursor_mode(mode):
            view._cursor_mode = mode

        view._apply_cursor_mode = apply_cursor_mode
        view._can_begin_annotation_placement = lambda: True
        view._enter_annotation_place_mode = enter_annotation_place_mode
        return view

    def test_cursor_mode_change_commits_named_view_edit_before_switching_tool(self):
        view = self._make_tool_change_commit_view()
        TakeoffPlanView.set_cursor_mode(view, CURSOR_MODE_SELECT)
        self.assertEqual(view.finished_inline_edits, [True])
        self.assertEqual(view._cursor_mode, CURSOR_MODE_SELECT)
        self.assertIsNone(view._annotation_place_type)
        self.assertEqual(
            view.cursor_mode_change_requested.emitted, [(CURSOR_MODE_SELECT,)]
        )

    def test_cursor_mode_change_stays_put_when_named_view_commit_keeps_edit_active(
        self,
    ):
        view = self._make_tool_change_commit_view()

        def finish_invalid_edit(commit):
            view.finished_inline_edits.append(commit)

        view._finish_active_inline_text_edit = finish_invalid_edit
        TakeoffPlanView.set_cursor_mode(view, CURSOR_MODE_SELECT)
        self.assertEqual(view.finished_inline_edits, [True])
        self.assertEqual(view._cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
        self.assertEqual(view.exited_annotation_place, 0)
        self.assertEqual(view.cursor_mode_change_requested.emitted, [])

    def test_annotation_tool_change_commits_named_view_edit_before_switching_tool(self):
        view = self._make_tool_change_commit_view()
        self.assertTrue(
            TakeoffPlanView.activate_annotation_placement(
                view, ANNOTATION_TYPE_DIMENSION
            )
        )
        self.assertEqual(view.finished_inline_edits, [True])
        self.assertEqual(view.entered_annotation_place, [ANNOTATION_TYPE_DIMENSION])
        self.assertEqual(view._cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
        self.assertEqual(view._annotation_place_type, ANNOTATION_TYPE_DIMENSION)
        self.assertEqual(
            view.cursor_mode_change_requested.emitted,
            [(CURSOR_MODE_ANNOTATION_PLACE,)],
        )

    def test_named_view_draft_commit_ignores_reentrant_focus_commit(self):
        position = [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]
        view = SimpleNamespace()
        view._finishing_named_view_rename = False
        view._editing_named_view_uid = "draft"
        view._draft_named_view_uid = "draft"
        view._named_view_name_validator = None
        view._editing_text_original = ""
        view._current_annotations = {
            "draft": BidAnnotation(
                uid="draft",
                annotation_type="namedview",
                page_uid="page-1",
                position=position,
                color="#008000",
                properties={"Text": ""},
            )
        }
        view.named_view_created = _interaction_support__FakeSignal()
        view.text_annotation_edit_mode_changed = _interaction_support__FakeSignal()
        view.removed_drafts = 0
        view.refreshed_labels = []

        class ReentrantItem:
            def toPlainText(self):
                return "Lobby"

            def setTextInteractionFlags(self, _flags):
                pass

            def clearFocus(self):
                TakeoffPlanView._finish_named_view_rename(view, True)

        view._editing_named_view_item = ReentrantItem()
        view._clear_inline_text_item_selection = lambda _item: None
        view._clear_inline_text_document = lambda: None

        def set_inline_text_edit_target(
            *, text_annotation_uid=None, named_view_uid=None, named_view_item=None
        ):
            del text_annotation_uid, named_view_uid, named_view_item
            view._editing_named_view_uid = None

        view._set_inline_text_edit_target = set_inline_text_edit_target
        view._update_cursor = lambda: None
        view._is_named_view_draft_uid = lambda uid: uid == view._draft_named_view_uid

        def clear_edit_state(item=None):
            if item is not None:
                item.setTextInteractionFlags(None)
                item.clearFocus()
            view._set_inline_text_edit_target()
            view.text_annotation_edit_mode_changed.emit(False)

        view._clear_inline_text_edit_state = clear_edit_state

        def remove_draft():
            view.removed_drafts += 1
            view._draft_named_view_uid = None

        view._remove_named_view_draft = remove_draft
        view._refresh_named_view_label_background = (
            lambda uid: view.refreshed_labels.append(uid)
        )
        TakeoffPlanView._finish_named_view_rename(view, True)
        self.assertEqual(view.removed_drafts, 1)
        self.assertEqual(
            view.named_view_created.emitted,
            [
                (
                    position,
                    "page-1",
                    {"Text": "Lobby", "Color": "#008000"},
                )
            ],
        )

    def test_duplicate_named_view_validation_ignores_modal_reentry(self):
        position = [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]
        view = SimpleNamespace()
        view._finishing_named_view_rename = False
        view._editing_named_view_uid = "draft"
        view._draft_named_view_uid = "draft"
        view._editing_text_original = ""
        view._current_annotations = {
            "draft": BidAnnotation(
                uid="draft",
                annotation_type="namedview",
                page_uid="page-1",
                position=position,
                color="#008000",
                properties={"Text": ""},
            )
        }
        view.named_view_created = _interaction_support__FakeSignal()
        view.text_annotation_edit_mode_changed = _interaction_support__FakeSignal()
        view.refreshed_labels = []
        validator_calls = []

        class ReentrantInvalidItem:
            def __init__(self):
                self.text = "Lobby"
                self.focus_restores = 0

            def toPlainText(self):
                return self.text

            def setFocus(self, _reason):
                self.focus_restores += 1
                TakeoffPlanView._finish_named_view_rename(view, True)

            def setTextInteractionFlags(self, _flags):
                pass

            def clearFocus(self):
                pass

        item = ReentrantInvalidItem()

        def validate(name, exclude_uid=None):
            validator_calls.append((name, exclude_uid))
            if len(validator_calls) == 1:
                TakeoffPlanView._finish_named_view_rename(view, True)
            return False

        view._editing_named_view_item = item
        view._named_view_name_validator = validate
        view._clear_inline_text_item_selection = lambda _item: None
        view._clear_inline_text_document = lambda: None
        view._is_named_view_draft_uid = lambda uid: uid == view._draft_named_view_uid
        view._remove_named_view_draft = lambda: self.fail(
            "duplicate commit must keep the draft"
        )
        view._refresh_named_view_label_background = (
            lambda uid: view.refreshed_labels.append(uid)
        )
        TakeoffPlanView._finish_named_view_rename(view, True)
        self.assertEqual(validator_calls, [("Lobby", "draft")])
        self.assertEqual(item.focus_restores, 0)
        self.assertEqual(view.named_view_created.emitted, [])
        self.assertEqual(view._editing_named_view_uid, "draft")
        self.assertEqual(view._draft_named_view_uid, "draft")
        self.assertEqual(view.refreshed_labels, ["draft"])

    def test_authoritative_refresh_cancels_all_transient_interaction_state(self):
        view = self._make_view()
        viewport = _interaction_support_FakeCursorViewport()
        view.viewport = lambda: viewport
        view._update_cursor = lambda: viewport.setCursor(view._resolve_cursor(None))
        viewport.setCursor(Qt.CursorShape.SizeAllCursor)
        view._editing_text_annotation_uid = "annotation-1"
        view._draft_text_annotation_uid = None
        view._draft_named_view_uid = None
        view._drag_plan_item_uid = "t1"
        view._select_band_active = True
        view._rotation_drag_active = True
        view._overlay_move_dragging = True
        view._annotation_place_dragging = True
        view._annotation_area_rect_dragging = True
        view._place_linear_dragging = True
        view._place_area_rect_dragging = True
        view._paste_backout_preview_items = [object()]
        view._dirty_positions = {"t1": [20.0, 0.0, 30.0, 0.0]}
        view._position_before_edit = {"t1": [0.0, 0.0, 10.0, 0.0]}
        view._dirty_rotations = {}
        view._rotation_before_edit = {}
        view._place_session_uid = "condition-1"
        view._annotation_place_type = "dimension"
        view._annotation_place_points = [(1.0, 1.0)]
        view._panning = False
        view._last_mouse_vp_pos = QtCore.QPoint(4, 5)

        def cancel_overlay_move_mode(restore_preview=True):
            view._overlay_move_dragging = False

        def cancel_rotation_drag_interaction():
            view._rotation_drag_active = False

        def reset_place_session_state():
            view._place_linear_dragging = False
            view._place_area_rect_dragging = False

        view.cancel_overlay_move_mode = cancel_overlay_move_mode
        view._cancel_rotation_drag_interaction = cancel_rotation_drag_interaction
        view._discard_unflushed_geometry_edits = lambda: (
            TakeoffPlanView._discard_unflushed_geometry_edits(view)
        )
        view.finish_intelligent_paste_placement = lambda: None
        view.cancel_paste_backout = lambda: view._paste_backout_preview_items.clear()
        view.clear_place_preview = lambda: None
        view._reset_place_session_state = reset_place_session_state
        view._set_area_placement_in_progress = lambda _active: None
        view._rebuild_current_overlays_from_model = lambda: None
        view._editing_annotation_uids = lambda: (
            TakeoffPlanView._editing_annotation_uids(view)
        )
        TakeoffPlanView.prepare_for_authoritative_refresh(view)
        self.assertFalse(TakeoffPlanView.has_active_remote_projection_blocker(view))
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 10.0, 0.0],
        )
        self.assertIsNone(view._last_mouse_vp_pos)
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)
        self.assertIsNone(QApplication.overrideCursor())


class PresentationChaosHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _chaos_app()

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

    def test_harness_cleanup_destroys_its_unparented_plan_view(self):
        harness = PresentationChaosHarness(9000, self)
        view = harness.view
        harness.cleanup()
        self.assertFalse(isValid(view))

    def test_known_sequence_page_switch_drops_stale_selection(self):
        harness = PresentationChaosHarness(9001, self)
        try:
            harness.run_sequence(["select_all"])
            selected_before_switch = set(harness.view.get_selected_uids())
            self.assertEqual(
                selected_before_switch,
                {"101", "102", "103", "p1-hotlink", "p1-hotlink-empty"}
                | {"p1-named", "p1-text"},
            )
            self.assertEqual(harness.state.active_page_uid, "p1")
            harness.run_sequence(
                [
                    "switch_page",
                    "refresh_overlays",
                    "apply_pending_visible_state",
                ]
            )
            self.assertNotEqual(harness.state.active_page_uid, "p1")
            self.assertEqual(
                harness.view.current_page_uid, harness.state.active_page_uid
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
                ]
            )
            self.assertEqual(
                harness.state.deleted_annotation_uids, {"p1-named", "p1-hotlink"}
            )
            self.assertEqual(
                sorted(harness.view._current_annotations),
                ["p1-hotlink-empty", "p1-text"],
            )
            self.assertEqual(
                [hotlink.uid for _item, hotlink in harness.view._hotlink_items],
                ["p1-hotlink-empty"],
            )
            self.assertNotIn("p1-named", harness.view._uid_to_items)
            self.assertNotIn("p1-hotlink", harness.view._uid_to_items)
            harness.run_sequence(["switch_page", "switch_page"])
        finally:
            harness.cleanup()

    def test_known_sequence_cancel_placement_clears_preview_and_mode(self):
        # Seed 9004 enters hotlink placement and the random pointer position
        # lands on the page, so a placement preview exists before cancelling.
        harness = PresentationChaosHarness(9004, self)
        try:
            harness.run_sequence(
                ["enter_annotation_placement", "mouse_move_during_placement"]
            )
            self.assertEqual(harness.view._cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
            self.assertEqual(
                harness.view.annotation_place_type, ANNOTATION_TYPE_HOTLINK
            )
            self.assertNotEqual(harness.view._place_preview_items, [])
            harness.run_sequence(
                [
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
