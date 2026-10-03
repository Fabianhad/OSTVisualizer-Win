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
        event_fields = {field.name for field in fields(NativeSceneUpdatedEvent)}
        interface_parameters = inspect.signature(
            IThreadSceneNotifier.notify_scene_ready
        ).parameters
        implementation_parameters = inspect.signature(
            QtSceneNotifier.notify_scene_ready
        ).parameters
        # Positive controls: the inspected payloads are the real scene
        # contract, so a missing "bounds" is not an artefact of inspecting an
        # empty or unrelated signature.
        self.assertTrue({"geometries", "scene_identity"} <= event_fields)
        for parameters in (interface_parameters, implementation_parameters):
            self.assertTrue({"geometries", "gen_id", "scene_failed"} <= set(parameters))
        self.assertNotIn("bounds", event_fields)
        self.assertNotIn("bounds", interface_parameters)
        self.assertNotIn("bounds", implementation_parameters)
