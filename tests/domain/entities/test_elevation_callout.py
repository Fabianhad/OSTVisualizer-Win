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
