import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.application.builders.service_builder import ServiceBuilder
from ost_visualizer.application.events.app_events import (
    AppEvents,
)
from ost_visualizer.application.service_container import ServiceContainer
from ost_visualizer.application.services.update_check_service import UpdateCheckService
from ost_visualizer.application.dtos.condition_summary_dtos import (
    ConditionSummaryGrouping,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service import CALC_COUNT


class FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.unsubscriptions.append((event_type, callback))


class FakeInfrastructureProvider:
    def get_icon_provider(self):
        return None

    def get_transaction_monitor(self):
        return SimpleNamespace(set_ost_status_callback=lambda _callback: None)

    def get_takeoff_domain_service(self):
        return object()

    def get_uom_service(self):
        return object()

    def get_visualization_provider(self, _takeoff_service):
        return object()

    def get_coordinate_transformer_factory(self):
        return SimpleNamespace(create=lambda: object())

    def get_color_service(self):
        return object()

    def get_pdf_exporter(
        self,
        _coord_system,
        _color_service,
        _takeoff_service,
        _uom_service,
        _annotation_caption_resolver,
    ):
        return object()

    def get_ost_exporter(self, _uom_service):
        return object()

    def get_osp_exporter(self, _uom_service, _version):
        return object()

    def get_ost_importer(self, conn_manager=None):
        _ = conn_manager
        return object()

    def get_osp_importer(self, conn_manager=None):
        _ = conn_manager
        return object()

    def get_database_creator(self):
        return object()

    def get_default_working_dir(self):
        return ""


class ServiceBuilderContractsTests(unittest.TestCase):
    def test_summary_csv_export_service_resolves_project_read_service_from_container(
        self,
    ):
        container = ServiceContainer()
        read_calls = []
        reader = SimpleNamespace(
            get_bid_areas=lambda path, bid: read_calls.append((path, bid)) or [],
        )
        container.register_instance("project_read_service", reader)
        container.register_instance("project_write_service", SimpleNamespace())
        container.register_instance(
            "reload_database_use_case",
            SimpleNamespace(
                execute=lambda: None,
                execute_after_write=lambda _database_id: None,
            ),
        )
        bid_ref = BidRef("summary.mdb", "7")
        condition = Condition(
            uid="condition",
            name="Fixtures",
            condition_type=Condition.TYPE_COUNT,
            calc_type1=CALC_COUNT,
        )
        bid = Bid("7", "Bid")
        project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_bid=lambda _ref: bid,
            get_bid_conditions=lambda: {condition.uid: condition},
            get_bid_condition_folders=lambda: {},
            get_all_takeoffs=lambda: [
                Takeoff("takeoff", condition.uid, page_uid="page", position=[1, 2])
            ],
            get_all_pages=lambda: [Page("page", "Sheet")],
        )
        ServiceBuilder(
            container=container,
            logger=logging.getLogger("test"),
            infrastructure_provider=FakeInfrastructureProvider(),
            scene_notifier=object(),
        ).build(
            config_model=SimpleNamespace(),
            project_data_service=project_data,
            project_operations_service=SimpleNamespace(),
            event_bus=FakeEventBus(),
            connection_manager=None,
            license_api_client=object(),
        )
        service = container.get("summary_csv_export_service")
        self.assertIs(container.get("summary_csv_export_service"), service)
        summary = service.build_current_summary(ConditionSummaryGrouping())
        self.assertEqual(read_calls, [("summary.mdb", "7")])
        self.assertEqual(
            [
                (node.condition_uid, node.values.name, node.values.quantity1)
                for node in summary.children
            ],
            [("condition", "Fixtures", 1.0)],
        )

    def test_ost_status_blocks_falsey_connection_manager(self):
        class _FalseyConnectionManager:
            def __init__(self):
                self.write_blocks = []

            def __bool__(self):
                return False

            def set_write_blocked(self, active):
                self.write_blocks.append(active)

        class _Signal:
            def connect(self, callback):
                self.callback = callback

        class _Signaler:
            def __init__(self):
                self.ost_changed = _Signal()

            def emit_status(self, active):
                self.ost_changed.callback(active)

        class _Monitor:
            def set_ost_status_callback(self, callback):
                self.callback = callback

        class _Provider(FakeInfrastructureProvider):
            def __init__(self, monitor):
                self.monitor = monitor

            def get_transaction_monitor(self):
                return self.monitor

        class _EventBus(FakeEventBus):
            def __init__(self):
                super().__init__()
                self.publications = []

            def publish(self, event_type, **payload):
                self.publications.append((event_type, payload))

        container = ServiceContainer()
        container.register_instance("project_read_service", SimpleNamespace())
        container.register_instance("project_write_service", SimpleNamespace())
        container.register_instance(
            "reload_database_use_case",
            SimpleNamespace(
                execute=lambda: None,
                execute_after_write=lambda _database_id: None,
            ),
        )
        connection_manager = _FalseyConnectionManager()
        monitor = _Monitor()
        event_bus = _EventBus()
        ServiceBuilder(
            container=container,
            logger=logging.getLogger("test"),
            infrastructure_provider=_Provider(monitor),
            scene_notifier=object(),
            ost_signaler=_Signaler(),
        ).build(
            config_model=SimpleNamespace(),
            project_data_service=SimpleNamespace(),
            project_operations_service=SimpleNamespace(),
            event_bus=event_bus,
            connection_manager=connection_manager,
            license_api_client=object(),
        )
        monitor.callback(True)
        monitor.callback(False)
        self.assertEqual(connection_manager.write_blocks, [True, False])
        self.assertEqual(
            event_bus.publications,
            [
                (AppEvents.OST_STATUS_CHANGED, {"active": True}),
                (AppEvents.OST_STATUS_CHANGED, {"active": False}),
            ],
        )


