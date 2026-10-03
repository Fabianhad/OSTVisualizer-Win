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
        self.parents = []
        self.update_states = []
        self.cleanups = 0

    def post_message(self, title, message, severity="info") -> None:
        self.messages.append((title, severity))

    def set_parent(self, parent) -> None:
        self.parents.append(parent)

    def set_update_active(self, active) -> None:
        self.update_states.append(active)

    def cleanup(self) -> None:
        self.cleanups += 1


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
            self.assertIs(monitor._connect_to_events(), False)
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
            self.assertIs(monitor._connect_to_events(), False)
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
            self.assertIs(monitor._connect_to_events(), True)
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


_MONITOR_LOGGER = "ost_visualizer.infrastructure.monitoring.transaction_monitor"
_MONITOR_TIME = f"{_MONITOR_LOGGER}.time"
_TIMEOUT = ost_winevent.WAIT_TIMEOUT
_SIGNALED = ost_winevent.WAIT_OBJECT_0
_ABANDONED = ost_winevent.WAIT_ABANDONED
_WAIT_FAILED = ost_winevent.WAIT_FAILED


class _RunawayLoop(BaseException):
    pass


class _FakeClock:
    def __init__(self, now=1000.0) -> None:
        self.now = now

    def time(self) -> float:
        return self.now


class _FakeStopFlag:
    # Stands in for threading.Event so the synchronous loop tests never sleep.
    # BaseException on runaway keeps a regressed loop from hanging the suite.
    def __init__(self, max_polls=200) -> None:
        self._set = False
        self._max_polls = max_polls
        self.polls = 0
        self.wait_timeouts = []

    def is_set(self) -> bool:
        self.polls += 1
        if self.polls > self._max_polls:
            raise _RunawayLoop()
        return self._set

    def set(self) -> None:
        self._set = True

    def clear(self) -> None:
        self._set = False

    def wait(self, timeout=None) -> bool:
        self.wait_timeouts.append(timeout)
        self.polls += 1
        if self.polls > self._max_polls:
            raise _RunawayLoop()
        return self._set


class _ScriptedEvent:
    # Each script entry is a wait result, an (result, seconds_spent) pair that
    # advances the fake clock first, or an exception instance to raise. An
    # exhausted script reports a timeout (after on_exhausted, if given).
    def __init__(self, script=(), clock=None, on_exhausted=None, opens=True) -> None:
        self.script = list(script)
        self.clock = clock
        self.on_exhausted = on_exhausted
        self.opens = opens
        self.timeouts = []
        self.opened_names = []
        self.closed = False

    def open(self, name) -> bool:
        self.opened_names.append(name)
        return self.opens

    def close(self) -> None:
        self.closed = True

    def wait(self, timeout_ms) -> int:
        self.timeouts.append(timeout_ms)
        if not self.script:
            if self.on_exhausted is not None:
                self.on_exhausted()
            return _TIMEOUT
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, tuple):
            entry, spent = entry
            self.clock.now += spent
        return entry


class _StopRequestingEvent(_ScriptedEvent):
    def __init__(self, stop_flag) -> None:
        super().__init__()
        self.stop_flag = stop_flag

    def wait(self, timeout_ms) -> int:
        self.timeouts.append(timeout_ms)
        self.stop_flag.set()
        return _SIGNALED


class _BlockingCommit(_ScriptedEvent):
    # After its script runs out, wait() blocks on the monitor's real stop flag
    # (released by stop_monitoring) and reports `entered` first.
    def __init__(self, script, clock, monitor, entered=None) -> None:
        super().__init__(script, clock)
        self.monitor = monitor
        self.entered = entered
        self.waits_after_stop = 0

    def wait(self, timeout_ms) -> int:
        if self.script:
            return super().wait(timeout_ms)
        self.timeouts.append(timeout_ms)
        if self.entered is not None:
            self.entered.set()
        if self.monitor._stop_flag.is_set():
            self.waits_after_stop += 1
            if self.waits_after_stop > 100:
                raise _RunawayLoop()
        self.monitor._stop_flag.wait(timeout=10.0)
        return _TIMEOUT


class _CallRecorder:
    def __init__(self, raises=None) -> None:
        self.calls = []
        self.raises = list(raises or [])

    def __call__(self, *args) -> None:
        self.calls.append(args)
        if self.raises:
            error = self.raises.pop(0)
            if error is not None:
                raise error


