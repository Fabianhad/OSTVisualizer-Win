import threading
import unittest
from unittest.mock import patch
from ost_visualizer.infrastructure.monitoring import ost_winevent
from ost_visualizer.infrastructure.monitoring.transaction_monitor import (
    MonitorState,
    TransactionMonitor,
)

_WINEVENT = "ost_visualizer.infrastructure.monitoring.transaction_monitor.ost_winevent"


class _FakeWinEvent:
    def __init__(self, opens=True, wait_result=ost_winevent.WAIT_OBJECT_0) -> None:
        self.opens = opens
        self.wait_result = wait_result
        self.opened_names = []
        self.closed = False

    def open(self, name) -> bool:
        self.opened_names.append(name)
        return self.opens

    def wait(self, _timeout_ms) -> int:
        return self.wait_result

    def close(self) -> None:
        self.closed = True


class _RecordingNotifier:
    def __init__(self) -> None:
        self.messages = []

    def post_message(self, title, message, severity="info") -> None:
        self.messages.append((title, severity))

    def set_parent(self, _parent) -> None:
        pass

    def set_update_active(self, _active) -> None:
        pass

    def cleanup(self) -> None:
        pass


class TransactionMonitorLifecycleTests(unittest.TestCase):
    def test_monitor_closes_commit_event_when_status_setup_fails(self):
        class _CommitEvent:
            def __init__(self) -> None:
                self.closed = False
                self.opened_names = []

            def open(self, name) -> bool:
                self.opened_names.append(name)
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
            patch(f"{_WINEVENT}.is_process_running", return_value=False),
            patch.object(
                monitor,
                "_open_status_event",
                side_effect=RuntimeError("status setup failed"),
            ),
        ):
            self.assertFalse(monitor._connect_to_events())
        self.assertEqual(commit_event.opened_names, [TransactionMonitor.EVENT_NAME])
        self.assertTrue(commit_event.closed)
        self.assertIsNone(monitor._event)
        self.assertIsNone(monitor._status_event)
        self.assertFalse(monitor._status_online)
        self.assertEqual(monitor._state, MonitorState.WAITING_FOR_OST)

    def test_connect_to_events_failure_leaves_no_events_and_reports_missing_service(
        self,
    ):
        notifier = _RecordingNotifier()
        monitor = TransactionMonitor(notifier)
        with (
            patch(f"{_WINEVENT}.WinEvent", return_value=_FakeWinEvent(opens=False)),
            patch(f"{_WINEVENT}.is_process_running", return_value=True),
        ):
            self.assertFalse(monitor._connect_to_events())
        self.assertIsNone(monitor._event)
        self.assertIsNone(monitor._status_event)
        self.assertEqual(monitor._state, MonitorState.DLL_NOT_LOADED)
        self.assertEqual(
            notifier.messages,
            [("Realtime Service Not Installed", "warning")],
        )

    def test_connect_to_events_success_tracks_commit_and_status_events(self):
        events = [_FakeWinEvent(), _FakeWinEvent()]
        monitor = TransactionMonitor()
        with patch(f"{_WINEVENT}.WinEvent", side_effect=events):
            self.assertTrue(monitor._connect_to_events())
        self.assertEqual(
            [event.opened_names for event in events],
            [[TransactionMonitor.EVENT_NAME], [TransactionMonitor.STATUS_EVENT_NAME]],
        )
        self.assertIs(monitor._event, events[0])
        self.assertIs(monitor._status_event, events[1])
        self.assertTrue(monitor._status_online)
        self.assertEqual(monitor._state, MonitorState.CONNECTED)

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
        self.assertFalse(monitor._is_monitoring)
        self.assertTrue(monitor._stop_flag.is_set())

    def test_monitor_stop_cleans_stale_state_after_worker_already_exited(self):
        worker = threading.Thread(target=lambda: None)
        worker.start()
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())
        event = _FakeWinEvent()
        monitor = TransactionMonitor()
        monitor._monitor_thread = worker
        monitor._event = event
        monitor._is_monitoring = True
        monitor._pending_callback = True
        monitor._last_signal_time = 123.0
        monitor._callback = lambda: None
        monitor.stop_monitoring()
        self.assertFalse(monitor._pending_callback)
        self.assertEqual(monitor._last_signal_time, 0.0)
        self.assertIsNone(monitor._callback)
        self.assertIsNone(monitor._monitor_thread)
        self.assertFalse(monitor._is_monitoring)
        self.assertTrue(event.closed)
        self.assertIsNone(monitor._event)

    def test_monitor_stop_resets_connection_state_for_later_access_restart(self):
        monitor = TransactionMonitor()
        monitor._is_monitoring = True
        monitor._state = MonitorState.CONNECTED
        monitor._status_online = True
        monitor.stop_monitoring()
        self.assertEqual(monitor._state, MonitorState.INITIAL)
        self.assertFalse(monitor._status_online)
        self.assertFalse(monitor.is_ost_active())

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
        event = _FakeWinEvent()
        monitor._monitor_thread = thread
        monitor._event = event
        monitor._is_monitoring = True
        monitor._pending_callback = True
        monitor._last_signal_time = 123.0
        monitor._callback = lambda: None
        with self.assertLogs(
            "ost_visualizer.infrastructure.monitoring.transaction_monitor",
            level="ERROR",
        ):
            monitor.stop_monitoring()
        self.assertIs(monitor._monitor_thread, thread)
        self.assertTrue(monitor._is_monitoring)
        self.assertIsNone(monitor._callback)
        self.assertEqual(thread.join_calls, [1.5])
        self.assertTrue(monitor._stop_flag.is_set())
        self.assertFalse(monitor._pending_callback)
        self.assertEqual(monitor._last_signal_time, 0.0)
        self.assertFalse(event.closed)
        self.assertIs(monitor._event, event)
