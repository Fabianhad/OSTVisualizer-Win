import unittest
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService


class AnnotationDeletionScopeTests(unittest.TestCase):
    def test_late_successful_replay_delete_notifies_peers_after_origin_history_clear(
        self,
    ):
        from ost_visualizer.presentation.services.undo_redo_service import (
            AnnotationHistoryTarget,
        )
        from ost_visualizer.domain.entities.identity_refs import BidRef
        from ost_visualizer.infrastructure.events.event_bus import EventBus
        from ost_visualizer.application.events.app_events import AppEvents

        bid = BidRef("one.mdb", "7")
        bus = EventBus()
        origin, peer = UndoRedoService(event_bus=bus), UndoRedoService(event_bus=bus)
        bus.subscribe(
            AppEvents.ANNOTATION_LIFETIMES_DELETED,
            peer.invalidate_deleted_annotation_lifetimes,
        )
        targets = [AnnotationHistoryTarget(bid, "p1", "text", "1") for _ in range(2)]
        for history, target in zip((origin, peer), targets):
            history.set_active_bid(bid)
            history.push_local(lambda: True, lambda: True, annotation_targets=(target,))
        origin.clear()
        origin.suspend_deleted_annotations(bid, (targets[0],))
        self.assertFalse(targets[1].available)
        self.assertFalse(origin.can_undo())