class TransactionMonitorEventProcessingTests(unittest.TestCase):
    def _monitor(self, script, callback=None):
        clock = _FakeClock()
        event = _ScriptedEvent(script, clock)
        monitor = TransactionMonitor()
        monitor._event = event
        monitor._callback = callback
        return monitor, event, clock

    def _step(self, monitor, clock, count=1):
        with patch(_MONITOR_TIME, clock):
            for _ in range(count):
                monitor._process_single_event()

    def test_process_without_event_does_nothing(self):
        callback = _CallRecorder()
        monitor = TransactionMonitor()
        monitor._callback = callback
        monitor._pending_callback = True
        monitor._last_signal_time = 5.0
        status = _ScriptedEvent()
        monitor._status_event = status
        with self.assertNoLogs(_MONITOR_LOGGER, level="DEBUG"):
            monitor._process_single_event()
        self.assertEqual(callback.calls, [])
        self.assertTrue(monitor._pending_callback)
        self.assertEqual(monitor._last_signal_time, 5.0)
        self.assertIsNone(monitor._event)
        self.assertFalse(status.closed)
        self.assertIs(monitor._status_event, status)

    def test_signal_arms_debounce_without_calling_back_and_shortens_next_wait(self):
        callback = _CallRecorder()
        monitor, event, clock = self._monitor([_SIGNALED, _TIMEOUT], callback)
        self._step(monitor, clock)
        self.assertTrue(monitor._pending_callback)
        self.assertEqual(monitor._last_signal_time, 1000.0)
        self.assertEqual(callback.calls, [])
        self._step(monitor, clock)
        self.assertEqual(event.timeouts, [1000, 100])
        self.assertEqual(callback.calls, [])

    def test_timeout_without_pending_signal_never_calls_back(self):
        callback = _CallRecorder()
        monitor, event, clock = self._monitor([(_TIMEOUT, 10.0)] * 2, callback)
        self._step(monitor, clock, 2)
        self.assertEqual(callback.calls, [])
        self.assertFalse(monitor._pending_callback)
        self.assertEqual(event.timeouts, [1000, 1000])

    def test_callback_fires_once_when_debounce_window_elapses_exactly(self):
        callback = _CallRecorder()
        monitor, event, clock = self._monitor(
            [_SIGNALED, (_TIMEOUT, 0.25), (_TIMEOUT, 0.25), (_TIMEOUT, 5.0)], callback
        )
        self._step(monitor, clock, 2)
        self.assertEqual(callback.calls, [])
        self.assertTrue(monitor._pending_callback)
        self._step(monitor, clock)
        self.assertEqual(callback.calls, [()])
        self.assertFalse(monitor._pending_callback)
        self._step(monitor, clock)
        self.assertEqual(callback.calls, [()])
        self.assertEqual(event.timeouts, [1000, 100, 100, 1000])

    def test_signal_burst_restarts_debounce_and_collapses_to_one_callback(self):
        callback = _CallRecorder()
        monitor, _event, clock = self._monitor(
            [
                _SIGNALED,
                (_SIGNALED, 0.25),
                (_TIMEOUT, 0.25),
                (_TIMEOUT, 0.25),
                (_TIMEOUT, 5.0),
            ],
            callback,
        )
        self._step(monitor, clock, 2)
        self.assertEqual(monitor._last_signal_time, 1000.25)
        self._step(monitor, clock)
        self.assertEqual(callback.calls, [])
        self._step(monitor, clock)
        self.assertEqual(callback.calls, [()])
        self._step(monitor, clock)
        self.assertEqual(callback.calls, [()])

    def test_pending_debounce_without_callback_is_cleared_quietly(self):
        monitor, event, clock = self._monitor([_SIGNALED, (_TIMEOUT, 1.0)], None)
        with self.assertNoLogs(_MONITOR_LOGGER, level="DEBUG"):
            self._step(monitor, clock, 2)
        self.assertFalse(monitor._pending_callback)
        self.assertIs(monitor._event, event)
        self.assertFalse(event.closed)

    def test_callback_exception_is_logged_and_next_signal_still_dispatches(self):
        callback = _CallRecorder(raises=[RuntimeError("callback boom")])
        script = [_SIGNALED, (_TIMEOUT, 1.0), _SIGNALED, (_TIMEOUT, 1.0)]
        monitor, event, clock = self._monitor(script, callback)
        with self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs:
            self._step(monitor, clock, 2)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Exception in transaction monitor callback: callback boom",
        )
        self.assertEqual(callback.calls, [()])
        self.assertFalse(monitor._pending_callback)
        self.assertFalse(event.closed)
        self.assertIs(monitor._event, event)
        self._step(monitor, clock, 2)
        self.assertEqual(callback.calls, [(), ()])

    def test_abandoned_handle_logs_warning_and_closes_events_without_callback(self):
        callback = _CallRecorder()
        monitor, event, clock = self._monitor([_ABANDONED], callback)
        status = _ScriptedEvent()
        monitor._status_event = status
        monitor._status_online = True
        with self.assertLogs(_MONITOR_LOGGER, level="WARNING") as logs:
            self._step(monitor, clock)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Transaction event handle abandoned"],
        )
        self.assertTrue(event.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)
        self.assertIsNone(monitor._status_event)
        self.assertFalse(monitor._status_online)
        self.assertEqual(callback.calls, [])

    def test_unexpected_wait_result_is_logged_closes_events_and_never_dispatches(self):
        for result in (_WAIT_FAILED, 99):
            with self.subTest(result=result):
                callback = _CallRecorder()
                monitor, event, clock = self._monitor([result], callback)
                status = _ScriptedEvent()
                monitor._status_event = status
                monitor._status_online = True
                with self.assertLogs(_MONITOR_LOGGER, level="WARNING") as logs:
                    self._step(monitor, clock)
                self.assertEqual(
                    [record.getMessage() for record in logs.records],
                    [f"Unexpected wait result: {result}"],
                )
                self.assertTrue(event.closed)
                self.assertTrue(status.closed)
                self.assertIsNone(monitor._event)
                self.assertIsNone(monitor._status_event)
                self.assertFalse(monitor._status_online)
                self.assertFalse(monitor._pending_callback)
                self.assertEqual(callback.calls, [])

    def test_wait_exception_is_contained_and_closes_events(self):
        callback = _CallRecorder()
        monitor, event, clock = self._monitor([OSError("wait broke")], callback)
        status = _ScriptedEvent()
        monitor._status_event = status
        with self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs:
            self._step(monitor, clock)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Exception processing events: wait broke"],
        )
        self.assertTrue(event.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)
        self.assertIsNone(monitor._status_event)
        self.assertEqual(callback.calls, [])


class TransactionMonitorStatusTests(unittest.TestCase):
    def _connected(self, status_script, notifier=None, status_callback=None):
        monitor = TransactionMonitor(notifier)
        commit = _ScriptedEvent()
        status = _ScriptedEvent(status_script)
        monitor._event = commit
        monitor._status_event = status
        monitor._state = MonitorState.CONNECTED
        monitor._status_online = True
        if status_callback is not None:
            monitor.set_ost_status_callback(status_callback)
        return monitor, commit, status

    def test_connection_established_announces_status_by_previous_state_and_presence(
        self,
    ):
        # (previous state, status online, status calls, messages). The first
        # connect (INITIAL) with OST already running publishes the status (the
        # write-block consumers never poll) but stays quiet in the UI: the
        # "Realtime Monitoring Active" toast belongs to a reconnect only. Not
        # running at first connect publishes nothing: every consumer already
        # defaults to "OST inactive".
        active_message = [("Realtime Monitoring Active", "info")]
        cases = [
            (MonitorState.INITIAL, True, [True], []),
            (MonitorState.INITIAL, False, [], []),
            (MonitorState.CONNECTED, True, [], []),
            (MonitorState.CONNECTED, False, [], []),
            (MonitorState.WAITING_FOR_OST, False, [], []),
            (MonitorState.DLL_NOT_LOADED, False, [], []),
            (MonitorState.WAITING_FOR_OST, True, [True], active_message),
            (MonitorState.DLL_NOT_LOADED, True, [True], active_message),
            (MonitorState.DISCONNECTED, True, [True], active_message),
        ]
        for previous_state, online, expected_calls, expected_messages in cases:
            with self.subTest(previous_state=previous_state.name, online=online):
                status_callback = _CallRecorder()
                notifier = _RecordingNotifier()
                monitor = TransactionMonitor(notifier)
                monitor.set_ost_status_callback(status_callback)
                monitor._state = previous_state
                monitor._status_online = online
                monitor._handle_connection_established()
                self.assertEqual(
                    status_callback.calls, [(value,) for value in expected_calls]
                )
                self.assertEqual(notifier.messages, expected_messages)
                self.assertEqual(monitor._state, MonitorState.CONNECTED)
                self.assertEqual(monitor._status_published, bool(expected_calls))

    def test_status_check_without_status_event_changes_nothing(self):
        status_callback = _CallRecorder()
        monitor = TransactionMonitor()
        monitor._status_online = True
        monitor._state = MonitorState.CONNECTED
        monitor.set_ost_status_callback(status_callback)
        monitor._check_status_state()
        self.assertEqual(status_callback.calls, [])
        self.assertTrue(monitor._status_online)
        self.assertEqual(monitor._state, MonitorState.CONNECTED)

    def test_unchanged_status_does_not_notify(self):
        status_callback = _CallRecorder()
        notifier = _RecordingNotifier()
        monitor, commit, _status = self._connected(
            [_SIGNALED], notifier, status_callback
        )
        monitor._check_status_state()
        self.assertEqual(status_callback.calls, [])
        self.assertEqual(notifier.messages, [])
        self.assertIs(monitor._event, commit)
        self.assertTrue(monitor._status_online)

    def test_status_going_offline_notifies_posts_message_and_drops_connection(self):
        status_callback = _CallRecorder()
        notifier = _RecordingNotifier()
        monitor, commit, status = self._connected([_TIMEOUT], notifier, status_callback)
        monitor._check_status_state()
        self.assertEqual(status_callback.calls, [(False,)])
        self.assertEqual(
            notifier.messages, [("Realtime Monitoring Stopped", "warning")]
        )
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)
        self.assertIsNone(monitor._status_event)
        self.assertFalse(monitor._status_online)
        self.assertEqual(monitor._state, MonitorState.WAITING_FOR_OST)

    def test_status_going_offline_without_collaborators_still_drops_connection(self):
        monitor, commit, _status = self._connected([_TIMEOUT])
        with self.assertNoLogs(_MONITOR_LOGGER, level="DEBUG"):
            monitor._check_status_state()
        self.assertTrue(commit.closed)
        self.assertFalse(monitor._status_online)
        self.assertEqual(monitor._state, MonitorState.WAITING_FOR_OST)

    def test_status_going_offline_outside_connected_state_only_notifies(self):
        status_callback = _CallRecorder()
        notifier = _RecordingNotifier()
        monitor, commit, _status = self._connected(
            [_TIMEOUT], notifier, status_callback
        )
        monitor._state = MonitorState.DLL_NOT_LOADED
        monitor._check_status_state()
        self.assertEqual(status_callback.calls, [(False,)])
        self.assertEqual(notifier.messages, [])
        self.assertFalse(commit.closed)
        self.assertIs(monitor._event, commit)
        self.assertFalse(monitor._status_online)
        self.assertEqual(monitor._state, MonitorState.DLL_NOT_LOADED)

    def test_status_coming_online_notifies_and_keeps_connection(self):
        status_callback = _CallRecorder()
        notifier = _RecordingNotifier()
        monitor, commit, status = self._connected(
            [_SIGNALED], notifier, status_callback
        )
        monitor._status_online = False
        monitor._check_status_state()
        self.assertEqual(status_callback.calls, [(True,)])
        self.assertEqual(notifier.messages, [])
        self.assertTrue(monitor._status_online)
        self.assertIs(monitor._event, commit)
        self.assertIs(monitor._status_event, status)
        self.assertEqual(monitor._state, MonitorState.CONNECTED)

    def test_status_wait_exception_is_contained_and_closes_events(self):
        monitor, commit, status = self._connected([OSError("status broke")])
        with self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs:
            monitor._check_status_state()
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Exception while checking status state: status broke"],
        )
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)
        self.assertFalse(monitor._status_online)

    def test_status_callback_exception_is_contained_and_closes_events(self):
        status_callback = _CallRecorder(raises=[RuntimeError("status cb boom")])
        monitor, commit, _status = self._connected(
            [_TIMEOUT], status_callback=status_callback
        )
        with self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs:
            monitor._check_status_state()
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Exception while checking status state: status cb boom"],
        )
        self.assertEqual(status_callback.calls, [(False,)])
        self.assertTrue(commit.closed)
        self.assertIsNone(monitor._event)