class ServiceBuilderRegistrationTests(unittest.TestCase):
    class _Recording(ServiceContainer):
        def __init__(self):
            super().__init__()
            self.instances = []
            self.singletons = []

        def register_instance(self, name, instance):
            self.instances.append(name)
            super().register_instance(name, instance)

        def register_singleton(self, name, factory):
            self.singletons.append(name)
            super().register_singleton(name, factory)

    def build(self, provider):
        container = self._Recording()
        for name in ("project_read_service", "project_write_service"):
            container.register_instance(name, SimpleNamespace())
        container.register_instance(
            "reload_database_use_case",
            SimpleNamespace(
                execute=lambda: None, execute_after_write=lambda _database_id: None
            ),
        )
        container.instances.clear()
        ServiceBuilder(
            container=container,
            logger=logging.getLogger("service-builder-test"),
            infrastructure_provider=provider,
            scene_notifier=object(),
        ).build(
            config_model=SimpleNamespace(),
            project_data_service=SimpleNamespace(),
            project_operations_service=SimpleNamespace(),
            event_bus=FakeEventBus(),
            connection_manager=None,
            license_api_client=object(),
        )
        return container

    def test_build_registers_exactly_these_instances_and_lazy_singletons_under_these_names(
        self,
    ):
        class Provider(FakeInfrastructureProvider):
            icon = object()

            def get_icon_provider(self):
                return self.icon

        container = self.build(Provider())
        # The contract is the set of registered names, not their order.
        self.assertCountEqual(
            container.instances,
            [
                "icon_provider",
                "transaction_monitor",
                "takeoff_domain_service",
                "uom_service",
                "visualization_provider",
                "coordinate_transformer_factory",
                "color_service",
                "pdf_exporter",
                "ost_exporter",
                "osp_exporter",
                "ost_importer",
                "osp_importer",
                "import_service",
                "working_directory_service",
            ],
        )
        self.assertCountEqual(
            container.singletons,
            [
                "file_loading_service",
                "config_service",
                "database_maintenance_service",
                "visualization_service",
                "page_visualization_metadata_service",
                "export_service",
                "summary_csv_export_service",
                "update_check_service",
            ],
        )
        self.assertIs(container.get("icon_provider"), Provider.icon)

    def test_an_absent_icon_provider_is_not_registered(self):
        container = self.build(FakeInfrastructureProvider())
        self.assertNotIn("icon_provider", container.instances)
        with self.assertRaises(KeyError):
            container.get("icon_provider")

    def test_infrastructure_products_are_registered_as_the_very_objects_the_provider_made(
        self,
    ):
        made = {}

        class Provider(FakeInfrastructureProvider):
            def _make(self, key):
                made[key] = object()
                return made[key]

            def get_takeoff_domain_service(self):
                return self._make("takeoff")

            def get_uom_service(self):
                return self._make("uom")

            def get_color_service(self):
                return self._make("color")

            def get_visualization_provider(self, _takeoff_service):
                return self._make("viz")

            def get_ost_exporter(self, _uom_service):
                return self._make("ost_exporter")

            def get_osp_exporter(self, _uom_service, _version):
                return self._make("osp_exporter")

            def get_ost_importer(self, conn_manager=None):
                return self._make("ost_importer")

            def get_osp_importer(self, conn_manager=None):
                return self._make("osp_importer")

        container = self.build(Provider())
        for name, key in (
            ("takeoff_domain_service", "takeoff"),
            ("uom_service", "uom"),
            ("color_service", "color"),
            ("visualization_provider", "viz"),
            ("ost_exporter", "ost_exporter"),
            ("osp_exporter", "osp_exporter"),
            ("ost_importer", "ost_importer"),
            ("osp_importer", "osp_importer"),
        ):
            with self.subTest(service=name):
                self.assertIs(container.get(name), made[key])

    def test_update_checks_use_the_given_client_and_a_named_child_logger(self):
        container = self.build(FakeInfrastructureProvider())
        service = container.get("update_check_service")
        self.assertEqual(service.logger.name, "service-builder-test.UpdateCheck")
        self.assertIsNotNone(service.api_client)
        self.assertEqual(
            container.get("import_service").logger.name,
            "service-builder-test.ImportService",
        )
        working = container.get("working_directory_service")
        self.assertEqual(working._logger.name, "service-builder-test.WorkingDirectory")


