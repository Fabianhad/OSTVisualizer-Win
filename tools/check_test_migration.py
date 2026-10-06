"""Compare discovered test-method and assertion inventories with the pre-migration tree."""

import argparse
import ast
import io
import subprocess
import tarfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def signatures(contents):
    methods = Counter()
    assertions = Counter()
    for content in contents:
        for cls in ast.parse(content).body:
            if not isinstance(cls, ast.ClassDef):
                continue
            for method in cls.body:
                if not isinstance(
                    method, ast.FunctionDef
                ) or not method.name.startswith("test"):
                    continue
                methods[method.name] += 1
                for node in ast.walk(method):
                    if isinstance(node, ast.Assert):
                        assertions[(method.name, "assert")] += 1
                    elif (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr.startswith("assert")
                    ):
                        assertions[(method.name, node.func.attr)] += 1
    return methods, assertions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="HEAD")
    parser.add_argument(
        "--allow-additions",
        action="store_true",
        help="Allow added tests/assertions while still rejecting every missing original",
    )
    args = parser.parse_args()
    archive = subprocess.check_output(
        ["git", "archive", args.baseline, "tests"], cwd=ROOT
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as saved:
        old = signatures(
            saved.extractfile(member).read().decode("utf-8-sig")
            for member in saved.getmembers()
            if member.isfile() and member.name.endswith(".py")
        )
    new = signatures(
        path.read_text(encoding="utf-8-sig")
        for path in (ROOT / "tests").rglob("test_*.py")
    )
    for kind, expected, actual in zip(("methods", "assertions"), old, new, strict=True):
        print(f"{kind}: baseline={expected.total()}, current={actual.total()}")
        missing, added = expected - actual, actual - expected
        if missing or added:
            print(f"  missing: {dict(missing)}\n  added: {dict(added)}")
            if missing or (added and not args.allow_additions):
                raise SystemExit(1)
    print(
        "All original test names and assertion counts retained. Run the suite to verify behavior."
    )


if __name__ == "__main__":
    main()