class TransactionMonitorLoopTests(unittest.TestCase):
    def _run_loop(self, monitor, flag, clock, events):
        monitor._stop_flag = flag
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=events) as factory,
            patch(f"{_WINEVENT}.is_process_running", return_value=False),
        ):
            monitor._monitor_loop()
        return factory

    def test_loop_with_stop_already_requested_never_connects(self):
        flag = _FakeStopFlag()
        flag.set()
        monitor = TransactionMonitor()
        monitor._is_monitoring = True
        factory = self._run_loop(monitor, flag, _FakeClock(), [])
        factory.assert_not_called()
        self.assertFalse(monitor._is_monitoring)
        self.assertEqual(flag.wait_timeouts, [])

    def test_loop_retries_connection_every_two_seconds_until_ost_appears(self):
        flag = _FakeStopFlag()
        clock = _FakeClock()
        status_callback = _CallRecorder()
        notifier = _RecordingNotifier()
        monitor = TransactionMonitor(notifier)
        monitor.set_ost_status_callback(status_callback)
        monitor._is_monitoring = True
        commit = _ScriptedEvent(clock=clock, on_exhausted=flag.set)
        status = _ScriptedEvent([_SIGNALED, _SIGNALED], clock)
        self._run_loop(
            monitor,
            flag,
            clock,
            [_ScriptedEvent(opens=False), _ScriptedEvent(opens=False), commit, status],
        )
        # Only the two failed attempts back off; the stop request ends the
        # connected session without another wait.
        self.assertEqual(flag.wait_timeouts, [2.0, 2.0])
        self.assertEqual(commit.opened_names, [TransactionMonitor.EVENT_NAME])
        self.assertEqual(status.opened_names, [TransactionMonitor.STATUS_EVENT_NAME])
        self.assertEqual(notifier.messages, [("Realtime Monitoring Active", "info")])
        self.assertEqual(status_callback.calls, [(True,)])
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)
        self.assertFalse(monitor._is_monitoring)

    def test_loop_dispatches_debounced_commit_then_closes_events_on_stop(self):
        flag = _FakeStopFlag()
        clock = _FakeClock()
        callback = _CallRecorder()
        monitor = TransactionMonitor()
        monitor._callback = callback
        monitor._is_monitoring = True
        commit = _ScriptedEvent(
            [_SIGNALED, (_TIMEOUT, 0.25), (_TIMEOUT, 0.25)], clock, flag.set
        )
        status = _ScriptedEvent([_SIGNALED] * 10, clock)
        self._run_loop(monitor, flag, clock, [commit, status])
        self.assertEqual(callback.calls, [()])
        self.assertEqual(commit.timeouts, [1000, 100, 100, 1000])
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)
        self.assertIsNone(monitor._status_event)
        self.assertFalse(monitor._is_monitoring)
        self.assertEqual(flag.wait_timeouts, [])

    def test_loop_survives_processing_exception_and_reconnects(self):
        flag = _FakeStopFlag()
        clock = _FakeClock()
        callback = _CallRecorder()
        monitor = TransactionMonitor()
        monitor._callback = callback
        monitor._is_monitoring = True
        broken_commit = _ScriptedEvent([OSError("handle lost")], clock)
        broken_status = _ScriptedEvent([_SIGNALED], clock)
        commit = _ScriptedEvent([_SIGNALED, (_TIMEOUT, 1.0)], clock, flag.set)
        status = _ScriptedEvent([_SIGNALED] * 10, clock)
        with self.assertLogs(_MONITOR_LOGGER, level="ERROR"):
            self._run_loop(
                monitor, flag, clock, [broken_commit, broken_status, commit, status]
            )
        self.assertTrue(broken_commit.closed)
        self.assertTrue(broken_status.closed)
        self.assertEqual(callback.calls, [()])
        self.assertEqual(flag.wait_timeouts, [2.0])
        self.assertTrue(commit.closed)
        self.assertFalse(monitor._is_monitoring)

    def test_loop_survives_callback_exception_and_dispatches_next_commit(self):
        flag = _FakeStopFlag()
        clock = _FakeClock()
        callback = _CallRecorder(raises=[RuntimeError("callback boom")])
        monitor = TransactionMonitor()
        monitor._callback = callback
        monitor._is_monitoring = True
        commit = _ScriptedEvent(
            [_SIGNALED, (_TIMEOUT, 1.0), _SIGNALED, (_TIMEOUT, 1.0)], clock, flag.set
        )
        status = _ScriptedEvent([_SIGNALED] * 10, clock)
        with self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs:
            self._run_loop(monitor, flag, clock, [commit, status])
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(callback.calls, [(), ()])
        self.assertEqual(flag.wait_timeouts, [])
        self.assertTrue(commit.closed)

    def test_loop_stops_processing_after_stop_request_and_drops_pending_commit(self):
        flag = _FakeStopFlag()
        clock = _FakeClock()
        callback = _CallRecorder()
        monitor = TransactionMonitor()
        monitor._callback = callback
        monitor._is_monitoring = True
        commit = _StopRequestingEvent(flag)
        status = _ScriptedEvent([_SIGNALED] * 10, clock)
        self._run_loop(monitor, flag, clock, [commit, status])
        self.assertEqual(commit.timeouts, [1000])
        self.assertEqual(callback.calls, [])
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)
        self.assertFalse(monitor._is_monitoring)
        self.assertEqual(flag.wait_timeouts, [])

    def test_loop_reconnects_after_ost_goes_offline_and_reports_both_transitions(
        self,
    ):
        flag = _FakeStopFlag()
        clock = _FakeClock()
        status_callback = _CallRecorder()
        notifier = _RecordingNotifier()
        monitor = TransactionMonitor(notifier)
        monitor.set_ost_status_callback(status_callback)
        monitor._is_monitoring = True
        first_commit = _ScriptedEvent(clock=clock)
        # The connect-time sync sees online; the first in-loop check sees offline.
        first_status = _ScriptedEvent([_SIGNALED, _TIMEOUT], clock)
        second_commit = _ScriptedEvent(clock=clock, on_exhausted=flag.set)
        second_status = _ScriptedEvent([_SIGNALED] * 10, clock)
        self._run_loop(
            monitor,
            flag,
            clock,
            [first_commit, first_status, second_commit, second_status],
        )
        self.assertTrue(first_commit.closed)
        self.assertTrue(first_status.closed)
        # First connect with OST running announces it (D2), then both transitions.
        self.assertEqual(status_callback.calls, [(True,), (False,), (True,)])
        self.assertEqual(
            notifier.messages,
            [
                ("Realtime Monitoring Stopped", "warning"),
                ("Realtime Monitoring Active", "info"),
            ],
        )
        self.assertEqual(flag.wait_timeouts, [2.0])
        self.assertTrue(second_commit.closed)
        self.assertFalse(monitor._is_monitoring)


