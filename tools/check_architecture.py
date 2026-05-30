"""
Automated architecture checks derived from CLAUDE.md.
Usage:
    python tools/check_architecture.py                  # full scan
    python tools/check_architecture.py --changed-only   # only staged/modified .py files
    python tools/check_architecture.py --verbose         # extra output
Exit code 0 = clean, 1 = violations found.
"""

import ast
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OST_ROOT = REPO_ROOT / "ost_visualizer"
VERBOSE = "--verbose" in sys.argv
CHANGED_ONLY = "--changed-only" in sys.argv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_changed_py_files() -> set:
    """Return set of absolute Paths for .py files that are staged or modified."""
    changed = set()
    for cmd in (
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        ["git", "diff", "--name-only", "--diff-filter=ACMR"],
    ):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            )
            for line in result.stdout.strip().splitlines():
                p = (REPO_ROOT / line.strip()).resolve()
                if p.suffix == ".py":
                    changed.add(p)
        except (FileNotFoundError, OSError):
            pass
    return changed


_changed_files_cache = None


def _is_file_in_scope(filepath: Path) -> bool:
    """In --changed-only mode, return True only for changed files."""
    if not CHANGED_ONLY:
        return True
    global _changed_files_cache
    if _changed_files_cache is None:
        _changed_files_cache = _get_changed_py_files()
    return filepath.resolve() in _changed_files_cache


def iter_py_files(directory: Path):
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith(".py"):
                p = Path(root) / f
                if _is_file_in_scope(p):
                    yield p


def relpath(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT)).replace("\\", "/")


def layer_of(filepath: Path) -> str:
    rel = filepath.relative_to(OST_ROOT)
    parts = rel.parts
    if parts[0] in (
        "domain",
        "application",
        "infrastructure",
        "presentation",
        "config",
    ):
        return parts[0]
    return "other"


def sublayer_of(filepath: Path) -> str:
    """Return e.g. 'application/services' or 'application/interfaces'."""
    rel = filepath.relative_to(OST_ROOT)
    parts = rel.parts
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


class Violation:
    def __init__(self, category: str, filepath: Path, line: int, message: str):
        self.category = category
        self.filepath = filepath
        self.line = line
        self.message = message

    def __str__(self):
        return f"[{self.category}] {relpath(self.filepath)}:{self.line}: {self.message}"


violations: list = []


def add(category: str, filepath: Path, line: int, message: str):
    violations.append(Violation(category, filepath, line, message))


# ---------------------------------------------------------------------------
# 1. Layer boundary checks
# ---------------------------------------------------------------------------
# Patterns to detect cross-layer imports via relative or absolute paths.
# We check the raw import text against known layer names.
LAYER_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+" r"(?:\.*)?" r"(.*)",
    re.MULTILINE,
)
# Documented exceptions:
#   - config/di_config.py may import anything (composition root)
#   - providers.py may import PageLoadStrategyService from application/services
#   - presentation may import domain entities (documented pragmatic shortcut)
#   - presentation may import UpdateCheckService.CURRENT_VERSION
PRESENTATION_APP_SERVICE_EXCEPTIONS = {
    # file stem -> allowed import
    "about_dialog": "update_check_service",
    "window_configurator": "update_check_service",
}
INFRA_APP_SERVICE_EXCEPTIONS = {
    "providers": "page_load_strategy_service",
}
# Infrastructure files that may import from presentation/visualization/
# (the Qt-aware rendering sub-package): DI factories + importers that
# delegate archive/compression work to C++ modules now living in presentation.
INFRA_PRESENTATION_VIZ_EXCEPTIONS = {
    "providers",
    "visualization_provider",
    "osp_importer",
}


def check_layer_boundaries():
    for py_file in iter_py_files(OST_ROOT):
        layer = layer_of(py_file)
        if layer == "config":
            continue  # composition root, may import everything
        if layer == "other":
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith(("from ", "import ")):
                continue
            if stripped.startswith("#"):
                continue
            import_text = stripped
            # Resolve relative imports: count leading dots
            resolved_target = _resolve_import(import_text, py_file)
            if resolved_target is None:
                continue
            _check_single_import(layer, py_file, i, resolved_target)


