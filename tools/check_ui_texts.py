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
        "ProgressDialog",
    }
)
UI_SETTERS = frozenset(
    {
        "setText",
        "setEditText",
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
TEXT_ARGUMENT_POSITIONS = {"context_command_state": (2,)}
FILE_DIALOGS = frozenset(
    {"getOpenFileName", "getSaveFileName", "getOpenFileNames", "getExistingDirectory"}
)
INPUT_DIALOGS = frozenset({"getText", "getItem", "getInt", "getDouble"})
USER_TEXT_DICT_KEYS = frozenset({"text", "tooltip"})
MENU_ENTRY_KINDS = frozenset({"cmd", "check", "radio", "cascade", "toggle"})
USER_TEXT_KEYWORDS = frozenset(
    {"action_text", "label_text", "color_label", "dialog_title"}
)
DISPLAY_COLLECTION = re.compile(
    r"(CATEGORIES|LABELS|CHOICES|TITLES|ITEMS|STYLES|ORDER|OPTIONS)$"
)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
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


def _is_str_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
    )


def _no_names(_node):
    return []


def _text_nodes(node, resolve=_no_names, visiting=frozenset()):
    if _is_str_call(node):
        yield from _text_nodes(node.args[0], resolve, visiting)
    elif isinstance(node, (ast.Name, ast.Attribute)):
        key = ast.dump(node)
        if key not in visiting:
            for value in resolve(node):
                yield from _text_nodes(value, resolve, visiting | {key})
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _text_nodes(value, resolve, visiting)
    elif isinstance(node, ast.IfExp):
        yield from _text_nodes(node.body, resolve, visiting)
        yield from _text_nodes(node.orelse, resolve, visiting)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        for leaf in _flatten_add(node):
            if _is_text_leaf(leaf) or isinstance(
                leaf, (ast.List, ast.Tuple, ast.Name, ast.Attribute)
            ):
                yield from _text_nodes(leaf, resolve, visiting)
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and _is_text_leaf(node.func.value)
    ):
        yield node.func.value
    elif isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            yield from _text_nodes(element, resolve, visiting)
    elif _is_text_leaf(node):
        yield node


def _scope_nodes(scope):
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _assignments(scope):
    assigned = {}
    for node in _scope_nodes(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                assigned.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            if isinstance(node.target, ast.Name):
                assigned.setdefault(node.target.id, []).append(node.value)
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        positional = scope.args.posonlyargs + scope.args.args
        for argument, default in zip(
            positional[len(positional) - len(scope.args.defaults) :],
            scope.args.defaults,
        ):
            assigned.setdefault(argument.arg, []).append(default)
        for argument, default in zip(scope.args.kwonlyargs, scope.args.kw_defaults):
            if default is not None:
                assigned.setdefault(argument.arg, []).append(default)
    return assigned


def _resolver(function_names, class_names, module_names):
    def resolve(node):
        if isinstance(node, ast.Name):
            return function_names.get(node.id) or module_names.get(node.id, [])
        if isinstance(node.value, ast.Name) and node.value.id in ("self", "cls"):
            return class_names.get(node.attr, [])
        return []

    return resolve


def _sink_calls(tree):
    module_names = _assignments(tree)
    pending = [(tree, {}, {})]
    while pending:
        scope, function_names, class_names = pending.pop()
        resolve = _resolver(function_names, class_names, module_names)
        for node in _scope_nodes(scope):
            if isinstance(node, ast.Call):
                yield node, resolve
            elif isinstance(node, ast.ClassDef):
                pending.append((node, {}, _assignments(node)))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                pending.append(
                    (node, {**function_names, **_assignments(node)}, class_names)
                )
            elif isinstance(node, ast.Lambda):
                pending.append((node, function_names, class_names))


def _menu_texts(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Tuple)
            and len(node.elts) >= 2
            and isinstance(node.elts[0], ast.Constant)
            and node.elts[0].value in MENU_ENTRY_KINDS
            and _is_text_leaf(node.elts[1])
        ):
            yield node.elts[1]
        elif isinstance(node, ast.Dict) and any(
            isinstance(value, ast.List)
            and any(element in _menu_entry_nodes(value) for element in value.elts)
            for value in node.values
        ):
            yield from (
                key for key in node.keys if key is not None and _is_text_leaf(key)
            )


def _menu_entry_nodes(container):
    return [
        element
        for element in container.elts
        if isinstance(element, ast.Tuple)
        and element.elts
        and isinstance(element.elts[0], ast.Constant)
        and isinstance(element.elts[0].value, str)
        and (
            element.elts[0].value in MENU_ENTRY_KINDS
            or element.elts[0].value in ("shared", "sep")
        )
    ]


