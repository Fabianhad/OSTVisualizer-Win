import inspect
import unittest
from dataclasses import fields
from ost_visualizer.application.events.app_events import (
    AppEvents,
    NativeSceneUpdatedEvent,
)
from ost_visualizer.application.interfaces.i_thread_scene_notifier import (
    IThreadSceneNotifier,
)
from ost_visualizer.presentation.services.qt_scene_notifier import QtSceneNotifier


class QtSceneNotifierLifecycleTests(unittest.TestCase):
    def test_native_scene_contract_has_no_legacy_bounds_payload(self):
        self.assertNotIn(
            "bounds",
            {field.name for field in fields(NativeSceneUpdatedEvent)},
        )
        self.assertNotIn(
            "bounds",
            inspect.signature(IThreadSceneNotifier.notify_scene_ready).parameters,
        )
        self.assertNotIn(
            "bounds",
            inspect.signature(QtSceneNotifier.notify_scene_ready).parameters,
        )