class ServiceBuilderLazyDependencyTests(unittest.TestCase):
    def test_dependent_singletons_resolve_their_dependencies_by_name_when_first_requested(
        self,
    ):
        class Provider(FakeInfrastructureProvider):
            def get_database_maintenance(self, connection_manager):
                return SimpleNamespace(connection_manager=connection_manager)

        container = ServiceBuilderRegistrationTests(
            "test_an_absent_icon_provider_is_not_registered"
        ).build(Provider())
        loading = container.get("file_loading_service")
        self.assertIs(container.get("file_loading_service"), loading)
        maintenance = container.get("database_maintenance_service")
        self.assertIs(container.get("database_maintenance_service"), maintenance)
        self.assertIs(maintenance._files, loading)
        metadata = container.get("page_visualization_metadata_service")
        export = container.get("export_service")
        self.assertIs(container.get("export_service"), export)
        self.assertIs(export._page_metadata, metadata)
        self.assertIs(container.get("page_visualization_metadata_service"), metadata)


class _Marker:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"<{self.name}>"


class _RecordingNotifier:
    def __init__(self):
        self.handlers = None

    def set_handlers(self, **handlers):
        self.handlers = handlers

    def cleanup(self):
        self.cleaned = True


class _WiringProvider(FakeInfrastructureProvider):
    """Every product is a distinct, named object so argument order is observable."""

    def __init__(self):
        self.monitor = SimpleNamespace(
            set_ost_status_callback=lambda _callback: None,
            stop_monitoring=lambda: None,
            cleanup=lambda: None,
        )
        self.takeoff = _Marker("takeoff service")
        self.uom = _Marker("uom service")
        self.color = _Marker("color service")
        self.coordinate_system = _Marker("coordinate system")
        self.registry = _Marker("descriptor registry")
        self.bridge = _Marker("callback bridge")
        self.maintenance = _Marker("maintenance")
        self.calls = {}
        provider = self

        class _Visualization(_Marker):
            def get_mesh_generator(self):
                return provider

        self.visualization = _Visualization("visualization provider")

    def get_transaction_monitor(self):
        return self.monitor

    def get_takeoff_domain_service(self):
        return self.takeoff

    def get_uom_service(self):
        return self.uom

    def get_color_service(self):
        return self.color

    def get_visualization_provider(self, takeoff_service):
        self.calls["visualization_provider"] = (takeoff_service,)
        return self.visualization

    def get_coordinate_transformer_factory(self):
        return SimpleNamespace(create=lambda: self.coordinate_system)

    def get_database_descriptor_registry(self):
        return self.registry

    def get_thread_callback_bridge(self):
        return self.bridge

    def get_database_maintenance(self, connection_manager):
        self.calls["maintenance"] = (connection_manager,)
        return self.maintenance

    def get_pdf_exporter(self, *args):
        self.calls["pdf_exporter"] = args
        return _Marker("pdf exporter")

    def get_ost_exporter(self, *args):
        self.calls["ost_exporter"] = args
        return _Marker("ost exporter")

    def get_osp_exporter(self, *args):
        self.calls["osp_exporter"] = args
        return _Marker("osp exporter")

    def get_ost_importer(self, conn_manager=None):
        self.calls["ost_importer"] = (conn_manager,)
        return _Marker("ost importer")

    def get_osp_importer(self, conn_manager=None):
        self.calls["osp_importer"] = (conn_manager,)
        return _Marker("osp importer")


