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
            # The committed drag is exactly one snap increment (1/64) long at the
            # snapped angle, independent of what the preview code returned.
            self.assertAlmostEqual(preview[0], 10.0)
            self.assertAlmostEqual(preview[1], 10.0)
            self.assertAlmostEqual(preview[2], 10 + math.cos(0.3) / 64)
            self.assertAlmostEqual(preview[3], 10 + math.sin(0.3) / 64)


class BoxPlacementBoundaryTests(_family_support__PlanFixture, unittest.TestCase):
    def test_minimum_fractional_box_commits(self):
        for kind in ("rect", "oval", "highlight", "text", "namedview"):
            with self.subTest(kind=kind):
                view = self.make_view()
                view._snap_increments = 1 / 25.4
                view.activate_annotation_placement(kind)
                created = []
                view.annotation_created.connect(
                    lambda kind, position, page: created.append((kind, position))
                )
                position = [10.0, 10.0, 10 + 1 / 25.4, 10 + 1 / 25.4]
                self.assertTrue(view._commit_annotation_placement(kind, position))
                if kind in ("text", "namedview"):
                    # Text-like boxes open an inline draft instead of emitting.
                    self.assertTrue(view.is_text_annotation_inline_edit_active())
                    self.assertEqual(created, [])
                else:
                    self.assertEqual(created, [(kind, position)])
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

    def test_placement_minimum_boundary_tracks_the_snap_increment(self):
        # Snap increment 1.0: linear kinds need a drag length of at least 1.0
        # (0.70 diagonal = 0.990, 0.71 diagonal = 1.004); box kinds need at
        # least 1.0 on each axis independently.
        linear = ("line", "arrow", "dimension", "ink")
        boxes = ("rect", "oval", "highlight", "text", "namedview")
        for kind, distance, expected in (
            *((kind, 0.70, False) for kind in linear),
            *((kind, 0.71, True) for kind in linear),
            *((kind, 0.99, False) for kind in boxes),
            *((kind, 1.0, True) for kind in boxes),
        ):
            with self.subTest(kind=kind, distance=distance):
                view = self.make_view()
                view._snap_increments = 1.0
                created = []
                view.annotation_created.connect(
                    lambda kind, position, page: created.append((kind, position))
                )
                position = [10.0, 10.0, 10.0 + distance, 10.0 + distance]
                self.assertEqual(
                    view._commit_annotation_placement(kind, position), expected
                )
                if kind in ("text", "namedview"):
                    # Accepted text-like boxes open a draft; nothing is emitted yet.
                    self.assertEqual(created, [])
                    self.assertEqual(
                        view.is_text_annotation_inline_edit_active(), expected
                    )
                    view._finish_active_inline_text_edit(commit=False)
                else:
                    self.assertEqual(created, [(kind, position)] if expected else [])

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

    def test_polygon_box_release_rejects_either_axis_below_minimum(self):
        from PySide6.QtGui import QMouseEvent

        minimum = 1 / 25.4
        for kind in ("polygon", "cloud"):
            for end in (
                (10 + minimum, 10 + minimum / 2),
                (10 + minimum / 2, 10 + minimum),
            ):
                with self.subTest(kind=kind, end=end):
                    view = self.make_view()
                    view._snap_increments = minimum
                    view.activate_annotation_placement(kind)
                    view._annotation_place_points = [(10.0, 10.0)]
                    view._annotation_area_rect_dragging = True
                    view._placement_snap_from_scene = lambda _, end=end: (
                        *end,
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
                    self.assertTrue(view.handle_annotation_place_release(event))
                    self.assertEqual(created, [])
                    self.assertFalse(view._annotation_area_rect_dragging)


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

        # Positive control: without Escape the same gesture completes and emits,
        # so the empty result below is caused by the cancel, not by the harness.
        for kind in ("line", "arrow", "dimension", "rect", "oval", "highlight"):
            with self.subTest(control=kind):
                view = self.make_view()
                created = []
                view.annotation_created.connect(
                    lambda kind, position, page: created.append((kind, position))
                )
                view.activate_annotation_placement(kind)
                QTest.mousePress(
                    view.viewport(),
                    QtCore.Qt.MouseButton.LeftButton,
                    pos=QtCore.QPoint(100, 100),
                )
                QTest.mouseMove(view.viewport(), QtCore.QPoint(150, 125))
                QTest.mouseRelease(
                    view.viewport(),
                    QtCore.Qt.MouseButton.LeftButton,
                    pos=QtCore.QPoint(150, 125),
                )
                self.assertEqual([item[0] for item in created], [kind])
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
