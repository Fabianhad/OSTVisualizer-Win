import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.application.events.app_events import (
    AppEvents,
)
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.application.services.annotation_view_event_handler import (
    AnnotationViewEventHandler,
)


class AnnotationViewEventHandlerLifecycleTests(unittest.TestCase):
    def test_annotation_view_event_handler_shutdown_releases_cached_use_case_graph(
        self,
    ):
        event_bus = EventBus()
        events = []
        factory_calls = []
        retained = SimpleNamespace(execute_from_hotlink=events.append)

        def make_use_case():
            factory_calls.append("create")
            return retained

        handler = AnnotationViewEventHandler(
            event_bus=event_bus,
            use_case_factory=make_use_case,
            logger=logging.getLogger("test"),
        )
        self.addCleanup(handler.shutdown)
        handler.start()
        handler.start()
        self.assertEqual(factory_calls, [])
        event_bus.publish(
            AppEvents.HOTLINK_CLICKED,
            hotlink_uid="link",
            bid_page_uid="page",
            target_view_uid="view",
            position_x=1.25,
            position_y=-2.5,
        )
        event_bus.publish(
            AppEvents.HOTLINK_CLICKED, hotlink_uid="no-target", bid_page_uid="page"
        )
        self.assertEqual(factory_calls, ["create"])
        self.assertEqual(
            events,
            [
                AppEvents.HOTLINK_CLICKED("link", "page", "view", 1.25, -2.5),
                AppEvents.HOTLINK_CLICKED(hotlink_uid="no-target", bid_page_uid="page"),
            ],
        )
        handler.shutdown()
        event_bus.publish(
            AppEvents.HOTLINK_CLICKED, hotlink_uid="late", bid_page_uid="page"
        )
        self.assertEqual(len(events), 2)
        self.assertFalse(handler._subscribed)
        self.assertIsNone(handler._use_case)
        self.assertIsNone(handler._use_case_factory)
        self.assertIsNone(handler._event_bus)

    def test_failed_unsubscribe_retains_owner_for_retry(self):
        class RetryingBus(EventBus):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            def unsubscribe(self, event_type, callback):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("unsubscribe failed")
                super().unsubscribe(event_type, callback)

        bus = RetryingBus()
        events = []
        handler = AnnotationViewEventHandler(
            bus,
            lambda: SimpleNamespace(execute_from_hotlink=events.append),
            logging.getLogger("test"),
        )
        self.addCleanup(handler.shutdown)
        handler.start()
        bus.publish(AppEvents.HOTLINK_CLICKED, hotlink_uid="first", bid_page_uid="page")
        with self.assertRaisesRegex(RuntimeError, "unsubscribe failed"):
            handler.shutdown()
        bus.publish(
            AppEvents.HOTLINK_CLICKED, hotlink_uid="retained", bid_page_uid="page"
        )
        handler.shutdown()
        handler.shutdown()
        bus.publish(AppEvents.HOTLINK_CLICKED, hotlink_uid="late", bid_page_uid="page")
        self.assertEqual([event.hotlink_uid for event in events], ["first", "retained"])
        self.assertEqual(bus.attempts, 2)

    def test_factory_and_execution_failure_are_logged_without_disabling_next_event(
        self,
    ):
        for failure_stage in ("factory", "execute"):
            with self.subTest(stage=failure_stage):
                calls = []
                events = []
                bus = EventBus()

                def execute(event):
                    events.append(event.hotlink_uid)
                    if failure_stage == "execute" and len(events) == 1:
                        raise RuntimeError("failed execution")

                def factory():
                    calls.append("create")
                    if failure_stage == "factory" and len(calls) == 1:
                        raise RuntimeError("failed construction")
                    return SimpleNamespace(execute_from_hotlink=execute)

                handler = AnnotationViewEventHandler(
                    bus, factory, logging.getLogger("test")
                )
                self.addCleanup(handler.shutdown)
                handler.start()
                with self.assertLogs("test", level="ERROR"):
                    bus.publish(
                        AppEvents.HOTLINK_CLICKED,
                        hotlink_uid="first",
                        bid_page_uid="page",
                    )
                bus.publish(
                    AppEvents.HOTLINK_CLICKED, hotlink_uid="second", bid_page_uid="page"
                )
                self.assertEqual(
                    events,
                    ["second"] if failure_stage == "factory" else ["first", "second"],
                )
                self.assertEqual(len(calls), 2 if failure_stage == "factory" else 1)
