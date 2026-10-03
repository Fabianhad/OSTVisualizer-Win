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
        # Positive control: the peer's target is live before the deletion is
        # reported, so only the published event can make it unavailable.
        self.assertTrue(targets[1].available)
        self.assertTrue(targets[0].available)
        origin.clear()
        self.assertFalse(targets[0].available)
        self.assertFalse(origin.can_undo())
        origin.suspend_deleted_annotations(bid, (targets[0],))
        self.assertFalse(targets[1].available)
        self.assertFalse(origin.can_undo())

    def test_rebind_after_history_clear_does_not_resurrect_cleared_targets(self):
        from ost_visualizer.presentation.services.undo_redo_service import (
            AnnotationHistoryTarget,
        )
        from ost_visualizer.domain.entities.identity_refs import BidRef

        bid = BidRef("one.mdb", "7")
        history = UndoRedoService()
        history.set_active_bid(bid)
        target = AnnotationHistoryTarget(bid, "p1", "text", "1")
        history.push_local(lambda: True, lambda: True, annotation_targets=(target,))
        suspended = history.suspend_deleted_annotations(bid, (target,))
        self.assertEqual(suspended, (target,))
        self.assertFalse(target.available)
        # Positive control: while its entry is retained, a restore rebinds it.
        history.rebind_restored_annotations(bid, {target.identity: "10"}, suspended)
        self.assertEqual((target.uid, target.available), ("10", True))
        suspended = history.suspend_deleted_annotations(bid, (target,))
        history.clear()
        self.assertFalse(target.available)
        # After the history is cleared the target is no longer retained, so a late
        # restore must neither rebind its UID nor make it available again.
        history.rebind_restored_annotations(bid, {target.identity: "11"}, suspended)
        self.assertEqual((target.uid, target.available), ("10", False))
