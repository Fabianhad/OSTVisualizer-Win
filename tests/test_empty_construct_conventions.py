import ast
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
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


def _is_abstract_method(node):
    return any(
        isinstance(decorator, ast.Name) and decorator.id == "abstractmethod"
        for decorator in node.decorator_list
    )


class EmptyConstructConventionTests(unittest.TestCase):
    def test_production_empty_classes_use_meaningful_docstring_only_bodies(self):
        violations = []
        for path in _python_paths():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                body = _body_without_docstring(node)
                if not body:
                    docstring = ast.get_docstring(node) or ""
                    if not docstring.strip():
                        violations.append(f"{path}:{node.lineno}:{node.name}")
                    continue
                if len(body) != 1 or not isinstance(body[0], (ast.Pass, ast.Expr)):
                    continue
                if isinstance(body[0], ast.Pass) or (
                    isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and body[0].value.value in (None, Ellipsis)
                ):
                    violations.append(f"{path}:{node.lineno}:{node.name}")
        self.assertEqual(violations, [])

    def test_empty_test_shell_classes_use_pass(self):
        violations = []
        for path in TEST_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                body = _body_without_docstring(node)
                if not body:
                    violations.append(f"{path}:{node.lineno}:{node.name}")
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
                    violations.append(f"{path}:{node.lineno}:{node.name}")
        self.assertEqual(violations, [])

    def test_protocol_and_abstract_declarations_use_ellipsis(self):
        violations = []
        for path in _python_paths():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for class_node in (
                node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            ):
                is_protocol = any(
                    isinstance(base, ast.Name) and base.id == "Protocol"
                    for base in class_node.bases
                )
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
                        violations.append(f"{path}:{node.lineno}:{node.name}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
