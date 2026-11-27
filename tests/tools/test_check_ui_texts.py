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

    def test_a_message_carried_by_an_outcome_or_reply_type_is_caught(self):
        cases = {
            "apply outcome positional": (
                'done(ApplyOutcome(False, None, f"The changeset is {status} and cannot be undone.", "invalid_state"))',
                ["The changeset is {} and cannot be undone."],
            ),
            "apply outcome keyword": (
                'ApplyOutcome(False, None, message="Rejected by the reviewer.", code="x")',
                ["Rejected by the reviewer."],
            ),
            "bridge error reply": (
                'return error_result("malformed", "Malformed request.")',
                ["Malformed request."],
            ),
            "bridge error reply keyword": (
                'return error_result(ERROR_TIMEOUT, message="No complete request was received in time.")',
                ["No complete request was received in time."],
            ),
        }
        for label, (source, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), expected)
        self.assertEqual(
            self.found(
                """
                ApplyOutcome(True, record, "", "")
                ApplyOutcome(False, None, MESSAGE, ERROR_INVALID_STATE)
                error_result(ERROR_MALFORMED, MALFORMED_REQUEST_MESSAGE)
                """
            ),
            [],
        )

    def test_text_joined_from_a_comprehension_or_list_is_caught(self):
        cases = {
            "generator through a local": (
                """
                lines = "\\n".join(f'Cannot delete "{name}" because it is in use.' for name, _ in items)
                show_warning(parent, TITLE, lines)
                """,
                ['Cannot delete "{}" because it is in use.'],
            ),
            "list comprehension inline": (
                'show_warning(parent, TITLE, ", ".join([f"Layer {n} is hidden." for n in names]))',
                ["Layer {} is hidden."],
            ),
            "joined literal list": (
                'show_info(parent, TITLE, "\\n".join(["First line.", MESSAGE]))',
                ["First line."],
            ),
        }
        for label, (source, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), expected)
        self.assertEqual(
            self.found('show_warning(parent, TITLE, "\\n".join(MESSAGES))'), []
        )

    def test_developer_context_and_logger_of_a_dialog_helper_are_not_user_text(self):
        source = """
        show_error(self, TITLE, MESSAGE, exc, context="Failed to save %s" % path)
        show_warning(self, TITLE, MESSAGE, context=f"Reload failed for {bid}", logger=log)
        show_error(self, TITLE, "Body text", exc, context="Developer detail")
        """
        self.assertEqual(self.found(source), ["Body text"])

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


