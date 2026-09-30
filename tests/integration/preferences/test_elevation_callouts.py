import tempfile
import unittest
from pathlib import Path
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)


class ElevationCalloutConfigTests(unittest.TestCase):
    def test_callout_settings_persist_through_existing_json_repository(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConfigRepository(
                config_path=Path(temp_dir) / "config.json"
            )
            expected = Config(
                html_elevation_callouts_enabled=False,
                pdf_elevation_callouts_enabled=True,
                elevation_callout_include_condition=False,
                elevation_callout_include_top=False,
                elevation_callout_include_bottom=True,
                elevation_callout_include_cubic_yards=False,
                html_elevation_callout_color="#123456",
                pdf_elevation_callout_color="#abcdef",
            )
            repository.save(expected)
            self.assertEqual(repository.load(), expected)

    def test_invalid_callout_colors_reset_to_canonical_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConfigRepository(
                config_path=Path(temp_dir) / "config.json"
            )
            repository.save(
                Config(
                    html_elevation_callout_color="not-a-color",
                    pdf_elevation_callout_color="#12345g",
                )
            )
            config = ConfigAggregate(repository).snapshot()
        self.assertEqual(config.html_elevation_callout_color, "#ff0000")
        self.assertEqual(config.pdf_elevation_callout_color, "#ff0000")
