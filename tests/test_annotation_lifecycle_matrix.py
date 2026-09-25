import math
import unittest
from PySide6 import QtCore, QtWidgets
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.infrastructure.mdb.components.serialization import (
    serialize_position_for_table,
    parse_position_storage,
)
from ost_visualizer.domain.services.page_scale_transform import (
    rescale_annotation_position_between_page_scales,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_dimension_geometry,
    format_dimension_distance,
)
from tests import test_plan_annotation_placement_keyboard as qt_fixtures


class _PlanFixture:
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_view(self, detached=False):
        fixture = qt_fixtures.AnnotationPlacementKeyboardTests()
        fixture.app = self.app
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture.make_view(detached=detached)


class DimensionLifecycleTests(_PlanFixture, unittest.TestCase):
    def test_dimension_fractional_roundtrip_does_not_quantize_model_geometry(self):
        for position in (
            [1 / 64, -1 / 25.4, 31 / 64, 2 / 25.4],
            [10.1234567, -100.7654321, 10000.1234567, -4.0123456],
        ):
            with self.subTest(position=position):
                self.assertEqual(
                    parse_position_storage(
                        serialize_position_for_table("BidDimensions", position)
                    ),
                    position,
                )

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

    def test_dimension_measurement_and_scale_do_not_depend_on_render_transform(self):
        for length in (1 / 64, 1 / 25.4, 1, 12, 100000.125):
            for angle in (0, math.pi / 2, 0.37):
                position = [
                    -12.0,
                    -7.0,
                    -12 + length * math.cos(angle),
                    -7 + length * math.sin(angle),
                ]
                original = list(position)
                ann = BidAnnotation("1", "dimension", position=position)
                for factor in (0.1, 1, 8):
                    for flip in (-1, 1):
                        transform = lambda points: [factor * flip * v for v in points]
                        geometry = calculate_dimension_geometry(
                            ann, position, transform
                        )
                        self.assertEqual(
                            geometry["label"],
                            format_dimension_distance(
                                math.hypot(
                                    position[2] - position[0], position[3] - position[1]
                                )
                            ),
                        )
                        self.assertEqual(
                            [geometry[k] for k in ("x1", "y1", "x2", "y2")],
                            transform(position),
                        )
                for _ in range(20):
                    position = rescale_annotation_position_between_page_scales(
                        "dimension", position, (1, 48), (1, 96)
                    )
                    geometry = calculate_dimension_geometry(ann, position, list)
                    self.assertEqual(
                        geometry["label"],
                        format_dimension_distance(
                            math.hypot(
                                position[2] - position[0], position[3] - position[1]
                            )
                        ),
                    )
                    position = rescale_annotation_position_between_page_scales(
                        "dimension", position, (1, 96), (1, 48)
                    )
                self.assertEqual(position, original)


class AnnotationFamilyGeometryTests(unittest.TestCase):
    POSITIONS = {
        "line": [10.015625, -20.03937007874, 40.015625, 60.7654321],
        "arrow": [10.015625, -20.03937007874, 40.015625, 60.7654321],
        "dimension": [10.015625, -20.03937007874, 40.015625, 60.7654321],
        "rect": [10.015625, -20.03937007874, 40.015625, 60.7654321],
        "oval": [10.015625, -20.03937007874, 40.015625, 60.7654321, math.pi / 7],
        "polygon": [
            10.015625,
            -20.03937007874,
            40.015625,
            60.7654321,
            80.1234567,
            30.7654321,
        ],
        "cloud": [
            10.015625,
            -20.03937007874,
            40.015625,
            60.7654321,
            80.1234567,
            30.7654321,
        ],
        "ink": [
            math.pi / 7,
            10.015625,
            -20.03937007874,
            40.015625,
            60.7654321,
            80.1234567,
            30.7654321,
        ],
        "highlight": [10.015625, -20.03937007874, 40.015625, 60.7654321],
        "namedview": [
            10.015625,
            20.7654321,
            40.015625,
            20.7654321,
            40.015625,
            60.7654321,
            10.015625,
            60.7654321,
        ],
        "hotlink": [10.015625, -20.03937007874],
        "callout": [10.015625, -20.03937007874, 40.015625, 60.7654321, math.pi / 7],
        "text": [10.015625, -20.03937007874, 40.015625, 60.7654321, math.pi / 7],
    }

    def test_each_family_storage_preserves_fractional_geometry(self):
        from ost_visualizer.infrastructure.database.annotation_storage import (
            ANNOTATION_TABLE_BY_TYPE,
        )

        self.assertEqual(set(self.POSITIONS), set(ANNOTATION_TABLE_BY_TYPE))
        for kind, position in self.POSITIONS.items():
            with self.subTest(kind=kind):
                stored = serialize_position_for_table(
                    ANNOTATION_TABLE_BY_TYPE[kind], position
                )
                self.assertEqual(parse_position_storage(stored), position)

    def test_copy_translation_and_scale_preserve_angles_and_dimensions(self):
        from ost_visualizer.domain.entities.annotation import annotation_rotation_index
        from ost_visualizer.presentation.utils.annotation_paste import (
            translate_annotation_position,
        )

        for kind, position in self.POSITIONS.items():
            with self.subTest(kind=kind):
                annotation = BidAnnotation("1", kind, position=list(position))
                moved = translate_annotation_position(annotation, 1 / 64, -1 / 32)
                rotation = annotation_rotation_index(kind, position)
                if rotation is not None:
                    self.assertEqual(moved[rotation], position[rotation])
                if kind == "text":
                    self.assertEqual(moved[2:], position[2:])
                annotation.position = moved
                self.assertEqual(
                    translate_annotation_position(annotation, -1 / 64, 1 / 32), position
                )
                scaled = rescale_annotation_position_between_page_scales(
                    kind, position, (1, 48), (1, 96)
                )
                if rotation is not None:
                    self.assertEqual(scaled[rotation], position[rotation])
                self.assertEqual(
                    rescale_annotation_position_between_page_scales(
                        kind, scaled, (1, 96), (1, 48)
                    ),
                    position,
                )