class LowerLayerUserTextTests(unittest.TestCase):
    def found(self, source):
        return [
            text
            for _path, _line, text in guard.find_lower_user_text(
                textwrap.dedent(source), "module.py"
            )
        ]

    def test_each_lower_layer_shape_is_caught(self):
        cases = {
            "exception message for people": (
                'raise DatabaseCatalogError("The database could not be opened. Close it and try again.")',
                ["The database could not be opened. Close it and try again."],
            ),
            "f-string exception message": (
                'raise ChangesetError(f"The changeset is {status} and cannot be applied.")',
                ["The changeset is {} and cannot be applied."],
            ),
            "user-result keyword": (
                'return MutationExecutionResult(False, message="The bid is locked.")',
                ["The bid is locked."],
            ),
            "error factory": (
                'return create_error_result(message="Failed to save the condition.")',
                ["Failed to save the condition."],
            ),
            "user message field": (
                'QueuedMutationResult(success=False, user_message="Reload the database before retrying.")',
                ["Reload the database before retrying."],
            ),
            "returned reason": (
                'def unavailable_reason(locator):\n    if not locator:\n        return "Select a database first."\n    return ""',
                ["Select a database first."],
            ),
            "returned user message": (
                'def blocked_message(self):\n    return f"Close {self.name} before compacting."',
                ["Close {} before compacting."],
            ),
        }
        for label, (source, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), expected)

    def test_a_notes_tag_warning_message_is_caught_even_when_it_quotes_syntax(self):
        source = """
        warnings.append(TagWarning("unexpected_text", "", f'{label}: "{token}" is not a key=value argument and is ignored.'))
        warnings.append(TagWarning(code, key.name, message=f"More than one [{name}] tag; the first one is used."))
        TagWarning(code, key.name, MESSAGE)
        """
        self.assertEqual(
            self.found(source),
            [
                '{}: "{}" is not a key=value argument and is ignored.',
                "More than one [{}] tag; the first one is used.",
            ],
        )

    def test_a_message_passed_to_an_error_or_result_factory_is_caught(self):
        source = """
        def _session_error(message):
            return SqlInfrastructureError(SqlErrorDetails(SqlErrorCode.SESSION_EXPIRED, message))
        class Proposals:
            def _assumption(self, position, reason, impact=None):
                return ChangesetAssumption(uid=f"a{position}", reason=reason)
            def run(self):
                self._assumption(1, "The slab thickness was not given.")
                raise _session_error("The SQL collaboration session expired. Reconnect before editing.")
                _session_error(MESSAGE)
                self._assumption(2, REASON)
        """
        self.assertEqual(
            self.found(source),
            [
                "The slab thickness was not given.",
                "The SQL collaboration session expired. Reconnect before editing.",
            ],
        )

    def test_a_factory_defined_in_another_module_is_followed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            package = root / "ost_visualizer" / "infrastructure"
            package.mkdir(parents=True)
            (package / "errors.py").write_text(
                "def sql_schema_mismatch(message):\n"
                "    return SqlInfrastructureError(SqlErrorDetails(SqlErrorCode.SCHEMA_MISMATCH, message))\n",
                encoding="utf-8",
            )
            (package / "writer.py").write_text(
                "def check(resource):\n"
                "    raise sql_schema_mismatch(f'The current SQL schema does not support {resource}.')\n",
                encoding="utf-8",
            )
            findings = guard.scan_lower(root)
        self.assertEqual(
            [(path, text) for path, _line, text in findings],
            [
                (
                    "ost_visualizer/infrastructure/writer.py",
                    "The current SQL schema does not support {}.",
                )
            ],
        )

    def test_a_message_looked_up_in_a_local_mapping_is_caught(self):
        source = """
        def lock_error(owner, kind):
            messages = {
                "item_owner": f"This item is being edited by {owner}.",
                "token_expired": "A required SQL edit lock expired before the write.",
            }
            raise SqlInfrastructureError(
                SqlErrorDetails(SqlErrorCode.LOCKED, messages.get(kind, "SQL edit-lock validation failed."))
            )
        """
        self.assertEqual(
            self.found(source),
            [
                "This item is being edited by {}.",
                "A required SQL edit lock expired before the write.",
                "SQL edit-lock validation failed.",
            ],
        )

    def test_contracts_logs_and_developer_diagnostics_are_not_flagged(self):
        source = """
        raise ValueError("ref_no must be positive")
        raise RuntimeError(f"Unknown section cut: {cut!r}")
        raise KeyError("BidUID")
        logger.warning("The database could not be opened. Close it and try again.")
        cursor.execute("SELECT [UID] FROM [Bids] WHERE [BidUID] = ?")
        raise DatabaseCatalogError(SHARED_MESSAGE.format(name=name))
        return Result(message=f"{table}.UID={uid} is malformed.")
        def unavailable_reason(self):
            return f"{self.table}.UID={self.uid} is malformed."
        """
        self.assertEqual(self.found(source), [])

    def test_the_repository_lower_layers_have_no_user_text_outside_the_shared_module(
        self,
    ):
        findings = guard.scan_lower()
        self.assertEqual(guard.violations(findings, guard.load_allowlist()), [])