class _BoundedWinEvents:
    # WinEvent factory for real-thread tests: a regressed worker that keeps
    # reconnecting after stop dies with the BaseException instead of spinning.
    def __init__(self, *events) -> None:
        self._events = list(events)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if not self._events:
            raise _RunawayLoop()
        event = self._events.pop(0)
        return event() if callable(event) else event


class TransactionMonitorWorkerThreadTests(unittest.TestCase):
    def test_worker_dispatches_on_its_own_thread_and_stop_joins_it(self):
        clock = _FakeClock()
        monitor = TransactionMonitor()
        self.addCleanup(monitor.stop_monitoring)
        fired = threading.Event()
        blocked = threading.Event()
        callback_threads = []

        def callback():
            callback_threads.append(threading.current_thread())
            fired.set()

        commit = _BlockingCommit([_SIGNALED, (_TIMEOUT, 1.0)], clock, monitor, blocked)
        status = _ScriptedEvent([_SIGNALED] * 1000, clock)
        factory = _BoundedWinEvents(commit, status)
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
        ):
            self.assertTrue(monitor.start_monitoring(callback))
            worker = monitor._monitor_thread
            self.assertTrue(worker.daemon)
            self.assertEqual(worker.name, "TransactionMonitor")
            self.assertFalse(monitor.start_monitoring(lambda: None))
            self.assertIs(monitor._monitor_thread, worker)
            self.assertTrue(fired.wait(10.0))
            self.assertTrue(blocked.wait(10.0))
            self.assertTrue(monitor.is_monitoring())
            waits_before_stop = len(commit.timeouts)
            monitor.stop_monitoring()
            self.assertFalse(worker.is_alive())
        self.assertEqual(callback_threads, [worker])
        self.assertIsNot(callback_threads[0], threading.current_thread())
        self.assertIsNone(monitor._monitor_thread)
        self.assertFalse(monitor.is_monitoring())
        self.assertIsNone(monitor._callback)
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)
        self.assertEqual(len(commit.timeouts), waits_before_stop)
        self.assertEqual(factory.calls, 2)

    def test_stop_interrupts_connection_retry_backoff_and_joins_worker(self):
        monitor = TransactionMonitor()
        self.addCleanup(monitor.stop_monitoring)
        attempted = threading.Event()
        attempts = []

        def failing_event():
            attempts.append(1)
            attempted.set()
            return _ScriptedEvent(opens=False)

        factory = _BoundedWinEvents(failing_event, failing_event)
        with (
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
            patch(f"{_WINEVENT}.is_process_running", return_value=False),
        ):
            self.assertTrue(monitor.start_monitoring(lambda: None))
            worker = monitor._monitor_thread
            self.assertTrue(attempted.wait(10.0))
            monitor.stop_monitoring()
        self.assertFalse(worker.is_alive())
        self.assertIsNone(monitor._monitor_thread)
        self.assertFalse(monitor.is_monitoring())
        self.assertEqual(len(attempts), 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(monitor._state, MonitorState.INITIAL)

    def test_monitor_can_restart_after_stop_and_delivers_only_to_new_callback(self):
        clock = _FakeClock()
        monitor = TransactionMonitor()
        self.addCleanup(monitor.stop_monitoring)
        first_blocked = threading.Event()
        fired = threading.Event()
        first_calls = []
        second_calls = []

        def second_callback():
            second_calls.append(1)
            fired.set()

        first = _BlockingCommit([], clock, monitor, first_blocked)
        second = _BlockingCommit([_SIGNALED, (_TIMEOUT, 1.0)], clock, monitor)
        statuses = [_ScriptedEvent([_SIGNALED] * 1000, clock) for _ in range(2)]
        factory = _BoundedWinEvents(first, statuses[0], second, statuses[1])
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
        ):
            self.assertTrue(monitor.start_monitoring(lambda: first_calls.append(1)))
            self.assertTrue(first_blocked.wait(10.0))
            monitor.stop_monitoring()
            self.assertTrue(first.closed)
            self.assertTrue(monitor.start_monitoring(second_callback))
            self.assertTrue(fired.wait(10.0))
            monitor.stop_monitoring()
        self.assertEqual(first_calls, [])
        self.assertEqual(second_calls, [1])
        self.assertTrue(second.closed)
        self.assertFalse(monitor.is_monitoring())
        self.assertEqual(factory.calls, 4)


class _StopAfterBackoffs(_FakeStopFlag):
    def __init__(self, backoffs, max_polls=200) -> None:
        super().__init__(max_polls)
        self._backoffs = backoffs

    def wait(self, timeout=None) -> bool:
        result = super().wait(timeout)
        if len(self.wait_timeouts) >= self._backoffs:
            self._set = True
        return self._set


class _CommitThenStatus:
    def __init__(self, commit_factory, clock) -> None:
        self._commit_factory = commit_factory
        self._clock = clock
        self._next_is_commit = True

    def __iter__(self):
        return self

    def __next__(self):
        commit = self._next_is_commit
        self._next_is_commit = not commit
        if commit:
            return self._commit_factory()
        return _ScriptedEvent([_SIGNALED] * 1000, self._clock)


