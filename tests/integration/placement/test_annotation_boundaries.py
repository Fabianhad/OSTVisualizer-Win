import math
import unittest
from PySide6 import QtCore, QtWidgets
import tests.integration.placement.test_annotation_keyboard as qt_fixtures
from tests.integration.annotations.family_support import (
    _PlanFixture as _family_support__PlanFixture,
)


class DimensionLifecycleTests(_family_support__PlanFixture, unittest.TestCase):
    def test_minimum_snapped_diagonal_preview_can_commit(self):
        for detached in (False, True):
            view = self.make_view(detached)
            view._snap_increments = 1 / 64
            view._mouse_unpressed_snap_angle = 0
            view.activate_annotation_placement("dimension")
            view._annotation_place_points = [(10.0, 10.0)]
            view._annotation_place_dragging = True
            from ost_visualizer.presentation.components.plan_view.components.snap_index import (
                GRID,
            )

            view._placement_snap_from_scene = lambda _: (
                10 + math.cos(0.3) / 64,
                10 + math.sin(0.3) / 64,
                0,
                0,
                GRID,
            )
            preview, _ = view._drag_annotation_placement_position(QtCore.QPointF())
            created = []
            view.annotation_created.connect(
                lambda kind, position, page: created.append(
                    (kind, list(position), page)
                )
            )
            self.assertTrue(view._commit_annotation_placement("dimension", preview))
            self.assertEqual(created, [("dimension", preview, "p1")])


class BoxPlacementBoundaryTests(_family_support__PlanFixture, unittest.TestCase):
    def test_minimum_fractional_box_commits(self):
        for kind in ("rect", "oval", "highlight", "text", "namedview"):
            with self.subTest(kind=kind):
                view = self.make_view()
                view._snap_increments = 1 / 25.4
                view.activate_annotation_placement(kind)
                self.assertTrue(
                    view._commit_annotation_placement(
                        kind, [10.0, 10.0, 10 + 1 / 25.4, 10 + 1 / 25.4]
                    )
                )
                view._finish_active_inline_text_edit(commit=False)

    def test_zero_and_below_minimum_placements_remain_rejected(self):
        for kind in (
            "line",
            "arrow",
            "dimension",
            "rect",
            "oval",
            "highlight",
            "text",
            "namedview",
            "ink",
        ):
            for distance in (0.0, 0.49):
                with self.subTest(kind=kind, distance=distance):
                    view = self.make_view()
                    view._snap_increments = 1.0
                    self.assertFalse(
                        view._commit_annotation_placement(
                            kind, [10.0, 10.0, 10.0 + distance, 10.0 + distance]
                        )
                    )

    def test_polygon_box_release_accepts_minimum_fractional_box(self):
        from PySide6.QtGui import QMouseEvent

        for kind in ("polygon", "cloud"):
            with self.subTest(kind=kind):
                view = self.make_view()
                view._snap_increments = 1 / 25.4
                view.activate_annotation_placement(kind)
                view._annotation_place_points = [(10.0, 10.0)]
                view._annotation_area_rect_dragging = True
                view._placement_snap_from_scene = lambda _: (
                    10 + 1 / 25.4,
                    10 + 1 / 25.4,
                    0,
                    0,
                    0,
                )
                created = []
                view.annotation_created.connect(
                    lambda kind, position, page: created.append(list(position))
                )
                event = QMouseEvent(
                    QtCore.QEvent.Type.MouseButtonRelease,
                    QtCore.QPointF(50, 50),
                    QtCore.QPointF(50, 50),
                    QtCore.Qt.MouseButton.LeftButton,
                    QtCore.Qt.MouseButton.NoButton,
                    QtCore.Qt.KeyboardModifier.NoModifier,
                )
                view.handle_annotation_place_release(event)
                self.assertEqual(
                    created,
                    [
                        [
                            10.0,
                            10.0,
                            10 + 1 / 25.4,
                            10.0,
                            10 + 1 / 25.4,
                            10 + 1 / 25.4,
                            10.0,
                            10 + 1 / 25.4,
                        ]
                    ],
                )


class AnnotationPlacementEventTests(_family_support__PlanFixture, unittest.TestCase):
    def test_real_qt_drag_preview_matches_release_for_linear_families(self):
        from PySide6.QtTest import QTest
        from ost_visualizer.presentation.components.plan_view.components.snap_index import (
            GRID,
        )

        for detached in (False, True):
            for kind in ("dimension", "line", "arrow"):
                for increment in (1 / 64, 1 / 25.4, 1.0, 2.0):
                    with self.subTest(
                        detached=detached, kind=kind, increment=increment
                    ):
                        view = self.make_view(detached)
                        view._snap_increments = increment
                        view._mouse_unpressed_snap_angle = 0.0
                        endpoint = [10.0, 10.0]
                        view._placement_snap_from_scene = lambda _: (
                            *endpoint,
                            0,
                            0,
                            GRID,
                        )
                        created = []
                        view.annotation_created.connect(
                            lambda kind, position, page: created.append(list(position))
                        )
                        view.activate_annotation_placement(kind)
                        QTest.mousePress(
                            view.viewport(),
                            QtCore.Qt.MouseButton.LeftButton,
                            pos=QtCore.QPoint(100, 100),
                        )
                        endpoint[:] = [
                            10 + increment * math.cos(0.3),
                            10 + increment * math.sin(0.3),
                        ]
                        QTest.mouseMove(view.viewport(), QtCore.QPoint(150, 125))
                        preview, _ = view._drag_annotation_placement_position(
                            view.mapToScene(QtCore.QPoint(150, 125))
                        )
                        self.assertTrue(view._place_preview_items)
                        QTest.mouseRelease(
                            view.viewport(),
                            QtCore.Qt.MouseButton.LeftButton,
                            pos=QtCore.QPoint(150, 125),
                        )
                        self.assertEqual(created, [preview])
                        self.assertAlmostEqual(
                            math.hypot(
                                preview[2] - preview[0], preview[3] - preview[1]
                            ),
                            increment,
                        )

    def test_escape_cancels_each_started_annotation_without_persistence(self):
        from PySide6.QtTest import QTest
        from ost_visualizer.presentation.utils.annotation_defaults import (
            PLACEABLE_ANNOTATION_TYPES,
        )

        for kind in sorted(PLACEABLE_ANNOTATION_TYPES - {"hotlink"}):
            with self.subTest(kind=kind):
                view = self.make_view()
                created = []
                view.annotation_created.connect(lambda *args: created.append(args))
                view.text_annotation_created.connect(lambda *args: created.append(args))
                view.named_view_created.connect(lambda *args: created.append(args))
                view.activate_annotation_placement(kind)
                QTest.mousePress(
                    view.viewport(),
                    QtCore.Qt.MouseButton.LeftButton,
                    pos=QtCore.QPoint(100, 100),
                )
                QTest.mouseMove(view.viewport(), QtCore.QPoint(150, 125))
                QTest.keyClick(view, QtCore.Qt.Key.Key_Escape)
                QTest.mouseRelease(
                    view.viewport(),
                    QtCore.Qt.MouseButton.LeftButton,
                    pos=QtCore.QPoint(150, 125),
                )
                self.assertEqual(created, [])
                self.assertEqual(view._annotation_place_points, [])
