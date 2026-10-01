"""Inventory quality-review work without treating static flags as verdicts."""
import argparse
import ast
import hashlib
import json
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def inventory():
    modules = {}
    review_path = ROOT / "tests" / "quality_review.json"
    reviews = json.loads(review_path.read_text(encoding="utf-8"))["modules"] if review_path.exists() else {}
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        methods = []
        relative = path.relative_to(ROOT).as_posix()
        reviewed = reviews.get(relative, {}).get("reviewed_tests", {})
        for owner in tree.body:
            if isinstance(owner, ast.ClassDef):
                candidates = owner.body
                prefix = owner.name + "."
            elif isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                candidates = [owner]
                prefix = ""
            else:
                continue
            for node in candidates:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
                    continue
                calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
                assertions = [ast.unparse(call.func) for call in calls if isinstance(call.func, ast.Attribute) and call.func.attr.startswith("assert")]
                assertions.extend("assert" for child in ast.walk(node) if isinstance(child, ast.Assert))
                methods.append({
                    "name": prefix + node.name,
                    "line": node.lineno,
                    "assertions": assertions,
                    "calls": sorted({ast.unparse(call.func) for call in calls}),
                    "decorators": [ast.unparse(item) for item in node.decorator_list],
                    "review_status": "reviewed; final fresh pass pending" if prefix + node.name in reviewed else "pending",
                    "review_note": reviewed.get(prefix + node.name, ""),
                })
        modules[relative] = {
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
            "methods": methods,
            "duplicate_method_names": [name for name, count in Counter(item["name"] for item in methods).items() if count > 1],
        }
    return {
        "scope": "Every test module and method; fixture and runtime review recorded separately. Static flags are triage only, never proof of review or weakness.",
        "module_count": len(modules),
        "method_count": sum(len(item["methods"]) for item in modules.values()),
        "modules": modules,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--discover", action="store_true", help="Compare definitions with real unittest discovery (imports tests, does not run them)")
    args = parser.parse_args()
    result = inventory()
    if args.discover:
        sys.path.insert(0, str(ROOT))
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        def test_ids(node):
            if isinstance(node, unittest.TestSuite):
                return [identity for child in node for identity in test_ids(child)]
            return [node.id()]
        identities = test_ids(suite)
        discovered = Counter(identities)
        defined = {
            path.removesuffix(".py").replace("/", ".") + "." + method["name"]
            for path, entry in result["modules"].items() for method in entry["methods"]
        }
        result["discovery"] = {
            "count": len(identities),
            "duplicate_ids": [identity for identity, count in discovered.items() if count > 1],
            "defined_but_not_discovered": sorted(defined - set(identities)),
            "discovered_without_local_definition": sorted(set(identities) - defined),
            "errors": list(unittest.defaultTestLoader.errors),
        }
        print(json.dumps(result["discovery"], indent=2))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['module_count']} modules; {result['method_count']} defined tests")
    print("Reviewed tests:", sum(method["review_status"] != "pending" for entry in result["modules"].values() for method in entry["methods"]))
    for name, entry in result["modules"].items():
        if entry["duplicate_method_names"]:
            print("DUPLICATE DEFINITIONS", name, entry["duplicate_method_names"])


if __name__ == "__main__":
    main()
