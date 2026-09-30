from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
import unittest
import os
from pathlib import Path
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)
from PySide6 import QtCore, QtGui, QtWidgets


class _ConfigRepository:
    config_path = "config.json"

    def __init__(self, config):
        self.config = config
        self.saved = []

    def load(self):
        return self.config

    def save(self, config):
        self.config = Config.from_dict(config.to_dict())
        self.saved.append(self.config)


class ConfigAggregateValidationTests(unittest.TestCase):
    def test_validation_constants_are_immutable_shared_state(self):
        self.assertIsInstance(ConfigAggregate.VALID_DISPLAY_MODES, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_ROPING_SELECTION_METHODS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_HOTLINK_TARGETS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_MOUSE_SNAP_ANGLES, frozenset)


class ConfigAggregateFontColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

    def test_invalid_new_fields_are_corrected_independently(self):
        config = Config(
            default_text_font=FontDefinition("", "Bold", 12, 700, False, False),
            default_area_label_color="blue",
            default_hotlink_color="#ABCDEF",
            show_toolbar_text=False,
        )
        repository = _ConfigRepository(config)
        aggregate = ConfigAggregate(repository)
        snapshot = aggregate.snapshot()
        self.assertEqual(snapshot.default_text_font, Config.DEFAULT_TEXT_FONT)
        self.assertEqual(
            snapshot.default_area_label_color, Config.DEFAULT_AREA_LABEL_COLOR
        )
        self.assertEqual(snapshot.default_hotlink_color, "#abcdef")
        self.assertFalse(snapshot.show_toolbar_text)
        self.assertEqual(len(repository.saved), 1)
