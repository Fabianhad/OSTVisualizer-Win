from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ost_visualizer.infrastructure.windows.file_associations import (  # noqa: E402
    FileAssociationRegistrar,
    FileAssociationRegistryError,
)


def _default_executable() -> Path:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        packaged = ROOT / "dist_visualizer" / "Visualizer.dist" / "Visualizer.exe"
        if packaged.exists():
            return packaged
    return exe


def _default_script_path(executable: Path) -> Path | None:
    if executable.name.lower() != "python.exe":
        return None
    script = ROOT / "Visualizer.py"
    return script if script.exists() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register OST Visualizer .ost and .osp file associations for "
            "development or manual repair."
        )
    )
    parser.add_argument("--unregister", action="store_true")
    parser.add_argument("--exe", type=Path, default=None)
    parser.add_argument("--script", type=Path, default=None)
    args = parser.parse_args(argv)
    executable = args.exe or _default_executable()
    script_path = (
        args.script if args.script is not None else _default_script_path(executable)
    )
    registrar = FileAssociationRegistrar(
        executable_path=executable,
        app_script_path=script_path,
    )
    try:
        if args.unregister:
            registrar.unregister()
            print("Removed OST Visualizer file associations.")
        else:
            registrar.register()
            print(f"Registered OST Visualizer file associations for {executable}.")
    except (FileAssociationRegistryError, OSError) as exc:
        print(f"File association registration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
