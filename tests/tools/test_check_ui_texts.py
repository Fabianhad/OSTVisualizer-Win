import contextlib
import io
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import check_ui_texts as guard


class RepositoryUserTextGuardTests(unittest.TestCase):
    def test_presentation_has_no_user_facing_text_outside_texts_py(self):
        findings = guard.scan()
        allowlist = guard.load_allowlist()
        self.assertEqual(guard.violations(findings, allowlist), [])
        self.assertEqual(guard.stale_allowlist_entries(findings, allowlist), [])

    def test_every_allowlist_entry_names_a_file_a_text_and_a_reason(self):
        entries = json.loads(guard.ALLOWLIST.read_text(encoding="utf-8"))
        for entry in entries:
            self.assertEqual(set(entry), {"file", "text", "reason"})
            self.assertTrue(entry["reason"].strip())

    def test_the_command_line_check_reports_success(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.main([]), 0)
        self.assertIn("No user-facing text outside texts.py", output.getvalue())


class UserTextDetectionTests(unittest.TestCase):
    def found(self, source):
        return [
            text
            for _path, _line, text in guard.find_user_text(
                textwrap.dedent(source), "module.py"
            )
        ]

    def test_each_kind_of_sink_is_caught(self):
        cases = {
            "message helper": (
                'show_warning(self, "Title", "Body text")',
                ["Title", "Body text"],
            ),
            "QMessageBox static": (
                'QtWidgets.QMessageBox.question(self, "Ask", "Really?")',
                ["Ask", "Really?"],
            ),
            "widget constructor": ('QtWidgets.QLabel("Name:")', ["Name:"]),
            "action constructor": ('QtGui.QAction("Undo", self)', ["Undo"]),
            "window title": ('self.setWindowTitle("Layers")', ["Layers"]),
            "tooltip": ('button.setToolTip("Delete layer")', ["Delete layer"]),
            "placeholder": ('edit.setPlaceholderText("Search")', ["Search"]),
            "status text": ('bar.showMessage("Saved")', ["Saved"]),
            "menu": ('menu.addMenu("Export")', ["Export"]),
            "menu action": ('menu.addAction("Copy")', ["Copy"]),
            "tab": ('tabs.addTab(page, "Preferences")', ["Preferences"]),
            "header": ('tree.setHeaderLabels(["Name", "Qty"])', ["Name", "Qty"]),
            "item": ('QtWidgets.QTreeWidgetItem(["Root"])', ["Root"]),
            "item columns by list concatenation": (
                'QtWidgets.QTreeWidgetItem(["New Folder"] + [""] * 7)',
                ["New Folder"],
            ),
            "combo item": ('combo.addItem("Solid", "solid")', ["Solid"]),
            "combo item after an icon call": (
                'combo.addItem(QtGui.QIcon(path), "Solid", "solid")',
                ["Solid"],
            ),
            "combo item after an icon name": (
                'combo.addItem(icon, "Ink", "ink")',
                ["Ink"],
            ),
            "file dialog": (
                'QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")',
                ["Open PDF", "PDF Files (*.pdf)"],
            ),
            "input dialog": (
                'QInputDialog.getText(self, "Rename", "New name:")',
                ["Rename", "New name:"],
            ),
            "context menu spec": (
                'ContextMenuManager.action_spec(None, "Paste")',
                ["Paste"],
            ),
            "result message": (
                'EditLeaseResult(False, "The edit was cancelled.")',
                ["The edit was cancelled."],
            ),
            "progress dialog name": (
                'ProgressDialog("new database", task, parent=self)',
                ["new database"],
            ),
            "combo edit text": ('combo.setEditText(f"{count} pages")', ["{} pages"]),
            "context command fallback": (
                'context_command_state(state_fn, ACTION_SELECT_OVERLAY_IMAGE, "Select Overlay Image")',
                ["Select Overlay Image"],
            ),
            "result keyword": (
                'QueuedMutationResult(message="Saved later")',
                ["Saved later"],
            ),
            "exception the UI shows": (
                'raise DatabaseCatalogError("Setup failed.") from None',
                ["Setup failed."],
            ),
            "ambiguous combo exception": (
                'raise AmbiguousComboIdentityError(f"{text!r} matches two items.")',
                ["{} matches two items."],
            ),
        }
        for label, (source, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), expected)

    def test_each_text_shape_is_caught(self):
        cases = {
            "f-string": (
                'show_info(self, "T", f"Deleted {name}.")',
                ["T", "Deleted {}."],
            ),
            "fallback": (
                'show_warning(self, "T", message or "It failed.")',
                ["T", "It failed."],
            ),
            "conditional": (
                'button.setText("Activate" if active else "Deactivate")',
                ["Activate", "Deactivate"],
            ),
            "concatenation": ('label.setText("Total: " + str(total))', ["Total: "]),
            "format receiver": (
                'label.setText("Pages: {count}".format(count=n))',
                ["Pages: {count}"],
            ),
        }
        for label, (source, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), expected)

    def test_each_indirect_shape_is_caught(self):
        cases = {
            "menu entries and menu titles": (
                """
                MENUS = {
                    "File": [
                        ("cmd", "Close", "unload_file"),
                        ("cascade", "Import", [("cmd", ".ost File...", "import_ost")]),
                        ("check", "Grayscale", "grayscale", "toggle"),
                        ("radio", "Solid", "solid", "set_mode"),
                        ("shared", "undo"),
                        ("sep",),
                    ]
                }
                """,
                ["File", "Close", "Import", ".ost File...", "Grayscale", "Solid"],
            ),
            "progress text keyword": (
                'ProgressDialog(path, task, parent=self, action_text="Importing")',
                ["Importing"],
            ),
            "label text keyword": (
                'run_with_progress(task, label_text="Pasting <b>{name}</b>...")',
                ["Pasting <b>{name}</b>..."],
            ),
            "color label keyword": (
                'build_menu(color_label="Select Font Color...")',
                ["Select Font Color..."],
            ),
            "display pairs": (
                'COLOR_CATEGORIES = ((COLOR_CATEGORY_TEXT, "Text"), (COLOR_CATEGORY_HOTLINK, "Hotlink"))',
                ["Text", "Hotlink"],
            ),
            "display items with constant or number keys": (
                """
                _STYLE_ITEMS = [(Condition.TYPE_LINEAR, "Linear"), (Condition.TYPE_AREA, "Area")]
                _SCALE_STYLES = ((1, "Architectural"), (2, "Civil"))
                _CHANGELOG_SECTION_ORDER = (("added", "Added"), ("fixed", "Fixed"))
                """,
                ["Linear", "Area", "Architectural", "Civil", "Added", "Fixed"],
            ),
            "progress report": (
                'reporter.report("bid data")',
                ["bid data"],
            ),
            "helper call inside a lambda": (
                """
                class Handler:
                    def _save(self, path, title, write):
                        show_warning(self, title, MESSAGE)
                    def go(self, path):
                        run(lambda done: self._save(path, "Job Statuses", done))
                """,
                ["Job Statuses"],
            ),
            "display options": (
                '_ROTATION_OPTIONS = ((0, "Original rotation"), (90, "90 (counterclockwise)"))',
                ["Original rotation", "90 (counterclockwise)"],
            ),
            "helper that wraps the text in str()": (
                """
                class Dialog:
                    def show_error(self, message):
                        self.error_label.setText(str(message))
                    def check(self):
                        self.show_error("Enter a valid number.")
                """,
                ["Enter a valid number."],
            ),
            "closure variable": (
                """
                def build(action):
                    enabled_tip = "Create a backout"
                    def refresh(on):
                        action.setToolTip(enabled_tip if on else DISABLED_TIP)
                    return refresh
                """,
                ["Create a backout"],
            ),
            "parameter default": (
                """
                class ColorButton:
                    def __init__(self, color, *, dialog_title="Select Color"):
                        self.dialog = QtWidgets.QColorDialog()
                        self.dialog.setWindowTitle(dialog_title)
                """,
                ["Select Color"],
            ),
            "attribute set from a parameter default": (
                """
                class ColorButton:
                    def __init__(self, color, *, dialog_title="Select Color"):
                        self._dialog_title = dialog_title
                    def pick(self):
                        dialog.setWindowTitle(self._dialog_title)
                """,
                ["Select Color"],
            ),
            "dialog title keyword": (
                'ColorButton(color, dialog_title="Text Color")',
                ["Text Color"],
            ),
            "action state text": (
                """
                def state(key):
                    return {"text": "Delete Page", "enabled": True, "tooltip": "Delete this page"}
                """,
                ["Delete Page", "Delete this page"],
            ),
            "display mapping": (
                '_STATE_LABELS = {"healthy": "SQL: CONNECTED", "conflicted": "SQL: CONFLICT"}',
                ["SQL: CONNECTED", "SQL: CONFLICT"],
            ),
            "message variable": (
                """
                def ask(parent, n):
                    msg = f"Delete {n} items?"
                    QtWidgets.QMessageBox.question(parent, TITLE, msg)
                """,
                ["Delete {} items?"],
            ),
            "message variable extended later": (
                """
                def ask(parent, name):
                    message = f"Remove {name}?"
                    if sql:
                        message += "\\n\\nOnly the saved connection is removed."
                    return confirm(parent, TITLE, message)
                """,
                ["Remove {}?", "\n\nOnly the saved connection is removed."],
            ),
            "argument of a helper that shows it": (
                """
                class Coordinator:
                    def _warn(self, title, message, critical=False):
                        show_warning(self, title, message)
                    def _refuse(self, title):
                        self._warn(title, MESSAGE)
                    def go(self):
                        self._warn("Layer Update", "Saved later.")
                        self._refuse("Delete Layer")
                        self._warn(title=TITLE, message="By keyword.")
                """,
                ["Layer Update", "Saved later.", "Delete Layer", "By keyword."],
            ),
            "constructor argument that is shown": (
                """
                class Banner:
                    def __init__(self, text, kind):
                        self.label = QtWidgets.QLabel(text)
                Banner("Read only", "warning")
                """,
                ["Read only"],
            ),
            "module constant": (
                """
                SAVE_LABEL = "Save Anyway"
                box.addButton(SAVE_LABEL, ROLE)
                """,
                ["Save Anyway"],
            ),
            "class constant": (
                """
                class Dialog:
                    _TITLE = "Job Statuses"
                    def build(self):
                        self.setWindowTitle(self._TITLE)
                """,
                ["Job Statuses"],
            ),
        }
        for label, (source, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), expected)

    def test_indirect_names_that_hold_no_literal_text_are_not_flagged(self):
        source = """
        LABEL = TEXTS_LABEL
        STATUS_KEY = "status/visible"
        def build(self, name):
            msg = MESSAGE.format(name=name)
            show_warning(self, TITLE, msg)
            key = "window/geometry"
            settings.setValue(key, value)
        ROWS = (("north", NORTH_LABEL),)
        PAIRS = ((KIND_A, "a"),)
        _FORMAT_ITEMS = (("pdf", "pdf"), (KIND_B, "lower_key"))
        report("Saved later")
        def add_command(menu, label, action_key):
            return context_command_state(state_fn, action_key, label)
        add_command(menu, PASTE_LABEL, "paste")
        _KIND_LOG_LABELS = {KIND_A: "Composite page"}
        """
        self.assertEqual(self.found(source), [])

    def test_constants_contracts_and_wordless_text_are_not_flagged(self):
        source = """
        show_warning(self, TITLE, MESSAGE.format(name=name))
        label.setText(f"{percent}%")
        label.setText("")
        combo.addItem(LABEL, "solid")
        widget.setObjectName("conditionsTree")
        logger.warning("Failed to save %s", path)
        settings.setValue("window/geometry", value)
        raise ValueError(f"Unknown section cut: {cut!r}")
        """
        self.assertEqual(self.found(source), [])

    def test_texts_py_itself_is_never_scanned(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder) / "presentation"
            (root / "dialogs").mkdir(parents=True)
            (root / "texts.py").write_text(
                'X = QLabel("Allowed here")\n', encoding="utf-8"
            )
            (root / "dialogs" / "texts.py").write_text(
                'QLabel("Not the texts module")\n', encoding="utf-8"
            )
            (root / "dialogs" / "a.py").write_text(
                'button.setToolTip("New literal")\n', encoding="utf-8"
            )
            findings = guard.scan(root, Path(folder))
        self.assertEqual(
            sorted((path, text) for path, _line, text in findings),
            [
                ("presentation/dialogs/a.py", "New literal"),
                ("presentation/dialogs/texts.py", "Not the texts module"),
            ],
        )


