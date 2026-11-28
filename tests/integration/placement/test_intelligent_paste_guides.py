import os
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QGraphicsLineItem
from shiboken6 import delete, isValid
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.infrastructure.providers import (
    AnnotationItemRenderer,
    ColorService,
    LinearGeometry,
    PageCache,
    PageLoadStrategyService,
    PDFRenderingService,
    TakeoffRenderer,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.services.selection_clipboard_service import (
    SelectionClipboardService,
)
from ost_visualizer.presentation.utils.annotation_paste import (
    offset_paste_anchor,
    position_paste_anchor,
    translate_annotation_position,
)

PASTE_OFFSET = 300.0
SNAP_PX = 8
CONDITIONS = {
    "area": Condition(
        uid="area", name="Area", ref_no=1, condition_type=Condition.TYPE_AREA
    ),
    "lin": Condition(
        uid="lin", name="Lin", ref_no=2, condition_type=Condition.TYPE_LINEAR
    ),
    "cnt": Condition(
        uid="cnt", name="Cnt", ref_no=3, condition_type=Condition.TYPE_COUNT
    ),
    "att": Condition(
        uid="att", name="Att", ref_no=4, condition_type=Condition.TYPE_ATTACHMENT
    ),
}
COLORS = {uid: "#ff0000" for uid in CONDITIONS}


def _takeoffs():
    return {
        "30": Takeoff(
            uid="30",
            condition_uid="area",
            page_uid="p1",
            position=[400.0, 400.0, 600.0, 400.0, 600.0, 550.0, 400.0, 550.0],
        ),
        "100": Takeoff(
            uid="100",
            condition_uid="area",
            page_uid="p1",
            parent_uid="30",
            position=[450.0, 430.0, 500.0, 430.0, 500.0, 470.0, 450.0, 470.0],
        ),
        "110": Takeoff(
            uid="110",
            condition_uid="att",
            page_uid="p1",
            parent_uid="30",
            position=[540.0, 500.0, 560.0, 500.0, 560.0, 520.0, 540.0, 520.0],
        ),
        "40": Takeoff(
            uid="40",
            condition_uid="lin",
            page_uid="p1",
            position=[700.0, 420.0, 900.0, 420.0],
        ),
        "50": Takeoff(
            uid="50", condition_uid="cnt", page_uid="p1", position=[1000.0, 480.0]
        ),
        "70": Takeoff(
            uid="70",
            condition_uid="area",
            page_uid="p1",
            is_negative=True,
            position=[760.0, 470.0, 820.0, 470.0, 820.0, 560.0, 760.0, 560.0],
        ),
    }


def _annotations():
    return {
        "a1": BidAnnotation(
            uid="a1",
            annotation_type="line",
            page_uid="p1",
            position=[1100.0, 400.0, 1200.0, 450.0],
        ),
        "a2": BidAnnotation(
            uid="a2",
            annotation_type="text",
            page_uid="p1",
            position=[1250.0, 420.0, 60.0, 20.0],
            properties={"Text": "Note"},
        ),
        "a3": BidAnnotation(
            uid="a3",
            annotation_type="ink",
            page_uid="p1",
            position=[3.0, 1300.0, 500.0, 1350.0, 520.0, 1400.0, 510.0],
        ),
    }


def _grab_point(position):
    if len(position) >= 8:
        xs, ys = position[0::2], position[1::2]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    if len(position) == 4:
        return (
            position[0] * 0.75 + position[2] * 0.25,
            position[1] * 0.75 + position[3] * 0.25,
        )
    return position[0], position[1]


def _expected_guides(offset):
    ex, ey = offset
    return (2 if abs(ey) <= SNAP_PX else 0, 2 if abs(ex) <= SNAP_PX else 0)


def _expected_snapped(offset):
    ex, ey = offset
    return (0 if abs(ex) <= SNAP_PX else ex, 0 if abs(ey) <= SNAP_PX else ey)


class IntelligentPasteGuideTests(unittest.TestCase):
    """Real plan view, renderers and mouse drags; the paste delta and anchors come
    from the handler's own translation and anchor functions."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _view(self):
        coordinates = OSTCoordinateSystem()
        colors = ColorService()
        cache = PageCache()
        view = TakeoffPlanView(
            colors,
            PDFRenderingService(cache, num_workers=1),
            PageLoadStrategyService(cache),
            TakeoffRenderer(coordinates, colors),
            AnnotationItemRenderer(coordinates),
            LinearGeometry(),
        )
        view.set_selection_enabled(True)
        view.set_editing_enabled(True)
        view.resize(900, 700)
        view.show()
        self.app.processEvents()

        def release():
            if isValid(view):
                view.cleanup()
                view.close()
                delete(view)

        self.addCleanup(release)
        return view

    def _mouse(self, view, event_type, viewport_pos, buttons):
        viewport = view.viewport()
        local = QtCore.QPointF(viewport_pos)
        button = (
            QtCore.Qt.MouseButton.NoButton
            if event_type == QtCore.QEvent.Type.MouseMove
            else QtCore.Qt.MouseButton.LeftButton
        )
        QtWidgets.QApplication.sendEvent(
            viewport,
            QtGui.QMouseEvent(
                event_type,
                local,
                local,
                QtCore.QPointF(viewport.mapToGlobal(viewport_pos)),
                button,
                buttons,
                QtCore.Qt.KeyboardModifier.NoModifier,
            ),
        )

    def _viewport_pos(self, view, point):
        return view.mapFromScene(view._ost_to_scene_pos(*point))

    @staticmethod
    def _guides(view):
        lines = [
            item.line()
            for item in view._intelligent_paste_guide_items
            if item.scene() is view._scene
        ]
        horizontal = sum(
            1 for line in lines if line.y1() == line.y2() and line.x1() != line.x2()
        )
        vertical = sum(
            1 for line in lines if line.x1() == line.x2() and line.y1() != line.y2()
        )
        stale = sum(
            1
            for item in view._scene.items()
            if isinstance(item, QGraphicsLineItem)
            and item.zValue() == 1000
            and item not in view._intelligent_paste_guide_items
        )
        return horizontal, vertical, stale

    def _paste(self, view, page, clipboard_order, grab_uid):
        originals = _takeoffs()
        annotations = _annotations()
        copied = [originals[uid] for uid in clipboard_order if uid in originals]
        copied_uids = {takeoff.uid for takeoff in copied}
        copied += [
            originals[uid]
            for uid in sorted(originals)
            if originals[uid].parent_uid in copied_uids and uid not in copied_uids
        ]
        clipboard = SelectionClipboardService()
        clipboard.copy(
            copied,
            [annotations[uid] for uid in clipboard_order if uid in annotations],
            source_bid_uid="7",
            source_file_path="paste.mdb",
            takeoff_extras={},
            conditions=CONDITIONS,
        )
        items = list(clipboard.items)
        regulars = [takeoff for takeoff in items if not takeoff.is_hole]
        holes = [takeoff for takeoff in items if takeoff.is_hole]
        pasted_annotations = list(clipboard.annotations)
        view.load_page(
            page,
            list(originals.values()),
            CONDITIONS,
            COLORS,
            annotations=list(annotations.values()),
        )
        self.app.processEvents()
        handler = PlanViewActionHandler.__new__(PlanViewActionHandler)
        handler._plan_view = view
        expected_anchor = handler._paste_source_anchor(regulars, pasted_annotations)
        view._last_mouse_vp_pos = self._viewport_pos(
            view,
            (expected_anchor[0] + PASTE_OFFSET, expected_anchor[1] + PASTE_OFFSET),
        )
        dx, dy, source_anchor = handler._paste_translation(regulars, pasted_annotations)
        self.assertEqual(source_anchor, expected_anchor)
        pasted_anchor = offset_paste_anchor(source_anchor, dx, dy)
        takeoff_map = {
            str(takeoff.uid): str(9000 + index)
            for index, takeoff in enumerate(regulars + holes)
        }
        pasted = [
            replace(
                takeoff,
                uid=takeoff_map[takeoff.uid],
                parent_uid=takeoff_map.get(takeoff.parent_uid, takeoff.parent_uid),
                position=handler._translate_position(takeoff.position, dx, dy),
            )
            for takeoff in regulars + holes
        ]
        annotation_map = {
            annotation.uid: f"b{index + 1}"
            for index, annotation in enumerate(pasted_annotations)
        }
        pasted_annotation_items = [
            replace(
                annotation,
                uid=annotation_map[annotation.uid],
                position=translate_annotation_position(annotation, dx, dy),
            )
            for annotation in pasted_annotations
        ]
        sorted_map = dict(sorted(takeoff_map.items()))

        def reload_and_mark():
            view.load_page(
                page,
                list(_takeoffs().values())
                + [replace(t, position=list(t.position)) for t in pasted],
                CONDITIONS,
                COLORS,
                annotations=list(_annotations().values())
                + [
                    replace(a, position=list(a.position))
                    for a in pasted_annotation_items
                ],
            )
            self.app.processEvents()
            selected = set(sorted_map.values())
            selected.update(
                view.find_annotation_keys_by_uid_type(
                    {
                        (annotation_map[a.uid], a.annotation_type)
                        for a in pasted_annotations
                    }
                )
            )
            view.set_selected_uids(selected)
            ordered = list(sorted_map.values())
            ordered.extend(sorted(selected.difference(ordered)))
            self.assertTrue(
                view.mark_intelligent_paste_drag_pending(
                    ordered, source_anchor, pasted_anchor_ost=pasted_anchor
                )
            )

        if grab_uid in originals:
            grab_source = _grab_point(originals[grab_uid].position)
        else:
            source = annotations[grab_uid]
            grab_source = position_paste_anchor(source.position, source.is_ink)
        return reload_and_mark, grab_source, (dx, dy)

    def _drop(self, view, reload_and_mark, grab_source, delta, offset):
        reload_and_mark()
        grab = (grab_source[0] + delta[0], grab_source[1] + delta[1])
        view.centerOn(
            view._ost_to_scene_pos(
                (grab[0] + grab_source[0]) / 2, (grab[1] + grab_source[1]) / 2
            )
        )
        self.app.processEvents()
        start = self._viewport_pos(view, grab)
        aligned = self._viewport_pos(view, grab_source)
        left = QtCore.Qt.MouseButton.LeftButton
        applied = []
        snap = view.apply_intelligent_paste_axis_snap

        def record_snap(ost_dx, ost_dy):
            result = snap(ost_dx, ost_dy)
            applied.append(result)
            return result

        view.apply_intelligent_paste_axis_snap = record_snap
        self._mouse(view, QtCore.QEvent.Type.MouseButtonPress, start, left)
        self._mouse(
            view, QtCore.QEvent.Type.MouseMove, start + QtCore.QPoint(6, 6), left
        )
        target = aligned + QtCore.QPoint(*offset)
        self._mouse(view, QtCore.QEvent.Type.MouseMove, target, left)
        self.app.processEvents()
        self.assertTrue(view._intelligent_paste_active, offset)
        horizontal, vertical, stale = self._guides(view)
        self.assertTrue(applied)
        ost_dx, ost_dy = applied[-1]
        point = self._viewport_pos(view, (grab[0] + ost_dx, grab[1] + ost_dy)) - aligned
        self._mouse(
            view,
            QtCore.QEvent.Type.MouseButtonRelease,
            target,
            QtCore.Qt.MouseButton.NoButton,
        )
        self.app.processEvents()
        del view.apply_intelligent_paste_axis_snap
        self.assertEqual(stale, 0)
        return (horizontal, vertical), (point.x(), point.y())

    @staticmethod
    def _page(rotation=0, flip_x=False):
        return Page(
            uid="p1",
            name="P1",
            width_pts=2448.0,
            height_pts=1584.0,
            scale_factor1=0.125,
            scale_factor2=12.0,
            rotation=rotation,
            flip_x=flip_x,
        )

    def _assert_dropped_on_originals_shows_both_guides(self, clipboard_order, grab_uid):
        view = self._view()
        paste = self._paste(view, self._page(), clipboard_order, grab_uid)
        guides, snapped = self._drop(view, *paste, (0, 0))
        self.assertEqual(guides, (2, 2))
        self.assertEqual(snapped, (0, 0))

    def test_a_group_whose_first_copy_is_not_the_lowest_uid_shows_both_guides(self):
        self._assert_dropped_on_originals_shows_both_guides(["70", "40"], "70")

    def test_an_area_with_a_hole_shows_both_guides_on_the_originals(self):
        self._assert_dropped_on_originals_shows_both_guides(["30", "100"], "30")

    def test_an_ink_annotation_shows_both_guides_on_the_original(self):
        self._assert_dropped_on_originals_shows_both_guides(["a3"], "a3")

    def test_every_first_copied_item_of_a_mixed_selection_snaps_per_axis(self):
        selection = ["30", "100", "110", "40", "50", "70", "a1", "a2", "a3"]
        offsets = ((0, 0), (0, 5), (-6, 0), (3, -4), (0, 60), (60, 0), (40, -40))
        view = self._view()
        for first in range(len(selection)):
            order = selection[first:] + selection[:first]
            paste = self._paste(view, self._page(), order, "50")
            for offset in offsets:
                with self.subTest(first=order[0], offset=offset):
                    guides, snapped = self._drop(view, *paste, offset)
                    self.assertEqual(guides, _expected_guides(offset))
                    self.assertEqual(snapped, _expected_snapped(offset))

    def test_rotated_and_flipped_pages_snap_only_the_axis_whose_guides_show(self):
        offsets = ((0, 0), (0, 150), (150, 0), (-40, 3), (3, 12), (12, 12))
        view = self._view()
        for rotation in (0, 90, 180, 270):
            for flip_x in (False, True):
                paste = self._paste(view, self._page(rotation, flip_x), ["50"], "50")
                for offset in offsets:
                    with self.subTest(rotation=rotation, flip_x=flip_x, offset=offset):
                        guides, snapped = self._drop(view, *paste, offset)
                        self.assertEqual(guides, _expected_guides(offset))
                        self.assertEqual(snapped, _expected_snapped(offset))


class IntelligentPasteSnapIncrementTests(unittest.TestCase):
    """With snap on, the committed pasted group keeps the alignment the guides
    showed: the anchor lands on the source anchor on every guided axis."""

    _view = IntelligentPasteGuideTests._view
    _mouse = IntelligentPasteGuideTests._mouse
    _viewport_pos = IntelligentPasteGuideTests._viewport_pos
    _guides = staticmethod(IntelligentPasteGuideTests._guides)
    _paste = IntelligentPasteGuideTests._paste
    _page = staticmethod(IntelligentPasteGuideTests._page)

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _committed_anchor_offset(self, view, paste, offset):
        reload_and_mark, grab_source, delta = paste
        reload_and_mark()
        flushed = []
        view.positions_flushed.connect(
            lambda takeoffs, annotations: flushed.append((takeoffs, annotations))
        )
        grab = (grab_source[0] + delta[0], grab_source[1] + delta[1])
        view.centerOn(
            view._ost_to_scene_pos(
                (grab[0] + grab_source[0]) / 2, (grab[1] + grab_source[1]) / 2
            )
        )
        self.app.processEvents()
        start = self._viewport_pos(view, grab)
        aligned = self._viewport_pos(view, grab_source)
        left = QtCore.Qt.MouseButton.LeftButton
        self._mouse(view, QtCore.QEvent.Type.MouseButtonPress, start, left)
        self._mouse(
            view, QtCore.QEvent.Type.MouseMove, start + QtCore.QPoint(6, 6), left
        )
        target = aligned + QtCore.QPoint(*offset)
        self._mouse(view, QtCore.QEvent.Type.MouseMove, target, left)
        self.app.processEvents()
        horizontal, vertical, _stale = self._guides(view)
        self._mouse(
            view,
            QtCore.QEvent.Type.MouseButtonRelease,
            target,
            QtCore.Qt.MouseButton.NoButton,
        )
        self.app.processEvents()
        view.positions_flushed.disconnect()
        moves = [
            (new_pos[0] - old_pos[0], new_pos[1] - old_pos[1])
            for takeoffs, _annotations in flushed
            for _uid, old_pos, new_pos in takeoffs
        ]
        self.assertTrue(moves, offset)
        moved_dx, moved_dy = moves[0]
        for other_dx, other_dy in moves:
            self.assertAlmostEqual(other_dx, moved_dx, places=9)
            self.assertAlmostEqual(other_dy, moved_dy, places=9)
        source_anchor = view._ost_to_scene_pos(*grab_source)
        landed = view._ost_to_scene_pos(
            grab_source[0] + delta[0] + moved_dx,
            grab_source[1] + delta[1] + moved_dy,
        )
        return (
            (horizontal, vertical),
            landed.x() - source_anchor.x(),
            landed.y() - source_anchor.y(),
        )

    def _assert_guided_axes_land_on_the_source(self, page, order, grab_uid):
        view = self._view()
        for increment in (1.0, 7.0, 12.0, 25.0):
            view.set_snap_settings(increment, 0)
            paste = self._paste(view, page, order, grab_uid)
            for offset in ((0, 0), (0, 60), (60, 0), (3, -4)):
                with self.subTest(increment=increment, offset=offset):
                    guides, scene_dx, scene_dy = self._committed_anchor_offset(
                        view, paste, offset
                    )
                    if guides[0]:
                        self.assertAlmostEqual(scene_dy, 0.0, places=6)
                    if guides[1]:
                        self.assertAlmostEqual(scene_dx, 0.0, places=6)
                    self.assertTrue(any(guides), offset)

    def test_a_single_pasted_count_lands_aligned_with_snap_on(self):
        self._assert_guided_axes_land_on_the_source(self._page(), ["50"], "50")

    def test_a_pasted_area_and_line_land_aligned_with_snap_on(self):
        self._assert_guided_axes_land_on_the_source(self._page(), ["70", "40"], "70")

    def test_a_pasted_mixed_group_lands_aligned_with_snap_on(self):
        self._assert_guided_axes_land_on_the_source(
            self._page(), ["40", "50", "70", "a1", "a3"], "50"
        )

    def test_rotated_and_flipped_pages_land_aligned_with_snap_on(self):
        for rotation in (90, 180, 270):
            for flip_x in (False, True):
                with self.subTest(rotation=rotation, flip_x=flip_x):
                    self._assert_guided_axes_land_on_the_source(
                        self._page(rotation, flip_x), ["40", "50"], "50"
                    )


if __name__ == "__main__":
    unittest.main()
