import base64
import unittest
from types import SimpleNamespace
from ost_visualizer.application.builders.annotation_view_builder import (
    AnnotationViewBuilder,
)
from ost_visualizer.domain.entities.workspace_state import (
    WorkspaceState,
)
from ost_visualizer.application.service_container import ServiceContainer
from ost_visualizer.infrastructure.events.event_bus import EventBus


class AnnotationViewBuilderTests(unittest.TestCase):
    def test_builder_wires_separate_annotation_and_view_window_state_providers(self):
        workspace_state = WorkspaceState()
        workspace_state.detached_windows.annotation_view.geometry_b64 = (
            base64.b64encode(b"annotation-geometry").decode("ascii")
        )
        workspace_state.detached_windows.view_window.geometry_b64 = base64.b64encode(
            b"view-geometry"
        ).decode("ascii")
        container = ServiceContainer()
        model = SimpleNamespace(state=workspace_state)
        container.register_instance("workspace_state_model", model)
        builder = AnnotationViewBuilder(
            container=container,
            event_bus=EventBus(),
            view_manager_factory=lambda **_options: object(),
            repository_factory=object,
        )
        annotation_provider = builder._saved_window_state_provider("annotation")
        view_provider = builder._saved_window_state_provider("view")
        self.assertIs(
            annotation_provider(), workspace_state.detached_windows.annotation_view
        )
        self.assertIs(view_provider(), workspace_state.detached_windows.view_window)
        model.state = WorkspaceState()
        self.assertIs(
            annotation_provider(), model.state.detached_windows.annotation_view
        )
        self.assertIs(view_provider(), model.state.detached_windows.view_window)
        self.assertIsNone(builder._saved_window_state_provider("main"))

    def test_builder_injects_canonical_access_owner_into_detached_managers(self):
        access_manager = object()
        services = {
            "project_data_service": object(),
            "config_model": object(),
            "icon_provider": object(),
            "main_window": object(),
            "ui_access_manager": access_manager,
            "project_write_service": object(),
            "annotation_write_service": object(),
        }
        container = ServiceContainer()
        for name, value in services.items():
            container.register_instance(name, value)
        factory_calls = []
        managers = {}
        repositories = []

        def make_manager(**options):
            factory_calls.append(options)
            manager = object()
            managers[options["view_kind"]] = manager
            return manager

        def make_repository():
            repository = object()
            repositories.append(repository)
            return repository

        event_bus = EventBus()
        builder = AnnotationViewBuilder(
            container=container,
            event_bus=event_bus,
            view_manager_factory=make_manager,
            repository_factory=make_repository,
        )
        builder.build()
        self.addCleanup(container.get("annotation_view_event_handler").shutdown)
        self.assertEqual(factory_calls, [])
        use_case = container.get("open_annotation_view_use_case")
        self.assertIs(container.get("open_annotation_view_use_case"), use_case)
        self.assertEqual(len(repositories), 2)
        self.assertEqual(
            [options["view_kind"] for options in factory_calls],
            ["annotation", "view", "main"],
        )
        for options in factory_calls:
            with self.subTest(view_kind=options["view_kind"]):
                self.assertIs(options["event_bus"], event_bus)
                self.assertIs(
                    options["project_data_service"], services["project_data_service"]
                )
                self.assertIs(options["parent_window"], services["main_window"])
                self.assertIs(options["icon_provider"], services["icon_provider"])
                self.assertIs(options["config_model"], services["config_model"])
                self.assertIs(
                    options["ui_access_manager"],
                    None if options["view_kind"] == "main" else access_manager,
                )
                self.assertIsNone(options["saved_window_state_provider"])
        self.assertIs(factory_calls[0]["repository"], repositories[0])
        self.assertIs(factory_calls[1]["repository"], repositories[1])
        self.assertIsNone(factory_calls[2]["repository"])
        self.assertIs(
            factory_calls[0]["write_service"], services["project_write_service"]
        )
        self.assertIs(
            factory_calls[0]["annotation_write_service"],
            services["annotation_write_service"],
        )
        self.assertIsNone(factory_calls[1]["write_service"])
        self.assertIsNone(factory_calls[2]["write_service"])
        self.assertIsNone(factory_calls[1]["annotation_write_service"])
        self.assertIsNone(factory_calls[2]["annotation_write_service"])
        self.assertIs(use_case.view_manager, managers["annotation"])
        self.assertIs(use_case.view_window_manager, managers["view"])
        self.assertIs(use_case.main_view_manager, managers["main"])
