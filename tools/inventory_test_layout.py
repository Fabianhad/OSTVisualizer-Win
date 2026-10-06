"""Inspect production symbols and test references without importing Qt or databases."""

import argparse
import ast
import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Reviewed exceptions, not inferred execution coverage. These do not justify
# empty primary test files or claim that operational entry points were run.
REVIEWED_COVERAGE_NOTES = {
    "ost_visualizer/presentation/managers/main_hotlink_view_manager.py": "Main-window navigation facade. Exact navigation ownership is exercised in the hotlink navigation/workspace integration tests; this facade has no isolated test.",
    "ost_visualizer/presentation/utils/qt_window_icon_provider.py": "Single-call adapter to window_configurator.set_window_icon; no additional state or branching to isolate.",
    "tools/audit_sql_integration_environment.py": "Operator-run SQL Server environment inspection. No direct unit suite; running it requires the configured local server and is not part of a layout migration.",
    "tools/check_architecture.py": "Executed directly against the complete source tree and changed files during validation. Architecture tests also enforce production contracts; no isolated checker unit suite.",
    "tools/profile_cover_sheet_dialog.py": "Manual timing harness, not application behavior. Cover Sheet construction, loading and lifetime have primary and integration tests; timing results are environment-dependent.",
    "tools/provision_sql_integration.py": "Operator provisioning changes SQL logins, credentials and server state. Not run for this migration; underlying SQL development and safety boundaries retain their dedicated tests.",
}


