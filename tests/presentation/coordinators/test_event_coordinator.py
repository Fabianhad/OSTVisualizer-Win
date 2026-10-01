import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation.coordinators.event_coordinator import EventCoordinator
from tests.presentation.utils.dialog_lifecycle_support import (
    FakeEventBus as _dialog_lifecycle_support_FakeEventBus,
)


class DialogLifecycleTests(unittest.TestCase):
    def test_event_coordinator_cleanup_releases_event_bus_reference(self):
        event_bus = _dialog_lifecycle_support_FakeEventBus()
        coordinator = EventCoordinator(event_bus)
        callback = lambda **_: None
        coordinator.register(AppEvents.LICENSE_STATUS_CHANGED, callback)
        coordinator.cleanup()
        coordinator.cleanup()
        self.assertEqual(
            event_bus.unsubscriptions,
            [(AppEvents.LICENSE_STATUS_CHANGED, callback)],
        )
        self.assertIsNone(coordinator.event_bus)
        self.assertEqual(coordinator._subscriptions, [])

    def test_event_coordinator_cleanup_continues_after_unsubscribe_failure(self):
        class FailingEventBus(_dialog_lifecycle_support_FakeEventBus):
            def unsubscribe(self, event_type, callback):
                super().unsubscribe(event_type, callback)
                if len(self.unsubscriptions) == 1:
                    raise RuntimeError("unsubscribe failed")

        event_bus = FailingEventBus()
        coordinator = EventCoordinator(event_bus)
        first = lambda **_: None
        second = lambda **_: None
        coordinator.register(AppEvents.LICENSE_STATUS_CHANGED, first)
        coordinator.register(AppEvents.FILE_OPENED, second)
        with self.assertRaisesRegex(RuntimeError, "unsubscribe failed"):
            coordinator.cleanup()
        self.assertEqual(
            event_bus.unsubscriptions,
            [
                (AppEvents.LICENSE_STATUS_CHANGED, first),
                (AppEvents.FILE_OPENED, second),
            ],
        )
        self.assertIs(coordinator.event_bus, event_bus)
        self.assertEqual(
            coordinator._subscriptions,
            [(AppEvents.LICENSE_STATUS_CHANGED, first)],
        )

    def test_event_coordinator_cleanup_reports_every_unsubscribe_failure(self):
        class FailingEventBus(_dialog_lifecycle_support_FakeEventBus):
            def unsubscribe(self, event_type, callback):
                super().unsubscribe(event_type, callback)
                raise RuntimeError(f"failed: {event_type.__name__}")

        event_bus = FailingEventBus()
        coordinator = EventCoordinator(event_bus)
        first = lambda **_: None
        second = lambda **_: None
        coordinator.register(AppEvents.LICENSE_STATUS_CHANGED, first)
        coordinator.register(AppEvents.FILE_OPENED, second)
        with self.assertRaises(ExceptionGroup) as captured:
            coordinator.cleanup()
        self.assertEqual(
            [str(error) for error in captured.exception.exceptions],
            [
                "failed: LicenseStatusChangedEvent",
                "failed: FileOpenedEvent",
            ],
        )
        self.assertEqual(len(event_bus.unsubscriptions), 2)
        self.assertIs(coordinator.event_bus, event_bus)
        self.assertEqual(
            coordinator._subscriptions,
            [
                (AppEvents.LICENSE_STATUS_CHANGED, first),
                (AppEvents.FILE_OPENED, second),
            ],
        )

    def test_event_coordinator_retries_transient_unsubscribe_failures(self):
        class TransientEventBus(_dialog_lifecycle_support_FakeEventBus):
            def __init__(self):
                super().__init__()
                self.subscribers = {}
                self.attempts = {}

            def subscribe(self, event_type, callback):
                super().subscribe(event_type, callback)
                self.subscribers.setdefault(event_type, []).append(callback)

            def unsubscribe(self, event_type, callback):
                key = (event_type, callback)
                self.attempts[key] = self.attempts.get(key, 0) + 1
                if self.attempts[key] == 1:
                    raise RuntimeError(f"transient: {event_type.__name__}")
                self.subscribers[event_type].remove(callback)

            def publish(self, event_type):
                for callback in tuple(self.subscribers.get(event_type, ())):
                    callback()

        event_bus = TransientEventBus()
        coordinator = EventCoordinator(event_bus)
        delivered = []
        first = lambda: delivered.append("first")
        second = lambda: delivered.append("second")
        coordinator.register(AppEvents.LICENSE_STATUS_CHANGED, first)
        coordinator.register(AppEvents.FILE_OPENED, second)
        with self.assertRaises(ExceptionGroup):
            coordinator.cleanup()
        coordinator.cleanup()
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED)
        event_bus.publish(AppEvents.FILE_OPENED)
        self.assertEqual(delivered, [])
        self.assertIsNone(coordinator.event_bus)
        self.assertEqual(coordinator._subscriptions, [])

    def test_event_coordinator_retry_after_partial_failure_only_unsubscribes_failed(
        self,
    ):
        class FlakyEventBus(_dialog_lifecycle_support_FakeEventBus):
            def __init__(self):
                super().__init__()
                self.fail_next = True

            def unsubscribe(self, event_type, callback):
                super().unsubscribe(event_type, callback)
                if event_type is AppEvents.FILE_OPENED and self.fail_next:
                    self.fail_next = False
                    raise RuntimeError("flaky")

        event_bus = FlakyEventBus()
        coordinator = EventCoordinator(event_bus)
        first = lambda **_: None
        second = lambda **_: None
        coordinator.register(AppEvents.LICENSE_STATUS_CHANGED, first)
        coordinator.register(AppEvents.FILE_OPENED, second)
        with self.assertRaisesRegex(RuntimeError, "flaky"):
            coordinator.cleanup()
        self.assertIs(coordinator.event_bus, event_bus)
        self.assertEqual(coordinator._subscriptions, [(AppEvents.FILE_OPENED, second)])
        coordinator.cleanup()
        self.assertEqual(
            event_bus.unsubscriptions,
            [
                (AppEvents.LICENSE_STATUS_CHANGED, first),
                (AppEvents.FILE_OPENED, second),
                (AppEvents.FILE_OPENED, second),
            ],
        )
        self.assertIsNone(coordinator.event_bus)
        self.assertEqual(coordinator._subscriptions, [])

    def test_event_coordinator_register_many_accepts_dict_and_pairs_in_order(self):
        event_bus = _dialog_lifecycle_support_FakeEventBus()
        coordinator = EventCoordinator(event_bus)
        first = lambda **_: None
        second = lambda **_: None
        third = lambda **_: None
        coordinator.register_many({AppEvents.LICENSE_STATUS_CHANGED: first})
        coordinator.register_many(
            [(AppEvents.FILE_OPENED, second), (AppEvents.FILE_OPENED, third)]
        )
        expected = [
            (AppEvents.LICENSE_STATUS_CHANGED, first),
            (AppEvents.FILE_OPENED, second),
            (AppEvents.FILE_OPENED, third),
        ]
        self.assertEqual(event_bus.subscriptions, expected)
        self.assertEqual(coordinator._subscriptions, expected)
        coordinator.cleanup()
        self.assertEqual(event_bus.unsubscriptions, expected)
