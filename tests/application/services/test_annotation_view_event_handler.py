import logging
import unittest
from ost_visualizer.application.events.app_events import (
    AppEvents,
    NativeSceneUpdatedEvent,
)
from ost_visualizer.application.services.annotation_view_event_handler import (
    AnnotationViewEventHandler,
)


class FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.unsubscriptions.append((event_type, callback))


class AnnotationViewEventHandlerLifecycleTests(unittest.TestCase):
    def test_annotation_view_event_handler_shutdown_releases_cached_use_case_graph(
        self,
    ):
        event_bus = FakeEventBus()
        retained = object()
        handler = AnnotationViewEventHandler(
            event_bus=event_bus,
            use_case_factory=lambda: retained,
            logger=logging.getLogger("test"),
        )
        handler.start()
        self.assertIs(handler._get_use_case(), retained)
        handler.shutdown()
        self.assertEqual(
            event_bus.unsubscriptions,
            [(AppEvents.HOTLINK_CLICKED, handler._on_hotlink_clicked)],
        )
        self.assertFalse(handler._subscribed)
        self.assertIsNone(handler._use_case)
        self.assertIsNone(handler._use_case_factory)
        self.assertIsNone(handler._event_bus)