def inventory():
    sources = {}
    execution_path = ROOT / "tests" / "execution_inventory.json"
    execution = (
        json.loads(execution_path.read_text(encoding="utf-8"))
        if execution_path.exists()
        else {}
    )
    observed = (
        execution.get("observed_functions", {}) if execution.get("successful") else {}
    )
    extra_sources = subprocess.check_output(
        ["git", "ls-files", "*.py", ":!:tests/*", ":!:ost_visualizer/*"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    production_paths = sorted(
        {
            *(ROOT / "ost_visualizer").rglob("*.py"),
            *(ROOT / name for name in extra_sources),
        }
    )
    metadata = {}
    for path in production_paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        symbols = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(node.name)
            elif isinstance(node, ast.ClassDef):
                symbols.append(node.name)
                symbols.extend(
                    f"{node.name}.{child.name}"
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
        source = path.relative_to(ROOT).as_posix()
        sources[source] = symbols
        relative = (
            path.relative_to(ROOT / "ost_visualizer")
            if path.is_relative_to(ROOT / "ost_visualizer")
            else path.relative_to(ROOT)
        )
        primary = Path("tests") / relative.parent / ("test_" + relative.name)
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        behavioral_methods = [
            node
            for node in methods
            if any(
                not isinstance(child, (ast.Pass, ast.Expr))
                or isinstance(child, ast.Expr)
                and not isinstance(child.value, ast.Constant)
                for child in node.body
            )
        ]
        delegate_methods = [
            node for node in behavioral_methods if node.name != "__init__"
        ]
        thin_delegate = bool(delegate_methods) and all(
            len(node.body) == 1
            and isinstance(node.body[0], ast.Return)
            and isinstance(node.body[0].value, ast.Call)
            for node in delegate_methods
        )
        metadata[source] = {
            "primary_test": primary.as_posix(),
            "primary_exists": (ROOT / primary).is_file(),
            "symbols": symbols,
            "public_symbols": [
                name for name in symbols if not name.rsplit(".", 1)[-1].startswith("_")
            ],
            "private_helpers": [
                name for name in symbols if name.rsplit(".", 1)[-1].startswith("_")
            ],
            "failure_path_symbols": [
                node.name
                for node in methods
                if any(
                    isinstance(child, (ast.Raise, ast.Try)) for child in ast.walk(node)
                )
            ],
            "ownership_lifecycle_symbols": [
                name
                for name in symbols
                if any(
                    token in name.lower()
                    for token in (
                        "owner",
                        "cleanup",
                        "shutdown",
                        "close",
                        "destroy",
                        "cancel",
                        "lease",
                        "generation",
                        "revision",
                    )
                )
            ],
            "behavior_kind": (
                "declarations/data/constants"
                if not behavioral_methods
                else "thin delegation" if thin_delegate else "implemented behavior"
            ),
        }
    tests = {}
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imports = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(
                    ("ost_visualizer", "ostv_sql_admin", "tools")
                ):
                    for alias in node.names:
                        imports[alias.asname or alias.name] = (node.module, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(
                        ("ost_visualizer", "ostv_sql_admin", "tools")
                    ):
                        imports[alias.asname or alias.name] = (alias.name, "")
        groups = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods = [
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name.startswith("test")
                ]
                if not methods:
                    continue
            elif isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                methods = [node]
            else:
                continue
            references = Counter()
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and child.id in imports:
                    module, symbol = imports[child.id]
                    references[f"{module}:{symbol}"] += 1
            groups.append(
                {
                    "name": node.name,
                    "tests": [method.name for method in methods],
                    "references": dict(references.most_common()),
                    "calls": sorted(
                        {
                            ast.unparse(child.func)
                            for child in ast.walk(node)
                            if isinstance(child, ast.Call)
                        }
                    ),
                }
            )
        tests[path.relative_to(ROOT).as_posix()] = {
            "imports": imports,
            "groups": groups,
        }
    for source, entry in metadata.items():
        module = source.removesuffix(".py").replace("/", ".")
        if module.startswith("sql_server.python."):
            module = module.removeprefix("sql_server.python.")
        references = []
        for test, details in tests.items():
            if any(
                import_module == module
                for import_module, _symbol in details["imports"].values()
            ):
                references.append(test)
        entry["import_reference_tests"] = references
        entry["integration_reference_tests"] = [
            name for name in references if name.startswith("tests/integration/")
        ]
        entry["review_note"] = REVIEWED_COVERAGE_NOTES.get(source, "")
        entry["observed_function_calls"] = observed.get(source.lower(), [])
        entry["symbols_without_observed_call"] = [
            name
            for name in entry["symbols"]
            if name not in entry["observed_function_calls"]
        ]
        if entry["primary_exists"]:
            entry["coverage_classification"] = "primary test module"
        elif source.endswith("/__init__.py"):
            entry["coverage_classification"] = "package exports; no separate test shell"
        elif "/interfaces/" in source or "/repositories/i_" in source:
            entry["coverage_classification"] = (
                "declaration contract; implementations and architecture checks own behavior"
            )
        elif not sources[source]:
            entry["coverage_classification"] = (
                "constants/entry point; no independent function tests"
            )
        elif entry["behavior_kind"] == "declarations/data/constants":
            entry["coverage_classification"] = (
                "declaration/data contract; tested through consuming behavior"
            )
        elif entry["integration_reference_tests"]:
            entry["coverage_classification"] = (
                "integration references; no dedicated direct unit tests"
            )
        elif references:
            entry["coverage_classification"] = (
                "referenced by neighboring tests; no dedicated direct unit tests"
            )
        elif entry["observed_function_calls"]:
            entry["coverage_classification"] = (
                "executed through broader suite; no isolated primary"
            )
        elif entry["behavior_kind"] == "thin delegation":
            entry["coverage_classification"] = (
                "thin delegation; no direct wrapper tests (writer/service boundaries have primary tests)"
            )
        elif entry["review_note"]:
            entry["coverage_classification"] = (
                "reviewed adapter/operational entry point; see review note"
            )
        else:
            entry["coverage_classification"] = (
                "no explicit direct test import; indirect coverage not inferred"
            )
    return {
        "analysis_limits": "Static symbols/imports/calls plus an optional successful call-observation snapshot. Observed calls are not statement or branch coverage; references do not prove execution. Missing primaries and unobserved symbols are documented rather than populated with empty tests. Snapshots describe the recorded run, not future edits.",
        "execution_snapshot": {
            key: value
            for key, value in execution.items()
            if key != "observed_functions"
        },
        "production": sources,
        "source_to_tests": metadata,
        "tests": tests,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prefix", default="")
    args = parser.parse_args()
    result = inventory()
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for path, entry in result["tests"].items():
        if args.prefix and args.prefix not in path:
            continue
        print(path)
        for group in entry["groups"]:
            refs = list(group["references"])[:5]
            print(f"  {group['name']} ({len(group['tests'])}): {'; '.join(refs)}")
    print(
        f"Production modules: {len(result['production'])}; test modules: {len(result['tests'])}"
    )


if __name__ == "__main__":
    main()