def _resolve_import(import_text: str, filepath: Path):
    """Resolve an import line to a layer-relative module path string.
    Returns None if the import is external (not ost_visualizer)."""
    # Absolute import: from ost_visualizer.domain.X import Y
    m = re.match(r"(?:from|import)\s+ost_visualizer\.(\S+)", import_text)
    if m:
        return m.group(1)
    # Relative import: from ..domain.X import Y or from . import X
    m = re.match(r"from\s+(\.+)([\w.]*)", import_text)
    if m:
        dots = len(m.group(1))
        rest = m.group(2)
        # Walk up from the file's directory
        base = filepath.parent
        for _ in range(dots):
            base = base.parent
        try:
            rel = base.relative_to(OST_ROOT)
            parts = list(rel.parts)
            if rest:
                parts.extend(rest.split("."))
            return ".".join(parts) if parts else rest
        except ValueError:
            # base landed at or above OST_ROOT — resolve from rest alone
            if base == OST_ROOT.parent or base == OST_ROOT:
                return rest if rest else None
    return None


def _check_single_import(layer: str, filepath: Path, lineno: int, target: str):
    """Check a single resolved import target against layer rules."""
    parts = target.split(".")
    target_layer = parts[0] if parts else ""
    target_sublayer = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else ""
    stem = filepath.stem
    # --- DOMAIN: must not import application, infrastructure, presentation ---
    if layer == "domain":
        if target_layer in ("application", "infrastructure", "presentation"):
            add(
                "layer",
                filepath,
                lineno,
                f"domain must not import {target_layer}: {target}",
            )
    # --- APPLICATION: must not import presentation or infrastructure ---
    elif layer == "application":
        if target_layer == "presentation":
            add(
                "layer",
                filepath,
                lineno,
                f"application must not import presentation: {target}",
            )
        if target_layer == "infrastructure":
            add(
                "layer",
                filepath,
                lineno,
                f"application must not import infrastructure: {target}",
            )
    # --- INFRASTRUCTURE: must not import presentation ---
    #     may import application/interfaces, application/dtos, application/events only
    elif layer == "infrastructure":
        if target_layer == "presentation":
            is_allowed_viz_exception = (
                stem in INFRA_PRESENTATION_VIZ_EXCEPTIONS
                and "presentation.visualization" in target
            )
            if not is_allowed_viz_exception:
                add(
                    "layer",
                    filepath,
                    lineno,
                    f"infrastructure must not import presentation: {target}",
                )
        if target_layer == "application":
            allowed_app = (
                "application/interfaces",
                "application/dtos",
                "application/events",
            )
            if target_sublayer not in allowed_app:
                # Check documented exception
                exception_module = INFRA_APP_SERVICE_EXCEPTIONS.get(stem)
                if not (exception_module and exception_module in target):
                    add(
                        "layer",
                        filepath,
                        lineno,
                        f"infrastructure may only import application/{{interfaces,dtos,events}}: {target}",
                    )
    # --- PRESENTATION: must not import infrastructure ---
    #     allowed to import application and domain (documented)
    elif layer == "presentation":
        if target_layer == "infrastructure":
            add(
                "layer",
                filepath,
                lineno,
                f"presentation must not import infrastructure: {target}",
            )
        # Check application/services imports (only documented exceptions)
        if target_sublayer == "application/services":
            exception_module = PRESENTATION_APP_SERVICE_EXCEPTIONS.get(stem)
            if not (exception_module and exception_module in target):
                add(
                    "layer",
                    filepath,
                    lineno,
                    f"presentation should not import application/services directly: {target}",
                )


# ---------------------------------------------------------------------------
# 2. EventBus rules (AST-based)
# ---------------------------------------------------------------------------
# Heuristic: event_bus.publish() inside a method that is a Thread target
# or inside a class that creates threads is suspicious.
# We check: .publish( must not appear inside files that define Thread targets,
# except through known safe patterns (signal handlers).
PUBLISH_RE = re.compile(
    r"event_bus\.publish\(|_event_bus\.publish\(|\.publish\(AppEvents\."
)
THREAD_TARGET_FILES = {
    # Files known to run code on worker threads
    "transaction_monitor.py",
    "license_validation_scheduler.py",
    "pdf_rendering_service.py",
}