class BoxPlacementBoundaryTests(_PlanFixture, unittest.TestCase):
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


class AnnotationDragPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_view(self):
        from tests import test_viewer_sync_coordinator_overlay_refresh as fixtures

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
        view._snap_increments = 1.0
        view._drag_handle_index = 2
        view._unrotate_annotation_for_resize(annotation, "oval")
        candidate = view._compute_ann_resize(
            annotation, list(annotation.position), 0.0, 10.0, 2, 4
        )
        view.update_drag_handle_positions(candidate, "oval", 0.0, 10.0)
        reconstructed = BidAnnotation("oval", "oval", position=candidate)
        after, _ = renderer.create_all_annotation_items([("oval", reconstructed)])
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
                    position=list(AnnotationFamilyGeometryTests.POSITIONS[kind]),
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


class AnnotationFamilyHistoryTests(unittest.TestCase):
    def test_every_family_replays_after_restore_uid_reuse_and_scale(self):
        from tests import test_text_annotation_lifecycle as fixtures
        from ost_visualizer.presentation.utils.annotation_paste import (
            translate_annotation_position,
        )

        for sql in (False, True):
            for kind, position in AnnotationFamilyGeometryTests.POSITIONS.items():
                with self.subTest(sql=sql, kind=kind):
                    fixture = fixtures.TextAnnotationHistoryTests()
                    handler, data, writer, write, undo = fixture.make_handler(sql)
                    original = data.annotations[0]
                    original.annotation_type = kind
                    original.position = list(position)
                    handler._plan_view.annotation_key_map = {("a1", kind): "a1"}
                    after = translate_annotation_position(original, 1 / 64, 0.0)
                    handler.on_positions_flushed(
                        [], [("a1", kind, list(position), after)]
                    )
                    if sql:
                        fixture.complete_edit("position", data, write)
                    self.assertEqual(original.position, after)
                    handler.on_elements_deleted(["a1"])
                    if sql:
                        data.remove_annotations_by_keys([("a1", kind)])
                        write.queued_deletes[-1][-1](fixture.committed())
                    self.assertEqual(data.annotations, [])
                    for cycle in range(2):
                        writer.next_uids = [f"restored-{cycle}"]
                        undo.undo()
                        if sql:
                            db, payload, _options, callback = write.queued_pastes[-1]
                            result = write.execute_plan_items_paste_local(db, payload)
                            handler._project_mdb_plan_items_paste(
                                fixtures.action_fixtures.FakeUiState().get_selected_bid_ref(),
                                payload,
                                result,
                            )
                            callback(result)
                        restored = data.annotations[0]
                        self.assertEqual(restored.uid, f"restored-{cycle}")
                        reused = BidAnnotation(
                            "a1", kind, page_uid="p1", position=[999.0, 999.0]
                        )
                        data.annotations.append(reused)
                        data.pages["p1"].scale_factor2 = 2.0
                        undo.undo()
                        if sql:
                            fixture.complete_edit("position", data, write)
                        expected = rescale_annotation_position_between_page_scales(
                            kind, position, (1, 1), (1, 2)
                        )
                        self.assertEqual(restored.position, expected)
                        self.assertEqual(reused.position, [999.0, 999.0])
                        undo.redo()
                        if sql:
                            fixture.complete_edit("position", data, write)
                        self.assertEqual(
                            restored.position,
                            rescale_annotation_position_between_page_scales(
                                kind, after, (1, 1), (1, 2)
                            ),
                        )
                        undo.redo()
                        if sql:
                            data.remove_annotations_by_keys([(restored.uid, kind)])
                            write.queued_deletes[-1][-1](fixture.committed())
                        self.assertEqual(data.annotations, [reused])
                        data.annotations.clear()
                        data.pages["p1"].scale_factor2 = 1.0

    def test_family_scoped_late_sql_completion_does_not_repopulate_history(self):
        from tests import test_text_annotation_lifecycle as fixtures

        for kind, position in AnnotationFamilyGeometryTests.POSITIONS.items():
            with self.subTest(kind=kind):
                fixture = fixtures.TextAnnotationHistoryTests()
                handler, data, writer, write, undo = fixture.make_handler(True)
                original = data.annotations[0]
                original.annotation_type = kind
                original.position = list(position)
                handler._plan_view.annotation_key_map = {("a1", kind): "a1"}
                after = list(position)
                after[0] += 1.0
                handler.on_positions_flushed([], [("a1", kind, list(position), after)])
                undo.clear()
                fixture.complete_edit("position", data, write)
                self.assertFalse(undo.can_undo())


