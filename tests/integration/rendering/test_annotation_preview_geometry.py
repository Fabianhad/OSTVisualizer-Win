import math
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
import tests.presentation.components.plan_view.test_view as view_fixtures
from PySide6 import QtCore, QtWidgets
from ost_visualizer.domain.entities.annotation import BidAnnotation
from tests.integration.annotations.family_support import (
    AnnotationFamilyGeometry as _family_support_AnnotationFamilyGeometry,
)


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

    def test_rotated_text_resize_preview_matches_unrotated_commit_contract(self):
        self.annotation.position = [10, 10, 80, 24, math.pi / 2]
        self.item.setRotation(90)
        self.view._snap_increments = 1
        self.view._drag_handle_index = 2
        self.view._unrotate_annotation_for_resize(self.annotation, "a1")
        resized = self.view._compute_ann_resize(
            self.annotation, list(self.annotation.position), 0, 10, 2, 4
        )
        self.view.update_drag_handle_positions(resized, "a1", 0, 10)
        self.assertEqual(resized, [10, 15, 80, 34, 0])
        self.assertEqual(self.item.rotation(), math.degrees(resized[4]))


class AnnotationDragPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_view(self):
        import tests.presentation.components.plan_view.test_view as fixtures

        fixture = fixtures.TakeoffPlanViewOverlayRefreshTests()
        self.addCleanup(fixture.doCleanups)
        return fixture._make_plan_view()

    def test_ink_body_preview_uses_snapped_candidate_not_raw_mouse_delta(self):
        from PySide6.QtGui import QTransform
        from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
            AnnotationItemRenderer,
        )

        for rotation in (0, 90, 180, 270):
            for prefix in ([], [math.pi / 7]):
                with self.subTest(rotation=rotation, prefix=prefix):
                    view = self.make_view()
                    cs = view._scene_builder.get_coordinate_system()
                    view._snap_increments = 1.0
                    annotation = BidAnnotation(
                        "ink",
                        "ink",
                        page_uid="p1",
                        position=prefix + [10.0, 10.0, 20.0, 20.0, 30.0, 10.0],
                    )
                    rendered, _ = AnnotationItemRenderer(
                        cs
                    ).create_all_annotation_items([("ink", annotation)])
                    item = rendered[0][0]
                    view._scene.addItem(item)
                    transform = QTransform().rotate(rotation)
                    view._current_page_transform = lambda: transform
                    item.setTransform(transform)
                    view._current_annotations = {"ink": annotation}
                    view._uid_to_items = {"ink": [item]}
                    view._drag_orig_position = list(annotation.position)
                    view._drag_handle_index = -1
                    view._drag_item_orig_positions = {id(item): item.pos()}
                    candidate = view._compute_ink_drag_position(
                        annotation.position, 0.6, 0.0
                    )
                    raw = view.ost_to_scene_delta(0.6, 0.0)
                    expected = view.ost_to_scene_delta(1.0, 0.0)
                    view.update_drag_handle_positions(candidate, "ink", *raw)
                    self.assertAlmostEqual(item.pos().x(), expected[0])
                    self.assertAlmostEqual(item.pos().y(), expected[1])
                    self.assertEqual(view._drag_last_valid_new_pos, candidate)

    def test_rotated_oval_resize_preview_equals_reconstructed_geometry(self):
        from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
            AnnotationItemRenderer,
        )
        from ost_visualizer.presentation.components.plan_view.components.input_handler import (
            _rotate_annotation,
        )

        view = self.make_view()
        cs = view._scene_builder.get_coordinate_system()
        annotation = BidAnnotation(
            "oval", "oval", page_uid="p1", position=[10.0, 10.0, 50.0, 30.0]
        )
        annotation.position = _rotate_annotation(
            annotation, annotation.position, 45.0, 30.0, 20.0
        )
        renderer = AnnotationItemRenderer(cs)
        rendered, _ = renderer.create_all_annotation_items([("oval", annotation)])
        item = rendered[0][0]
        view._scene.addItem(item)
        view._current_annotations = {"oval": annotation}
        view._uid_to_items = {"oval": [item]}
        self.assertAlmostEqual(item.rotation(), 45.0)
        view._snap_increments = 1.0
        view._drag_handle_index = 2
        view._unrotate_annotation_for_resize(annotation, "oval")
        candidate = view._compute_ann_resize(
            annotation, list(annotation.position), 0.0, 10.0, 2, 4
        )
        # Independent oracle for the resize itself: the unrotated 40x20 box
        # grows by the 10-unit handle drag along y.
        self.assertEqual(len(candidate), 4)
        for actual, expected in zip(candidate, [10.0, 10.0, 50.0, 40.0]):
            self.assertAlmostEqual(actual, expected)
        view.update_drag_handle_positions(candidate, "oval", 0.0, 10.0)
        reconstructed = BidAnnotation("oval", "oval", position=candidate)
        after, _ = renderer.create_all_annotation_items([("oval", reconstructed)])
        self.assertAlmostEqual(item.rotation(), 0.0)
        self.assertEqual(item.rotation(), after[0][0].rotation())
        self.assertEqual(
            item.mapToScene(item.path()), after[0][0].mapToScene(after[0][0].path())
        )

    def test_successive_body_previews_do_not_lag_one_mouse_event(self):
        from ost_visualizer.presentation.utils.annotation_paste import (
            translate_annotation_position,
        )
        from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
            AnnotationItemRenderer,
        )

        for kind in (
            "text",
            "rect",
            "oval",
            "highlight",
            "polygon",
            "cloud",
            "namedview",
            "hotlink",
        ):
            with self.subTest(kind=kind):
                view = self.make_view()
                cs = view._scene_builder.get_coordinate_system()
                ann = BidAnnotation(
                    "a",
                    kind,
                    page_uid="p1",
                    position=list(
                        _family_support_AnnotationFamilyGeometry.POSITIONS[kind]
                    ),
                    properties={"Text": "Example"},
                )
                rendered, _ = AnnotationItemRenderer(cs).create_all_annotation_items(
                    [("a", ann)]
                )
                self.assertTrue(rendered)
                items = [item for item, _ in rendered]
                for item in items:
                    view._scene.addItem(item)
                view._current_annotations = {"a": ann}
                view._uid_to_items = {"a": items}
                view._drag_orig_position = list(ann.position)
                view._drag_handle_index = -1
                origins = {id(item): item.pos() for item in items}
                view._drag_item_orig_positions = origins
                view._drag_last_valid_new_pos = list(ann.position)
                for delta in (1.0, 2.0, 0.0):
                    candidate = translate_annotation_position(ann, delta, 0.0)
                    view.update_drag_handle_positions(
                        candidate, "a", *view.ost_to_scene_delta(delta, 0.0)
                    )
                    expected = QtCore.QPointF(*view.ost_to_scene_delta(delta, 0.0))
                    for item in items:
                        self.assertEqual(item.pos(), origins[id(item)] + expected)
                    self.assertEqual(view._drag_last_valid_new_pos, candidate)

    def test_body_preview_of_boxed_and_polygon_kinds_uses_snapped_candidate(self):
        from ost_visualizer.presentation.utils.annotation_paste import (
            translate_annotation_position,
        )
        from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
            AnnotationItemRenderer,
        )

        for kind in (
            "text",
            "rect",
            "oval",
            "highlight",
            "polygon",
            "cloud",
            "namedview",
            "hotlink",
        ):
            with self.subTest(kind=kind):
                view = self.make_view()
                cs = view._scene_builder.get_coordinate_system()
                view._snap_increments = 1.0
                ann = BidAnnotation(
                    "a",
                    kind,
                    page_uid="p1",
                    position=list(
                        _family_support_AnnotationFamilyGeometry.POSITIONS[kind]
                    ),
                    properties={"Text": "Example"},
                )
                rendered, _ = AnnotationItemRenderer(cs).create_all_annotation_items(
                    [("a", ann)]
                )
                items = [item for item, _ in rendered]
                self.assertTrue(items)
                for item in items:
                    view._scene.addItem(item)
                view._current_annotations = {"a": ann}
                view._uid_to_items = {"a": items}
                view._drag_orig_position = list(ann.position)
                view._drag_handle_index = -1
                origins = {id(item): item.pos() for item in items}
                view._drag_item_orig_positions = origins
                # The mouse moved 0.6 units; the snapped candidate moved 1.0.
                candidate = translate_annotation_position(ann, 1.0, 0.0)
                raw = view.ost_to_scene_delta(0.6, 0.0)
                snapped = QtCore.QPointF(*view.ost_to_scene_delta(1.0, 0.0))
                self.assertNotAlmostEqual(raw[0], snapped.x())
                view.update_drag_handle_positions(candidate, "a", *raw)
                for item in items:
                    self.assertAlmostEqual(
                        item.pos().x(), origins[id(item)].x() + snapped.x()
                    )
                    self.assertAlmostEqual(
                        item.pos().y(), origins[id(item)].y() + snapped.y()
                    )
