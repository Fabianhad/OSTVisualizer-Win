"""Fail when a text in presentation/texts.py breaks the wording rules in AGENTS.md.
Mechanical rules, checked on every constant: US spelling for the British forms
listed in BRITISH_SPELLINGS, no leading, trailing or double spaces, three
periods instead of the ellipsis character, hyphens instead of en or em dashes,
straight quotes, double quotes around quoted placeholders, no repeated words,
no space before punctuation, a space before px and pt, separate singular and
plural strings instead of "(s)", and well-formed named placeholders.
Capitalization is checked per kind of text, taken from the call that shows the
constant: Title Case for window and dialog titles, buttons, menu items, menus,
tabs, group boxes and column headers; sentence case for tooltips, check boxes
and radio buttons. Messages start with a capital letter and end with terminal
punctuation or a placeholder. A constant used as more than one kind is not
checked for capitalization.
Usage: python tools/check_text_wording.py
"""

import ast
import re
import string
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from tools import check_ui_texts as ui_texts  # noqa: E402

PRESENTATION = REPO_ROOT / "ost_visualizer" / "presentation"
TEXTS = PRESENTATION / "texts.py"
SHARED_TEXTS = REPO_ROOT / "ost_visualizer" / "shared" / "texts.py"
NAME_KINDS = (
    ("_MESSAGE_", "message"),
    ("_STATUS_", "status"),
    ("_LABEL_", "label"),
    ("_TITLE_", "title"),
    ("_TOOLTIP_", "tooltip"),
)
SENTENCE_VERBS = re.compile(
    r"\b(is|are|was|were|could|cannot|can|has|have|had|must|will|would|does|did"
    r"|should|may|might|failed)\b"
)
BRITISH_SPELLINGS = {
    "metre": "meter",
    "metres": "meters",
    "centimetre": "centimeter",
    "centimetres": "centimeters",
    "millimetre": "millimeter",
    "millimetres": "millimeters",
    "colour": "color",
    "colours": "colors",
    "grey": "gray",
    "greyscale": "grayscale",
    "behaviour": "behavior",
    "centre": "center",
    "licence": "license",
    "organise": "organize",
    "synchronise": "synchronize",
    "visualise": "visualize",
    "finalise": "finalize",
    "initialise": "initialize",
    "initialised": "initialized",
    "initialising": "initializing",
    "neighbouring": "neighboring",
    "neighbour": "neighbor",
    "dialogue": "dialog",
    "catalogue": "catalog",
    "whilst": "while",
    "pre-defined": "predefined",
}
TERMS = {
    "hot link": "hotlink",
    "hot links": "hotlinks",
    "unable to": "failed to",
    "error creating": "failed to create",
    "canceled": "cancelled",
    "refresh the database": "reload the database",
    "refresh the bid": "reload the bid",
    "refresh required": "reload required",
}
SHOUTING = re.compile(r"\b[A-Z]{2,}[!?.]?(?:\s+[A-Z]{2,}[!?.]?){2,}")
SINGLE_QUOTED = re.compile(r"(?<![A-Za-z])'[A-Za-z][^'\n]*'(?![A-Za-z])")
GENERATED_PLACEHOLDER = re.compile(r"^(value|text|arg)(_\d+)?$|_\d+$|^[a-z]$")
NUMBER_WITHOUT_PERIOD = re.compile(r"(?<=\w )No(?![.\w])")
FIELD_LABEL_CALLS = frozenset({"addRow"})
COMMAND_KINDS = frozenset({"action", "button", "menu"})
VIEWER_TEMPLATE = (
    PRESENTATION
    / "visualization"
    / "renderers"
    / "threejs"
    / "templates"
    / "viewer.html"
)
DOMAIN_NOUNS = frozenset(
    {
        "Condition",
        "Conditions",
        "Takeoff",
        "Takeoffs",
        "Bid",
        "Bids",
        "Page",
        "Pages",
        "Layer",
        "Layers",
        "Project",
        "Projects",
        "Folder",
        "Folders",
        "Area",
        "Areas",
        "Annotation",
        "Annotations",
        "Delete",
    }
)
SMALL_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "nor",
        "but",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "by",
        "with",
        "from",
        "as",
        "per",
        "vs",
        "via",
        "into",
        "while",
    }
)
PROPER_WORDS = frozenset(
    {
        "Visualizer",
        "Server",
        "Windows",
        "Microsoft",
        "Access",
        "Codex",
        "OK",
        "Yes",
        "No",
    }
)
PROPER_PHRASES = (
    "On-Screen Takeoff",
    "Named Views",
    "Named View",
    "Open Files",
    "Deleted Bids",
    "Summary CSV",
    "Takeoff tab",
    "Print Preview",
    "Active Area",
    "Display Size",
    "Add Length",
    "Base Bid",
    "Change Orders",
    "Alternates",
    "Options",
    "Windows Credential Manager",
)
_PROPER_PHRASE = re.compile(
    r"\b(" + "|".join(re.escape(phrase) for phrase in PROPER_PHRASES) + r")\b"
)
CASE_EXEMPTIONS = {
    "OPTIONS_LABEL_HTML_ELEVATION_CALLOUT_COLOR": "Field label (sentence case) that is also the title of its color dialog.",
    "OPTIONS_LABEL_PDF_ELEVATION_CALLOUT_COLOR": "Field label (sentence case) that is also the title of its color dialog.",
    "PLAN_TOOL_REGISTRY_LABEL_PAGE_SETTINGS_SCALE_AND_AREA": "Names the Page Settings toolbar group and its Scale and Area controls.",
    "THREEJS_RENDERER_TITLE_OST_TAKEOFF_3D_VISUALIZATION": "Title of the exported HTML page (Title Case).",
    "TAKEOFF_TOOLBAR_TAB_LABEL_ANNOTATION_TOOLS": "Group title matched against TakeoffToolbarItemSpec.group in plan_tool_registry (a lookup key).",
    "TAKEOFF_TOOLBAR_TAB_LABEL_PAGE_NAVIGATION": "Group title matched against TakeoffToolbarItemSpec.group in plan_tool_registry (a lookup key).",
    "TAKEOFF_TOOLBAR_TAB_LABEL_CURSOR_TOOLS": "Group title matched against TakeoffToolbarItemSpec.group in plan_tool_registry (a lookup key).",
    "TAKEOFF_TOOLBAR_TAB_LABEL_VIEW_CONTROLS": "Group title matched against TakeoffToolbarItemSpec.group in plan_tool_registry (a lookup key).",
}
TITLE_KINDS = frozenset({"title", "button", "action", "menu", "tab", "group", "header"})
SENTENCE_KINDS = frozenset({"tooltip", "option"})
RUNNING_TEXT_KINDS = frozenset({"tooltip", "option", "message"})
SINK_KIND = {
    "QCheckBox": "option",
    "QRadioButton": "option",
    "QLabel": "label",
    "QPushButton": "button",
    "QToolButton": "button",
    "QCommandLinkButton": "button",
    "addButton": "button",
    "QAction": "action",
    "addAction": "action",
    "action_spec": "action",
    "QMenu": "menu",
    "addMenu": "menu",
    "setToolTip": "tooltip",
    "setStatusTip": "tooltip",
    "setWindowTitle": "title",
    "setHeaderLabels": "header",
    "setHorizontalHeaderLabels": "header",
    "setVerticalHeaderLabels": "header",
    "addTab": "tab",
    "insertTab": "tab",
    "setTabText": "tab",
    "QGroupBox": "group",
    "setTitle": "group",
    "setPlaceholderText": "placeholder",
    "showMessage": "status",
}
_TOKEN = re.compile(
    r"\{[^{}]*\}|(?<![A-Za-z0-9])\.[a-z0-9]{2,4}\b|[.!?:;](?=\s)|[A-Za-z0-9][A-Za-z0-9'\-/.]*"
)
UNITS = frozenset({"px", "pt", "in", "ft", "mm", "cm", "m"})
ITEM_LIST_HELPERS = {"confirm_multi_delete": (2, 3), "confirm_delete_conditions": (1,)}
TITLE_KEYWORDS = frozenset({"title", "window_title", "dialog_title"})


