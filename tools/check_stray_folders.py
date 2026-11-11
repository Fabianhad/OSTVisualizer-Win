"""Detect stray folders that a test or mutation run leaves outside its temp dir.
Run it as a script, outside the unit tests, before and after a full test or
mutation run:
    python tools/check_stray_folders.py snapshot --state <file>
    ... run the suite or the mutation sweep ...
    python tools/check_stray_folders.py compare --state <file>
``snapshot`` records the top level of the system drive root (name, kind,
mtime, and size for files), a recursive fingerprint of the three known stray
folders (``T``, ``outside``, ``OSTVTemp``) when they exist, and the number of
``ostv_osp_*`` folders directly inside the real temp folder. ``compare`` takes
a new snapshot and fails (exit code 1) on any new top-level entry, any changed
entry, any known stray folder that is new or whose fingerprint changed, and any
increase of the ``ostv_osp_*`` count. A known stray folder that exists in both
snapshots with an equal fingerprint is not a stray (an old, untouched
``C:\\OSTVTemp`` does not fail the check). Exit code 2 means the script itself
could not run: unreadable or invalid state, unreadable root, a temp folder that
was countable at the snapshot but cannot be read at compare time, or a refused
state path. ``--state`` has no default: the caller picks a file outside every
drive root and outside the repository (``--allow-repo`` lifts only the
repository restriction).
The fingerprint covers the names, kinds, sizes and mtimes of everything under
the folder. The walk is read-only, bounded by ``MAX_FINGERPRINT_ENTRIES``, does
not follow links and uses the extended-length path form on Windows; when the
bound is hit only the first entries (in sorted order) are compared, and
``compare`` prints one warning line to stderr (the exit code is unchanged).
The built-in ignore list (system-managed names such as ``pagefile.sys`` or
``Recovery``) hides only changes of entries that already existed in the
snapshot: such an entry that is new after the snapshot is reported. A name
given with ``--ignore`` is the caller's explicit choice and also hides a new
entry of that name; it never hides a known stray folder.
The tool only reads the scanned root and temp folder. ``--root`` and ``--temp``
replace them (the unit tests use sandboxed folders).
"""

from __future__ import annotations
import argparse
import hashlib
import json
import ntpath
import os
import stat
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_VERSION = 1
TEMP_FOLDER_PREFIX = "ostv_osp_"
MAX_FINGERPRINT_ENTRIES = 20000
# System-managed top-level names whose size or mtime change on their own.
WINDOWS_IGNORED_NAMES = (
    "System Volume Information",
    "$Recycle.Bin",
    "Windows",
    "Users",
    "ProgramData",
    "OneDriveTemp",
    "pagefile.sys",
    "hiberfil.sys",
    "swapfile.sys",
    "DumpStack.log.tmp",
    "Recovery",
    "$AV_ASW",
)
_STRAY_CAUSE = (
    "likely a mutant of ost_visualizer/infrastructure/mdb/importers/osp_importer.py "
    "or a test writing outside its temp dir"
)
# Casefolded name -> cause. Reported when new or when their fingerprint changed.
STRAY_NAMES = {"t": _STRAY_CAUSE, "outside": _STRAY_CAUSE, "ostvtemp": _STRAY_CAUSE}


def system_drive_root(environ=None, windows=None):
    """Return the root to scan: ``<SystemDrive>\\`` on Windows, ``/`` elsewhere."""
    if environ is None:
        environ = os.environ
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return "/"
    drive = ntpath.splitdrive(environ.get("SystemDrive", "C:"))[0] or "C:"
    return drive + "\\"


def ignored_names(extra, windows):
    """Return the casefolded names whose changes are not findings."""
    names = {name.casefold() for name in extra}
    if windows:
        names.update(name.casefold() for name in WINDOWS_IGNORED_NAMES)
    return frozenset(names)