class AnnotationFamilyAccessTests(unittest.TestCase):
    def test_all_families_real_access_save_reload_and_batch_rollback(self):
        # Access has a process-wide client-task ceiling; follow the existing
        # live-MDB style test's isolated-process contract.
        import os
        import subprocess
        import sys

        if os.environ.get("OSTV_ANNOTATION_ACCESS_CHILD") != "1":
            environment = dict(os.environ, OSTV_ANNOTATION_ACCESS_CHILD="1")
            result = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "faulthandler",
                    "-m",
                    "unittest",
                    "tests." + self.id().removeprefix("tests."),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        import tempfile
        from pathlib import Path
        from tests import test_takeoff_text_style_persistence as fixtures
        from ost_visualizer.domain.entities.named_view import (
            normalize_named_view_position,
        )

        if not fixtures._access_available():
            self.skipTest("Access driver/DAO unavailable")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "annotation-families.mdb"
            self.assertTrue(
                fixtures.DatabaseCreator().create_database(path, "Annotation audit")
            )
            connections = fixtures.MdbConnectionManager()
            writer = fixtures.MdbWriter(connections)
            reader = fixtures.MdbReader(connections)
            try:
                bid = writer.create_bid(
                    str(path),
                    None,
                    {
                        "job_name": "Families",
                        "pages": [
                            {
                                "name": "Page",
                                "width": 42.0,
                                "height": 30.0,
                                "scale_factor1": 1.0,
                                "scale_factor2": 1.0,
                            }
                        ],
                    },
                )
                conn = fixtures.pyodbc.connect(
                    f"DRIVER={{{fixtures._ACCESS_DRIVER}}};DBQ={path};", autocommit=True
                )
                try:
                    page = str(
                        conn.cursor()
                        .execute("SELECT UID FROM BidPages WHERE BidUID=?", bid)
                        .fetchone()[0]
                    )
                finally:
                    conn.close()
                expected = {
                    kind: (
                        normalize_named_view_position(pos)
                        if kind == "namedview"
                        else list(pos)
                    )
                    for kind, pos in AnnotationFamilyGeometryTests.POSITIONS.items()
                }
                specs = [
                    fixtures.InsertAnnotationSpec(
                        page_uid=page,
                        annotation_type=kind,
                        position=list(pos),
                        color="#123456",
                        width=2.0,
                        properties={
                            "Text": "caf\u00e9",
                            "FontName": "Arial",
                            "FontSize": 17,
                            "FontColor": 0x563412,
                            "FontBold": True,
                            "FontItalic": True,
                            "FontUnderline": True,
                            "TextAlign": 2,
                        },
                    )
                    for kind, pos in expected.items()
                ]
                uids = writer.insert_annotations(str(path), bid, specs)
                self.assertEqual(len(uids), len(specs))

                def reload():
                    connections.close_database(str(path))
                    return {
                        a.annotation_type: a
                        for a in reader.get_bid_data(str(path), bid)[6]
                    }

                loaded = reload()
                self.assertEqual(set(loaded), set(expected))
                for kind, pos in expected.items():
                    with self.subTest(kind=kind):
                        self.assertEqual(loaded[kind].position, pos)
                        self.assertEqual(loaded[kind].page_uid, page)
                        self.assertEqual(loaded[kind].color.upper(), "#123456")
                updates = [
                    (loaded[kind].uid, kind, list(pos))
                    for kind, pos in expected.items()
                ]
                self.assertTrue(writer.save_annotation_positions(str(path), updates))
                self.assertEqual(
                    {kind: a.position for kind, a in reload().items()}, expected
                )
                # Missing member must reject the entire transaction.
                self.assertFalse(
                    writer.save_annotation_positions(
                        str(path),
                        [
                            (
                                loaded["dimension"].uid,
                                "dimension",
                                [1.0, 2.0, 3.0, 4.0],
                            ),
                            ("999999", "ink", [1.0, 2.0, 3.0, 4.0]),
                        ],
                    )
                )
                self.assertEqual(
                    {kind: a.position for kind, a in reload().items()}, expected
                )
                keys = [(a.uid, a.annotation_type) for a in loaded.values()]
                self.assertTrue(writer.delete_annotations(str(path), keys))
                self.assertEqual(reload(), {})
            finally:
                connections.close_database(str(path))


