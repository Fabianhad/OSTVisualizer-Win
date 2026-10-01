import gc
import threading
import unittest
import weakref
from unittest.mock import patch
from ost_visualizer.infrastructure.services.license_validation_scheduler import (
    LicenseValidationScheduler,
)


class LicenseValidationSchedulerPersistenceTests(unittest.TestCase):
    def test_license_validation_scheduler_stop_releases_thread_reference(self):
        calls = []
        scheduler = LicenseValidationScheduler(interval_seconds=60)
        scheduler.set_task(lambda: calls.append("ran"))
        self.assertFalse(scheduler.is_running())
        scheduler.start()
        thread = scheduler._thread
        self.assertTrue(scheduler.is_running())
        scheduler.stop()
        self.assertIsNone(scheduler._thread)
        self.assertFalse(scheduler.is_running())
        self.assertFalse(thread.is_alive())
        self.assertEqual(calls, [])

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
        self.assertFalse(thread.is_alive())
        scheduler.stop()
        self.assertIsNone(scheduler._thread)
        self.assertFalse(scheduler.is_running())

    def test_license_validation_scheduler_clear_task_releases_callback(self):
        class _Callback:
            def __call__(self):
                return None

        callback = _Callback()
        reference = weakref.ref(callback)
        scheduler = LicenseValidationScheduler(interval_seconds=60, task=callback)
        self.assertIs(scheduler._task, callback)
        del callback
        scheduler.clear_task()
        gc.collect()
        self.assertIsNone(scheduler._task)
        self.assertIsNone(reference())

    def test_license_validation_scheduler_logs_task_failure_and_keeps_running(self):
        second_run = threading.Event()
        calls = []

        def flaky_task():
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                raise RuntimeError("license server unreachable")
            second_run.set()

        scheduler = LicenseValidationScheduler(interval_seconds=0, task=flaky_task)
        try:
            with self.assertLogs(scheduler.logger, level="ERROR") as logs:
                scheduler.start()
                self.assertTrue(second_run.wait(timeout=2))
        finally:
            scheduler.stop()
        self.assertIsNone(scheduler._thread)
        self.assertEqual(calls[:2], [1, 2])
        self.assertIn(
            "Scheduled license validation failed: license server unreachable",
            logs.output[0],
        )
