import unittest
from unittest.mock import Mock
from ost_visualizer.application.dtos.collaboration_dtos import (
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.synchronization_conflict_publisher import (
    publish_synchronization_conflict,
)


class PublishSynchronizationConflictTests(unittest.TestCase):
    def test_payload_keeps_resource_scope_and_only_session_conflicts_block_database(
        self,
    ):
        for kind in SynchronizationConflictKind:
            with self.subTest(kind=kind):
                bus = Mock()
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
        bus = Mock()
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