class AnnotationPlacementEventTests(_PlanFixture, unittest.TestCase):
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


class MixedAnnotationFailureTests(unittest.TestCase):
    def test_failed_restore_does_not_project_early_named_views(self):
        from tests import test_text_annotation_lifecycle as fixtures

        fixture = fixtures.TextAnnotationHistoryTests()
        handler, data, writer, write, undo = fixture.make_handler()
        data.annotations.clear()
        saved = [
            BidAnnotation(
                "n",
                "namedview",
                page_uid="p1",
                position=[0.0, 0.0, 10.0, 10.0],
                properties={"Text": "View"},
            ),
            BidAnnotation(
                "d", "dimension", page_uid="p1", position=[0.0, 0.0, 10.0, 0.0]
            ),
        ]
        original_insert = writer.insert_annotations

        def fail_dimension(path, bid, specs, *args, **options):
            if any(spec.annotation_type == "dimension" for spec in specs):
                return []
            return original_insert(path, bid, specs, *args, **options)

        writer.insert_annotations = fail_dimension
        restored = handler._annotation_writes.insert_saved_annotations(
            fixtures.action_fixtures.FakeUiState().get_selected_bid_ref(),
            saved,
            execute_paste=write.execute_plan_items_paste_local,
        )
        self.assertEqual(restored, [])
        self.assertEqual(data.annotations, [])

    def test_detached_copy_excludes_named_view_and_preserves_existing_link_target(self):
        from tests import test_detached_window_workspace_state as fixtures

        fixture = fixtures.DetachedPageViewManagerLifecycleTests()
        saved = [
            fixtures._named_view_annotation("view", "View"),
            fixtures._hotlink_annotation("link", "view"),
        ]
        window, plan, writer = fixture._make_annotation_clipboard_window(
            saved, undo_service=fixtures.FakeUndoService()
        )
        plan.set_selected_uids({"view", "link"})
        fixtures.DetachedPageViewWindow._on_copy_requested(window, ["view", "link"])
        fixtures.DetachedPageViewWindow._on_paste_requested(window)
        inserted = window._test_project_data.annotations[2:]
        self.assertEqual(len(inserted), 1)
        self.assertTrue(inserted[0].is_hotlink)
        self.assertEqual(inserted[0].hotlink_target_view_uid, "view")


class QueuedAnnotationSnapshotTests(unittest.TestCase):
    def test_each_family_queue_keeps_geometry_style_and_page_from_submission(self):
        from tests import test_mdb_sql_behavior_parity as fixtures
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.collaboration_resource_catalog import (
            annotation_resource_id,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )

        for kind, position in AnnotationFamilyGeometryTests.POSITIONS.items():
            with self.subTest(kind=kind):
                service, provider = (
                    fixtures.MdbSqlBehaviorParityTests._queued_project_service()
                )
                service._insert_annotations = fixtures._SequenceUseCase(["new"])
                spec = InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type=kind,
                    position=list(position),
                    color="#123456",
                    width=2.0,
                    properties={"Text": "Before"},
                )
                payload = PlanItemsPastePayload(
                    source_bid_uid="7",
                    destination_bid_uid="7",
                    annotation_source_uids=(annotation_resource_id(kind, "1"),),
                    annotation_specs=(spec,),
                )
                service.queue_plan_items_paste("database", payload, lambda _: None)
                request, execute, _callback = provider.requests[0]
                spec.page_uid = "p2"
                spec.position[0] = 999.0
                spec.properties["Text"] = "After"
                spec.color = "#ffffff"
                execute()
                captured = service._insert_annotations.calls[0][2][0]
                self.assertEqual(captured.page_uid, "p1")
                self.assertEqual(captured.position, position)
                self.assertEqual(captured.properties["Text"], "Before")
                self.assertEqual(captured.color, "#123456")
                self.assertEqual(
                    request.payload.annotation_specs[0].page_uid, request.page_uid
                )


