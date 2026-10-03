import ast
import unittest
from pathlib import Path
from tests.paths import REPO_ROOT

REPOSITORY_ROOT = REPO_ROOT
PRODUCTION_ROOTS = (
    REPOSITORY_ROOT / "ost_visualizer",
    REPOSITORY_ROOT / "sql_server" / "python",
)
TEST_ROOT = REPOSITORY_ROOT / "tests"


def _python_paths():
    for root in PRODUCTION_ROOTS:
        yield from root.rglob("*.py")
    yield REPOSITORY_ROOT / "Visualizer.py"
    yield REPOSITORY_ROOT / "McpServer.py"


def _body_without_docstring(node):
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body.pop(0)
    return body


def _is_declaration_ellipsis(node):
    body = _body_without_docstring(node)
    return (
        len(body) == 1
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and body[0].value.value is Ellipsis
    )


def _decorator_name(decorator):
    if isinstance(decorator, ast.Call):
        decorator = decorator.func
    if isinstance(decorator, ast.Attribute):
        return decorator.attr
    if isinstance(decorator, ast.Name):
        return decorator.id
    return None


def _is_abstract_method(node):
    return any(
        _decorator_name(decorator) == "abstractmethod"
        for decorator in node.decorator_list
    )


def _is_protocol_class(class_node):
    for base in class_node.bases:
        if isinstance(base, ast.Subscript):
            base = base.value
        if isinstance(base, ast.Attribute):
            base = ast.Name(id=base.attr)
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
    return False


def _empty_class_violations(tree, label):
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        body = _body_without_docstring(node)
        if not body:
            docstring = ast.get_docstring(node) or ""
            if not docstring.strip():
                violations.append(f"{label}:{node.lineno}:{node.name}")
            continue
        if len(body) != 1 or not isinstance(body[0], (ast.Pass, ast.Expr)):
            continue
        if isinstance(body[0], ast.Pass) or (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and body[0].value.value in (None, Ellipsis)
        ):
            violations.append(f"{label}:{node.lineno}:{node.name}")
    return violations


def _test_shell_violations(tree, label):
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        body = _body_without_docstring(node)
        if not body:
            violations.append(f"{label}:{node.lineno}:{node.name}")
            continue
        if len(body) != 1:
            continue
        statement = body[0]
        is_minimal = isinstance(statement, ast.Pass) or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value in (None, Ellipsis)
        )
        if is_minimal and not isinstance(statement, ast.Pass):
            violations.append(f"{label}:{node.lineno}:{node.name}")
    return violations


def _declaration_violations(tree, label):
    violations = []
    for class_node in (
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ):
        is_protocol = _is_protocol_class(class_node)
        for node in class_node.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not is_protocol and not _is_abstract_method(node):
                continue
            body = _body_without_docstring(node)
            is_declaration_only = len(body) == 1 and isinstance(
                body[0], (ast.Pass, ast.Expr)
            )
            if is_declaration_only and not _is_declaration_ellipsis(node):
                violations.append(f"{label}:{node.lineno}:{node.name}")
    return violations


def _scan(paths, scanner):
    """Return (violations, files scanned, classes seen, protocols seen)."""
    violations = []
    files = 0
    classes = 0
    protocols = 0
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        files += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes += 1
                protocols += _is_protocol_class(node)
        violations.extend(scanner(tree, str(path)))
    return violations, files, classes, protocols


class EmptyConstructConventionTests(unittest.TestCase):
    def test_production_empty_classes_use_meaningful_docstring_only_bodies(self):
        violations, files, classes, _protocols = _scan(
            _python_paths(), _empty_class_violations
        )
        self.assertEqual(violations, [])
        # Positive control: ~590 production files / ~925 classes exist
        # (counted with find/grep); a vacuous glob would scan none.
        self.assertGreaterEqual(files, 500)
        self.assertGreaterEqual(classes, 800)

    def test_empty_test_shell_classes_use_pass(self):
        violations, files, classes, _protocols = _scan(
            TEST_ROOT.rglob("*.py"), _test_shell_violations
        )
        self.assertEqual(violations, [])
        # Positive control: ~690 test files / ~2600 test classes exist.
        self.assertGreaterEqual(files, 500)
        self.assertGreaterEqual(classes, 2000)

    def test_protocol_and_abstract_declarations_use_ellipsis(self):
        violations, files, _classes, protocols = _scan(
            _python_paths(), _declaration_violations
        )
        self.assertEqual(violations, [])
        self.assertGreaterEqual(files, 500)
        # Positive control: the scanner reaches the ~75 production Protocols.
        self.assertGreaterEqual(protocols, 60)


class EmptyConstructScannerSelfTests(unittest.TestCase):
    """Prove each scanner reports a violation and accepts the convention."""

    @staticmethod
    def _run(scanner, source):
        return scanner(ast.parse(source), "<snippet>")

    def test_empty_class_scanner_flags_pass_ellipsis_none_and_blank_docstring(self):
        for body in ("    pass", "    ...", "    None", '    """   """'):
            with self.subTest(body=body):
                self.assertEqual(
                    self._run(_empty_class_violations, f"class Empty:\n{body}\n"),
                    ["<snippet>:1:Empty"],
                )
        self.assertEqual(
            self._run(
                _empty_class_violations, 'class Empty:\n    """Doc."""\n    pass\n'
            ),
            ["<snippet>:1:Empty"],
        )

    def test_empty_class_scanner_accepts_docstring_only_and_real_bodies(self):
        for source in (
            'class Marker:\n    """Marks the thing."""\n',
            "class Real:\n    value = 1\n",
        ):
            with self.subTest(source=source):
                self.assertEqual(self._run(_empty_class_violations, source), [])

    def test_test_shell_scanner_requires_pass_for_empty_classes(self):
        self.assertEqual(
            self._run(_test_shell_violations, "class A:\n    ...\n"),
            ["<snippet>:1:A"],
        )
        self.assertEqual(
            self._run(_test_shell_violations, 'class A:\n    """Only doc."""\n'),
            ["<snippet>:1:A"],
        )
        self.assertEqual(self._run(_test_shell_violations, "class A:\n    pass\n"), [])
        self.assertEqual(
            self._run(_test_shell_violations, 'class A:\n    """Doc."""\n    pass\n'),
            [],
        )

    def test_declaration_scanner_flags_pass_in_protocol_and_abstract_methods(self):
        violating_sources = (
            "class P(Protocol):\n    def m(self):\n        pass\n",
            "class P(typing.Protocol):\n    def m(self):\n        pass\n",
            "class P(Protocol[T]):\n    async def m(self):\n        pass\n",
            "class A(ABC):\n    @abstractmethod\n    def m(self):\n        pass\n",
            "class A(ABC):\n    @abc.abstractmethod\n    def m(self):\n        pass\n",
        )
        for source in violating_sources:
            with self.subTest(source=source):
                found = self._run(_declaration_violations, source)
                self.assertEqual(len(found), 1)
                self.assertTrue(found[0].endswith(":m"), found)

    def test_declaration_scanner_accepts_ellipsis_and_ignores_concrete_classes(self):
        for source in (
            "class P(Protocol):\n    def m(self): ...\n",
            'class P(Protocol):\n    def m(self):\n        """Doc."""\n        ...\n',
            "class A(ABC):\n    @abstractmethod\n    def m(self): ...\n",
            "class C:\n    def m(self):\n        pass\n",
        ):
            with self.subTest(source=source):
                self.assertEqual(self._run(_declaration_violations, source), [])


if __name__ == "__main__":
    unittest.main()
