import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.services.qt_scene_notifier import QtSceneNotifier
from PySide6.QtCore import QCoreApplication


class QtSceneNotifierLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def test_scene_outcome_crosses_qt_bridge_and_cleanup_blocks_late_callbacks(self):
        notifier = QtSceneNotifier()
        scene_calls = []
        notifier.set_handlers(
            on_scene_ready=lambda geometries, generation, scene_failed: scene_calls.append(
                (geometries, generation, scene_failed)
            ),
            on_full_refresh=lambda _file_path: None,
        )
        notifier.notify_scene_ready([], 7, True)
        notifier.cleanup()
        notifier.notify_scene_ready([], 8, False)
        self.assertEqual(scene_calls, [([], 7, True)])

    def test_worker_thread_notification_is_delivered_on_the_qt_thread(self):
        notifier = QtSceneNotifier()
        calls = []
        notifier.set_handlers(
            on_scene_ready=lambda geometries, generation, scene_failed: calls.append(
                (threading.get_ident(), generation, scene_failed)
            ),
            on_full_refresh=lambda file_path: calls.append(
                (threading.get_ident(), file_path)
            ),
        )
        worker = threading.Thread(
            target=lambda: (
                notifier.notify_scene_ready([], 3, False),
                notifier.notify_full_refresh("C:/jobs/a.mdb"),
            )
        )
        worker.start()
        worker.join()
        self.assertEqual(calls, [])
        QCoreApplication.processEvents()
        main_thread = threading.get_ident()
        self.assertEqual(
            calls,
            [(main_thread, 3, False), (main_thread, "C:/jobs/a.mdb")],
        )
        notifier.cleanup()

    def test_replacing_handlers_disconnects_the_previous_ones(self):
        notifier = QtSceneNotifier()
        old_calls = []
        new_calls = []
        notifier.set_handlers(
            on_scene_ready=lambda *args: old_calls.append(args),
            on_full_refresh=lambda path: old_calls.append(path),
        )
        notifier.set_handlers(
            on_scene_ready=lambda *args: new_calls.append(args),
            on_full_refresh=lambda path: new_calls.append(path),
        )
        notifier.notify_scene_ready([], 1, False)
        notifier.notify_full_refresh("C:/jobs/a.mdb")
        self.assertEqual(old_calls, [])
        self.assertEqual(new_calls, [([], 1, False), "C:/jobs/a.mdb"])
        notifier.cleanup()

    def test_cleanup_blocks_late_full_refresh_callbacks(self):
        notifier = QtSceneNotifier()
        refreshes = []
        notifier.set_handlers(
            on_scene_ready=lambda *_args: None,
            on_full_refresh=refreshes.append,
        )
        notifier.notify_full_refresh("C:/jobs/a.mdb")
        notifier.cleanup()
        notifier.notify_full_refresh("C:/jobs/b.mdb")
        QCoreApplication.processEvents()
        self.assertEqual(refreshes, ["C:/jobs/a.mdb"])
