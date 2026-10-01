import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.application.builders.service_builder import ServiceBuilder
from ost_visualizer.application.events.app_events import (
    AppEvents,
)
from ost_visualizer.application.service_container import ServiceContainer
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
