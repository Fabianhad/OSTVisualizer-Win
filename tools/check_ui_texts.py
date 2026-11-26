"""Fail when user-facing English text is written outside presentation/texts.py.
Scans every presentation module except texts.py for string literals and
f-strings that reach a user-facing sink: message boxes, Qt widget
constructors, UI setters (titles, labels, tooltips, menus, actions, tabs,
headers, items, placeholders, status text, file dialogs) and the result
messages and exceptions the UI shows. Literals inside fallbacks (``a or "text"``),
conditionals, concatenations (including list concatenation) and ``"...".format(...)`` receivers count too.
Text without letters once placeholders are removed is ignored. Approved
exceptions live in tools/ui_text_allowlist.json, matched by file and exact
text, each with a reason.
Usage: python tools/check_ui_texts.py
"""

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRESENTATION = REPO_ROOT / "ost_visualizer" / "presentation"
ALLOWLIST = REPO_ROOT / "tools" / "ui_text_allowlist.json"
TEXTS_MODULE = "texts.py"
MESSAGE_HELPERS = frozenset(
    {
        "show_warning",
        "show_critical",
        "show_info",
        "confirm",
        "confirm_save_with_warnings",
        "confirm_delete_page_with_contents",
        "confirm_save_discard_cancel",
        "confirm_multi_delete",
        "confirm_delete_conditions",
        "confirm_not_found",
    }
)
QMESSAGEBOX_STATICS = frozenset(
    {"warning", "critical", "information", "question", "about"}
)
WIDGET_CONSTRUCTORS = frozenset(
    {
        "QLabel",
        "QPushButton",
        "QCheckBox",
        "QRadioButton",
        "QGroupBox",
        "QToolButton",
        "QAction",
        "QMenu",
        "QTableWidgetItem",
        "QTreeWidgetItem",
        "QListWidgetItem",
        "QStandardItem",
        "QProgressDialog",
        "QCommandLinkButton",
    }
)
UI_SETTERS = frozenset(
    {
        "setText",
        "setWindowTitle",
        "setToolTip",
        "setPlaceholderText",
        "setStatusTip",
        "setWhatsThis",
        "setTitle",
        "addAction",
        "addMenu",
        "addTab",
        "insertTab",
        "setTabText",
        "setTabToolTip",
        "showMessage",
        "setHeaderLabels",
        "setHorizontalHeaderLabels",
        "setVerticalHeaderLabels",
        "setLabelText",
        "setInformativeText",
        "setDetailedText",
        "addItem",
        "addItems",
        "insertItem",
        "setItemText",
        "setSpecialValueText",
        "setSuffix",
        "setPrefix",
        "setCancelButtonText",
        "setOkButtonText",
        "addButton",
        "setButtonText",
        "addRow",
        "getText",
        "getItem",
        "getInt",
        "getDouble",
        "getOpenFileName",
        "getSaveFileName",
        "getOpenFileNames",
        "getExistingDirectory",
        "setAccessibleName",
        "setAccessibleDescription",
        "action_spec",
    }
)
USER_RESULT_TYPES = frozenset(
    {
        "EditLeaseResult",
        "QueuedMutationResult",
        "UpdateConditionResultDto",
        "MutationExecutionResult",
        "DatabaseMutationResult",
        "WriteReloadResult",
        "ValidationResult",
    }
)
USER_EXCEPTION_TYPES = frozenset(
    {"DatabaseCatalogError", "AmbiguousComboIdentityError"}
)
RESULT_MESSAGE_KEYWORDS = frozenset({"message", "error", "user_message", "reason"})
DATA_ARGUMENT_SETTERS = frozenset({"addItem", "insertItem", "setItemText", "addRow"})
FILE_DIALOGS = frozenset(
    {"getOpenFileName", "getSaveFileName", "getOpenFileNames", "getExistingDirectory"}
)
INPUT_DIALOGS = frozenset({"getText", "getItem", "getInt", "getDouble"})
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Name):
        return func.id, ""
    if isinstance(func, ast.Attribute):
        owner = func.value
        if isinstance(owner, ast.Name):
            return func.attr, owner.id
        if isinstance(owner, ast.Attribute):
            return func.attr, owner.attr
        return func.attr, ""
    return "", ""


def _is_text_leaf(node):
    return (
        isinstance(node, ast.Constant) and isinstance(node.value, str)
    ) or isinstance(node, ast.JoinedStr)


