import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.builders.annotation_view_builder import (
    AnnotationViewBuilder,
)
from ost_visualizer.domain.entities.workspace_state import (
    HeaderLayoutState,
    WorkspaceState,
)
from PySide6 import QtCore, QtWidgets
from tests.presentation.coordinators.workspace_restore_support import (
    _encoded_geometry as _detached_support__encoded_geometry,
)


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    def test_builder_wires_separate_annotation_and_view_window_state_providers(self):
        workspace_state = WorkspaceState()
        workspace_state.detached_windows.annotation_view.geometry_b64 = (
            _detached_support__encoded_geometry(b"annotation-geometry")
        )
        workspace_state.detached_windows.view_window.geometry_b64 = (
            _detached_support__encoded_geometry(b"view-geometry")
        )

        class Container:
            def get(self, key):
                if key == "workspace_state_model":
                    return SimpleNamespace(state=workspace_state)
                raise KeyError(key)

        builder = AnnotationViewBuilder.__new__(AnnotationViewBuilder)
        builder.container = Container()
        annotation_provider = builder._saved_window_state_provider("annotation")
        view_provider = builder._saved_window_state_provider("view")
        self.assertIs(
            annotation_provider(), workspace_state.detached_windows.annotation_view
        )
        self.assertIs(view_provider(), workspace_state.detached_windows.view_window)

    def test_builder_injects_canonical_access_owner_into_detached_managers(self):
        access_manager = object()
        services = {
            "project_data_service": object(),
            "config_model": object(),
            "icon_provider": object(),
            "main_window": object(),
            "ui_access_manager": access_manager,
        }
        factory_calls = []
        builder = AnnotationViewBuilder(
            container=SimpleNamespace(get=lambda key: services[key]),
            event_bus=object(),
            view_manager_factory=lambda **options: factory_calls.append(options)
            or object(),
            repository_factory=lambda: object(),
        )
        builder._create_shared_manager(
            repository=object(),
            view_kind="annotation",
        )
        self.assertIs(factory_calls[0]["ui_access_manager"], access_manager)