def scan_root(root):
    """Return ``{name: {is_dir, mtime_ns, size}}`` for the entries of ``root``."""
    entries = {}
    for entry in os.scandir(root):
        try:
            info = entry.stat(follow_symlinks=False)
            is_dir = entry.is_dir(follow_symlinks=False)
            entries[entry.name] = {
                "is_dir": is_dir,
                "mtime_ns": info.st_mtime_ns,
                "size": 0 if is_dir else info.st_size,
            }
        except OSError:
            entries[entry.name] = {"is_dir": None, "mtime_ns": 0, "size": 0}
    return entries


def count_osp_folders(temp):
    """Return the number of ``ostv_osp_*`` folders in ``temp``, None if unreadable."""
    try:
        return sum(
            1
            for entry in os.scandir(temp)
            if entry.name.startswith(TEMP_FOLDER_PREFIX) and entry.is_dir()
        )
    except OSError:
        return None


def _long_path(path, windows):
    """Return ``path`` in the extended-length form on Windows."""
    if not windows:
        return path
    path = ntpath.abspath(path)
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def fingerprint_tree(path, limit=MAX_FINGERPRINT_ENTRIES, windows=None):
    """Return ``{entries, truncated, digest}`` for everything under ``path``.
    The digest covers the relative name, kind, size and mtime of ``path`` and of
    every entry below it (sorted, links are recorded but not followed). At most
    ``limit`` entries are read; ``truncated`` tells when more existed.
    """
    if windows is None:
        windows = os.name == "nt"
    digest = hashlib.sha256()
    count = 0
    truncated = False

    def record(relative, kind, size, mtime_ns):
        nonlocal count
        line = f"{relative}\t{kind}\t{size}\t{mtime_ns}\n"
        digest.update(line.encode("utf-8", "surrogatepass"))
        count += 1

    top = _long_path(path, windows)
    try:
        info = os.lstat(top)
    except OSError:
        record(".", "unreadable", 0, 0)
        return {"entries": count, "truncated": False, "digest": digest.hexdigest()}
    is_dir = stat.S_ISDIR(info.st_mode)
    record(
        ".",
        "folder" if is_dir else "file",
        0 if is_dir else info.st_size,
        info.st_mtime_ns,
    )
    pending = [(".", top)] if is_dir else []
    while pending and not truncated:
        relative, folder = pending.pop()
        try:
            with os.scandir(folder) as scan:
                children = sorted(scan, key=lambda child: child.name)
        except OSError:
            record(relative, "unreadable", 0, 0)
            continue
        subfolders = []
        for child in children:
            if count >= limit:
                truncated = True
                break
            name = f"{relative}/{child.name}"
            try:
                # lstat, not the cached DirEntry data: on NTFS the directory
                # listing can hold a stale mtime for a folder that just changed.
                info = os.lstat(child.path)
                if child.is_symlink():
                    kind = "link"
                elif child.is_dir(follow_symlinks=False):
                    kind = "folder"
                    subfolders.append((name, child.path))
                else:
                    kind = "file"
                size = info.st_size if kind == "file" else 0
                record(name, kind, size, info.st_mtime_ns)
            except OSError:
                record(name, "unreadable", 0, 0)
        pending.extend(reversed(subfolders))
    return {"entries": count, "truncated": truncated, "digest": digest.hexdigest()}


def take_snapshot(root, temp):
    entries = scan_root(root)
    return {
        "version": SNAPSHOT_VERSION,
        "root": root,
        "temp": temp,
        "osp_folder_count": count_osp_folders(temp),
        "entries": entries,
        "suspects": {
            name: fingerprint_tree(os.path.join(root, name))
            for name in entries
            if name.casefold() in STRAY_NAMES
        },
    }


def _kind(entry):
    return "folder" if entry["is_dir"] else "file"


def _describe_change(old, new):
    if old["is_dir"] != new["is_dir"]:
        return f"kind {_kind(old)} -> {_kind(new)}"
    parts = []
    if not new["is_dir"] and old["size"] != new["size"]:
        parts.append(f"size {old['size']} -> {new['size']}")
    if old["mtime_ns"] != new["mtime_ns"]:
        parts.append(f"mtime_ns {old['mtime_ns']} -> {new['mtime_ns']}")
    return "; ".join(parts)


