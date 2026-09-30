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
        self.assertEqual(bus.publish.call_count, 2)