class TransactionMonitorConnectionLossTests(unittest.TestCase):
    _run_loop = TransactionMonitorLoopTests._run_loop
    _LOSSES = [
        ("abandoned", _ABANDONED),
        ("wait failed", _WAIT_FAILED),
        ("unknown result", 99),
        ("wait exception", OSError("handle lost")),
    ]

    def test_loop_backs_off_and_reconnects_after_each_kind_of_connection_loss(self):
        for name, trigger in self._LOSSES:
            with self.subTest(loss=name):
                flag = _FakeStopFlag()
                clock = _FakeClock()
                callback = _CallRecorder()
                monitor = TransactionMonitor()
                monitor._callback = callback
                monitor._is_monitoring = True
                broken_commit = _ScriptedEvent([trigger], clock)
                broken_status = _ScriptedEvent([_SIGNALED], clock)
                commit = _ScriptedEvent([_SIGNALED, (_TIMEOUT, 1.0)], clock, flag.set)
                status = _ScriptedEvent([_SIGNALED] * 10, clock)
                with self.assertLogs(_MONITOR_LOGGER):
                    self._run_loop(
                        monitor,
                        flag,
                        clock,
                        [broken_commit, broken_status, commit, status],
                    )
                self.assertTrue(broken_commit.closed)
                self.assertTrue(broken_status.closed)
                self.assertEqual(flag.wait_timeouts, [2.0])
                self.assertEqual(callback.calls, [()])
                self.assertTrue(commit.closed)
                self.assertTrue(status.closed)
                self.assertFalse(monitor._is_monitoring)

    def test_persistent_wait_failure_costs_one_wait_per_backoff_cycle(self):
        flag = _StopAfterBackoffs(3)
        clock = _FakeClock()
        monitor = TransactionMonitor()
        monitor._is_monitoring = True
        commits = []

        def failing_commit():
            event = _ScriptedEvent([_WAIT_FAILED] * 1000, clock)
            commits.append(event)
            return event

        with self.assertLogs(_MONITOR_LOGGER, level="WARNING"):
            self._run_loop(
                monitor, flag, clock, _CommitThenStatus(failing_commit, clock)
            )
        self.assertEqual(flag.wait_timeouts, [2.0, 2.0, 2.0])
        self.assertEqual([event.timeouts for event in commits], [[1000]] * 3)
        self.assertTrue(all(event.closed for event in commits))
        self.assertFalse(monitor._is_monitoring)

    def _scenario(self, trigger, reconnect_events, backoffs):
        flag = _StopAfterBackoffs(backoffs)
        clock = _FakeClock()
        status_callback = _CallRecorder()
        notifier = _RecordingNotifier()
        monitor = TransactionMonitor(notifier)
        monitor.set_ost_status_callback(status_callback)
        monitor._is_monitoring = True
        events = [
            _ScriptedEvent(opens=False),
            _ScriptedEvent([trigger], clock),
            _ScriptedEvent([_SIGNALED] * 3, clock),
        ] + list(reconnect_events(clock, flag))
        with self.assertLogs(_MONITOR_LOGGER):
            self._run_loop(monitor, flag, clock, events)
        return monitor, status_callback, notifier, flag

    def test_reconnect_that_finds_ost_offline_reports_offline_after_connection_loss(
        self,
    ):
        for name, trigger in self._LOSSES:
            with self.subTest(loss=name):

                def reconnect(clock, flag):
                    yield _ScriptedEvent(clock=clock, on_exhausted=flag.set)
                    yield _ScriptedEvent([_TIMEOUT] * 3, clock)

                monitor, status_callback, notifier, flag = self._scenario(
                    trigger, reconnect, backoffs=99
                )
                self.assertEqual(status_callback.calls, [(True,), (False,)])
                self.assertEqual(
                    notifier.messages, [("Realtime Monitoring Active", "info")]
                )
                self.assertEqual(flag.wait_timeouts, [2.0, 2.0])
                self.assertFalse(monitor.is_ost_active())

    def test_reconnect_that_finds_ost_online_does_not_repeat_status_reports(self):
        for name, trigger in self._LOSSES:
            with self.subTest(loss=name):

                def reconnect(clock, flag):
                    yield _ScriptedEvent(clock=clock, on_exhausted=flag.set)
                    yield _ScriptedEvent([_SIGNALED] * 3, clock)

                monitor, status_callback, notifier, flag = self._scenario(
                    trigger, reconnect, backoffs=99
                )
                self.assertEqual(status_callback.calls, [(True,)])
                self.assertEqual(
                    notifier.messages, [("Realtime Monitoring Active", "info")]
                )
                self.assertEqual(flag.wait_timeouts, [2.0, 2.0])

    def test_failed_reconnects_after_connection_loss_report_offline_once(self):
        def reconnect(_clock, _flag):
            yield _ScriptedEvent(opens=False)
            yield _ScriptedEvent(opens=False)
            yield _ScriptedEvent(opens=False)

        monitor, status_callback, _notifier, flag = self._scenario(
            OSError("handle lost"), reconnect, backoffs=5
        )
        self.assertEqual(flag.wait_timeouts, [2.0] * 5)
        self.assertEqual(status_callback.calls, [(True,), (False,)])
        self.assertFalse(monitor.is_ost_active())

    def test_offline_report_is_owed_after_stop_and_restart_while_ost_is_gone(self):
        status_callback = _CallRecorder()
        monitor = TransactionMonitor()
        monitor.set_ost_status_callback(status_callback)
        monitor._status_published = True
        monitor._state = MonitorState.CONNECTED
        monitor.stop_monitoring()
        self.assertEqual(monitor._state, MonitorState.INITIAL)
        with (
            patch(f"{_WINEVENT}.WinEvent", return_value=_ScriptedEvent(opens=False)),
            patch(f"{_WINEVENT}.is_process_running", return_value=False),
        ):
            self.assertFalse(monitor._connect_to_events())
        self.assertEqual(status_callback.calls, [(False,)])
        self.assertEqual(monitor._state, MonitorState.WAITING_FOR_OST)

    def test_stale_offline_report_failure_is_contained_and_retried(self):
        status_callback = _CallRecorder(raises=[RuntimeError("status cb boom")])
        monitor = TransactionMonitor()
        monitor.set_ost_status_callback(status_callback)
        monitor._status_published = True
        with patch(f"{_WINEVENT}.is_process_running", return_value=False):
            with self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs:
                monitor._handle_connection_failed()
            self.assertEqual(len(logs.records), 1)
            self.assertEqual(status_callback.calls, [(False,)])
            monitor._handle_connection_failed()
            self.assertEqual(status_callback.calls, [(False,), (False,)])
            monitor._handle_connection_failed()
        self.assertEqual(status_callback.calls, [(False,), (False,)])


class TransactionMonitorCallbackLockTests(unittest.TestCase):
    def _events(self, clock, commit):
        status = _ScriptedEvent([_SIGNALED] * 1000, clock)
        factory = _BoundedWinEvents(commit, status)
        return factory, status

    def test_stop_does_not_wait_for_a_callback_that_is_still_running(self):
        clock = _FakeClock()
        monitor = TransactionMonitor()
        self.addCleanup(monitor.stop_monitoring)
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def callback():
            entered.set()
            release.wait(30.0)

        commit = _BlockingCommit([_SIGNALED, (_TIMEOUT, 1.0)], clock, monitor)
        factory, status = self._events(clock, commit)
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
        ):
            self.assertTrue(monitor.start_monitoring(callback))
            worker = monitor._monitor_thread
            self.assertTrue(entered.wait(10.0))
            stopper = threading.Thread(target=monitor.stop_monitoring, daemon=True)
            with self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs:
                stopper.start()
                stopper.join(10.0)
                stop_returned = not stopper.is_alive()
            release.set()
            stopper.join(10.0)
            worker.join(10.0)
        self.assertTrue(stop_returned)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["The transaction-monitor worker did not stop within 1.5 seconds."],
        )
        self.assertFalse(worker.is_alive())
        self.assertFalse(monitor.is_monitoring())
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)

    def test_callback_reentering_start_and_stop_cannot_deadlock_the_worker(self):
        clock = _FakeClock()
        monitor = TransactionMonitor()
        self.addCleanup(monitor.stop_monitoring)
        results = {}
        finished = threading.Event()

        def callback():
            try:
                results["start"] = monitor.start_monitoring(lambda: None)
                try:
                    monitor.stop_monitoring()
                except RuntimeError:
                    results["stop_raised"] = True
            finally:
                finished.set()

        commit = _BlockingCommit([_SIGNALED, (_TIMEOUT, 1.0)], clock, monitor)
        factory, status = self._events(clock, commit)
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
        ):
            self.assertTrue(monitor.start_monitoring(callback))
            worker = monitor._monitor_thread
            self.assertTrue(finished.wait(10.0))
            worker.join(10.0)
        self.assertFalse(worker.is_alive())
        self.assertIs(results["start"], False)
        self.assertFalse(monitor.is_monitoring())
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)
        self.assertEqual(factory.calls, 2)


