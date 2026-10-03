import json
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)


class ElevationCalloutConfigTests(unittest.TestCase):
    CALLOUT_KEYS = (
        "html_elevation_callouts_enabled",
        "pdf_elevation_callouts_enabled",
        "elevation_callout_include_condition",
        "elevation_callout_include_top",
        "elevation_callout_include_bottom",
        "elevation_callout_include_cubic_yards",
        "html_elevation_callout_color",
        "pdf_elevation_callout_color",
    )

    def test_callout_settings_persist_through_existing_json_repository(self):
        # Two mirrored sets: every flag takes both values across them, so a flag
        # silently falling back to its default on save/load cannot pass both.
        mirrored = (
            Config(
                html_elevation_callouts_enabled=False,
                pdf_elevation_callouts_enabled=True,
                elevation_callout_include_condition=False,
                elevation_callout_include_top=False,
                elevation_callout_include_bottom=True,
                elevation_callout_include_cubic_yards=False,
                html_elevation_callout_color="#123456",
                pdf_elevation_callout_color="#abcdef",
            ),
            Config(
                html_elevation_callouts_enabled=True,
                pdf_elevation_callouts_enabled=False,
                elevation_callout_include_condition=True,
                elevation_callout_include_top=True,
                elevation_callout_include_bottom=False,
                elevation_callout_include_cubic_yards=True,
                html_elevation_callout_color="#fedcba",
                pdf_elevation_callout_color="#654321",
            ),
        )
        for key in self.CALLOUT_KEYS:
            self.assertNotEqual(
                getattr(mirrored[0], key), getattr(mirrored[1], key), key
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            repository = JsonConfigRepository(config_path=path)
            for index, expected in enumerate(mirrored):
                with self.subTest(index=index):
                    repository.save(expected)
                    # Independent read-back: a fresh repository over the same file
                    # plus the literal JSON the file holds.
                    self.assertEqual(
                        JsonConfigRepository(config_path=path).load(), expected
                    )
                    stored = json.loads(path.read_text(encoding="utf-8"))
                    for key in self.CALLOUT_KEYS:
                        self.assertEqual(stored[key], getattr(expected, key), key)

    def test_invalid_callout_colors_reset_to_canonical_defaults(self):
        # Each colour is validated independently: a valid one is kept (positive
        # control) while the invalid sibling falls back to the canonical default.
        for html, pdf, expected_html, expected_pdf in (
            ("not-a-color", "#12345g", "#ff0000", "#ff0000"),
            ("not-a-color", "#abcdef", "#ff0000", "#abcdef"),
            ("#123456", "#12345g", "#123456", "#ff0000"),
            ("#123456", "#abcdef", "#123456", "#abcdef"),
        ):
            with self.subTest(html=html, pdf=pdf):
                with tempfile.TemporaryDirectory() as temp_dir:
                    repository = JsonConfigRepository(
                        config_path=Path(temp_dir) / "config.json"
                    )
                    repository.save(
                        Config(
                            html_elevation_callout_color=html,
                            pdf_elevation_callout_color=pdf,
                        )
                    )
                    config = ConfigAggregate(repository).snapshot()
                self.assertEqual(config.html_elevation_callout_color, expected_html)
                self.assertEqual(config.pdf_elevation_callout_color, expected_pdf)
