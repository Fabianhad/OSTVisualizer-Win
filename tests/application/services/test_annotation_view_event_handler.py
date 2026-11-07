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
        with self.assertNoLogs("test", level="DEBUG"):
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
        with self.assertNoLogs("test", level="DEBUG"):
            bus.publish(
                AppEvents.HOTLINK_CLICKED, hotlink_uid="late", bid_page_uid="page"
            )
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

    def test_shutdown_removes_exactly_the_handlers_own_subscription_and_leaves_others(
        self,
    ):
        bus = EventBus()
        other_received = []
        bus.subscribe(
            AppEvents.HOTLINK_CLICKED,
            lambda **payload: other_received.append(payload["hotlink_uid"]),
        )
        handler = AnnotationViewEventHandler(
            bus,
            lambda: SimpleNamespace(execute_from_hotlink=lambda event: None),
            logging.getLogger("test-annotation-shutdown"),
        )
        handler.start()
        self.assertEqual(len(bus._subscribers[AppEvents.HOTLINK_CLICKED]), 2)
        handler.shutdown()
        self.assertEqual(len(bus._subscribers[AppEvents.HOTLINK_CLICKED]), 1)
        with self.assertNoLogs("test-annotation-shutdown", level="DEBUG"):
            bus.publish(
                AppEvents.HOTLINK_CLICKED, hotlink_uid="late", bid_page_uid="page"
            )
        self.assertEqual(other_received, ["late"])


class AnnotationViewEventHandlerDefaultsAndErrorTests(unittest.TestCase):
    class _Logger:
        def __init__(self):
            self.messages = []

        def exception(self, message, *args):
            self.messages.append(message % args)

    def test_a_click_without_details_opens_nothing_particular_with_zero_positions_and_no_target(
        self,
    ):
        events = []
        handler = AnnotationViewEventHandler(
            event_bus=EventBus(),
            use_case_factory=lambda: SimpleNamespace(
                execute_from_hotlink=events.append
            ),
            logger=logging.getLogger("test"),
        )
        handler._on_hotlink_clicked()
        (event,) = events
        self.assertEqual(
            (
                event.hotlink_uid,
                event.bid_page_uid,
                event.target_view_uid,
                event.position_x,
                event.position_y,
            ),
            ("", "", None, 0, 0),
        )
        self.assertEqual((event.position_x, event.position_y), (0.0, 0.0))

    def test_a_failing_use_case_is_logged_once_and_later_clicks_still_work(self):
        calls = []

        def execute(event):
            calls.append(event.hotlink_uid)
            if event.hotlink_uid == "bad":
                raise RuntimeError("view failed")

        logger = self._Logger()
        bus = EventBus()
        handler = AnnotationViewEventHandler(
            event_bus=bus,
            use_case_factory=lambda: SimpleNamespace(execute_from_hotlink=execute),
            logger=logger,
        )
        self.addCleanup(handler.shutdown)
        handler.start()
        bus.publish(AppEvents.HOTLINK_CLICKED, hotlink_uid="bad", bid_page_uid="p")
        bus.publish(AppEvents.HOTLINK_CLICKED, hotlink_uid="good", bid_page_uid="p")
        self.assertEqual(calls, ["bad", "good"])
        self.assertEqual(logger.messages, ["Error handling HOTLINK_CLICKED"])

    def test_a_failing_use_case_factory_is_also_contained_and_retried_on_the_next_click(
        self,
    ):
        attempts = []

        def factory():
            attempts.append(1)
            raise RuntimeError("no graph")

        logger = self._Logger()
        handler = AnnotationViewEventHandler(
            event_bus=EventBus(), use_case_factory=factory, logger=logger
        )
        handler._on_hotlink_clicked(hotlink_uid="a")
        handler._on_hotlink_clicked(hotlink_uid="b")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(logger.messages), 2)
