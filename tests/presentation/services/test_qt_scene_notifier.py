import unittest
from ost_visualizer.presentation.services.qt_scene_notifier import QtSceneNotifier


class QtSceneNotifierLifecycleTests(unittest.TestCase):
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