def check_eventbus_publish():
    for py_file in iter_py_files(OST_ROOT):
        if py_file.name not in THREAD_TARGET_FILES:
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(source.splitlines(), 1):
            if PUBLISH_RE.search(line) and not line.strip().startswith("#"):
                add(
                    "eventbus",
                    py_file,
                    i,
                    f"event_bus.publish() in thread-hosting file (must marshal to main thread)",
                )


# ---------------------------------------------------------------------------
# 3. Lifecycle rules (AST-based)
# ---------------------------------------------------------------------------
def check_lifecycle():
    for py_file in iter_py_files(OST_ROOT):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = _base_names(node)
            has_shutdown_aware = "IShutdownAware" in bases
            has_cleanup = any(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "cleanup"
                for item in node.body
            )
            if has_shutdown_aware and has_cleanup:
                add(
                    "lifecycle",
                    py_file,
                    node.lineno,
                    f"class {node.name} implements both cleanup() and IShutdownAware",
                )


def _base_names(classdef: ast.ClassDef) -> set:
    names = set()
    for base in classdef.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


# ---------------------------------------------------------------------------
# 4. Interface naming rules (AST-based)
# ---------------------------------------------------------------------------
ALLOWED_ABCS = {
    "IShutdownAware",
    "IStartable",
    "IAnnotationViewManager",
    "BaseExporter",
}


def check_interface_naming():
    for py_file in iter_py_files(OST_ROOT):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = _base_names(node)
            # Protocol classes must start with I
            if "Protocol" in bases:
                if not node.name.startswith("I"):
                    add(
                        "interface",
                        py_file,
                        node.lineno,
                        f"Protocol class {node.name} must start with 'I'",
                    )
            # ABC only allowed for specific classes
            if "ABC" in bases:
                if node.name not in ALLOWED_ABCS:
                    add(
                        "interface",
                        py_file,
                        node.lineno,
                        f"ABC class {node.name} not in allowed list: {sorted(ALLOWED_ABCS)}",
                    )


# ---------------------------------------------------------------------------
# 5. Logging rules
# ---------------------------------------------------------------------------
# getLogger must be at module level (column 0) or in __init__ (constructor injection).
# Not inside arbitrary methods/functions.
GETLOGGER_RE = re.compile(r"logging\.getLogger\(")
# LoggerFactory is the logging configuration entry point — it wraps getLogger by design.
LOGGING_EXCLUDED_FILES = {"logger_factory.py"}


def check_logging():
    for py_file in iter_py_files(OST_ROOT):
        if py_file.name in LOGGING_EXCLUDED_FILES:
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError):
            continue
        # Collect line ranges for all function/method bodies EXCEPT __init__
        # and module-level code.
        forbidden_ranges = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "__init__":
                    continue  # constructor injection is allowed
                if node.body:
                    start = node.body[0].lineno
                    end = node.end_lineno or node.body[-1].lineno
                    forbidden_ranges.append((start, end))
        lines = source.splitlines()
        for i, line in enumerate(lines, 1):
            if GETLOGGER_RE.search(line) and not line.strip().startswith("#"):
                in_forbidden = any(start <= i <= end for start, end in forbidden_ranges)
                if in_forbidden:
                    add(
                        "logging",
                        py_file,
                        i,
                        "logging.getLogger() inside function body (move to module level or __init__)",
                    )


