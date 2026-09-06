import os
import threading
from collections import OrderedDict
from collections.abc import Iterable
from itertools import count

SourceFileSignature = tuple[int, int, int] | None
_revisions: OrderedDict[str, int] = OrderedDict()
_revision_ids = count(1)
_revision_lock = threading.Lock()
_MAX_SOURCE_REVISIONS = 4096


def _source_revision(file_path: str, *, advance: bool = False) -> int:
    path = os.path.normcase(os.path.abspath(file_path))
    with _revision_lock:
        revision = _revisions.pop(path, None)
        if advance or revision is None:
            revision = next(_revision_ids)
        _revisions[path] = revision
        if len(_revisions) > _MAX_SOURCE_REVISIONS:
            _revisions.popitem(last=False)
        return revision


def invalidate_source_files(file_paths: Iterable[str]) -> None:
    for path in set(file_paths):
        if path:
            _source_revision(path, advance=True)


def source_file_signature(file_path: str) -> SourceFileSignature:
    try:
        stat = os.stat(file_path)
    except OSError:
        return None
    return int(stat.st_mtime_ns), int(stat.st_size), _source_revision(file_path)
