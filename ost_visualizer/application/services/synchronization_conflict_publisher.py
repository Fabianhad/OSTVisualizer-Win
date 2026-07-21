from ..dtos.collaboration_dtos import (
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ..events.app_events import AppEvents
from ..interfaces.i_event_bus import IEventBus


def publish_synchronization_conflict(
    event_bus: IEventBus, conflict: SynchronizationConflict
) -> None:
    event_bus.publish(
        AppEvents.SYNCHRONIZATION_CONFLICT,
        database_id=conflict.database_id,
        resource_type=conflict.resource.resource_type,
        resource_id=conflict.resource.resource_id,
        bid_uid=str(conflict.resource.bid_uid or ""),
        message=conflict.reason,
        blocks_database=(conflict.kind == SynchronizationConflictKind.SESSION),
    )