def load_texts(path=TEXTS):
    texts = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            value = ast.literal_eval(node.value)
            texts[node.targets[0].id] = value if isinstance(value, tuple) else (value,)
    return texts


def _kind_of_call(call, index):
    name, owner = ui_texts._call_name(call)
    if index in ITEM_LIST_HELPERS.get(name, ()):
        return "item"
    if name in ui_texts.MESSAGE_HELPERS or (
        owner == "QMessageBox" and name in ui_texts.QMESSAGEBOX_STATICS
    ):
        return "title" if index == 1 else "message"
    if name in ui_texts.FILE_DIALOGS:
        return "title" if index == 1 else None
    if name in ui_texts.USER_RESULT_TYPES or name in ui_texts.USER_EXCEPTION_TYPES:
        return "message"
    return SINK_KIND.get(name)


def _upper_names(node, resolve, visiting=frozenset()):
    if isinstance(node, ast.Name) and node.id.isupper():
        yield node.id
    elif isinstance(node, (ast.Name, ast.Attribute)):
        key = ast.dump(node)
        if key not in visiting:
            for value in resolve(node):
                yield from _upper_names(value, resolve, visiting | {key})
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            yield from _upper_names(node.func.value, resolve, visiting)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _upper_names(value, resolve, visiting)
    elif isinstance(node, ast.IfExp):
        yield from _upper_names(node.body, resolve, visiting)
        yield from _upper_names(node.orelse, resolve, visiting)
    elif isinstance(node, ast.BinOp):
        yield from _upper_names(node.left, resolve, visiting)
        yield from _upper_names(node.right, resolve, visiting)
    elif isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            yield from _upper_names(element, resolve, visiting)