class ServiceBuilderArgumentWiringTests(unittest.TestCase):
    """Each service must receive each collaborator in the right position."""

    def setUp(self):
        self.provider = _WiringProvider()
        self.config_model = _Marker("config model")
        self.project_data = _Marker("project data")
        self.project_ops = _Marker("project operations")
        self.event_bus = FakeEventBus()
        self.connection_manager = _Marker("connection manager")
        self.notifier = _RecordingNotifier()
        self.container = ServiceContainer()
        for name in ("project_read_service", "project_write_service"):
            self.container.register_instance(name, SimpleNamespace())
        self.container.register_instance(
            "reload_database_use_case",
            SimpleNamespace(execute=lambda: None, execute_after_write=lambda _id: None),
        )
        ServiceBuilder(
            container=self.container,
            logger=logging.getLogger("wiring-test"),
            infrastructure_provider=self.provider,
            scene_notifier=self.notifier,
        ).build(
            config_model=self.config_model,
            project_data_service=self.project_data,
            project_operations_service=self.project_ops,
            event_bus=self.event_bus,
            connection_manager=self.connection_manager,
            license_api_client=_Marker("license client"),
        )

    def test_file_loading_and_config_services_receive_their_own_collaborators(self):
        loading = self.container.get("file_loading_service")
        self.assertIs(loading.operations_service, self.project_ops)
        self.assertIs(loading.data_service, self.project_data)
        config = self.container.get("config_service")
        self.assertIs(config.config_model, self.config_model)
        self.assertIs(config.event_bus, self.event_bus)

    def test_the_visualization_service_gets_every_collaborator_including_the_scene_notifier(
        self,
    ):
        service = self.container.get("visualization_service")
        self.addCleanup(service.cleanup)
        self.assertIs(self.container.get("visualization_service"), service)
        self.assertIs(service.config_model, self.config_model)
        self.assertIs(service.project_data, self.project_data)
        self.assertIs(service.project_operations, self.project_ops)
        self.assertIs(service.event_bus, self.event_bus)
        self.assertIs(service._transaction_monitor, self.provider.monitor)
        self.assertIs(service._database_descriptor_registry, self.provider.registry)
        self.assertIs(service._callback_bridge, self.provider.bridge)
        self.assertIs(service._visualization_provider, self.provider.visualization)
        # The scene notifier is both stored and handed the service's handlers.
        self.assertIs(service._scene_notifier, self.notifier)
        self.assertEqual(
            set(self.notifier.handlers), {"on_scene_ready", "on_full_refresh"}
        )

    def test_export_and_maintenance_services_receive_their_own_collaborators(self):
        metadata = self.container.get("page_visualization_metadata_service")
        export = self.container.get("export_service")
        self.assertIs(export._provider, self.provider.visualization)
        self.assertIs(export.project_data, self.project_data)
        self.assertIs(export._page_metadata, metadata)
        self.container.get("database_maintenance_service")
        self.assertEqual(self.provider.calls["maintenance"], (self.connection_manager,))

    def test_exporters_and_importers_are_created_with_the_matching_infrastructure_services(
        self,
    ):
        pdf = self.provider.calls["pdf_exporter"]
        self.assertEqual(len(pdf), 5)
        self.assertIs(pdf[0], self.provider.coordinate_system)
        self.assertIs(pdf[1], self.provider.color)
        self.assertIs(pdf[2], self.provider.takeoff)
        self.assertIs(pdf[3], self.provider.uom)
        self.assertEqual(type(pdf[4]).__name__, "AnnotationCaptionResolver")
        self.assertIs(pdf[4]._uom_service, self.provider.uom)
        self.assertEqual(self.provider.calls["ost_exporter"], (self.provider.uom,))
        self.assertEqual(
            self.provider.calls["osp_exporter"],
            (self.provider.uom, UpdateCheckService.CURRENT_VERSION),
        )
        self.assertEqual(
            self.provider.calls["visualization_provider"], (self.provider.takeoff,)
        )
        for name in ("ost_importer", "osp_importer"):
            self.assertEqual(self.provider.calls[name], (self.connection_manager,))
