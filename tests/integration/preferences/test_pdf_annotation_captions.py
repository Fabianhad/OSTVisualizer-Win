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
            repository.save(expected)
            loaded = repository.load()
            self.assertEqual(loaded, expected)
            self.assertEqual(repository.config_path, config_path)
            self.assertEqual(list(Path(temp_dir).iterdir()), [config_path])

    def test_aggregate_preserves_selections_when_master_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConfigRepository(
                config_path=Path(temp_dir) / "config.json"
            )
            repository.save(
                Config(
                    pdf_annotation_captions_enabled=True,
                    pdf_annotation_caption_ids=("area", "volume"),
                )
            )
            aggregate = ConfigAggregate(repository)
            aggregate.update_options(
                Config(
                    pdf_annotation_captions_enabled=False,
                    pdf_annotation_caption_ids=("area", "volume"),
                )
            )
            config = aggregate.snapshot()
            self.assertFalse(config.pdf_annotation_captions_enabled)
            self.assertEqual(
                config.pdf_annotation_caption_ids,
                ("area", "volume"),
            )
            self.assertEqual(
                repository.load().pdf_annotation_caption_ids,
                ("area", "volume"),
            )

    def test_aggregate_canonicalizes_supported_caption_identifiers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConfigRepository(
                config_path=Path(temp_dir) / "config.json"
            )
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

    def test_aggregate_preserves_empty_caption_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConfigRepository(
                config_path=Path(temp_dir) / "config.json"
            )
            repository.save(Config(pdf_annotation_caption_ids=()))
            aggregate = ConfigAggregate(repository)
            self.assertEqual(aggregate.snapshot().pdf_annotation_caption_ids, ())
