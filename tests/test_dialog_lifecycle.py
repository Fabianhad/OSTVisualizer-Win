import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from ost_visualizer.application.dtos.license_view_model_dto import LicenseViewModelDto
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseResult,
    ResourceRef,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation import main_window as main_window_module
from ost_visualizer.presentation.components.progress_dialog import (
    ProgressDialog,
    ProgressReporter,
)
from ost_visualizer.presentation.coordinators.event_coordinator import EventCoordinator
from ost_visualizer.presentation.coordinators.license_ui_coordinator import (
    LicenseUICoordinator,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.coordinators import (
    license_ui_coordinator as license_ui_coordinator_module,
)
from ost_visualizer.presentation.dialogs.license_dialog import LicenseDialog
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.utils.dialog import BaseListDialog
from ost_visualizer.presentation.utils.qt_message_notifier import QtMessageNotifier
from ost_visualizer.presentation.utils.ost_blocking import exec_with_ost_blocking
from ost_visualizer.presentation.utils.windows import set_fixed_width_auto_height


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _painted_x_bounds(widget):
    image = widget.grab().toImage()
    background = image.pixelColor(0, 0)
    min_x = image.width()
    max_x = -1
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            color_delta = (
                abs(color.red() - background.red())
                + abs(color.green() - background.green())
                + abs(color.blue() - background.blue())
            )
            if color.alpha() > 0 and color_delta > 12:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
    return min_x, max_x, image.width()


class FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.unsubscriptions.append((event_type, callback))


class FakeIconProvider:
    def set_window_icon(self, _widget):
        pass


class FakeLicenseOrchestrator:
    def __init__(self, view_model=None):
        self._view_model = view_model or LicenseViewModelDto(has_license=False)

    def get_view_model(self):
        return self._view_model

    def has_valid_license(self):
        return False


class FakeProgressDialog:
    instances = []
    result_code = QtWidgets.QDialog.DialogCode.Accepted

    def __init__(
        self,
        filename,
        task_fn,
        parent=None,
        reporter=None,
        action_text="Processing",
    ):
        self.filename = filename
        self.task_fn = task_fn
        self.parent = parent
        self.reporter = reporter
        self.action_text = action_text
        self.result = None
        self.error = None
        self.cleaned_up = False
        self.deleted = False
        self.exec_calls = 0
        self.cleanup_calls = 0
        self.delete_calls = 0
        self.messages = []
        if reporter is not None:
            reporter.progress.connect(self.messages.append)
        FakeProgressDialog.instances.append(self)

    def exec(self):
        self.exec_calls += 1
        self.result = self.task_fn()
        return self.result_code

    def cleanup(self):
        self.cleanup_calls += 1
        self.cleaned_up = True

    def deleteLater(self):
        self.delete_calls += 1
        self.deleted = True


class DialogLifecycleTests(unittest.TestCase):
    def test_collaboration_modal_return_marks_destroyed_dialog_unexecuted(self):
        _app()
        parent = QtWidgets.QWidget()
        dialog = QtWidgets.QDialog(parent)
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.event_bus = EventBus()
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="dialog",
            owning_surface="main-window-dialog",
            resources=(ResourceRef("page", "page-1", 8),),
        )
        released = []
        cleaned = []
        after_close = []
        coordinator.end_collaboration_edit = released.append

        def request_edit(_database_id, _resources, callback, **_kwargs):
            callback(EditLeaseResult(True, handle=handle))

        coordinator.request_collaboration_edit = request_edit

        def destroy_parent(_dialog, _event_bus):
            delete(parent)
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "exec_with_ost_blocking",
            side_effect=destroy_parent,
        ):
            coordinator._exec_with_collaboration_lease(
                dialog,
                "database",
                handle.resources,
                lambda: cleaned.append(True),
                after_close.append,
            )
        self.assertEqual(released, [handle])
        self.assertEqual(cleaned, [True])
        self.assertEqual(after_close, [False])

    def test_message_notifier_cleanup_tolerates_parent_destroyed_dialog(self):
        _app()
        parent = QtWidgets.QDialog()
        parent.show()
        notifier = QtMessageNotifier(parent=None)
        notifier.set_parent(parent)
        notifier.post_message("Notice", "Queued work completed")
        self.assertIsNotNone(notifier._current_dialog)
        delete(parent)
        notifier.cleanup()
        self.assertIsNone(notifier._current_dialog)
        self.assertIsNone(notifier._default_parent)

    def test_message_notifier_drops_stale_queue_after_parent_is_destroyed(self):
        _app()
        parent = QtWidgets.QDialog()
        notifier = QtMessageNotifier(parent=None)
        notifier.set_parent(parent)
        notifier._update_active = True
        notifier.post_message("Notice", "Queued work completed")
        self.assertEqual(len(notifier._queue), 1)
        delete(parent)
        notifier._update_active = False
        notifier._maybe_show_next()
        self.assertEqual(notifier._queue, [])
        self.assertIsNone(notifier._current_dialog)
        self.assertIsNone(notifier._default_parent)
        notifier.cleanup()

    def test_fixed_width_auto_height_tracks_layout_spacing(self):
        _app()
        dialog = QtWidgets.QDialog()
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel("First row"))
        layout.addWidget(QtWidgets.QLabel("Second row"))
        layout.setSpacing(5)
        set_fixed_width_auto_height(dialog, 240)
        compact_height = dialog.height()
        layout.setSpacing(25)
        set_fixed_width_auto_height(dialog, 240)
        try:
            self.assertEqual(dialog.width(), 240)
            self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
            self.assertEqual(dialog.height(), compact_height + 20)
        finally:
            dialog.deleteLater()

    def test_base_list_dialog_cleanup_releases_save_callback(self):
        dialog = BaseListDialog.__new__(BaseListDialog)
        retained = object()
        dialog.icon_provider = retained
        dialog._save_fn = lambda: retained
        dialog._on_cleanup = lambda: None
        BaseListDialog.cleanup(dialog)
        self.assertIsNone(dialog.icon_provider)
        self.assertIsNone(dialog._save_fn)

    def test_license_dialog_ignores_stale_status_event_after_cleanup(self):
        _app()
        event_bus = FakeEventBus()
        dialog = LicenseDialog(
            FakeIconProvider(),
            None,
            FakeLicenseOrchestrator(),
            event_bus,
        )
        dialog.done(0)
        dialog._on_license_status_changed()
        self.assertEqual(
            event_bus.unsubscriptions,
            [(AppEvents.LICENSE_STATUS_CHANGED, dialog._on_license_status_changed)],
        )
        self.assertIsNone(dialog.event_bus)
        self.assertIsNone(dialog.license_orchestrator)

    def test_license_dialog_projects_hardware_identity_failure(self):
        _app()
        event_bus = FakeEventBus()
        message = "The machine identity is unavailable."
        dialog = LicenseDialog(
            FakeIconProvider(),
            None,
            FakeLicenseOrchestrator(
                LicenseViewModelDto(
                    has_license=False,
                    message=message,
                    hardware_identity_available=False,
                )
            ),
            event_bus,
        )
        try:
            self.assertEqual(
                dialog.status_label.text(), "Status: Hardware ID Unavailable"
            )
            self.assertEqual(dialog.status_label.toolTip(), message)
        finally:
            dialog.done(0)

    def test_license_dialog_constructor_failure_unsubscribes_event_callback(self):
        _app()
        event_bus = EventBus()

        class FailingLicenseOrchestrator(FakeLicenseOrchestrator):
            def get_view_model(self):
                raise RuntimeError("view model unavailable")

        with self.assertRaisesRegex(RuntimeError, "view model unavailable"):
            LicenseDialog(
                FakeIconProvider(),
                None,
                FailingLicenseOrchestrator(),
                event_bus,
            )
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=False)

    def test_event_coordinator_cleanup_releases_event_bus_reference(self):
        event_bus = FakeEventBus()
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
        class FailingEventBus(FakeEventBus):
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
        class FailingEventBus(FakeEventBus):
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
        class TransientEventBus(FakeEventBus):
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

    def test_event_bus_skips_subscriber_removed_during_same_publish(self):
        event_bus = EventBus()
        coordinator = EventCoordinator(event_bus)
        delivered = []
        event_bus.subscribe(
            AppEvents.LICENSE_STATUS_CHANGED,
            lambda **_: coordinator.cleanup(),
        )
        coordinator.register(
            AppEvents.LICENSE_STATUS_CHANGED,
            lambda **_: delivered.append("stale"),
        )
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertEqual(delivered, [])

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

    def test_ost_blocking_skips_access_change_after_dialog_is_destroyed(self):
        _app()
        event_bus = EventBus()

        class Signal:
            def __init__(self):
                self.callback = None

            def connect(self, callback):
                self.callback = callback

            def emit(self, active):
                self.callback(active)

        class Signaler:
            def __init__(self):
                self.ost_changed = Signal()

            def deleteLater(self):
                pass

        class Dialog(QtWidgets.QDialog):
            def set_interactive(self, enabled):
                self.setEnabled(enabled)

            def exec(self):
                event_bus.publish(AppEvents.OST_STATUS_CHANGED, active=True)
                return QtWidgets.QDialog.DialogCode.Rejected

        dialog = Dialog()
        event_bus.subscribe(
            AppEvents.OST_STATUS_CHANGED,
            lambda **_payload: delete(dialog),
        )
        with patch(
            "ost_visualizer.presentation.utils.ost_blocking.OstSignaler",
            Signaler,
        ):
            result = exec_with_ost_blocking(dialog, event_bus)
        self.assertEqual(result, QtWidgets.QDialog.DialogCode.Rejected)

    def test_license_dialog_return_does_not_touch_cleaned_coordinator(self):
        status_updates = []
        menu_updates = []
        coordinator = LicenseUICoordinator(
            window=object(),
            icon_provider=object(),
            license_orchestrator=FakeLicenseOrchestrator(),
            event_bus=FakeEventBus(),
            status_panel=type(
                "StatusPanel",
                (),
                {
                    "set_license_active": lambda _self, active: status_updates.append(
                        active
                    )
                },
            )(),
            menu_controller=type(
                "MenuController",
                (),
                {"update_menu_states": lambda _self: menu_updates.append(True)},
            )(),
        )

        class ClosingLicenseDialog:
            def __init__(self, *_args):
                self.license_orchestrator = object()
                self.event_bus = object()

            def exec(self):
                coordinator.cleanup()

            def cleanup(self):
                self.license_orchestrator = None
                self.event_bus = None

            def deleteLater(self):
                pass

        with patch.object(
            license_ui_coordinator_module,
            "LicenseDialog",
            ClosingLicenseDialog,
        ):
            coordinator.show_dialog()
        self.assertEqual(status_updates, [])
        self.assertEqual(menu_updates, [])

    def test_license_dialog_return_tolerates_parent_destroying_dialog(self):
        _app()
        coordinator = LicenseUICoordinator(
            window=object(),
            icon_provider=object(),
            license_orchestrator=FakeLicenseOrchestrator(),
            event_bus=FakeEventBus(),
            status_panel=SimpleNamespace(set_license_active=lambda _active: None),
            menu_controller=SimpleNamespace(update_menu_states=lambda: None),
        )

        class DestroyedLicenseDialog(QtWidgets.QDialog):
            def __init__(self, *_args):
                super().__init__()
                self.license_orchestrator = object()
                self.event_bus = object()

            def exec(self):
                delete(self)
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                self.license_orchestrator = None
                self.event_bus = None

        with patch.object(
            license_ui_coordinator_module,
            "LicenseDialog",
            DestroyedLicenseDialog,
        ):
            coordinator.show_dialog()

    def test_destroyed_license_dialog_releases_event_subscription(self):
        _app()
        parent = QtWidgets.QDialog()
        event_bus = EventBus()
        coordinator = LicenseUICoordinator(
            window=parent,
            icon_provider=FakeIconProvider(),
            license_orchestrator=FakeLicenseOrchestrator(),
            event_bus=event_bus,
            status_panel=SimpleNamespace(set_license_active=lambda _active: None),
            menu_controller=SimpleNamespace(update_menu_states=lambda: None),
        )

        def destroy_parent(_dialog):
            delete(parent)
            event_bus.publish(
                AppEvents.LICENSE_STATUS_CHANGED,
                has_license=False,
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch.object(LicenseDialog, "exec", destroy_parent):
            coordinator.show_dialog()
        event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=False)

    def test_ui_event_cleanup_attempts_later_stages_and_retries_unsubscribe(self):
        calls = []

        class EventBus:
            def __init__(self):
                self.attempts = 0

            def unsubscribe(self, event_type, _callback):
                calls.append(f"unsubscribe:{event_type.__name__}")
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("transient unsubscribe")

        def failing(name):
            def cleanup():
                calls.append(name)
                raise RuntimeError(f"{name} failed")

            return cleanup

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.project_operations = SimpleNamespace(
            cancel_navigation_load=failing("navigation")
        )
        coordinator._status_panel = None
        coordinator._sync_collaboration_status = lambda *_args, **_kwargs: None
        coordinator._invalidate_mesh_scene_request = lambda: None
        coordinator._plan_view_handler = None
        coordinator._view_stack = None
        coordinator._tab_widget = None
        coordinator._undo_service = None
        coordinator.event_bus = EventBus()
        coordinator._subscriptions = [
            (AppEvents.LICENSE_STATUS_CHANGED, lambda **_: None),
            (AppEvents.FILE_OPENED, lambda **_: None),
        ]
        coordinator._plan_view_signaler = None
        coordinator._menu_state_signaler = None
        coordinator._bid_data_cache = None
        coordinator._pending_3d_takeoff_uids_by_database = {}
        coordinator._mesh_window = None
        coordinator._mesh_window_action = None
        coordinator._placement = SimpleNamespace(cleanup=failing("placement"))
        coordinator.opengl_viewer = SimpleNamespace(
            cleanup=lambda: calls.append("viewer")
        )
        coordinator.takeoff_sidebar = None
        coordinator.plan_view = None
        coordinator._sidebar = None
        coordinator._viewer = None
        coordinator._toolbar = None
        coordinator.main_window = object()
        coordinator.ui_state_manager = object()
        coordinator.ui_access_manager = object()
        coordinator.project_data = object()
        coordinator.visualization_service = object()
        coordinator._color_service = object()
        coordinator._icon_provider = object()
        coordinator._project_write_service = object()
        coordinator._project_read_service = object()
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator._condition_handler = object()
        coordinator._deferred_persistence = object()
        with self.assertRaises(ExceptionGroup) as captured:
            coordinator.cleanup()
        self.assertEqual(
            [str(error) for error in captured.exception.exceptions],
            [
                "navigation failed",
                "transient unsubscribe",
                "placement failed",
            ],
        )
        self.assertIn("viewer", calls)
        self.assertEqual(len(coordinator._subscriptions), 1)
        coordinator.cleanup()
        self.assertEqual(coordinator._subscriptions, [])
        self.assertIsNone(coordinator.event_bus)

    def test_progress_dialog_cleanup_releases_worker_callback_references(self):
        dialog = ProgressDialog.__new__(ProgressDialog)
        retained = object()
        dialog._task_fn = lambda: retained
        dialog._thread = None
        dialog._worker = object()
        dialog._reporter = None
        dialog._label = object()
        dialog._progress = object()
        dialog._cleaned_up = False
        dialog._cleanup_complete = False
        ProgressDialog.cleanup(dialog)
        ProgressDialog.cleanup(dialog)
        self.assertIsNone(dialog._task_fn)
        self.assertIsNone(dialog._worker)
        self.assertIsNone(dialog._thread)
        self.assertIsNone(dialog._reporter)
        self.assertIsNone(dialog._label)
        self.assertIsNone(dialog._progress)

    def test_progress_dialog_cleanup_retries_after_worker_wait_timeout(self):
        class Signal:
            def __init__(self):
                self.disconnect_calls = 0

            def disconnect(self, _callback):
                self.disconnect_calls += 1

        class Thread:
            def __init__(self):
                self.finished = Signal()
                self.wait_calls = 0

            def isRunning(self):
                return True

            def quit(self):
                pass

            def wait(self, _timeout):
                self.wait_calls += 1
                return self.wait_calls > 1

        thread = Thread()
        dialog = ProgressDialog.__new__(ProgressDialog)
        dialog._task_fn = lambda: None
        dialog._thread = thread
        dialog._worker = object()
        dialog._reporter = None
        dialog._label = object()
        dialog._progress = object()
        dialog._cleaned_up = False
        dialog._cleanup_complete = False
        ProgressDialog.cleanup(dialog)
        ProgressDialog.cleanup(dialog)
        self.assertEqual(thread.wait_calls, 2)
        self.assertEqual(thread.finished.disconnect_calls, 1)
        self.assertIsNone(dialog._thread)
        self.assertIsNone(dialog._task_fn)

    def test_progress_dialog_cleanup_tolerates_destroyed_qt_children(self):
        _app()
        dialog = ProgressDialog("export.ost", lambda: True)
        delete(dialog)
        dialog.cleanup()
        self.assertTrue(dialog._cleanup_complete)
        self.assertIsNone(dialog._progress)

    def test_progress_dialog_ignores_worker_finish_after_cleanup(self):
        dialog = ProgressDialog.__new__(ProgressDialog)
        accepted = []
        rejected = []
        dialog._cleaned_up = True
        dialog._result = None
        dialog._error = None
        dialog.accept = lambda: accepted.append(True)
        dialog.reject = lambda: rejected.append(True)
        ProgressDialog._on_finished(dialog, True, RuntimeError("late"))
        self.assertIsNone(dialog._result)
        self.assertIsNone(dialog._error)
        self.assertEqual(accepted, [])
        self.assertEqual(rejected, [])

    def test_progress_dialog_does_not_start_worker_before_show(self):
        _app()
        calls = []
        dialog = ProgressDialog("export.ost", lambda: calls.append("run") or True)
        try:
            self.assertEqual(calls, [])
            self.assertFalse(dialog._started)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_is_fixed_size_with_centered_progress_bar(self):
        _app()
        dialog = ProgressDialog("export.ost", lambda: True)
        try:
            self.assertEqual(dialog.minimumWidth(), dialog.maximumWidth())
            self.assertEqual(dialog.minimumHeight(), dialog.maximumHeight())
            self.assertFalse(dialog.isSizeGripEnabled())
            self.assertLess(dialog._progress.width(), dialog.width())
            progress_item = dialog.layout().itemAt(1)
            self.assertEqual(
                progress_item.alignment(),
                QtCore.Qt.AlignmentFlag.AlignHCenter,
            )
            self.assertTrue(
                bool(dialog._label.alignment() & QtCore.Qt.AlignmentFlag.AlignHCenter)
            )
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_paints_track_across_full_progress_width(self):
        _app()
        dialog = ProgressDialog("export.ost", lambda: True)
        try:
            min_x, max_x, width = _painted_x_bounds(dialog._progress)
            self.assertEqual(min_x, 0)
            self.assertEqual(max_x, width - 1)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_title_bar_has_no_window_buttons(self):
        _app()
        dialog = ProgressDialog("export.ost", lambda: True)
        try:
            flags = dialog.windowFlags()
            self.assertTrue(bool(flags & QtCore.Qt.WindowType.Dialog))
            self.assertTrue(bool(flags & QtCore.Qt.WindowType.CustomizeWindowHint))
            self.assertTrue(bool(flags & QtCore.Qt.WindowType.WindowTitleHint))
            self.assertFalse(
                bool(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint)
            )
            self.assertFalse(
                bool(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint)
            )
            self.assertFalse(bool(flags & QtCore.Qt.WindowType.WindowCloseButtonHint))
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_progress_dialog_runs_task_on_worker_thread_after_show(self):
        _app()
        ui_thread = threading.get_ident()
        task_threads = []

        def task():
            task_threads.append(threading.get_ident())
            return True

        dialog = ProgressDialog("export.ost", task)
        QtCore.QTimer.singleShot(5000, dialog.reject)
        try:
            rc = dialog.exec()
            self.assertEqual(rc, QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.result, True)
            self.assertEqual(len(task_threads), 1)
            self.assertNotEqual(task_threads[0], ui_thread)
        finally:
            worker_thread = dialog._thread
            dialog.cleanup()
            self.assertIsNotNone(worker_thread)
            self.assertFalse(worker_thread.isRunning())
            dialog.deleteLater()

    def test_progress_dialog_delivers_worker_progress_to_label(self):
        _app()
        reporter = ProgressReporter()

        def task():
            reporter.report("page 1")
            return True

        dialog = ProgressDialog("export.pdf", task, reporter=reporter)
        QtCore.QTimer.singleShot(5000, dialog.reject)
        try:
            rc = dialog.exec()
            self.assertEqual(rc, QtWidgets.QDialog.DialogCode.Accepted)
            self.assertIn("page 1", dialog._label.text())
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_create_database_uses_progress_dialog_worker_task(self):
        class FakeAppController:
            def __init__(self):
                self.calls = []

            def create_new_database(self, name=None, progress_callback=None):
                self.calls.append((name, progress_callback is not None))
                if progress_callback is not None:
                    progress_callback("schema tables")
                return "created.mdb"

        window = MainWindow.__new__(MainWindow)
        window.app_controller = FakeAppController()
        original_dialog = main_window_module.ProgressDialog
        FakeProgressDialog.instances = []
        FakeProgressDialog.result_code = QtWidgets.QDialog.DialogCode.Accepted
        try:
            main_window_module.ProgressDialog = FakeProgressDialog
            result = MainWindow._create_database_with_progress(window, "Named DB")
        finally:
            main_window_module.ProgressDialog = original_dialog
        dialog = FakeProgressDialog.instances[0]
        self.assertEqual(result, "created.mdb")
        self.assertEqual(dialog.filename, "new database")
        self.assertEqual(dialog.action_text, "Creating database")
        self.assertEqual(window.app_controller.calls, [("Named DB", True)])
        self.assertEqual(dialog.messages, ["schema tables"])
        self.assertEqual(dialog.exec_calls, 1)
        self.assertEqual(dialog.cleanup_calls, 1)
        self.assertEqual(dialog.delete_calls, 1)
        self.assertTrue(dialog.cleaned_up)
        self.assertTrue(dialog.deleted)

    def test_create_database_progress_dialog_failure_cleans_up(self):
        class FakeAppController:
            def create_new_database(self, name=None, progress_callback=None):
                return None

        window = MainWindow.__new__(MainWindow)
        window.app_controller = FakeAppController()
        original_dialog = main_window_module.ProgressDialog
        FakeProgressDialog.instances = []
        FakeProgressDialog.result_code = QtWidgets.QDialog.DialogCode.Rejected
        try:
            main_window_module.ProgressDialog = FakeProgressDialog
            result = MainWindow._create_database_with_progress(window)
        finally:
            main_window_module.ProgressDialog = original_dialog
        dialog = FakeProgressDialog.instances[0]
        self.assertIsNone(result)
        self.assertEqual(dialog.exec_calls, 1)
        self.assertEqual(dialog.cleanup_calls, 1)
        self.assertEqual(dialog.delete_calls, 1)
        self.assertTrue(dialog.cleaned_up)
        self.assertTrue(dialog.deleted)

    def test_create_database_prompt_stops_after_main_window_destruction(self):
        _app()
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._collaboration_shutdown_pending = False
        window._shutdown_deferred_callbacks = {}
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window.icon_provider = None
        continued = []
        window._complete_create_database_prompt = lambda: continued.append(True)

        class DestroyingDialog(QtWidgets.QDialog):
            def __init__(self, _icon_provider, parent):
                super().__init__(parent)

            def exec(self):
                delete(window)
                return QtWidgets.QDialog.DialogCode.Accepted

        with patch.object(main_window_module, "CreateDatabaseDialog", DestroyingDialog):
            MainWindow._prompt_create_database(window)
        self.assertEqual(continued, [])

    def test_create_database_progress_stops_after_main_window_destruction(self):
        _app()
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        window.app_controller = SimpleNamespace(create_new_database=lambda *_args: "x")
        cleaned = []

        class DestroyingProgress(QtWidgets.QDialog):
            def __init__(self, *_args, parent=None, **_kwargs):
                super().__init__(parent)

            def exec(self):
                delete(window)
                return QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                cleaned.append(True)

        with patch.object(main_window_module, "ProgressDialog", DestroyingProgress):
            result = MainWindow._create_database_with_progress(window)
        self.assertIsNone(result)
        self.assertEqual(cleaned, [])


if __name__ == "__main__":
    unittest.main()