def _flatten_add(node):
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _flatten_add(node.left) + _flatten_add(node.right)
    return [node]


def _text_nodes(node):
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _text_nodes(value)
    elif isinstance(node, ast.IfExp):
        yield from _text_nodes(node.body)
        yield from _text_nodes(node.orelse)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        for leaf in _flatten_add(node):
            if _is_text_leaf(leaf) or isinstance(leaf, (ast.List, ast.Tuple)):
                yield from _text_nodes(leaf)
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and _is_text_leaf(node.func.value)
    ):
        yield node.func.value
    elif isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            yield from _text_nodes(element)
    elif _is_text_leaf(node):
        yield node


def _is_icon(node):
    if isinstance(node, ast.Call):
        func = node.func
        return not (isinstance(func, ast.Attribute) and func.attr == "format")
    if isinstance(node, ast.Name):
        return "icon" in node.id.lower()
    if isinstance(node, ast.Attribute):
        return "icon" in node.attr.lower()
    return False


def _sink_arguments(call):
    name, owner = _call_name(call)
    if name in MESSAGE_HELPERS or (
        owner == "QMessageBox" and name in QMESSAGEBOX_STATICS
    ):
        return list(call.args[1:]) + [keyword.value for keyword in call.keywords]
    if name in USER_EXCEPTION_TYPES:
        return list(call.args)
    if name in USER_RESULT_TYPES:
        return list(call.args) + [
            keyword.value
            for keyword in call.keywords
            if keyword.arg in RESULT_MESSAGE_KEYWORDS
        ]
    if name in FILE_DIALOGS:
        return [arg for index, arg in enumerate(call.args) if index in (1, 3)]
    if name in INPUT_DIALOGS:
        return [arg for index, arg in enumerate(call.args) if index in (1, 2)]
    if name in WIDGET_CONSTRUCTORS or name in UI_SETTERS:
        arguments = list(call.args)
        if name in DATA_ARGUMENT_SETTERS:
            arguments = (
                arguments[1:2]
                if arguments and _is_icon(arguments[0])
                else arguments[:1]
            )
        return arguments + [
            keyword.value
            for keyword in call.keywords
            if keyword.arg in {"text", "title"}
        ]
    return []


def _literal_text(node):
    if isinstance(node, ast.Constant):
        return node.value
    return "".join(
        value.value if isinstance(value, ast.Constant) else "{}"
        for value in node.values
    )


def find_user_text(source, relative_path):
    tree = ast.parse(source)
    findings = []
    seen = set()
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        for argument in _sink_arguments(call):
            for node in _text_nodes(argument):
                if id(node) in seen:
                    continue
                seen.add(id(node))
                text = _literal_text(node)
                if not re.search(r"[A-Za-z]", _PLACEHOLDER.sub("", text)):
                    continue
                findings.append((relative_path, node.lineno, text))
    return findings


def load_allowlist(path=ALLOWLIST):
    entries = json.loads(path.read_text(encoding="utf-8"))
    for entry in entries:
        if not entry.get("reason", "").strip():
            raise ValueError(f"allowlist entry without a reason: {entry}")
    return {(entry["file"], entry["text"]) for entry in entries}


def scan(root=PRESENTATION, repo_root=REPO_ROOT):
    findings = []
    for path in sorted(root.rglob("*.py")):
        if path.name == TEXTS_MODULE and path.parent == root:
            continue
        relative = path.relative_to(repo_root).as_posix()
        findings.extend(find_user_text(path.read_text(encoding="utf-8-sig"), relative))
    return findings


def violations(findings, allowlist):
    return [
        finding for finding in findings if (finding[0], finding[2]) not in allowlist
    ]


def stale_allowlist_entries(findings, allowlist):
    present = {(finding[0], finding[2]) for finding in findings}
    return sorted(allowlist - present)


def main(argv=None):
    findings = scan()
    allowlist = load_allowlist()
    found = violations(findings, allowlist)
    stale = stale_allowlist_entries(findings, allowlist)
    for path, line, text in found:
        print(f"{path}:{line}: user-facing text outside texts.py: {text!r}")
    for path, text in stale:
        print(f"{path}: allowlisted text no longer present: {text!r}")
    if found or stale:
        print(f"\n{len(found)} violation(s), {len(stale)} stale allowlist entr(ies).")
        return 1
    print(f"No user-facing text outside texts.py ({len(allowlist)} allowlisted).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