def _describe_stray(name, cause, old, new):
    """Return the finding for a known stray folder, None when it is unchanged."""
    if old is None:
        detail = "new since the snapshot"
    elif old != new:
        detail = (
            "content changed since the snapshot (entries counted: "
            f"{old['entries']} -> {new['entries']})"
        )
    else:
        return None
    return f"STRAY top-level entry: {name} ({cause}, {detail})"


def compare_snapshots(before, after, ignored, ignored_new=frozenset()):
    """Return the findings (strings) of ``after`` against ``before``.
    ``ignored`` hides changes of entries that existed before; ``ignored_new``
    (the names given explicitly) hides new entries as well. Known stray folders
    are compared by their fingerprint and can never be ignored.
    """
    findings = []
    old_entries, new_entries = before["entries"], after["entries"]
    for name in sorted(new_entries):
        new = new_entries[name]
        old = old_entries.get(name)
        folded = name.casefold()
        cause = STRAY_NAMES.get(folded)
        if cause is not None:
            finding = _describe_stray(
                name, cause, before["suspects"].get(name), after["suspects"][name]
            )
            if finding:
                findings.append(finding)
        elif folded in ignored_new or (old is not None and folded in ignored):
            continue
        elif old is None:
            findings.append(f"NEW top-level {_kind(new)}: {name}")
        else:
            change = _describe_change(old, new)
            if change:
                findings.append(f"CHANGED top-level entry: {name} ({change})")
    old_count, new_count = before["osp_folder_count"], after["osp_folder_count"]
    if None not in (old_count, new_count) and new_count > old_count:
        findings.append(
            f"{TEMP_FOLDER_PREFIX}* folders in the temp folder increased "
            f"from {old_count} to {new_count}"
        )
    return findings


def _real(path):
    return os.path.normcase(os.path.realpath(path))


def _inside(path, folder):
    path, folder = _real(path), _real(folder)
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:
        return False


def state_path_problem(state, root, repo_root, allow_repo):
    """Return why ``state`` may not be written, or None when it may."""
    state_dir = os.path.dirname(os.path.realpath(state))
    if not os.path.isdir(state_dir):
        return f"the folder of the state file does not exist: {state_dir}"
    if _real(state_dir) == _real(root):
        return (
            "the state file must not be written at the top level of the scanned "
            f"root: {state}"
        )
    typed_dir = os.path.dirname(os.path.abspath(state))
    if any(os.path.dirname(folder) == folder for folder in (typed_dir, state_dir)):
        return (
            "the state file must not be written at the top level of a drive "
            f"root: {state}"
        )
    if not allow_repo and _inside(state_dir, repo_root):
        return (
            "the state file must not be inside the repository "
            f"(use --allow-repo): {state}"
        )
    return None