# ---------------------------------------------------------------------------
# 6. C++ extension rules
# ---------------------------------------------------------------------------
# Canonical .pyd locations from CLAUDE.md
PYD_ALLOWED_DIRS = {
    "ost_geometry": "presentation/visualization/core",
    "ost_renderer": "presentation/components",
    "ost_pdf": "presentation/visualization/pdf",
    "ost_pdf_writer": "presentation/visualization/exporters",
    "ost_earcut": "presentation/visualization/core/geometry",
    "ost_dxf": "presentation/visualization/exporters",
    "ost_image": "presentation/visualization/utils",
    "ost_cab": "presentation/visualization/exporters",
    "ost_winevent": "infrastructure/monitoring",
    "ost_geom_utils": "presentation/components/plan_view/components",
    "ost_snap": "presentation/components/plan_view/components",
    "ost_coord_transform": "domain/services",
    "ost_linear_geom": "presentation/visualization/core/geometry",
}
# C++ modules may only be imported from files within their canonical layer.
# Map module name -> allowed layer prefix for the importing file.
PYD_IMPORT_ALLOWED_LAYER = {}
for mod, dest in PYD_ALLOWED_DIRS.items():
    layer = dest.split("/")[0]
    PYD_IMPORT_ALLOWED_LAYER[mod] = layer
# Infrastructure DI factories that must import C++ modules living in presentation/
CPP_CROSS_LAYER_EXCEPTIONS = {
    "providers",  # imports ost_pdf for PDF page size detection
    "osp_importer",  # imports ost_cab for CAB archive extraction
}
CPP_IMPORT_RE = re.compile(
    r"(?:from\s+\S+\s+import\s+|import\s+)(ost_(?:geometry|renderer|pdf_writer|pdf|"
    r"earcut|dxf|image|cab|winevent|geom_utils|snap|coord_transform|linear_geom))\b"
)


def check_cpp_extensions():
    # Check for duplicate .pyd files
    pyd_locations = defaultdict(list)
    for root, _, files in os.walk(OST_ROOT):
        for f in files:
            if f.endswith(".pyd"):
                full = Path(root) / f
                # Extract module name: ost_foo.cpXXX-win_amd64.pyd -> ost_foo
                mod_name = f.split(".")[0]
                rel_dir = str(Path(root).relative_to(OST_ROOT)).replace("\\", "/")
                pyd_locations[mod_name].append(rel_dir)
    for mod_name, dirs in pyd_locations.items():
        if len(dirs) > 1:
            add(
                "cpp",
                OST_ROOT / "?",
                0,
                f"duplicate .pyd for {mod_name}: found in {dirs}",
            )
        # Check against canonical location
        canonical = PYD_ALLOWED_DIRS.get(mod_name)
        if canonical:
            for d in dirs:
                if d != canonical:
                    pyd_path = OST_ROOT / d / f"{mod_name}.pyd"
                    add(
                        "cpp",
                        pyd_path,
                        0,
                        f"{mod_name}.pyd in {d}, expected {canonical}",
                    )
    # Check imports are from the correct layer
    for py_file in iter_py_files(OST_ROOT):
        file_layer = layer_of(py_file)
        if file_layer in ("config", "other"):
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(source.splitlines(), 1):
            m = CPP_IMPORT_RE.search(line)
            if m:
                mod = m.group(1)
                allowed = PYD_IMPORT_ALLOWED_LAYER.get(mod)
                if allowed and file_layer != allowed:
                    if py_file.stem not in CPP_CROSS_LAYER_EXCEPTIONS:
                        add(
                            "cpp",
                            py_file,
                            i,
                            f"C++ module {mod} imported from {file_layer}/ "
                            f"but .pyd lives in {allowed}/",
                        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    mode = "changed files only" if CHANGED_ONLY else "full scan"
    print(f"Checking architecture in {OST_ROOT} ({mode}) ...\n")
    checks = [
        ("Layer boundaries", check_layer_boundaries),
        ("EventBus rules", check_eventbus_publish),
        ("Lifecycle rules", check_lifecycle),
        ("Interface naming", check_interface_naming),
        ("Logging rules", check_logging),
        ("C++ extensions", check_cpp_extensions),
    ]
    for name, fn in checks:
        count_before = len(violations)
        fn()
        count_after = len(violations)
        found = count_after - count_before
        status = "PASS" if found == 0 else f"FAIL ({found})"
        print(f"  {name}: {status}")
    print()
    if violations:
        by_category = defaultdict(list)
        for v in violations:
            by_category[v.category].append(v)
        for cat, items in sorted(by_category.items()):
            print(f"--- {cat} ({len(items)}) ---")
            for v in items:
                print(f"  {v}")
            print()
        print(f"Total: {len(violations)} violation(s)")
        return 1
    print("No violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
