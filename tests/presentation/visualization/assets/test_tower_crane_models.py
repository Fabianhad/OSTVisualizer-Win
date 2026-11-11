import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.presentation.visualization.assets import (
    tower_crane_models as models,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
    TOWER_CRANE_KIT_FILES,
    TOWER_CRANE_MODELS_DIR,
    load_tower_crane_kit,
    tower_crane_catalog,
    tower_crane_kit,
    tower_crane_kits,
)


def _rewrite_metadata(data, change):
    length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + length])
    change(document["asset"]["extras"]["kit"])
    body = bytearray(json.dumps(document).encode("utf-8"))
    while len(body) % 4:
        body += b" "
    rest = data[20 + length :]
    return (
        struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(body) + len(rest))
        + struct.pack("<I4s", len(body), b"JSON")
        + bytes(body)
        + rest
    )


class TowerCraneModelRegistryTests(unittest.TestCase):
    def test_the_shipped_kits_are_listed_in_selector_order(self):
        self.assertEqual(
            TOWER_CRANE_KIT_FILES,
            ("tower_crane_classic.glb", "tower_crane_liebherr.glb"),
        )
        kits = tower_crane_kits()
        self.assertEqual([kit.model.id for kit in kits], ["classic", "liebherr"])
        self.assertEqual([kit.path.name for kit in kits], list(TOWER_CRANE_KIT_FILES))
        self.assertEqual(tower_crane_catalog().ids, ("classic", "liebherr"))
        self.assertIs(tower_crane_catalog().default, kits[0].model)

    def test_a_kit_is_found_by_its_model_id(self):
        self.assertEqual(tower_crane_kit("liebherr").model.label, "Liebherr")
        self.assertEqual(
            tower_crane_kit("liebherr").credit["title"], "Liebherr tower crane"
        )
        self.assertEqual(tower_crane_kit("classic").credit["author"], "Chamod")
        self.assertIsNone(tower_crane_kit("potain"))

    def test_a_kit_must_hold_the_model_its_file_is_named_for(self):
        data = (TOWER_CRANE_MODELS_DIR / "tower_crane_liebherr.glb").read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            wrong = Path(folder) / "tower_crane_other.glb"
            wrong.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "holds model 'liebherr'"):
                load_tower_crane_kit(wrong)
            no_credit = Path(folder) / "tower_crane_liebherr.glb"
            no_credit.write_bytes(
                _rewrite_metadata(data, lambda kit: kit.pop("credit"))
            )
            with self.assertRaisesRegex(ValueError, "no credit"):
                load_tower_crane_kit(no_credit)
            # Help > About and the export print every credit field, so a credit
            # that lacks one (or holds a non-text value) makes the kit unusable.
            for field, value in (("license_url", None), ("author", 7)):
                with self.subTest(field=field):

                    def damage(kit, field=field, value=value):
                        if value is None:
                            kit["credit"].pop(field)
                        else:
                            kit["credit"][field] = value

                    no_credit.write_bytes(_rewrite_metadata(data, damage))
                    with self.assertRaisesRegex(ValueError, f"credit lacks {field}"):
                        load_tower_crane_kit(no_credit)

    def test_a_kit_whose_default_crane_cannot_be_laid_out_is_refused(self):
        # A kit missing a key the layout reads would load, then fail every time
        # a crane of that model is drawn; it is refused when it loads instead.
        data = (TOWER_CRANE_MODELS_DIR / "tower_crane_liebherr.glb").read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "tower_crane_liebherr.glb"
            for name, damage in (
                ("trolley_rope", lambda kit: kit["anchors"].pop("trolley_rope")),
                ("pendant_thickness", lambda kit: kit.pop("pendant_thickness")),
                ("attach_dx", lambda kit: kit["jib"]["lugs"][0].pop("attach_dx")),
            ):
                with self.subTest(missing=name):
                    broken.write_bytes(_rewrite_metadata(data, damage))
                    with self.assertRaisesRegex(
                        ValueError, "layout data is incomplete"
                    ):
                        load_tower_crane_kit(broken)

    def test_about_still_opens_when_a_kit_has_a_broken_credit(self):
        from unittest.mock import Mock
        from PySide6 import QtWidgets
        from ost_visualizer.application.interfaces.i_window_icon_provider import (
            IWindowIconProvider,
        )
        from ost_visualizer.presentation.dialogs.about_dialog import AboutDialog

        QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        data = (TOWER_CRANE_MODELS_DIR / "tower_crane_liebherr.glb").read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            shutil.copy(TOWER_CRANE_MODELS_DIR / "tower_crane_classic.glb", folder)
            (Path(folder) / "tower_crane_liebherr.glb").write_bytes(
                _rewrite_metadata(data, lambda kit: kit["credit"].pop("license_url"))
            )
            tower_crane_kits.cache_clear()
            tower_crane_catalog.cache_clear()
            try:
                with patch.object(models, "TOWER_CRANE_MODELS_DIR", Path(folder)):
                    with self.assertLogs(models.__name__, "WARNING"):
                        dialog = AboutDialog(
                            Mock(spec=IWindowIconProvider), creator_name="Creator"
                        )
                    text = dialog.content_view.toPlainText()
                    dialog.cleanup()
                    dialog.deleteLater()
            finally:
                tower_crane_kits.cache_clear()
                tower_crane_catalog.cache_clear()
        self.assertIn("Chamod", text)
        self.assertNotIn("Cem Alagozlu", text)

    def test_an_unusable_kit_is_left_out_with_a_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            shutil.copy(TOWER_CRANE_MODELS_DIR / "tower_crane_liebherr.glb", folder)
            (Path(folder) / "tower_crane_classic.glb").write_bytes(b"not a kit")
            tower_crane_kits.cache_clear()
            tower_crane_catalog.cache_clear()
            try:
                with patch.object(models, "TOWER_CRANE_MODELS_DIR", Path(folder)):
                    with self.assertLogs(models.__name__, "WARNING") as logs:
                        kits = tower_crane_kits()
                    catalog = tower_crane_catalog()
            finally:
                tower_crane_kits.cache_clear()
                tower_crane_catalog.cache_clear()
        self.assertIn("tower_crane_classic.glb", logs.output[0])
        self.assertEqual([kit.model.id for kit in kits], ["liebherr"])
        # The first kit that loads becomes the model a bare [crane] tag gets.
        self.assertEqual(catalog.ids, ("liebherr",))
        self.assertEqual(tower_crane_catalog().ids, ("classic", "liebherr"))


if __name__ == "__main__":
    unittest.main()
