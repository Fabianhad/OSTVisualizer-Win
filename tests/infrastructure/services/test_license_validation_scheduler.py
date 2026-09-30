import threading
import unittest
from unittest.mock import Mock, patch
from ost_visualizer.infrastructure.services.license_validation_scheduler import (
    LicenseValidationScheduler,
)


class LicenseValidationSchedulerPersistenceTests(unittest.TestCase):
    def test_license_validation_scheduler_stop_releases_thread_reference(self):
        scheduler = LicenseValidationScheduler(interval_seconds=60)
        scheduler.set_task(lambda: None)
        scheduler.start()
        scheduler.stop()
        self.assertIsNone(scheduler._thread)

    def test_license_validation_scheduler_retains_in_flight_thread(self):
        task_started = threading.Event()
        release_task = threading.Event()

        def blocking_task():
            task_started.set()
            release_task.wait()

        scheduler = LicenseValidationScheduler(interval_seconds=0, task=blocking_task)
        scheduler.start()
        self.assertTrue(task_started.wait(timeout=1))
        thread = scheduler._thread
        with patch.object(threading.Thread, "join"):
            scheduler.stop()
        self.assertIs(scheduler._thread, thread)
        self.assertTrue(scheduler.is_running())
        scheduler.start()
        self.assertIs(scheduler._thread, thread)
        release_task.set()
        thread.join(timeout=1)
        scheduler.stop()
        self.assertIsNone(scheduler._thread)

    def test_license_validation_scheduler_clear_task_releases_callback(self):
        retained = object()
        scheduler = LicenseValidationScheduler(
            interval_seconds=60, task=lambda retained=retained: retained
        )
        scheduler.clear_task()
        self.assertIsNone(scheduler._task)
