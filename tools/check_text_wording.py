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
}
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
_TOKEN = re.compile(r"\{[^{}]*\}|[.!?:;](?=\s)|[A-Za-z0-9][A-Za-z0-9'\-/.]*")
UNITS = frozenset({"px", "pt", "in", "ft", "mm", "cm", "m"})
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
    if name in ui_texts.MESSAGE_HELPERS or (
        owner == "QMessageBox" and name in ui_texts.QMESSAGEBOX_STATICS
    ):
        return "title" if index == 1 else "message"
    if name in ui_texts.FILE_DIALOGS:
        return "title" if index == 1 else None
    if name in ui_texts.USER_RESULT_TYPES or name in ui_texts.USER_EXCEPTION_TYPES:
        return "message"
    return SINK_KIND.get(name)


def usage_kinds(root=PRESENTATION, texts_path=TEXTS):
    kinds = defaultdict(set)
    for path in root.rglob("*.py"):
        if path == texts_path:
            continue
        for call in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if not isinstance(call, ast.Call):
                continue
            arguments = list(call.args) + [keyword.value for keyword in call.keywords]
            for index, argument in enumerate(arguments):
                kind = _kind_of_call(call, index)
                if (
                    index >= len(call.args)
                    and call.keywords[index - len(call.args)].arg in TITLE_KEYWORDS
                ):
                    kind = "title"
                if kind is None:
                    continue
                for node in ast.walk(argument):
                    if isinstance(node, ast.Name) and node.id.isupper():
                        kinds[node.id].add(kind)
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
        if token.startswith("{"):
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
    repeated = re.search(r"\b([A-Za-z]+)\s+\1\b", text, re.IGNORECASE)
    if repeated:
        problems.append(f"repeated word {repeated.group(0)!r}")
    if re.search(r"\s[?!,;:]|\s\.(?!\.\.)", text):
        problems.append("space before punctuation")
    if re.search(r"(\d|\})(px|pt)\b", text):
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


def check(texts=None, kinds=None):
    texts = load_texts() if texts is None else texts
    kinds = usage_kinds() if kinds is None else kinds
    findings = []
    for name, values in texts.items():
        found_kinds = kinds.get(name, set())
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
            for problem in mechanical_problems(value) + problems:
                findings.append((name, value, problem))
    return findings


def main(argv=None):
    findings = check()
    for name, value, problem in findings:
        print(f"{name}: {problem}: {value!r}")
    if findings:
        print(f"\n{len(findings)} wording problem(s) in texts.py.")
        return 1
    print("Wording in texts.py follows the AGENTS.md rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