class TransactionMonitorThreadAffinityTests(unittest.TestCase):
    def test_status_callback_and_messages_run_on_the_worker_thread(self):
        clock = _FakeClock()
        notifier_threads = []
        status_threads = []
        announced = threading.Event()

        class _ThreadNotifier(_RecordingNotifier):
            def post_message(self, title, message, severity="info") -> None:
                notifier_threads.append(threading.current_thread())
                super().post_message(title, message, severity)

        def status_callback(active) -> None:
            status_threads.append((threading.current_thread(), active))
            announced.set()

        monitor = TransactionMonitor(_ThreadNotifier())
        self.addCleanup(monitor.stop_monitoring)
        monitor.set_ost_status_callback(status_callback)
        monitor._state = MonitorState.DLL_NOT_LOADED
        commit = _BlockingCommit([], clock, monitor)
        status = _ScriptedEvent([_SIGNALED] * 1000, clock)
        factory = _BoundedWinEvents(commit, status)
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
        ):
            self.assertTrue(monitor.start_monitoring(lambda: None))
            worker = monitor._monitor_thread
            self.assertTrue(announced.wait(10.0))
            monitor.stop_monitoring()
        self.assertEqual(status_threads, [(worker, True)])
        self.assertEqual(notifier_threads, [worker])
        self.assertIsNot(worker, threading.current_thread())

    def test_monitor_never_references_the_event_bus_or_publication(self):
        from ost_visualizer.infrastructure.monitoring import transaction_monitor

        names = set(vars(transaction_monitor))
        for member in vars(TransactionMonitor).values():
            code = getattr(member, "__code__", None)
            if code is not None:
                names.update(code.co_names)
        values = [
            getattr(value, "__module__", "") or ""
            for value in vars(transaction_monitor).values()
        ]
        self.assertIn("IMessageNotifier", names)
        self.assertEqual(
            sorted(
                name
                for name in names
                if name == "publish"
                or any(
                    word in name.lower()
                    for word in ("event_bus", "eventbus", "appevents")
                )
            ),
            [],
        )
        self.assertEqual([m for m in values if "event" in m.lower() and "bus" in m], [])


class TransactionMonitorSurfaceTests(unittest.TestCase):
    def test_ost_is_active_only_while_monitoring_with_online_status(self):
        for monitoring, online, expected in (
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ):
            with self.subTest(monitoring=monitoring, online=online):
                monitor = TransactionMonitor()
                monitor._is_monitoring = monitoring
                monitor._status_online = online
                self.assertIs(monitor.is_ost_active(), expected)
                self.assertIs(monitor.is_monitoring(), monitoring)

    def test_dialog_state_and_message_parent_reach_the_notifier(self):
        notifier = _RecordingNotifier()
        monitor = TransactionMonitor(notifier)
        parent = object()
        monitor.set_update_dialog_active(True)
        monitor.set_update_dialog_active(False)
        monitor.set_message_parent(parent)
        self.assertEqual(notifier.update_states, [True, False])
        self.assertEqual(notifier.parents, [parent])
        self.assertEqual(notifier.messages, [])
        silent = TransactionMonitor()
        silent.set_update_dialog_active(True)
        silent.set_message_parent(parent)
        silent._post_message("title", "message")

    def test_cleanup_stops_monitoring_and_releases_callbacks_and_notifier(self):
        notifier = _RecordingNotifier()
        status_callback = _CallRecorder()
        event = _ScriptedEvent()
        monitor = TransactionMonitor(notifier)
        monitor.set_ost_status_callback(status_callback)
        monitor._event = event
        monitor._is_monitoring = True
        monitor._status_online = True
        monitor._callback = lambda: None
        monitor.cleanup()
        self.assertTrue(event.closed)
        self.assertFalse(monitor.is_monitoring())
        self.assertTrue(monitor._stop_flag.is_set())
        self.assertIsNone(monitor._callback)
        self.assertIsNone(monitor._ost_status_callback)
        self.assertIsNone(monitor._notifier)
        self.assertEqual(notifier.cleanups, 1)
        monitor._post_message("late", "message")
        monitor.cleanup()
        self.assertEqual(notifier.cleanups, 1)
        self.assertEqual(notifier.messages, [])
        self.assertEqual(status_callback.calls, [])

    def test_cleanup_without_a_notifier_still_stops_monitoring(self):
        monitor = TransactionMonitor()
        monitor._is_monitoring = True
        monitor.set_ost_status_callback(lambda active: None)
        monitor.cleanup()
        self.assertFalse(monitor.is_monitoring())
        self.assertIsNone(monitor._ost_status_callback)

    def test_connecting_without_a_status_event_reports_ost_offline(self):
        commit = _ScriptedEvent()
        no_status = _ScriptedEvent(opens=False)
        monitor = TransactionMonitor()
        monitor._status_online = True
        with patch(f"{_WINEVENT}.WinEvent", side_effect=[commit, no_status]):
            self.assertIs(monitor._connect_to_events(), True)
        self.assertIs(monitor._event, commit)
        self.assertIsNone(monitor._status_event)
        self.assertIs(monitor._status_online, False)
        self.assertEqual(monitor._state, MonitorState.CONNECTED)
        self.assertEqual(no_status.timeouts, [])

    def test_status_probes_never_block_on_the_status_event(self):
        commit = _ScriptedEvent()
        status = _ScriptedEvent([_SIGNALED, _SIGNALED])
        monitor = TransactionMonitor()
        with patch(f"{_WINEVENT}.WinEvent", side_effect=[commit, status]):
            self.assertTrue(monitor._connect_to_events())
        self.assertEqual(status.timeouts, [0])
        monitor._check_status_state()
        self.assertEqual(status.timeouts, [0, 0])
        self.assertTrue(monitor._status_online)

    def test_sync_without_a_status_event_clears_a_stale_online_flag(self):
        monitor = TransactionMonitor()
        monitor._status_online = True
        monitor._sync_status_state()
        self.assertIs(monitor._status_online, False)

    def test_restart_discards_a_stale_debounce_armed_before_the_stop(self):
        clock = _FakeClock()
        monitor = TransactionMonitor()
        self.addCleanup(monitor.stop_monitoring)
        monitor._pending_callback = True
        monitor._last_signal_time = 1.0
        fired = []
        blocked = threading.Event()
        commit = _BlockingCommit([(_TIMEOUT, 5.0)], clock, monitor, blocked)
        status = _ScriptedEvent([_SIGNALED] * 1000, clock)
        factory = _BoundedWinEvents(commit, status)
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
        ):
            self.assertTrue(monitor.start_monitoring(lambda: fired.append(1)))
            self.assertTrue(blocked.wait(10.0))
            self.assertFalse(monitor._pending_callback)
            self.assertEqual(monitor._last_signal_time, 0.0)
            monitor.stop_monitoring()
        self.assertEqual(fired, [])


