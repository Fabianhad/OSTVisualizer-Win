import unittest
from dataclasses import fields
from ost_visualizer.domain.entities.elevation_callout import (
    ElevationCallout,
    ElevationCalloutSettings,
)


class ElevationCalloutResolverTests(unittest.TestCase):
    def test_resolved_dto_contains_only_rendered_content_and_center(self):
        self.assertEqual(
            {field.name for field in fields(ElevationCallout)},
            {"x", "y", "lines"},
        )


class ElevationCalloutSettingsTests(unittest.TestCase):
    FLAGS = (
        "include_condition",
        "include_top",
        "include_bottom",
        "include_cubic_yards",
    )

    def test_default_settings_include_everything_and_the_module_default_matches(self):
        from ost_visualizer.domain.entities.elevation_callout import (
            DEFAULT_ELEVATION_CALLOUT_SETTINGS,
        )

        settings = ElevationCalloutSettings()
        self.assertEqual([getattr(settings, name) for name in self.FLAGS], [True] * 4)
        self.assertEqual(DEFAULT_ELEVATION_CALLOUT_SETTINGS, settings)

    def test_has_content_is_true_for_each_single_flag_and_false_only_when_all_are_off(
        self,
    ):
        none = {name: False for name in self.FLAGS}
        self.assertIs(ElevationCalloutSettings(**none).has_content, False)
        for name in self.FLAGS:
            with self.subTest(only=name):
                settings = ElevationCalloutSettings(**{**none, name: True})
                self.assertIs(settings.has_content, True)
        for name in self.FLAGS:
            with self.subTest(everything_but=name):
                settings = ElevationCalloutSettings(**{name: False})
                self.assertIs(settings.has_content, True)

    def test_settings_and_resolved_callout_are_immutable_value_objects(self):
        from dataclasses import FrozenInstanceError

        settings = ElevationCalloutSettings()
        with self.assertRaises(FrozenInstanceError):
            settings.include_top = False
        callout = ElevationCallout(1.0, 2.0, ("a",))
        with self.assertRaises(FrozenInstanceError):
            callout.x = 5.0
        self.assertEqual(callout, ElevationCallout(1.0, 2.0, ("a",)))
        self.assertNotEqual(callout, ElevationCallout(1.0, 2.0, ("b",)))