def _structural_kinds(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Tuple)
            and len(node.elts) >= 2
            and isinstance(node.elts[0], ast.Constant)
            and node.elts[0].value in ui_texts.MENU_ENTRY_KINDS
            and isinstance(node.elts[1], ast.Name)
        ):
            yield node.elts[1].id, (
                "menu" if node.elts[0].value == "cascade" else "action"
            )
        elif isinstance(node, ast.Dict) and any(
            isinstance(value, ast.List) and ui_texts._menu_entry_nodes(value)
            for value in node.values
        ):
            for key in node.keys:
                if isinstance(key, ast.Name):
                    yield key.id, "menu"


def _argument_kind(call, index):
    kind = _kind_of_call(call, index)
    if (
        index >= len(call.args)
        and call.keywords[index - len(call.args)].arg in TITLE_KEYWORDS
    ):
        kind = "title"
    return kind


def _helper_parameter_slots(call, text_params):
    name = ui_texts._call_name(call)[0]
    if name not in text_params:
        return []
    positions, hits = text_params[name]
    slots = [
        (argument, positions[index])
        for index, argument in enumerate(call.args)
        if index < len(positions) and positions[index] in hits
    ]
    return [(name, parameter, argument) for argument, parameter in slots] + [
        (name, keyword.arg, keyword.value)
        for keyword in call.keywords
        if keyword.arg in hits
    ]


def parameter_kinds(trees, text_params):
    kinds = defaultdict(set)
    changed = True
    while changed:
        changed = False
        for tree in trees:
            for name, function in ui_texts._functions(tree):
                if name not in text_params:
                    continue
                hits = text_params[name][1]
                assigned = {
                    key: values
                    for key, values in ui_texts._assignments(function).items()
                    if key not in hits
                }
                for node in ui_texts._scope_nodes(function):
                    if not isinstance(node, ast.Call):
                        continue
                    found = []
                    arguments = list(node.args) + [
                        keyword.value for keyword in node.keywords
                    ]
                    for index, argument in enumerate(arguments):
                        kind = _argument_kind(node, index)
                        if kind:
                            found.append(({kind}, argument))
                    for callee, parameter, argument in _helper_parameter_slots(
                        node, text_params
                    ):
                        found.append((kinds[(callee, parameter)], argument))
                    for found_kinds, argument in found:
                        for parameter in ui_texts._text_position_names(
                            argument, assigned
                        ):
                            if (
                                parameter in hits
                                and not found_kinds <= kinds[(name, parameter)]
                            ):
                                kinds[(name, parameter)] |= found_kinds
                                changed = True
    return kinds


def usage_kinds(root=PRESENTATION, texts_path=TEXTS):
    kinds = defaultdict(set)
    trees = [
        ast.parse(path.read_text(encoding="utf-8-sig"))
        for path in sorted(root.rglob("*.py"))
        if path != texts_path
    ]
    text_params = ui_texts.text_parameters(trees)
    helper_kinds = parameter_kinds(trees, text_params)
    for tree in trees:
        for name, kind in _structural_kinds(tree):
            kinds[name].add(kind)
        for call, resolve in ui_texts._sink_calls(tree):
            arguments = list(call.args) + [keyword.value for keyword in call.keywords]
            for index, argument in enumerate(arguments):
                kind = _argument_kind(call, index)
                if kind is None:
                    continue
                for name in _upper_names(argument, resolve):
                    kinds[name].add(kind)
            for callee, parameter, argument in _helper_parameter_slots(
                call, text_params
            ):
                for name in _upper_names(argument, resolve):
                    kinds[name] |= helper_kinds[(callee, parameter)]
    return kinds