class CrossFamilyReplayTests(unittest.TestCase):
    def test_same_uid_across_families_move_delete_restore_and_replay_remains_typed(
        self,
    ):
        from unittest.mock import patch
        from tests import test_text_annotation_lifecycle as fixtures
        from ost_visualizer.presentation.utils.annotation_paste import (
            translate_annotation_position,
        )

        fixture = fixtures.TextAnnotationHistoryTests()
        handler, data, writer, write, undo = fixture.make_handler()
        originals = [
            BidAnnotation(
                "1",
                kind,
                page_uid="p1",
                position=list(pos),
                properties={"Text": "View"},
            )
            for kind, pos in AnnotationFamilyGeometryTests.POSITIONS.items()
        ]
        data.annotations = originals
        handler._plan_view.annotations = {
            f"{a.annotation_type}:1": a for a in originals
        }
        handler._plan_view.annotation_key_map = {
            (a.uid, a.annotation_type): f"{a.annotation_type}:1" for a in originals
        }
        changes = [
            (
                a.uid,
                a.annotation_type,
                list(a.position),
                translate_annotation_position(a, 1 / 64, -1 / 32),
            )
            for a in originals
        ]
        before = {kind: position for _uid, kind, position, _after in changes}
        after = {kind: position for _uid, kind, _before, position in changes}
        handler.on_positions_flushed([], changes)
        self.assertEqual(
            {a.annotation_type: a.position for a in data.annotations}, after
        )
        handler.on_elements_deleted(list(handler._plan_view.annotations))
        self.assertEqual(data.annotations, [])
        for cycle in range(2):
            with patch.object(
                writer,
                "insert_annotations",
                side_effect=lambda _db, _bid, specs, *args: [
                    f"restored-{cycle}" for _ in specs
                ],
            ):
                undo.undo()
            self.assertEqual(len(data.annotations), len(originals))
            self.assertEqual({a.uid for a in data.annotations}, {f"restored-{cycle}"})
            reused = [
                BidAnnotation(
                    "1", a.annotation_type, page_uid="p1", position=[999.0, 999.0]
                )
                for a in originals
            ]
            data.annotations.extend(reused)
            undo.undo()
            self.assertEqual(
                {
                    a.annotation_type: a.position
                    for a in data.annotations
                    if a.uid != "1"
                },
                before,
            )
            undo.redo()
            self.assertEqual(
                {
                    a.annotation_type: a.position
                    for a in data.annotations
                    if a.uid != "1"
                },
                after,
            )
            self.assertTrue(all(a.position == [999.0, 999.0] for a in reused))
            undo.redo()
            self.assertEqual(data.annotations, reused)
            data.annotations.clear()

    def test_restore_failure_uses_one_application_mutation_and_no_success_event(self):
        from tests import test_text_annotation_lifecycle as fixtures
        from tests import test_mdb_sql_behavior_parity as parity

        fixture = fixtures.TextAnnotationHistoryTests()
        handler, data, _writer, _write, _undo = fixture.make_handler()
        data.annotations.clear()
        service = parity.MdbSqlBehaviorParityTests._local_composite_service()
        service._insert_annotations = parity._SequenceUseCase(
            ["new-view"], RuntimeError("second-family failure")
        )
        saved = [
            BidAnnotation("1", "namedview", page_uid="p1", position=[0, 0, 10, 10]),
            BidAnnotation("1", "dimension", page_uid="p1", position=[0, 0, 10, 0]),
        ]
        events = list(handler._event_bus.events)
        result = handler._annotation_writes.insert_saved_annotations(
            fixtures.action_fixtures.FakeUiState().get_selected_bid_ref(),
            saved,
            execute_paste=service.execute_plan_items_paste_local,
        )
        self.assertEqual(result, [])
        self.assertEqual(len(service.mutation_calls), 1)
        self.assertEqual(len(service._insert_annotations.calls), 2)
        self.assertEqual(data.annotations, [])
        self.assertEqual(handler._event_bus.events, events)
        self.assertEqual(service.reload_calls, [])
