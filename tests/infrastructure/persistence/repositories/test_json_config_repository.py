import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)
from PySide6 import QtCore, QtGui, QtWidgets


class ConfigRepositoryFontColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

    def test_config_repository_round_trip_uses_only_the_canonical_file(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            repository = JsonConfigRepository(config_path)
            expected = Config(
                default_area_label_color="#123456",
                inactive_object_color="#abcdef",
            )
            repository.save(expected)
            self.assertEqual(repository.load(), expected)
            self.assertEqual(
                sorted(path.name for path in Path(temp_dir).iterdir()),
                ["config.json"],
            )
