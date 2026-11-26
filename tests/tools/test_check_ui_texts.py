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
