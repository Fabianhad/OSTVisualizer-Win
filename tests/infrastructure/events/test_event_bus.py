import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.infrastructure.events.event_bus import EventBus


class DialogLifecycleTests(unittest.TestCase):
    def test_event_bus_defers_readded_subscriber_until_next_publish(self):
        event_bus = EventBus()
        delivered = []

        def target(**_payload):
            delivered.append("target")

        def replace_target(**_payload):
            event_bus.unsubscribe(AppEvents.LICENSE_STATUS_CHANGED, replace_target)
            event_bus.unsubscribe(AppEvents.LICENSE_STATUS_CHANGED, target)
            event_bus.subscribe(AppEvents.LICENSE_STATUS_CHANGED, target)

        event_bus.subscribe(AppEvents.LICENSE_STATUS_CHANGED, replace_target)
        event_bus.subscribe(AppEvents.LICENSE_STATUS_CHANGED, target)
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(delivered, [])
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(delivered, ["target"])

    def test_event_bus_recursive_publish_uses_current_subscription_identity(self):
        event_bus = EventBus()
        delivered = []
        reentered = False

        def target(**_payload):
            delivered.append("target")

        def replace_and_reenter(**_payload):
            nonlocal reentered
            if reentered:
                return
            reentered = True
            event_bus.unsubscribe(
                AppEvents.LICENSE_STATUS_CHANGED,
                replace_and_reenter,
            )
            event_bus.unsubscribe(AppEvents.LICENSE_STATUS_CHANGED, target)
            event_bus.subscribe(AppEvents.LICENSE_STATUS_CHANGED, target)
            event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)

        event_bus.subscribe(
            AppEvents.LICENSE_STATUS_CHANGED,
            replace_and_reenter,
        )
        event_bus.subscribe(AppEvents.LICENSE_STATUS_CHANGED, target)
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(delivered, ["target"])
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(delivered, ["target", "target"])

    def test_event_bus_subscription_mutation_survives_subscriber_exception(self):
        event_bus = EventBus()
        delivered = []

        def target(**_payload):
            delivered.append("target")

        def replace_and_fail(**_payload):
            event_bus.unsubscribe(AppEvents.LICENSE_STATUS_CHANGED, target)
            event_bus.subscribe(AppEvents.LICENSE_STATUS_CHANGED, target)
            raise RuntimeError("subscriber failed")

        event_bus.subscribe(AppEvents.LICENSE_STATUS_CHANGED, replace_and_fail)
        event_bus.subscribe(AppEvents.LICENSE_STATUS_CHANGED, target)
        with self.assertRaisesRegex(RuntimeError, "subscriber failed"):
            event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        event_bus.unsubscribe(
            AppEvents.LICENSE_STATUS_CHANGED,
            replace_and_fail,
        )
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(delivered, ["target"])