class ErrorDialogGuardTests(unittest.TestCase):
    def found(self, source, path="ost_visualizer/presentation/handlers/module.py"):
        return [
            kind
            for _path, _line, kind in guard.find_unlogged_error_dialogs(
                textwrap.dedent(source), path
            )
        ]

    def test_each_direct_error_box_shape_is_caught(self):
        cases = {
            "static warning": (
                "QtWidgets.QMessageBox.warning(self, TITLE, MESSAGE)",
                ["QMessageBox.warning"],
            ),
            "static critical": (
                "QtWidgets.QMessageBox.critical(self, TITLE, MESSAGE)",
                ["QMessageBox.critical"],
            ),
            "imported class static": (
                "QMessageBox.critical(None, TITLE, str(exc))",
                ["QMessageBox.critical"],
            ),
            "constructed with an error icon": (
                "box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Critical, TITLE, MESSAGE)",
                ["QMessageBox.Icon.Critical"],
            ),
            "error icon set later": (
                "box.setIcon(QtWidgets.QMessageBox.Icon.Warning)",
                ["QMessageBox.Icon.Warning"],
            ),
            "error icon in a mapping": (
                'ICONS = {"error": QtWidgets.QMessageBox.Icon.Critical}',
                ["QMessageBox.Icon.Critical"],
            ),
        }
        for label, (source, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), expected)

    def test_helpers_questions_logged_notices_and_the_helper_module_pass(self):
        self.assertEqual(
            self.found(
                """
                show_error(self, TITLE, MESSAGE, exc)
                show_warning(self, TITLE, MESSAGE)
                QtWidgets.QMessageBox.question(self, TITLE, MESSAGE)
                QtWidgets.QMessageBox.information(self, TITLE, MESSAGE)
                box.setIcon(QtWidgets.QMessageBox.Icon.Information)
                level = Severity.Critical
                badge.set_state(MonitorState.Warning)
                """
            ),
            [],
        )
        self.assertEqual(
            self.found(
                """
                box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
                log_user_notice(logging.WARNING, TITLE, box.text())
                """
            ),
            [],
        )
        self.assertEqual(
            self.found(
                "QtWidgets.QMessageBox.critical(parent, title, message)",
                path="ost_visualizer/presentation/utils/messagebox.py",
            ),
            [],
        )

    def test_the_repository_has_no_error_box_outside_the_logging_helper(self):
        findings = guard.scan_error_dialogs()
        allowlist = guard.load_error_dialog_allowlist()
        self.assertEqual(allowlist, set())
        self.assertEqual(guard.error_dialog_violations(findings, allowlist), [])

    def test_an_error_dialog_allowlist_entry_needs_a_reason(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "allow.json"
            path.write_text(
                json.dumps(
                    [{"file": "a.py", "kind": "QMessageBox.warning", "reason": ""}]
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                guard.load_error_dialog_allowlist(path)
            path.write_text(
                json.dumps(
                    [
                        {
                            "file": "a.py",
                            "kind": "QMessageBox.warning",
                            "reason": "Crash reporter",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                guard.load_error_dialog_allowlist(path),
                {("a.py", "QMessageBox.warning")},
            )
        findings = [
            ("a.py", 3, "QMessageBox.warning"),
            ("b.py", 9, "QMessageBox.critical"),
        ]
        self.assertEqual(
            guard.error_dialog_violations(findings, {("a.py", "QMessageBox.warning")}),
            [("b.py", 9, "QMessageBox.critical")],
        )

    def test_the_command_line_check_fails_on_a_direct_error_box(self):
        output = io.StringIO()
        with patch.object(guard, "scan", return_value=[]), patch.object(
            guard, "scan_lower", return_value=[]
        ), patch.object(
            guard,
            "scan_error_dialogs",
            return_value=[
                ("ost_visualizer/presentation/x.py", 4, "QMessageBox.critical")
            ],
        ), contextlib.redirect_stdout(
            output
        ):
            self.assertEqual(guard.main([]), 1)
        self.assertIn(
            "ost_visualizer/presentation/x.py:4: error dialog outside the logging "
            "helper: QMessageBox.critical",
            output.getvalue(),
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


class LowerLayerTextPositionTests(unittest.TestCase):
    def found(self, source):
        return [
            text
            for _path, _line, text in guard.find_lower_user_text(
                textwrap.dedent(source), "module.py"
            )
        ]

    def test_a_sentence_returned_collected_appended_assigned_or_defaulted_is_caught(
        self,
    ):
        cases = {
            "returned tuple": (
                'def gap_text(g):\n    return (f"{g} in", f"The outline was closed across a {g} in gap.")',
                ["The outline was closed across a {} in gap."],
            ),
            "list element": (
                'warnings = [("opening", f"The region runs through a {w} in opening; check the outline.")]',
                ["The region runs through a {} in opening; check the outline."],
            ),
            "mapping value": (
                'REASONS = {"pen": "No stroke width stands clearly above the lightest lines, so no filter was applied."}',
                [
                    "No stroke width stands clearly above the lightest lines, so no filter was applied."
                ],
            ),
            "appended warning": (
                'warnings.append(f"{name} affected pages truncated to {limit} of {total} pages.")',
                ["{} affected pages truncated to {} of {} pages."],
            ),
            "assigned message": (
                'message = f"SQL collaboration cleanup failed for {database_id}."',
                ["SQL collaboration cleanup failed for {}."],
            ),
            "module constant": (
                'SKIPPED_REASON = ("This region was not checked for openings, "\n    "so it may merge two areas; check the outline.")',
                [
                    "This region was not checked for openings, so it may merge two areas; check the outline."
                ],
            ),
            "parameter default": (
                'class Conflict(Exception):\n    def __init__(self, *, message: str = "This item changed in another session. Reload it before saving."):\n        pass',
                ["This item changed in another session. Reload it before saving."],
            ),
        }
        for label, (source, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.found(source), expected)

    def test_an_unpunctuated_result_text_or_a_progress_step_is_caught(self):
        source = """
        result = FileLoadResultDto(error_message=ops.last_error or "Failed to unload file")
        LicenseFailureResponse(server_message="Network error")
        on_progress(1, 1, "Writing OST")
        self._report_progress(progress_callback, "database file")
        ExportResultDto(error_message=f"Unknown export format: {name}")
        """
        self.assertEqual(
            self.found(source),
            [
                "Failed to unload file",
                "Network error",
                "Writing OST",
                "database file",
                "Unknown export format: {}",
            ],
        )

    def test_a_warning_or_note_written_for_people_into_a_list_is_caught(self):
        source = """
        warnings.append(
            f"[crane]: a trolley position of {pct:g}% is outside 0% to 100% of "
            "its travel; the jib tip end is used."
        )
        self.notes.append("[crane]: hook and hookheight are both given; hookheight is used.")
        messages.insert(0, f"{label} bid contains duplicate values here.")
        """
        self.assertEqual(
            self.found(source),
            [
                "[crane]: a trolley position of {}% is outside 0% to 100% of its travel; the jib tip end is used.",
                "[crane]: hook and hookheight are both given; hookheight is used.",
                "{} bid contains duplicate values here.",
            ],
        )

    def test_developer_entries_and_constants_in_lists_are_not_flagged(self):
        source = """
        warnings.append(WARNING.format(label=label))
        warnings.append(code)
        issues.append(f"{table}.UID={uid} occurs twice in the table.")
        notes.append("mast")
        warnings.append("mast section count")
        steps.append(("clean up the plan view", plan.cleanup))
        """
        self.assertEqual(self.found(source), [])

    def test_a_one_word_step_or_a_step_under_another_callback_name_is_caught(self):
        source = """
        self._report_progress(progress_callback, "finalizing")
        progress("Creating database")
        progress_callback("schema tables")
        progress(STEP)
        progress(0.5)
        """
        self.assertEqual(
            self.found(source), ["finalizing", "Creating database", "schema tables"]
        )

    def test_a_default_file_name_built_from_words_is_caught(self):
        source = """
        def _prepare_export_filename(ext, bid, pages, remaining):
            return f"{bid} - {pages[0]} + {pages[1]} + {remaining} more.{ext}"
        def default_file_name(bid):
            return f"{bid} Summary.csv"
        def _temp_filename(stem, ext):
            return f"{stem}.{ext}"
        """
        self.assertEqual(
            self.found(source), ["{} - {} + {} + {} more.{}", "{} Summary.csv"]
        )

    def test_a_fallback_display_name_built_from_a_word_is_caught(self):
        source = """
        name = row.name or f"Project {uid}"
        label = bid.name if bid.name else f"Bid {uid}"
        mesh = condition.name if condition.name else f"Condition_{uid}"
        other = row.name or EMPLOYEE_LABEL.format(uid=uid)
        """
        self.assertEqual(self.found(source), ["Project {}", "Bid {}"])

    def test_empty_constant_and_lowercase_result_codes_are_not_flagged(self):
        source = """
        FileLoadResultDto(error_message="")
        Result(message=MESSAGE.format(name=name))
        Result(error=failure or "not retryable")
        """
        self.assertEqual(self.found(source), [])

    def test_logs_labels_comparisons_and_calls_in_those_positions_are_not_flagged(
        self,
    ):
        source = '''
        def describe():
            """Return the summary that the review shows."""
            logger.warning("The cache could not be read, so it was rebuilt.")
            labels = ["leak check skipped", "Page navigation"]
            if name == "The default condition name.":
                pass
            steps = [("clean up the plan view", plan.cleanup)]
            error = SidecarWriteRefused(f"The AI sidecar is {status}; nothing was written.")
            return SUMMARY_TEXT.format(count=count)
        '''
        self.assertEqual(self.found(source), [])


class LowerLayerBuiltTextTests(unittest.TestCase):
    def found(self, source, relative_path):
        return [
            text
            for _path, _line, text in guard.find_lower_user_text(
                textwrap.dedent(source), relative_path
            )
        ]

    def test_a_word_appended_after_a_value_is_caught_in_the_application_layer(self):
        source = """
        values[SLOPE] = f"{rise}/{run} Pitch"
        def distance(value):
            return f"{value:,.2f} mm"
        """
        self.assertEqual(
            self.found(source, "ost_visualizer/application/services/caption.py"),
            ["{}/{} Pitch", "{} mm"],
        )
        self.assertEqual(
            self.found(source, "ost_visualizer/domain/entities/tower_crane_spec.py"),
            [],
        )
        self.assertEqual(
            self.found(source, "ost_visualizer/infrastructure/parsers/position.py"),
            [],
        )

    def test_a_default_file_name_assigned_to_a_variable_is_caught_in_every_layer(
        self,
    ):
        source = """
        file_name = f"{stamp} Backup.mdb"
        filename = f"{stamp}.mdb"
        """
        for layer in ("domain", "application", "infrastructure"):
            with self.subTest(layer=layer):
                self.assertEqual(
                    self.found(source, f"ost_visualizer/{layer}/module.py"),
                    ["{} Backup.mdb"],
                )

    def test_a_fallback_word_in_a_lower_layer_diagnostic_is_not_flagged(self):
        source = """
        detail = f"{error} [{', '.join(flags) or 'not retryable'}]"
        """
        self.assertEqual(
            self.found(source, "ost_visualizer/application/services/coordinator.py"),
            [],
        )


class PresentationAppendedTextTests(unittest.TestCase):
    def found(self, source):
        return [
            text
            for _path, _line, text in guard.find_user_text(
                textwrap.dedent(source), "module.py"
            )
        ]

    def test_a_sentence_appended_to_a_message_list_is_caught(self):
        source = """
        lines = []
        lines.append(f"Successfully imported {count} project files into the database.")
        lines.insert(0, "Imported as orphaned because the bid cannot be used as an import target.")
        show_info(self, TITLE, "\\n".join(lines))
        """
        self.assertEqual(
            self.found(source),
            [
                "Successfully imported {} project files into the database.",
                "Imported as orphaned because the bid cannot be used as an import target.",
            ],
        )

    def test_a_progress_step_reported_by_an_exporter_is_caught(self):
        source = """
        report(index, total, f"Collecting {Path(source_path).name}")
        on_progress(idx + 1, total, page.name or "Untitled page")
        """
        self.assertEqual(self.found(source), ["Collecting {}", "Untitled page"])

    def test_a_text_passed_through_a_text_keyword_is_caught(self):
        source = """
        Dialog(accept_button_text="OK" if menu_mode else "Select")
        Panel(empty_title="No Pages", hint_tooltip="Drag to pan", name_label="Name:")
        Dialog(accept_button_text=BUTTON_OK, object_name="okButton")
        """
        self.assertEqual(
            self.found(source), ["OK", "Select", "No Pages", "Drag to pan", "Name:"]
        )

    def test_a_step_under_another_callback_name_or_a_built_name_is_caught(self):
        source = """
        _report(2, 4, "Writing metadata")
        progress("Rendering pages")
        def prepare_filename(bid, page):
            return f"{bid} - {page} Plan.pdf"
        label = page.name or f"Page {index}"
        """
        self.assertEqual(
            self.found(source),
            ["Writing metadata", "Rendering pages", "{} - {} Plan.pdf", "Page {}"],
        )

    def test_a_fallback_word_inside_a_built_text_is_caught(self):
        source = """
        label = f"AI: {changeset.summary or 'takeoffs'}"
        other = f"AI: {changeset.summary or AI_TAKEOFFS}"
        logger.info("%s", f"{reason or 'unknown'}")
        """
        self.assertEqual(self.found(source), ["takeoffs"])

    def test_a_default_file_name_assigned_to_a_variable_is_caught(self):
        source = """
        default_filename = f"{bid_name} - {first_page_name}"
        default_filename = f"{default_filename}{PDF_EXTENSION}"
        file_name = f"{stamp}.mdb"
        filename = f"{bid_name}.{extension}"
        target = f"{bid_name} - {page_name}"
        """
        self.assertEqual(self.found(source), ["{} - {}"])

    def test_a_word_appended_after_a_value_is_caught(self):
        source = """
        caption = f"{rise}/{run} Pitch"
        distance = f"{value:,.2f} mm"
        key = f"{prefix}_{uid}"
        logger.info(f"{count} Rows")
        raise ValueError(f"{count} Rows")
        show_error(self, TITLE, MESSAGE, context=f"Error importing {name} File")
        expected = f"{count} numbers"
        """
        self.assertEqual(self.found(source), ["{}/{} Pitch", "{} mm"])

    def test_appended_developer_steps_and_constants_are_not_flagged(self):
        source = """
        steps.append(("clean up the plan view", plan.cleanup))
        lines.append(IMPORT_MESSAGE.format(count=count))
        """
        self.assertEqual(self.found(source), [])


class DuplicateTextTests(unittest.TestCase):
    constants = {
        "Failed to move layer.": "LAYERS_DIALOG_MESSAGE_FAILED_TO_MOVE_LAYER",
        "Move Layer": "LAYERS_DIALOG_TITLE_MOVE_LAYER",
        "Page {uid}": "PAGE_LABEL_PAGE",
        "Default": "DEFAULT_LAYER_NAME",
    }

    def found(self, source):
        return [
            (text, name)
            for _path, _line, text, name in guard.find_duplicate_texts(
                textwrap.dedent(source), "module.py", self.constants
            )
        ]

    def test_a_literal_that_repeats_a_texts_constant_is_caught_in_any_position(self):
        source = """
        show_warning(self, TITLE, MESSAGE, exc, context="Failed to move layer.", logger=logger)
        self._refuse_locked_layer_write("Move Layer")
        logger.warning("Failed to move layer.")
        page = Page(uid=uid, name=f"Page {uid}")
        """
        self.assertEqual(
            self.found(source),
            [
                ("Failed to move layer.", "LAYERS_DIALOG_MESSAGE_FAILED_TO_MOVE_LAYER"),
                ("Move Layer", "LAYERS_DIALOG_TITLE_MOVE_LAYER"),
                ("Failed to move layer.", "LAYERS_DIALOG_MESSAGE_FAILED_TO_MOVE_LAYER"),
                ("Page {}", "PAGE_LABEL_PAGE"),
            ],
        )

    def test_one_word_other_case_other_punctuation_and_docstrings_are_not_duplicates(
        self,
    ):
        source = '''
        def f():
            """Move Layer"""
            if layer.name == "Default":
                logger.warning("Failed to move layer")
                return "move layer"
        '''
        self.assertEqual(self.found(source), [])

    def test_a_constant_without_words_is_not_a_duplicate_key(self):
        found = [
            (text, name)
            for _path, _line, text, name in guard.find_duplicate_texts(
                textwrap.dedent(
                    """
                    title = f"{database_name} - {app_title}"
                    tooltip = f"{reason}\\n{path}"
                    """
                ),
                "module.py",
                {
                    "{database_name} - {app_title}": "WINDOW_TITLE_TITLE_DATABASE",
                    "{reason}\n{path}": "TOOLTIP_CANNOT_BE_ACCESSED",
                },
            )
        ]
        self.assertEqual(found, [])

    def test_the_repository_repeats_no_texts_constant(self):
        findings = guard.scan_duplicate_texts()
        allowlist = guard.load_allowlist(guard.DUPLICATE_ALLOWLIST)
        self.assertEqual(guard.violations(findings, allowlist), [])
        self.assertEqual(guard.stale_allowlist_entries(findings, allowlist), [])

    def test_every_duplicate_allowlist_entry_is_a_contract_with_a_reason(self):
        entries = json.loads(guard.DUPLICATE_ALLOWLIST.read_text(encoding="utf-8"))
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertEqual(set(entry), {"file", "text", "reason"})
                self.assertIn("contract", entry["reason"])


class LogTextTests(unittest.TestCase):
    def found(self, source):
        return [
            text
            for _path, _line, text in guard.find_log_texts(
                textwrap.dedent(source), "module.py"
            )
        ]

    def test_an_explanation_sentence_in_a_logger_call_is_log_text(self):
        source = """
        logger.warning("Page %s was renamed in %s, but the reload after the rename failed", uid, path)
        self.logger.warning(
            "Could not read the stored condition folders of bid %s; the folder check uses the loaded bid",
            bid_uid,
        )
        _LOGGER.error("The MDB transaction could not be rolled back after %s.", exc)
        logger.error("The transaction-monitor worker did not stop within 1.5 seconds.")
        """
        self.assertEqual(
            self.found(source),
            [
                "Page {} was renamed in {}, but the reload after the rename failed",
                "Could not read the stored condition folders of bid {}; the folder check uses the loaded bid",
                "The MDB transaction could not be rolled back after {}.",
                "The transaction-monitor worker did not stop within 1.5 seconds.",
            ],
        )

    def test_terse_developer_logs_and_constants_are_not_log_text(self):
        source = """
        logger.warning("Failed to load layer UIDs in use for the layers sidebar")
        logger.exception("Error loading page into plan_view")
        logger.warning("%s: the active bid is locked", context)
        logger.info("Skipping %s because self.ready is False.", name)
        logger.warning(LOG_TEXT.format(bid_uid=bid_uid))
        logger.info("Cache reset; retrying the read.")
        """
        self.assertEqual(self.found(source), [])

    def test_a_baselined_log_text_passes_and_a_missing_one_is_stale(self):
        findings = [("a.py", 3, "Old text, kept for now.")]
        baseline = {("a.py", "Old text, kept for now."), ("b.py", "Gone, long ago.")}
        self.assertEqual(guard.log_text_violations(findings, baseline), [])
        self.assertEqual(
            guard.stale_allowlist_entries(findings, baseline),
            [("b.py", "Gone, long ago.")],
        )
        self.assertEqual(
            guard.log_text_violations([("a.py", 4, "New text, this round.")], baseline),
            [("a.py", 4, "New text, this round.")],
        )

    def test_a_baseline_entry_needs_a_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "baseline.json"
            path.write_text(
                json.dumps([{"file": "a.py", "text": "X", "reason": " "}]),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                guard.load_log_text_baseline(path)

    def test_the_log_text_baseline_is_empty_so_every_log_text_is_a_constant(self):
        self.assertEqual(
            json.loads(guard.LOG_TEXT_BASELINE.read_text(encoding="utf-8")), []
        )

    def test_the_repository_has_no_log_text_outside_the_baseline(self):
        findings = guard.scan_log_texts()
        baseline = guard.load_log_text_baseline()
        self.assertEqual(guard.log_text_violations(findings, baseline), [])
        self.assertEqual(guard.stale_allowlist_entries(findings, baseline), [])


if __name__ == "__main__":
    unittest.main()
