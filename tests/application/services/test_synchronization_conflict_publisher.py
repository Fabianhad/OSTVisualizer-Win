import unittest
from unittest.mock import Mock
from ost_visualizer.application.dtos.collaboration_dtos import (
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.interfaces.i_event_bus import IEventBus
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.application.services.synchronization_conflict_publisher import (
    publish_synchronization_conflict,
)


class PublishSynchronizationConflictTests(unittest.TestCase):
    def test_payload_keeps_resource_scope_and_only_session_conflicts_block_database(
        self,
    ):
        for kind in SynchronizationConflictKind:
            with self.subTest(kind=kind):
                bus = Mock(spec=IEventBus)
                conflict = SynchronizationConflict(
                    "database", ResourceRef("bid", "7", bid_uid=7), "changed", kind=kind
                )
                publish_synchronization_conflict(bus, conflict)
                bus.publish.assert_called_once_with(
                    AppEvents.SYNCHRONIZATION_CONFLICT,
                    database_id="database",
                    resource_type="bid",
                    resource_id="7",
                    bid_uid="7",
                    message="changed",
                    blocks_database=(kind == SynchronizationConflictKind.SESSION),
                )

    def test_global_resource_has_an_empty_bid_not_none(self):
        bus = Mock(spec=IEventBus)
        publish_synchronization_conflict(
            bus,
            SynchronizationConflict(
                "database", ResourceRef("database", "database"), "changed"
            ),
        )
        bus.publish.assert_called_once_with(
            AppEvents.SYNCHRONIZATION_CONFLICT,
            database_id="database",
            resource_type="database",
            resource_id="database",
            bid_uid="",
            message="changed",
            blocks_database=False,
        )
        # The publisher's output must construct its declared event contract.
        AppEvents.SYNCHRONIZATION_CONFLICT(**bus.publish.call_args.kwargs)


class PublishSynchronizationConflictThroughTheRealBusTests(unittest.TestCase):
    def _published(self, conflict):
        bus = EventBus()
        received = []
        bus.subscribe(
            AppEvents.SYNCHRONIZATION_CONFLICT,
            lambda **payload: received.append(payload),
        )
        publish_synchronization_conflict(bus, conflict)
        return received

    def test_each_conflict_kind_reaches_subscribers_with_its_literal_blocking_flag(
        self,
    ):
        blocking = {
            SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY: False,
            SynchronizationConflictKind.LEASE: False,
            SynchronizationConflictKind.SESSION: True,
        }
        self.assertEqual(set(blocking), set(SynchronizationConflictKind))
        for kind, expected in blocking.items():
            with self.subTest(kind=kind):
                received = self._published(
                    SynchronizationConflict(
                        "db-1",
                        ResourceRef("condition", "42", 8),
                        "Locked elsewhere",
                        kind=kind,
                    )
                )
                self.assertEqual(
                    received,
                    [
                        {
                            "database_id": "db-1",
                            "resource_type": "condition",
                            "resource_id": "42",
                            "bid_uid": "8",
                            "message": "Locked elsewhere",
                            "blocks_database": expected,
                            "draft_id": "",
                            "allowed_actions": [],
                        }
                    ],
                )

    def test_default_conflict_kind_is_optimistic_concurrency_and_not_blocking(self):
        conflict = SynchronizationConflict(
            "db-1", ResourceRef("database", "database"), "stale"
        )
        self.assertIs(conflict.kind, SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY)
        received = self._published(conflict)
        self.assertEqual(len(received), 1)
        self.assertIs(received[0]["blocks_database"], False)
        self.assertEqual(received[0]["bid_uid"], "")
