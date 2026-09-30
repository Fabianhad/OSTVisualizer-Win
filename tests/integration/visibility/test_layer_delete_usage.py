import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.presentation.dialogs.master_data_support import (
    _app as _master_data_support__app,
)


class LayerDeleteUsageProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _layer(
        self, uid: str, name: str, sequence: int, *, show: bool = True
    ) -> BidLayer:
        return BidLayer(
            uid=uid,
            bid_uid="bid-1",
            name=name,
            show=show,
            sequence=sequence,
        )

    def test_layer_delete_confirmation_uses_current_annotation_ownership(self):
        from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
        from ost_visualizer.domain.entities.annotation import (
            ANNOTATION_TYPE_TEXT,
            BidAnnotation,
        )
        from ost_visualizer.domain.services.project_data_service import (
            ProjectDataService,
        )

        model = OstAggregate(None)
        data = ProjectDataService(model)
        sidebar = BidLayersSidebar(None)
        self.addCleanup(lambda: delete(sidebar))
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1)], {"layer-1"})
        sidebar.table.setCurrentItem(sidebar.table.topLevelItem(0))
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.project_data = data
        coordinator._sidebar = SimpleNamespace(bid_layers_sidebar=None)
        coordinator._toolbar = SimpleNamespace(
            set_bid_layers_sidebar=lambda widget: None
        )
        coordinator.set_bid_layers_sidebar(sidebar)
        original_row = sidebar.table.topLevelItem(0)
        usage_scans = []
        original_usage = data.get_layer_uids_in_use

        def usage():
            usage_scans.append(True)
            return original_usage()

        data.get_layer_uids_in_use = usage
        for label, annotations, in_use in (
            ("last annotation deleted", [], False),
            (
                "undo/recreate on another Page",
                [
                    BidAnnotation(
                        uid="a1",
                        annotation_type=ANNOTATION_TYPE_TEXT,
                        page_uid="other",
                        layer_uid="layer-1",
                    )
                ],
                True,
            ),
            (
                "move to another Layer",
                [
                    BidAnnotation(
                        uid="a1",
                        annotation_type=ANNOTATION_TYPE_TEXT,
                        page_uid="third",
                        layer_uid="layer-2",
                    )
                ],
                False,
            ),
            (
                "move back",
                [
                    BidAnnotation(
                        uid="a1",
                        annotation_type=ANNOTATION_TYPE_TEXT,
                        page_uid="other",
                        layer_uid="layer-1",
                    )
                ],
                True,
            ),
            ("redo deletion", [], False),
        ):
            with self.subTest(workflow=label):
                model.set_annotations(annotations)
                usage_scans.clear()
                with (
                    patch.object(QtWidgets.QMessageBox, "warning") as warning,
                    patch.object(
                        QtWidgets.QMessageBox,
                        "question",
                        return_value=QtWidgets.QMessageBox.StandardButton.No,
                    ) as question,
                ):
                    sidebar._delete_btn.click()
                self.assertEqual(warning.call_count, int(in_use))
                self.assertEqual(question.call_count, int(not in_use))
                self.assertIs(sidebar.table.currentItem(), original_row)
                self.assertEqual(len(usage_scans), 1)
        # An initially unused Layer must acquire the warning without a reload.
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1)], set())
        sidebar.table.setCurrentItem(sidebar.table.topLevelItem(0))
        model.set_annotations(
            [
                BidAnnotation(
                    uid="a2",
                    annotation_type=ANNOTATION_TYPE_TEXT,
                    page_uid="other",
                    layer_uid="layer-1",
                )
            ]
        )
        with (
            patch.object(QtWidgets.QMessageBox, "warning") as warning,
            patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.StandardButton.No,
            ) as question,
        ):
            sidebar._delete_btn.click()
        self.assertEqual(warning.call_count, 1)
        self.assertEqual(question.call_count, 0)
        from ost_visualizer.domain.entities.condition import Condition
        from ost_visualizer.domain.entities.page import Page
        from ost_visualizer.domain.entities.takeoff import Takeoff

        model.set_annotations([])
        model.bid_conditions = {"c1": Condition(uid="c1", layer_uid="layer-1")}
        page = Page(uid="other", name="Other")
        model.set_pages({"other": page})
        takeoff = Takeoff(uid="t1", condition_uid="c1", page_uid="other")
        for current in ([takeoff], [], [takeoff]):
            page.takeoffs = current
            with (
                patch.object(QtWidgets.QMessageBox, "warning") as warning,
                patch.object(
                    QtWidgets.QMessageBox,
                    "question",
                    return_value=QtWidgets.QMessageBox.StandardButton.No,
                ) as question,
            ):
                sidebar._delete_btn.click()
            self.assertEqual(warning.call_count, int(bool(current)))
            self.assertEqual(question.call_count, int(not current))
