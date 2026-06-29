import logging
import threading
import time
from enum import Enum, auto
from typing import Callable, Optional
from ...application.interfaces.i_message_notifier import IMessageNotifier
from . import ost_winevent

logger = logging.getLogger(__name__)
WAIT_ABANDONED_0 = ost_winevent.WAIT_ABANDONED


class MonitorState(Enum):
    INITIAL = auto()
    WAITING_FOR_OST = auto()
    DLL_NOT_LOADED = auto()
    CONNECTED = auto()
    DISCONNECTED = auto()


class TransactionMonitor:
    EVENT_NAME = "Global\\OSTMdbCommit"
    STATUS_EVENT_NAME = "Global\\OSTRealtimeStatus"
    DEBOUNCE_SECONDS = 0.5

    def __init__(self, message_notifier: Optional[IMessageNotifier] = None):
        self._event: Optional[ost_winevent.WinEvent] = None
        self._status_event: Optional[ost_winevent.WinEvent] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._callback: Optional[Callable[[], None]] = None
        self._is_monitoring = False
        self._pending_callback = False
        self._last_signal_time = 0.0
        self._debounce_lock = threading.Lock()
        self._state = MonitorState.INITIAL
        self._status_online = False
        self._notifier = message_notifier
        self._ost_status_callback: Optional[Callable[[bool], None]] = None

    def _connect_to_events(self) -> bool:
        try:
            self._event = ost_winevent.WinEvent()
            if not self._event.open(self.EVENT_NAME):
                self._event = None
                self._handle_connection_failed()
                return False
            self._status_event = self._open_status_event()
            self._sync_status_state()
            self._handle_connection_established()
            return True
        except Exception:
            self._handle_connection_failed()
            return False

    def _open_status_event(self) -> Optional[ost_winevent.WinEvent]:
        evt = ost_winevent.WinEvent()
        if evt.open(self.STATUS_EVENT_NAME):
            return evt
        return None

    def _sync_status_state(self) -> None:
        if not self._status_event:
            self._status_online = False
            return
        wait_result = self._status_event.wait(0)
        self._status_online = wait_result == ost_winevent.WAIT_OBJECT_0

    def _handle_connection_established(self) -> None:
        previous_state = self._state
        self._state = MonitorState.CONNECTED
        if previous_state in (
            MonitorState.WAITING_FOR_OST,
            MonitorState.DLL_NOT_LOADED,
            MonitorState.DISCONNECTED,
        ):
            if self._status_online:
                self._show_available_message()
                if self._ost_status_callback:
                    self._ost_status_callback(True)

    def _handle_connection_failed(self) -> None:
        if self._state == MonitorState.INITIAL:
            if ost_winevent.is_process_running("Ost.exe"):
                self._state = MonitorState.DLL_NOT_LOADED
                self._show_dll_not_loaded_message()
            else:
                self._state = MonitorState.WAITING_FOR_OST

    def set_update_dialog_active(self, active: bool) -> None:
        if self._notifier is None:
            return
        self._notifier.set_update_active(active)

    def set_message_parent(self, parent) -> None:
        if self._notifier is None:
            return
        self._notifier.set_parent(parent)

    def _post_message(self, title: str, message: str, severity: str = "info") -> None:
        if self._notifier is None:
            return
        self._notifier.post_message(title, message, severity)

    def _show_dll_not_loaded_message(self) -> None:
        self._post_message(
            "Realtime Service Not Installed",
            (
                "Realtime monitoring is not available because the realtime service "
                "(as2port.dll) is not installed or failed to load.\n\n"
                "To enable realtime monitoring:\n"
                "1. Close On-Screen Takeoff\n"
                "2. Run RealtimeService\\install.cmd as Administrator\n"
                "3. Restart On-Screen Takeoff\n\n"
                "The install script will install the DLL to the On-Screen Takeoff directory."
            ),
            "warning",
        )

    def _show_available_message(self) -> None:
        self._post_message(
            "Realtime Monitoring Active",
            "Realtime monitoring is enabled.",
            "info",
        )

    def is_available(self) -> bool:
        return True

    def is_monitoring(self) -> bool:
        return self._is_monitoring

    def is_ost_active(self) -> bool:
        return self._is_monitoring and self._status_online

    def set_ost_status_callback(self, callback: Callable[[bool], None]) -> None:
        self._ost_status_callback = callback

    def start_monitoring(self, callback: Callable[[], None]) -> bool:
        if self._is_monitoring:
            return False
        self._callback = callback
        self._stop_flag.clear()
        self._is_monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="TransactionMonitor"
        )
        self._monitor_thread.start()
        return True

    def _process_single_event(self) -> None:
        if not self._event:
            return
        try:
            wait_time_ms = 100 if self._pending_callback else 1000
            result = self._event.wait(wait_time_ms)
            if result == ost_winevent.WAIT_OBJECT_0:
                with self._debounce_lock:
                    self._pending_callback = True
                    self._last_signal_time = time.time()
            elif result == WAIT_ABANDONED_0:
                logger.warning("Transaction event handle abandoned")
                self._reset_events()
            elif result == ost_winevent.WAIT_TIMEOUT:
                if self._pending_callback:
                    with self._debounce_lock:
                        elapsed = time.time() - self._last_signal_time
                        if elapsed >= self.DEBOUNCE_SECONDS:
                            self._pending_callback = False
                            if self._callback:
                                try:
                                    self._callback()
                                except Exception as e:
                                    logger.error(
                                        "Exception in transaction monitor callback: %s",
                                        e,
                                        exc_info=True,
                                    )
            else:
                logger.warning("Unexpected wait result: %s", result)
        except Exception as e:
            logger.error("Exception processing events: %s", e, exc_info=True)
            self._reset_events()

    def _monitor_loop(self) -> None:
        while not self._stop_flag.is_set():
            if not self._connect_to_events():
                self._stop_flag.wait(timeout=2.0)
                continue
            while not self._stop_flag.is_set() and self._event:
                self._process_single_event()
                self._check_status_state()
            self._reset_events()
            if self._event is None and not self._stop_flag.is_set():
                self._stop_flag.wait(timeout=2.0)
        self._reset_events()
        self._is_monitoring = False

    def stop_monitoring(self) -> None:
        if not self._is_monitoring:
            return
        self._stop_flag.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.5)
        self._reset_events()
        self._monitor_thread = None
        self._callback = None
        self._is_monitoring = False

    def cleanup(self) -> None:
        self.stop_monitoring()
        self._reset_events()
        self._status_online = False
        self._state = MonitorState.INITIAL
        self._ost_status_callback = None
        if self._notifier is not None:
            self._notifier.cleanup()
            self._notifier = None

    def _check_status_state(self) -> None:
        if not self._status_event:
            return
        try:
            wait_result = self._status_event.wait(0)
            current_status = wait_result == ost_winevent.WAIT_OBJECT_0
            if current_status != self._status_online:
                self._status_online = current_status
                if self._ost_status_callback:
                    self._ost_status_callback(self._status_online)
                if not self._status_online and self._state == MonitorState.CONNECTED:
                    self._state = MonitorState.DISCONNECTED
                    self._post_message(
                        "Realtime Monitoring Stopped",
                        "Realtime monitoring is disabled.",
                        "warning",
                    )
                    self._reset_events()
        except Exception as e:
            logger.error("Exception while checking status state: %s", e, exc_info=True)
            self._reset_events()

    def _reset_events(self) -> None:
        if self._event:
            self._event.close()
            self._event = None
        if self._status_event:
            self._status_event.close()
            self._status_event = None
        self._status_online = False
        if self._state == MonitorState.DISCONNECTED:
            self._state = MonitorState.WAITING_FOR_OST