class _FailingNotifier(_RecordingNotifier):
    # Records every attempt, then raises for the first `failures` posts.
    def __init__(self, failures=1) -> None:
        super().__init__()
        self.attempts = []
        self._failures = failures

    def post_message(self, title, message, severity="info") -> None:
        self.attempts.append((title, severity))
        if len(self.attempts) <= self._failures:
            raise RuntimeError("notifier boom")
        super().post_message(title, message, severity)


class _RaisingOpenEvent(_ScriptedEvent):
    def open(self, name) -> bool:
        self.opened_names.append(name)
        raise OSError("open failed")


class _FastBackoffStopFlag(threading.Event):
    # Real Event (stop still interrupts waits) whose 2 s reconnect backoff is
    # shortened so a real-thread test can watch the worker reconnect.
    def wait(self, timeout=None) -> bool:
        return super().wait(0.01 if timeout == 2.0 else timeout)


class TransactionMonitorCallbackFailureTests(unittest.TestCase):
    _NOTIFIER_FAILED = "Exception in message notifier: notifier boom"

    def test_worker_keeps_delivering_commits_after_a_notifier_failure_while_connecting(
        self,
    ):
        clock = _FakeClock()
        notifier = _FailingNotifier()
        monitor = TransactionMonitor(notifier)
        monitor._stop_flag = _FastBackoffStopFlag()
        self.addCleanup(monitor.stop_monitoring)
        fired = threading.Event()
        died = []
        # Attempt 1: the status event cannot be opened while Ost.exe runs, so
        # the monitor reports the missing service and the notifier raises.
        # Attempt 2: a healthy connection that signals one commit.
        commit = _BlockingCommit([_SIGNALED, (_TIMEOUT, 1.0)], clock, monitor)
        status = _ScriptedEvent([_SIGNALED] * 1000, clock)
        factory = _BoundedWinEvents(
            _ScriptedEvent(), _RaisingOpenEvent(), commit, status
        )
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
            patch(f"{_WINEVENT}.is_process_running", return_value=True),
            patch("threading.excepthook", side_effect=died.append),
            self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs,
        ):
            self.assertTrue(monitor.start_monitoring(fired.set))
            worker = monitor._monitor_thread
            for _ in range(200):
                if fired.wait(0.05) or not worker.is_alive():
                    break
            try:
                self.assertEqual(
                    {
                        "commit delivered": fired.is_set(),
                        "worker alive": worker.is_alive(),
                        "uncaught": [args.exc_value for args in died],
                    },
                    {"commit delivered": True, "worker alive": True, "uncaught": []},
                )
            finally:
                monitor.stop_monitoring()
        self.assertEqual(factory.calls, 4)
        self.assertEqual(
            notifier.attempts,
            [
                ("Realtime Service Not Installed", "warning"),
                ("Realtime Monitoring Active", "info"),
            ],
        )
        self.assertIn(
            self._NOTIFIER_FAILED, [record.getMessage() for record in logs.records]
        )

    def test_notifier_failure_while_reporting_a_missing_service_does_not_escape(self):
        cases = [
            ("status event cannot be opened", [_ScriptedEvent(), _RaisingOpenEvent()]),
            ("commit event cannot be opened", [_RaisingOpenEvent()]),
            ("commit event is missing", [_ScriptedEvent(opens=False)]),
        ]
        for name, events in cases:
            with self.subTest(case=name):
                notifier = _FailingNotifier()
                monitor = TransactionMonitor(notifier)
                with (
                    patch(f"{_WINEVENT}.WinEvent", side_effect=events),
                    patch(f"{_WINEVENT}.is_process_running", return_value=True),
                    self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs,
                ):
                    self.assertIs(monitor._connect_to_events(), False)
                self.assertEqual(
                    notifier.attempts, [("Realtime Service Not Installed", "warning")]
                )
                self.assertEqual(monitor._state, MonitorState.DLL_NOT_LOADED)
                self.assertIsNone(monitor._event)
                self.assertIsNone(monitor._status_event)
                self.assertIn(
                    self._NOTIFIER_FAILED,
                    [record.getMessage() for record in logs.records],
                )

    def test_notifier_failure_does_not_cost_the_online_report_or_the_connection(self):
        status_callback = _CallRecorder()
        notifier = _FailingNotifier()
        monitor = TransactionMonitor(notifier)
        monitor.set_ost_status_callback(status_callback)
        monitor._state = MonitorState.DLL_NOT_LOADED
        commit = _ScriptedEvent()
        status = _ScriptedEvent([_SIGNALED])
        with (
            patch(f"{_WINEVENT}.WinEvent", side_effect=[commit, status]),
            self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs,
        ):
            self.assertIs(monitor._connect_to_events(), True)
        self.assertEqual(
            [record.getMessage() for record in logs.records], [self._NOTIFIER_FAILED]
        )
        self.assertEqual(status_callback.calls, [(True,)])
        self.assertEqual(notifier.attempts, [("Realtime Monitoring Active", "info")])
        self.assertIs(monitor._event, commit)
        self.assertIs(monitor._status_event, status)
        self.assertFalse(commit.closed)
        self.assertEqual(monitor._state, MonitorState.CONNECTED)
        self.assertTrue(monitor._status_published)

    def test_notifier_failure_on_going_offline_still_reports_and_drops_connection(
        self,
    ):
        status_callback = _CallRecorder()
        notifier = _FailingNotifier()
        monitor = TransactionMonitor(notifier)
        monitor.set_ost_status_callback(status_callback)
        commit = _ScriptedEvent()
        status = _ScriptedEvent([_TIMEOUT])
        monitor._event = commit
        monitor._status_event = status
        monitor._state = MonitorState.CONNECTED
        monitor._status_online = True
        monitor._status_published = True
        with self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs:
            monitor._check_status_state()
        self.assertEqual(
            [record.getMessage() for record in logs.records], [self._NOTIFIER_FAILED]
        )
        self.assertEqual(status_callback.calls, [(False,)])
        self.assertEqual(
            notifier.attempts, [("Realtime Monitoring Stopped", "warning")]
        )
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)
        self.assertEqual(monitor._state, MonitorState.WAITING_FOR_OST)
        self.assertFalse(monitor._status_published)

    def test_status_callback_failure_while_connecting_is_logged_not_silent(self):
        status_callback = _CallRecorder(raises=[RuntimeError("status cb boom")])
        monitor = TransactionMonitor()
        monitor.set_ost_status_callback(status_callback)
        monitor._state = MonitorState.WAITING_FOR_OST
        commit = _ScriptedEvent()
        status = _ScriptedEvent([_SIGNALED])
        with (
            patch(f"{_WINEVENT}.WinEvent", side_effect=[commit, status]),
            patch(f"{_WINEVENT}.is_process_running", return_value=False),
            self.assertLogs(_MONITOR_LOGGER, level="ERROR") as logs,
        ):
            self.assertIs(monitor._connect_to_events(), False)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Exception connecting to the OST events: status cb boom"],
        )
        self.assertEqual(status_callback.calls, [(True,)])
        self.assertTrue(commit.closed)
        self.assertTrue(status.closed)
        self.assertIsNone(monitor._event)