class SubclassAttributeTests(unittest.TestCase):
    def test_a_subclass_value_for_an_attribute_the_base_class_shows_is_caught(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder) / "presentation"
            root.mkdir()
            (root / "base.py").write_text(
                "class Base:\n"
                "    _delete_title = BASE_TITLE\n"
                "    def confirm(self):\n"
                "        show_warning(self, self._delete_title, MESSAGE)\n",
                encoding="utf-8",
            )
            (root / "child.py").write_text(
                "class Child(Base):\n"
                '    _delete_title = "Delete Job Status"\n'
                '    _name_col = "name"\n',
                encoding="utf-8",
            )
            findings = guard.scan(root, Path(folder))
        self.assertEqual(
            [(path, text) for path, _line, text in findings],
            [("presentation/child.py", "Delete Job Status")],
        )


class AllowlistTests(unittest.TestCase):
    def write(self, folder, entries):
        path = Path(folder) / "allow.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path

    def test_an_allowlisted_text_passes_and_a_missing_one_is_stale(self):
        findings = [("presentation/a.py", 3, "Kept"), ("presentation/a.py", 4, "New")]
        allowlist = {("presentation/a.py", "Kept"), ("presentation/b.py", "Gone")}
        self.assertEqual(
            guard.violations(findings, allowlist), [("presentation/a.py", 4, "New")]
        )
        self.assertEqual(
            guard.stale_allowlist_entries(findings, allowlist),
            [("presentation/b.py", "Gone")],
        )

    def test_an_entry_without_a_reason_is_refused(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = self.write(folder, [{"file": "a.py", "text": "X", "reason": " "}])
            with self.assertRaises(ValueError):
                guard.load_allowlist(path)
            path = self.write(
                folder, [{"file": "a.py", "text": "X", "reason": "Brand name"}]
            )
            self.assertEqual(guard.load_allowlist(path), {("a.py", "X")})

    def test_the_command_line_check_fails_on_a_new_literal_and_names_it(self):
        with patch.object(
            guard, "scan", return_value=[("presentation/a.py", 7, "Fresh text")]
        ), patch.object(guard, "load_allowlist", return_value=set()):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(guard.main([]), 1)
        self.assertIn(
            "presentation/a.py:7: user-facing text outside texts.py: 'Fresh text'",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