def _display_pair_texts(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(
            node.value, (ast.Tuple, ast.List, ast.Dict)
        ):
            continue
        if not any(
            isinstance(target, ast.Name)
            and DISPLAY_COLLECTION.search(target.id)
            and not re.search(r"(^|_)LOG(_|$)", target.id)
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Dict):
            yield from (value for value in node.value.values if _is_text_leaf(value))
            continue
        for pair in node.value.elts:
            if (
                isinstance(pair, ast.Tuple)
                and len(pair.elts) == 2
                and isinstance(pair.elts[0], (ast.Name, ast.Attribute, ast.Constant))
                and _is_text_leaf(pair.elts[1])
                and re.search(r"[A-Z]|[a-z] |\) ?|\(", _literal_text(pair.elts[1]))
            ):
                yield pair.elts[1]


def _is_icon(node):
    if isinstance(node, ast.Call):
        func = node.func
        return not (isinstance(func, ast.Attribute) and func.attr == "format")
    if isinstance(node, ast.Name):
        return "icon" in node.id.lower()
    if isinstance(node, ast.Attribute):
        return "icon" in node.attr.lower()
    return False


def _progress_report_arguments(call):
    name, owner = _call_name(call)
    if name == "report" and "reporter" in owner.lower():
        return list(call.args[:1])
    return []


def _sink_arguments(call):
    return (
        _direct_sink_arguments(call)
        + _progress_report_arguments(call)
        + [
            keyword.value
            for keyword in call.keywords
            if keyword.arg in USER_TEXT_KEYWORDS
        ]
    )


def _direct_sink_arguments(call):
    name, owner = _call_name(call)
    if name in TEXT_ARGUMENT_POSITIONS:
        return [
            argument
            for index, argument in enumerate(call.args)
            if index in TEXT_ARGUMENT_POSITIONS[name]
        ]
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


def _text_position_names(node, assigned, visiting=frozenset()):
    if _is_str_call(node):
        yield from _text_position_names(node.args[0], assigned, visiting)
    elif isinstance(node, ast.Name):
        if node.id in assigned and node.id not in visiting:
            for value in assigned[node.id]:
                yield from _text_position_names(value, assigned, visiting | {node.id})
        else:
            yield node.id
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _text_position_names(value, assigned, visiting)
    elif isinstance(node, ast.IfExp):
        yield from _text_position_names(node.body, assigned, visiting)
        yield from _text_position_names(node.orelse, assigned, visiting)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        for leaf in _flatten_add(node):
            yield from _text_position_names(leaf, assigned, visiting)


def _helper_arguments(call, text_params):
    name = _call_name(call)[0]
    if name not in text_params:
        return []
    positions, hits = text_params[name]
    arguments = [
        argument
        for index, argument in enumerate(call.args)
        if index < len(positions) and positions[index] in hits
    ]
    return arguments + [
        keyword.value for keyword in call.keywords if keyword.arg in hits
    ]


def _functions(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "__init__":
                    yield node.name, child


def text_parameters(trees):
    text_params = {}
    changed = True
    while changed:
        changed = False
        for tree in trees:
            for name, function in _functions(tree):
                ordered = [
                    a.arg for a in function.args.posonlyargs + function.args.args
                ]
                if ordered and ordered[0] in ("self", "cls"):
                    ordered = ordered[1:]
                parameters = set(ordered) | {a.arg for a in function.args.kwonlyargs}
                assigned = {
                    key: values
                    for key, values in _assignments(function).items()
                    if key not in parameters
                }
                used = set()
                for node in _scope_nodes(function):
                    if isinstance(node, ast.Call):
                        for argument in _sink_arguments(node) + _helper_arguments(
                            node, text_params
                        ):
                            used.update(_text_position_names(argument, assigned))
                hits = frozenset(parameters & used)
                if (
                    hits
                    and text_params.get(name, (None, frozenset()))[1] | hits
                    != text_params.get(name, (None, frozenset()))[1]
                ):
                    previous = text_params.get(name, (ordered, frozenset()))[1]
                    text_params[name] = (ordered, previous | hits)
                    changed = True
    return text_params


def _self_attributes(node):
    if _is_str_call(node):
        yield from _self_attributes(node.args[0])
    elif isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id in ("self", "cls"):
            yield node.attr
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _self_attributes(value)
    elif isinstance(node, ast.IfExp):
        yield from _self_attributes(node.body)
        yield from _self_attributes(node.orelse)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        for leaf in _flatten_add(node):
            yield from _self_attributes(leaf)


def shown_attributes(trees, text_params):
    names = set()
    for tree in trees:
        for call, _resolve in _sink_calls(tree):
            for argument in _sink_arguments(call) + _helper_arguments(
                call, text_params
            ):
                names.update(_self_attributes(argument))
    return names


def _class_attribute_texts(tree, attributes):
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name) and target.id in attributes:
                        yield from _text_nodes(statement.value)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assigned = _assignments(statement)
                resolve = _resolver(assigned, {}, {})
                for child in _scope_nodes(statement):
                    if isinstance(child, ast.Assign):
                        for target in child.targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                                and target.attr in attributes
                            ):
                                yield from _text_nodes(child.value, resolve)