class TransactionMonitorStopPublicationTests(unittest.TestCase):
    # stop_monitoring/cleanup run on the Qt thread (database unload, app close)
    # where OstSignaler.emit_status is delivered synchronously: the status
    # callback would set_write_blocked(False) and publish OST_STATUS_CHANGED
    # while OST may still be running and while the UI is shutting down. So a
    # stop must not publish; the last status stays owed until the next connect.
    def _stop_after_online_report(self, stop):
        clock = _FakeClock()
        status_callback = _CallRecorder()
        notifier = _RecordingNotifier()
        monitor = TransactionMonitor(notifier)
        self.addCleanup(monitor.stop_monitoring)
        announced = threading.Event()

        def on_status(active):
            status_callback(active)
            announced.set()

        monitor.set_ost_status_callback(on_status)
        monitor._state = MonitorState.DLL_NOT_LOADED
        commit = _BlockingCommit([], clock, monitor)
        status = _ScriptedEvent([_SIGNALED] * 1000, clock)
        factory = _BoundedWinEvents(commit, status)
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
        ):
            self.assertTrue(monitor.start_monitoring(lambda: None))
            self.assertTrue(announced.wait(10.0))
            self.assertTrue(monitor.is_ost_active())
            stop(monitor)
        return monitor, status_callback, notifier

    def test_stopping_after_an_active_report_publishes_nothing_and_keeps_it_owed(self):
        for name, stop in (
            ("stop_monitoring", lambda monitor: monitor.stop_monitoring()),
            ("cleanup", lambda monitor: monitor.cleanup()),
        ):
            with self.subTest(stop=name):
                monitor, status_callback, notifier = self._stop_after_online_report(
                    stop
                )
                self.assertEqual(status_callback.calls, [(True,)])
                self.assertEqual(
                    notifier.messages, [("Realtime Monitoring Active", "info")]
                )
                self.assertFalse(monitor.is_ost_active())
                self.assertFalse(monitor.is_monitoring())
                self.assertTrue(monitor._status_published)


class TransactionMonitorInitialAnnouncementTests(unittest.TestCase):
    # Decision D2: the first connect publishes the status when OST is already
    # running. The Access write-block (ConnectionManager.set_write_blocked via
    # OstSignaler) is driven only by this callback; UiAccessManager.refresh()
    # polling covers the UI, never the write connections.
    def _first_connect(self, status_script, status_opens=True, notifier=None):
        status_callback = _CallRecorder()
        monitor = TransactionMonitor(notifier)
        monitor.set_ost_status_callback(status_callback)
        commit = _ScriptedEvent()
        status = _ScriptedEvent(status_script, opens=status_opens)
        with (
            patch(f"{_WINEVENT}.WinEvent", side_effect=[commit, status]),
            patch(f"{_WINEVENT}.is_process_running", return_value=True),
        ):
            self.assertIs(monitor._connect_to_events(), True)
        return monitor, status_callback, commit, status

    def test_first_connect_with_ost_running_publishes_active_exactly_once(self):
        notifier = _RecordingNotifier()
        monitor, status_callback, commit, status = self._first_connect(
            [_SIGNALED] * 5, notifier=notifier
        )
        self.assertEqual(status_callback.calls, [(True,)])
        self.assertEqual(monitor._state, MonitorState.CONNECTED)
        self.assertTrue(monitor._status_online)
        self.assertTrue(monitor._status_published)
        self.assertEqual(notifier.messages, [])
        # Steady polling of the unchanged status must not re-publish it.
        for _ in range(3):
            monitor._check_status_state()
        self.assertEqual(status_callback.calls, [(True,)])
        self.assertIs(monitor._event, commit)
        self.assertIs(monitor._status_event, status)

    def test_first_connect_without_ost_running_publishes_nothing_until_it_starts(
        self,
    ):
        cases = [
            ("status event not signaled", [_TIMEOUT] * 3, True),
            ("status event cannot be opened", [], False),
        ]
        for name, script, opens in cases:
            with self.subTest(case=name):
                notifier = _RecordingNotifier()
                monitor, status_callback, _commit, _status = self._first_connect(
                    script, status_opens=opens, notifier=notifier
                )
                self.assertEqual(status_callback.calls, [])
                self.assertEqual(notifier.messages, [])
                self.assertFalse(monitor._status_online)
                self.assertFalse(monitor._status_published)
                self.assertEqual(monitor._state, MonitorState.CONNECTED)
        # Positive control: OST starting later is still published, once.
        monitor, status_callback, _commit, _status = self._first_connect(
            [_TIMEOUT, _SIGNALED, _SIGNALED]
        )
        self.assertEqual(status_callback.calls, [])
        monitor._check_status_state()
        monitor._check_status_state()
        self.assertEqual(status_callback.calls, [(True,)])

    def test_first_connect_active_report_is_followed_by_exactly_one_offline_report(
        self,
    ):
        monitor, status_callback, _commit, _status = self._first_connect(
            [_SIGNALED, _TIMEOUT, _TIMEOUT]
        )
        monitor._check_status_state()
        monitor._check_status_state()
        self.assertEqual(status_callback.calls, [(True,), (False,)])
        self.assertFalse(monitor._status_published)

    def test_worker_thread_publishes_initial_active_once_and_stop_publishes_nothing(
        self,
    ):
        clock = _FakeClock()
        status_callback = _CallRecorder()
        notifier = _RecordingNotifier()
        monitor = TransactionMonitor(notifier)
        self.addCleanup(monitor.stop_monitoring)
        announced = threading.Event()

        def on_status(active):
            status_callback(active)
            announced.set()

        monitor.set_ost_status_callback(on_status)
        commit = _BlockingCommit([_TIMEOUT] * 3, clock, monitor)
        status = _ScriptedEvent([_SIGNALED] * 1000, clock)
        factory = _BoundedWinEvents(commit, status)
        with (
            patch(_MONITOR_TIME, clock),
            patch(f"{_WINEVENT}.WinEvent", side_effect=factory),
        ):
            self.assertEqual(monitor._state, MonitorState.INITIAL)
            self.assertTrue(monitor.start_monitoring(lambda: None))
            self.assertTrue(announced.wait(10.0))
            self.assertTrue(monitor.is_ost_active())
            monitor.stop_monitoring()
        self.assertEqual(status_callback.calls, [(True,)])
        self.assertEqual(notifier.messages, [])
        self.assertEqual(monitor._state, MonitorState.INITIAL)
        # Stop stays silent and keeps the last report owed.
        self.assertTrue(monitor._status_published)

    def test_restart_with_ost_gone_reports_the_owed_offline_before_connecting(self):
        status_callback = _CallRecorder()
        monitor = TransactionMonitor()
        monitor.set_ost_status_callback(status_callback)
        monitor._status_published = True
        commit = _ScriptedEvent()
        status = _ScriptedEvent([_TIMEOUT])
        with patch(f"{_WINEVENT}.WinEvent", side_effect=[commit, status]):
            self.assertIs(monitor._connect_to_events(), True)
        self.assertEqual(monitor._state, MonitorState.CONNECTED)
        self.assertEqual(status_callback.calls, [(False,)])
        self.assertFalse(monitor._status_published)

    def test_restart_with_ost_still_running_announces_active_again(self):
        # stop_monitoring is silent and resets the state to INITIAL, so a restart
        # with OST still running re-announces it (consumers are idempotent).
        status_callback = _CallRecorder()
        monitor = TransactionMonitor()
        monitor.set_ost_status_callback(status_callback)
        monitor._status_published = True
        commit = _ScriptedEvent()
        status = _ScriptedEvent([_SIGNALED])
        with patch(f"{_WINEVENT}.WinEvent", side_effect=[commit, status]):
            self.assertIs(monitor._connect_to_events(), True)
        self.assertEqual(status_callback.calls, [(True,)])
        self.assertTrue(monitor._status_published)