def _is_number(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_entry(entry):
    return (
        isinstance(entry, dict)
        and "is_dir" in entry
        and (entry["is_dir"] is None or isinstance(entry["is_dir"], bool))
        and _is_number(entry.get("mtime_ns"))
        and _is_number(entry.get("size"))
    )


def _valid_fingerprint(entry):
    return (
        isinstance(entry, dict)
        and _is_number(entry.get("entries"))
        and isinstance(entry.get("truncated"), bool)
        and isinstance(entry.get("digest"), str)
    )


def _load_state(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    valid = (
        isinstance(data, dict)
        and data.get("version") == SNAPSHOT_VERSION
        and isinstance(data.get("root"), str)
        and isinstance(data.get("temp"), str)
        and "osp_folder_count" in data
        and (data["osp_folder_count"] is None or _is_number(data["osp_folder_count"]))
        and isinstance(data.get("entries"), dict)
        and all(_valid_entry(entry) for entry in data["entries"].values())
        and isinstance(data.get("suspects"), dict)
        and all(_valid_fingerprint(entry) for entry in data["suspects"].values())
    )
    if not valid:
        raise ValueError("unexpected structure")
    return data


def _same_place(left, right):
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def _error(message):
    print(f"check_stray_folders: {message}", file=sys.stderr)
    return 2


def _snapshot_command(args, root, temp, repo_root):
    problem = state_path_problem(args.state, root, repo_root, args.allow_repo)
    if problem:
        return _error(problem)
    try:
        snap = take_snapshot(root, temp)
    except OSError as exc:
        return _error(f"cannot scan {root}: {exc}")
    text = json.dumps(snap, indent=1, sort_keys=True)  # before the file is created
    try:
        with open(args.state, "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError as exc:
        return _error(f"cannot write the state file {args.state}: {exc}")
    count = snap["osp_folder_count"]
    counted = (
        f"{TEMP_FOLDER_PREFIX}* folders unreadable"
        if count is None
        else f"{count} {TEMP_FOLDER_PREFIX}* folders"
    )
    print(
        f"snapshot written to {args.state}: {len(snap['entries'])} top-level "
        f"entries, {counted}"
    )
    return 0


def _truncation_warning(before, after):
    """Return a warning when a fingerprint hit its bound, else None."""
    bounds = [
        fingerprint["entries"]
        for snap in (before, after)
        for fingerprint in snap["suspects"].values()
        if fingerprint["truncated"]
    ]
    if not bounds:
        return None
    return (
        f"fingerprint truncated at {max(bounds)} entries: changes beyond are "
        "not detected"
    )


def _compare_command(args, root, temp, ignored):
    try:
        before = _load_state(args.state)
    except OSError as exc:
        return _error(f"cannot read the state file {args.state}: {exc}")
    except ValueError as exc:
        return _error(f"{args.state} is not a valid snapshot: {exc}")
    if not (_same_place(before["root"], root) and _same_place(before["temp"], temp)):
        return _error(
            f"the state file was taken for root {before['root']} and temp "
            f"{before['temp']}, not for root {root} and temp {temp}"
        )
    try:
        after = take_snapshot(root, temp)
    except OSError as exc:
        return _error(f"cannot scan {root}: {exc}")
    if before["osp_folder_count"] is not None and after["osp_folder_count"] is None:
        return _error(
            f"cannot read the temp folder {temp}: the snapshot counted "
            f"{before['osp_folder_count']} {TEMP_FOLDER_PREFIX}* folders"
        )
    warning = _truncation_warning(before, after)
    if warning:
        print(f"check_stray_folders: {warning}", file=sys.stderr)
    explicit = frozenset(name.casefold() for name in args.ignore)
    findings = compare_snapshots(before, after, ignored, explicit)
    if not findings:
        print("no stray folders")
        return 0
    for finding in findings:
        print(finding)
    print(f"{len(findings)} stray finding(s)")
    return 1


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("snapshot", "record the drive root top level and the ostv_osp_* count"),
        ("compare", "fail when the drive root or temp folder gained strays"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--state", required=True, help="JSON state file")
        command.add_argument("--root", help="folder to scan (default: system drive)")
        command.add_argument("--temp", help="temp folder (default: the real one)")
        command.add_argument(
            "--ignore",
            action="append",
            default=[],
            metavar="NAME",
            help="top-level name to ignore (repeatable)",
        )
        command.add_argument(
            "--allow-repo",
            action="store_true",
            help="allow the state file inside the repository",
        )
    return parser


def main(argv=None, windows=None, repo_root=None):
    args = _parser().parse_args(argv)
    if windows is None:
        windows = os.name == "nt"
    root = args.root or system_drive_root(os.environ, windows)
    temp = args.temp or tempfile.gettempdir()
    if args.command == "snapshot":
        return _snapshot_command(args, root, temp, repo_root or REPO_ROOT)
    return _compare_command(args, root, temp, ignored_names(args.ignore, windows))


if __name__ == "__main__":
    raise SystemExit(main())