def _dict_text_values(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in USER_TEXT_DICT_KEYS:
                    yield from _text_nodes(value)


def _user_text_nodes(tree, text_params, attributes):
    for call, resolve in _sink_calls(tree):
        for argument in _sink_arguments(call) + _helper_arguments(call, text_params):
            yield from _text_nodes(argument, resolve)
    yield from _menu_texts(tree)
    yield from _display_pair_texts(tree)
    yield from _class_attribute_texts(tree, attributes)
    yield from _dict_text_values(tree)


def find_user_text(source, relative_path, text_params=None, attributes=None):
    tree = ast.parse(source)
    if text_params is None:
        text_params = text_parameters([tree])
    if attributes is None:
        attributes = shown_attributes([tree], text_params)
    nodes = {}
    for node in _user_text_nodes(tree, text_params, attributes):
        text = _literal_text(node)
        if re.search(r"[A-Za-z]", _PLACEHOLDER.sub("", text)):
            nodes[id(node)] = (node.lineno, node.col_offset, text)
    return [
        (relative_path, line, text)
        for line, _column, text in sorted(nodes.values(), key=lambda item: item[:2])
    ]


LOWER_LAYERS = ("domain", "application", "infrastructure")
LOWER_RESULT_KEYWORDS = frozenset(
    {"user_message", "message", "error", "error_message", "reason", "detail"}
)
_CODE_TOKEN = re.compile(
    r"\b[a-z]+_[a-z_]+\b|\b[a-z]+[A-Z]\w*\b|[=<>]{1,2}|\(\)|::|\w+\.\w+\(|\{\}\."
)


def is_people_sentence(text):
    plain = _PLACEHOLDER.sub("X", text).strip()
    if len(plain.split()) < 3 or not plain[:1].isupper():
        return False
    if not plain.rstrip().endswith((".", "?", "!")):
        return False
    return not _CODE_TOKEN.search(text.replace("{}", "X"))


def _lower_sink_arguments(node):
    if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
        name = _call_name(node.exc)[0]
        if name.endswith(("Error", "Exception")):
            return list(node.exc.args)
    if isinstance(node, ast.Call):
        return [
            keyword.value
            for keyword in node.keywords
            if keyword.arg in LOWER_RESULT_KEYWORDS
        ]
    return []


LOWER_RETURN_SUFFIXES = ("reason", "message", "error_text")


def _lower_returned_text(tree):
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not function.name.endswith(LOWER_RETURN_SUFFIXES):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Return) and node.value is not None:
                yield node.value


def find_lower_user_text(source, relative_path):
    tree = ast.parse(source)
    nodes = {}
    arguments = [
        argument for node in ast.walk(tree) for argument in _lower_sink_arguments(node)
    ]
    for argument in arguments + list(_lower_returned_text(tree)):
        for leaf in _text_nodes(argument):
            text = _literal_text(leaf)
            if is_people_sentence(text):
                nodes[id(leaf)] = (leaf.lineno, leaf.col_offset, text)
    return [
        (relative_path, line, text)
        for line, _column, text in sorted(nodes.values(), key=lambda item: item[:2])
    ]


def scan_lower(repo_root=REPO_ROOT):
    findings = []
    for layer in LOWER_LAYERS:
        for path in sorted((repo_root / "ost_visualizer" / layer).rglob("*.py")):
            relative = path.relative_to(repo_root).as_posix()
            findings.extend(
                find_lower_user_text(path.read_text(encoding="utf-8-sig"), relative)
            )
    return findings


def load_allowlist(path=ALLOWLIST):
    entries = json.loads(path.read_text(encoding="utf-8"))
    for entry in entries:
        if not entry.get("reason", "").strip():
            raise ValueError(f"allowlist entry without a reason: {entry}")
    return {(entry["file"], entry["text"]) for entry in entries}


def scan(root=PRESENTATION, repo_root=REPO_ROOT):
    sources = {}
    for path in sorted(root.rglob("*.py")):
        if path.name == TEXTS_MODULE and path.parent == root:
            continue
        sources[path.relative_to(repo_root).as_posix()] = path.read_text(
            encoding="utf-8-sig"
        )
    trees = [ast.parse(source) for source in sources.values()]
    text_params = text_parameters(trees)
    attributes = shown_attributes(trees, text_params)
    findings = []
    for relative, source in sources.items():
        findings.extend(find_user_text(source, relative, text_params, attributes))
    return findings


def violations(findings, allowlist):
    return [
        finding for finding in findings if (finding[0], finding[2]) not in allowlist
    ]


def stale_allowlist_entries(findings, allowlist):
    present = {(finding[0], finding[2]) for finding in findings}
    return sorted(allowlist - present)


def main(argv=None):
    findings = scan() + scan_lower()
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
