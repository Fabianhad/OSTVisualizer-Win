import json
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)


class PdfAnnotationCaptionSettingsTests(unittest.TestCase):
    def test_caption_configuration_round_trips_through_existing_json_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            repository = JsonConfigRepository(config_path=config_path)
            expected = Config(
                pdf_annotation_captions_enabled=True,
                pdf_annotation_caption_ids=("area", "volume"),
            )
            # Neither value is the default, so the read-back cannot be a fallback.
            self.assertNotEqual(expected, Config())
            repository.save(expected)
            loaded = JsonConfigRepository(config_path=config_path).load()
            self.assertEqual(loaded, expected)
            stored = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIs(stored["pdf_annotation_captions_enabled"], True)
            self.assertEqual(stored["pdf_annotation_caption_ids"], ["area", "volume"])
            self.assertEqual(repository.config_path, config_path)
            self.assertEqual(list(Path(temp_dir).iterdir()), [config_path])

    def test_aggregate_preserves_selections_when_master_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            repository = JsonConfigRepository(config_path=config_path)
            repository.save(
                Config(
                    pdf_annotation_captions_enabled=True,
                    pdf_annotation_caption_ids=("area", "volume"),
                )
            )
            aggregate = ConfigAggregate(repository)
            self.assertEqual(
                aggregate.update_options(
                    Config(
                        pdf_annotation_captions_enabled=False,
                        pdf_annotation_caption_ids=("area", "volume"),
                    )
                ),
                ["pdf_annotation_captions_enabled"],
            )
            config = aggregate.snapshot()
            self.assertFalse(config.pdf_annotation_captions_enabled)
            self.assertEqual(
                config.pdf_annotation_caption_ids,
                ("area", "volume"),
            )
            reloaded = JsonConfigRepository(config_path=config_path).load()
            self.assertFalse(reloaded.pdf_annotation_captions_enabled)
            self.assertEqual(reloaded.pdf_annotation_caption_ids, ("area", "volume"))

    def test_aggregate_canonicalizes_supported_caption_identifiers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            repository = JsonConfigRepository(config_path=config_path)
            repository.save(
                Config(
                    pdf_annotation_caption_ids=(
                        "volume",
                        "unknown",
                        "area",
                        "volume",
                    )
                )
            )
            aggregate = ConfigAggregate(repository)
            self.assertEqual(
                aggregate.snapshot().pdf_annotation_caption_ids,
                ("area", "volume"),
            )
            # The correction is written back, so the file holds the canonical list.
            stored = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["pdf_annotation_caption_ids"], ["area", "volume"])

    def test_aggregate_preserves_empty_caption_selection(self):
        # The default selection is also empty, so start from a populated one: the
        # user clearing every caption must persist as empty and not revert.
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            repository = JsonConfigRepository(config_path=config_path)
            repository.save(
                Config(
                    pdf_annotation_captions_enabled=True,
                    pdf_annotation_caption_ids=("area",),
                )
            )
            aggregate = ConfigAggregate(repository)
            self.assertEqual(aggregate.snapshot().pdf_annotation_caption_ids, ("area",))
            self.assertEqual(
                aggregate.update_options(
                    Config(
                        pdf_annotation_captions_enabled=True,
                        pdf_annotation_caption_ids=(),
                    )
                ),
                ["pdf_annotation_caption_ids"],
            )
            self.assertEqual(aggregate.snapshot().pdf_annotation_caption_ids, ())
            stored = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["pdf_annotation_caption_ids"], [])
            reloaded = ConfigAggregate(JsonConfigRepository(config_path=config_path))
            self.assertEqual(reloaded.snapshot().pdf_annotation_caption_ids, ())
            self.assertTrue(reloaded.snapshot().pdf_annotation_captions_enabled)
