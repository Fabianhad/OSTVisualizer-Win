import unittest
from unittest.mock import Mock, call
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.orchestrators.license_event_publisher import (
    LicenseEventPublisher,
)
from ost_visualizer.domain.entities.license import LicenseStatus


class LicenseEventPublisherTests(unittest.TestCase):
    def test_invalidation_is_published_once_until_a_new_activation(self):
        bus = Mock()
        publisher = LicenseEventPublisher(bus, Mock())
        self.assertTrue(publisher.publish_invalidated("invalid"))
        self.assertFalse(publisher.publish_invalidated("again"))
        publisher.publish_activated()
        self.assertTrue(publisher.publish_invalidated("new failure"))
        self.assertEqual(
            bus.publish.call_args_list,
            [
                call(AppEvents.LICENSE_STATUS_CHANGED, has_license=False),
                call(AppEvents.LICENSE_STATUS_CHANGED, has_license=True),
                call(AppEvents.LICENSE_STATUS_CHANGED, has_license=False),
            ],
        )

    def test_expiration_event_precedes_access_loss(self):
        bus = Mock()
        publisher = LicenseEventPublisher(bus, Mock())
        self.assertTrue(publisher.publish_invalidated("expired", LicenseStatus.EXPIRED))
        self.assertFalse(
            publisher.publish_invalidated("expired again", LicenseStatus.EXPIRED)
        )
        self.assertEqual(
            bus.publish.call_args_list,
            [
                call(AppEvents.LICENSE_EXPIRED),
                call(AppEvents.LICENSE_STATUS_CHANGED, has_license=False),
            ],
        )

    def test_license_loss_does_not_suppress_a_later_invalidation(self):
        bus = Mock()
        publisher = LicenseEventPublisher(bus, Mock())
        publisher.publish_license_lost()
        self.assertTrue(publisher.publish_invalidated("invalid"))
        self.assertEqual(
            bus.publish.call_args_list,
            [
                call(AppEvents.LICENSE_STATUS_CHANGED, has_license=False),
                call(AppEvents.LICENSE_STATUS_CHANGED, has_license=False),
            ],
        )


class LicenseEventPublisherLoggingTests(unittest.TestCase):
    class _Recorder:
        def __init__(self):
            self.calls = []

        def warning(self, message, *args):
            self.calls.append(("warning", message % args))

    class _Bus:
        def __init__(self):
            self.published = []

        def publish(self, event, **kwargs):
            self.published.append((event, kwargs))

    def publisher(self):
        from ost_visualizer.application.orchestrators.license_event_publisher import LicenseEventPublisher

        logger, bus = self._Recorder(), self._Bus()
        return LicenseEventPublisher(bus, logger), logger, bus

    def test_expired_and_other_invalidations_log_their_own_warning_and_events(self):
        from ost_visualizer.application.events.app_events import AppEvents
        from ost_visualizer.domain.entities.license import LicenseStatus

        publisher, logger, bus = self.publisher()
        self.assertIs(publisher.publish_invalidated("too old", LicenseStatus.EXPIRED), True)
        self.assertEqual(logger.calls, [("warning", "License expired: too old")])
        self.assertEqual(
            bus.published,
            [(AppEvents.LICENSE_EXPIRED, {}), (AppEvents.LICENSE_STATUS_CHANGED, {"has_license": False})],
        )
        publisher, logger, bus = self.publisher()
        self.assertIs(publisher.publish_invalidated("bad signature", LicenseStatus.INVALID), True)
        self.assertEqual(logger.calls, [("warning", "License invalid: bad signature")])
        self.assertEqual(bus.published, [(AppEvents.LICENSE_STATUS_CHANGED, {"has_license": False})])
        publisher, logger, bus = self.publisher()
        self.assertIs(publisher.publish_invalidated("no status"), True)
        self.assertEqual(logger.calls, [("warning", "License invalid: no status")])

    def test_a_second_failure_is_suppressed_and_returns_a_real_false_until_reactivation(self):
        from ost_visualizer.application.events.app_events import AppEvents

        publisher, logger, bus = self.publisher()
        self.assertIs(publisher.publish_invalidated("first"), True)
        self.assertIs(publisher.publish_invalidated("second"), False)
        self.assertEqual(len(logger.calls), 1)
        self.assertEqual(len(bus.published), 1)
        publisher.publish_activated()
        self.assertEqual(bus.published[-1], (AppEvents.LICENSE_STATUS_CHANGED, {"has_license": True}))
        self.assertIs(publisher.publish_invalidated("third"), True)
        publisher.publish_license_lost()
        self.assertEqual(bus.published[-1], (AppEvents.LICENSE_STATUS_CHANGED, {"has_license": False}))
        self.assertIs(publisher.publish_invalidated("fourth"), False)
