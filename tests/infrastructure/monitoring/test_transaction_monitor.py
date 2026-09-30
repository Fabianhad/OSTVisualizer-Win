import unittest
from unittest.mock import patch
from ost_visualizer.infrastructure.monitoring.transaction_monitor import (
    MonitorState,
    TransactionMonitor,
)


class TransactionMonitorLifecycleTests(unittest.TestCase):
    def test_monitor_closes_commit_event_when_status_setup_fails(self):
        class _CommitEvent:
            def __init__(self) -> None:
                self.closed = False

            def open(self, _name) -> bool:
                return True

            def close(self) -> None:
                self.closed = True

        monitor = TransactionMonitor()
        commit_event = _CommitEvent()
        with (
            patch(
                "ost_visualizer.infrastructure.monitoring.transaction_monitor."
                "ost_winevent.WinEvent",
                return_value=commit_event,
            ),
            patch.object(
                monitor,
                "_open_status_event",
                side_effect=RuntimeError("status setup failed"),
            ),
        ):
            self.assertFalse(monitor._connect_to_events())
        self.assertTrue(commit_event.closed)
        self.assertIsNone(monitor._event)
        self.assertIsNone(monitor._status_event)

    def test_monitor_stop_clears_pending_debounced_commit(self):
        monitor = TransactionMonitor()
        monitor._is_monitoring = True
        monitor._pending_callback = True
        monitor._last_signal_time = 123.0
        monitor._callback = lambda: None
        monitor.stop_monitoring()
        self.assertFalse(monitor._pending_callback)
        self.assertEqual(monitor._last_signal_time, 0.0)
        self.assertIsNone(monitor._callback)

    def test_monitor_stop_cleans_stale_state_after_worker_already_exited(self):
        monitor = TransactionMonitor()
        monitor._pending_callback = True
        monitor._last_signal_time = 123.0
        monitor._callback = lambda: None
        monitor.stop_monitoring()
        self.assertFalse(monitor._pending_callback)
        self.assertEqual(monitor._last_signal_time, 0.0)
        self.assertIsNone(monitor._callback)

    def test_monitor_stop_resets_connection_state_for_later_access_restart(self):
        monitor = TransactionMonitor()
        monitor._is_monitoring = True
        monitor._state = MonitorState.CONNECTED
        monitor._status_online = True
        monitor.stop_monitoring()
        self.assertEqual(monitor._state, MonitorState.INITIAL)
        self.assertFalse(monitor._status_online)

    def test_monitor_stop_retains_worker_reference_until_worker_really_exits(self):
        class _StillRunningThread:
            def __init__(self) -> None:
                self.join_calls = []

            def is_alive(self) -> bool:
                return True

            def join(self, timeout=None) -> None:
                self.join_calls.append(timeout)

        monitor = TransactionMonitor()
        thread = _StillRunningThread()
        monitor._monitor_thread = thread
        monitor._is_monitoring = True
        monitor._callback = lambda: None
        monitor.stop_monitoring()
        self.assertIs(monitor._monitor_thread, thread)
        self.assertTrue(monitor._is_monitoring)
        self.assertIsNone(monitor._callback)
        self.assertEqual(thread.join_calls, [1.5])