def _after(punctuation):
    if punctuation in ".!?":
        return True
    return None if punctuation == ":" else False


def _words(text):
    words = []
    sentence_start = True
    first_line = _PROPER_PHRASE.sub("{}", re.sub(r"<[^>]+>", " ", text.split("\n")[0]))
    for token in _TOKEN.findall(first_line):
        if token.startswith("{") or (token.startswith(".") and len(token) > 1):
            sentence_start = False
        elif token in ".!?:;":
            sentence_start = _after(token)
        else:
            stripped = token.rstrip(".!?:;")
            words.append((stripped, sentence_start))
            sentence_start = _after(token[-1]) if stripped != token else False
    return words


def _significant(word):
    return (
        word[0].isalpha()
        and word.lower() not in SMALL_WORDS
        and word.lower() not in UNITS
        and word not in PROPER_WORDS
        and not re.match(r"^[A-Z0-9]{2,}", word)
    )


def is_title_case(text):
    return all(
        word[0].isupper()
        for word, start in _words(text)
        if _significant(word) or (start and word[0].isalpha())
    )


def is_sentence_case(text):
    for word, start in _words(text):
        if start is True and word[0].islower():
            return False
        if start is False and _significant(word) and word[0].isupper():
            return False
    return True


def mechanical_problems(text):
    problems = []
    if text != text.strip(" \t"):
        problems.append("leading or trailing space")
    if "  " in text:
        problems.append("double space")
    if "…" in text:
        problems.append("ellipsis character instead of three periods")
    if re.search("[–—]|&[nm]dash;", text):
        problems.append("en or em dash instead of a hyphen")
    if re.search("[‘’“”]", text):
        problems.append("curly quote")
    if re.search(r"'\{\w*\}'", text):
        problems.append("single quotes around a placeholder")
    elif SINGLE_QUOTED.search(text):
        problems.append(
            "single-quoted phrase (use double quotes, or none for a named place)"
        )
    repeated = re.search(r"\b([A-Za-z]+)\s+\1\b", text, re.IGNORECASE)
    if repeated:
        problems.append(f"repeated word {repeated.group(0)!r}")
    if re.search(r"\s[?!,;]|\s:(?!\s*[\d{])|\s\.(?![A-Za-z{]|\.\.)", text):
        problems.append("space before punctuation")
    if re.search(r"(\d|\})(px|pt|in|ft|mm|cm)\b", text):
        problems.append("no space before unit")
    if "(s)" in text:
        problems.append("(s) instead of separate singular and plural strings")
    for word in re.findall(r"[A-Za-z][A-Za-z\-]*", text):
        if word.lower() in BRITISH_SPELLINGS:
            problems.append(
                f"British spelling {word!r} (use {BRITISH_SPELLINGS[word.lower()]!r})"
            )
    for term, preferred in TERMS.items():
        match = re.search(rf"\b{term}\b", text, re.IGNORECASE)
        if match:
            problems.append(f"term {match.group(0)!r} (use {preferred!r})")
    try:
        fields = [
            field
            for _, field, _, _ in string.Formatter().parse(text)
            if field is not None
        ]
    except ValueError:
        problems.append("unbalanced placeholder braces")
    else:
        for field in fields:
            if not field.isidentifier():
                problems.append(f"placeholder {{{field}}} is not a name")
            elif GENERATED_PLACEHOLDER.search(field):
                problems.append(f"placeholder {{{field}}} has no meaningful name")
    return problems


def domain_noun_problems(text):
    nouns = []
    for line in text.split("\n"):
        nouns.extend(
            word
            for word, start in _words(line)
            if start is False and word in DOMAIN_NOUNS
        )
    return [f"capitalized {noun!r} in running text" for noun in nouns]


def case_problems(kind, text):
    if kind == "field_label":
        problems = (
            []
            if text.rstrip().endswith(":")
            else ["field label does not end with a colon"]
        )
        return problems + label_problems(text)
    if kind in TITLE_KINDS:
        return [] if is_title_case(text) else [f"{kind} is not Title Case"]
    problems = domain_noun_problems(text) if kind in RUNNING_TEXT_KINDS else []
    if problems:
        return problems
    if kind in SENTENCE_KINDS and not is_sentence_case(text):
        return [f"{kind} is not sentence case"]
    if kind == "message":
        stripped = text.strip()
        problems = []
        if stripped[:1].islower():
            problems.append("message does not start with a capital letter")
        if stripped[-1:] not in ".?!}":
            problems.append(
                "message does not end with terminal punctuation or a placeholder"
            )
        return problems
    return []


def label_problems(text):
    problems = []
    if text.rstrip().endswith(":") and "\n" not in text and not is_sentence_case(text):
        problems.append("label ending with a colon is not sentence case")
    if NUMBER_WITHOUT_PERIOD.search(text):
        problems.append("No without its period (use No.)")
    return problems


SHOUTING_EXEMPTIONS = {
    "DATABASE_CREATOR_MESSAGE_CANNOT_CREATE_A_DATABASE_ON_THIS": "CREATE ANY DATABASE is the SQL Server permission name.",
}


def name_problems(name, text):
    if (
        "_STATUS_" not in name
        and name not in SHOUTING_EXEMPTIONS
        and SHOUTING.search(text)
    ):
        return ["three or more words in capitals"]
    return []


def ellipsis_problems(texts, kinds):
    commands = {}
    for name, values in texts.items():
        if kinds.get(name, set()) & COMMAND_KINDS:
            for value in values:
                commands.setdefault(value, []).append(name)
    return [
        (name, value, "command also appears with ... (use one form)")
        for value, names in commands.items()
        if value + "..." in commands
        for name in names
    ]


def viewer_button_problems(path=VIEWER_TEMPLATE):
    source = path.read_text(encoding="utf-8")
    labels = re.findall(r"<button[^>]*>\s*([^<]*?[A-Za-z][^<]*?)\s*</button>", source)
    for assignment in re.findall(r"Button\.textContent\s*=\s*([^;]+);", source):
        labels.extend(re.findall(r'"([^"]*)"', assignment))
    return [
        ("viewer.html", label, "HTML viewer button is not Title Case")
        for label in labels
        if not is_title_case(label)
    ]


def check(texts=None, kinds=None):
    texts = load_texts() if texts is None else texts
    kinds = usage_kinds() if kinds is None else kinds
    findings = []
    for name, values in texts.items():
        found_kinds = kinds.get(name) or name_kinds(name)
        kind = (
            next(iter(found_kinds))
            if len(found_kinds) == 1 and name not in CASE_EXEMPTIONS
            else None
        )
        untitled = not found_kinds & TITLE_KINDS and name not in CASE_EXEMPTIONS
        for value in values:
            if kind:
                problems = case_problems(kind, value)
            else:
                running = untitled and len(_words(value)) >= 4
                problems = domain_noun_problems(value) if running else []
            if kind in ("label", "header") or kind is None:
                problems = problems + label_problems(value)
            problems = problems + name_problems(name, value)
            if "_LOG_" in name:
                for problem in mechanical_problems(value):
                    if problem.startswith(LOG_TEXT_RULES):
                        findings.append((name, value, problem))
                continue
            if kind in ("label", None) and reads_as_sentence(value):
                problems.append("sentence without a final period")
            for problem in mechanical_problems(value) + problems:
                findings.append((name, value, problem))
    return findings + ellipsis_problems(texts, kinds)


LOG_TEXT_RULES = (
    "placeholder",
    "unbalanced placeholder",
    "leading or trailing space",
    "double space",
)


def name_kinds(name):
    return {kind for token, kind in NAME_KINDS if token in name}


def reads_as_sentence(text):
    plain = re.sub(r"\{[^{}]*\}", "X", text).strip()
    if plain.endswith((".", "?", "!", ":")) or text.rstrip().endswith("}"):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z']+", plain)
    if len(words) < 4 or not text.lstrip()[:1].isupper() or is_title_case(plain):
        return False
    return bool(SENTENCE_VERBS.search(plain.lower()))


def shared_kinds(texts):
    return {
        name: {kind} for name in texts for token, kind in NAME_KINDS if token in name
    }


def check_shared(path=SHARED_TEXTS):
    if not path.exists():
        return []
    texts = load_texts(path)
    return check(texts, shared_kinds(texts))


def main(argv=None):
    findings = check() + viewer_button_problems() + check_shared()
    for name, value, problem in findings:
        print(f"{name}: {problem}: {value!r}")
    if findings:
        print(
            f"\n{len(findings)} wording problem(s) in presentation/texts.py and shared/texts.py."
        )
        return 1
    print(
        "Wording in presentation/texts.py and shared/texts.py follows the AGENTS.md rules."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
