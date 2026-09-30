import os
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.mdb.importers import (
    osp_importer as osp_importer_module,
)
from ost_visualizer.infrastructure.pdf_metadata_provider import (
    NativePdfMetadataProvider,
)
from tests.paths import TESTS_ROOT

CORPUS_ENV_VAR = "OSTV_PRESENTATION_CORPUS_DIR"
DEFAULT_CORPUS_DIR = TESTS_ROOT / "presentation_corpus"
CORPUS_SUFFIXES = {".ost", ".osp", ".pdf", ".mdb"}


def _corpus_root() -> Path:
    configured = os.environ.get(CORPUS_ENV_VAR)
    return Path(configured) if configured else DEFAULT_CORPUS_DIR


def _relative_corpus_name(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _is_safe_cab_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        return False
    return all(part not in ("", ".", "..") for part in normalized.split("/"))


class PresentationCorpusConventionTests(unittest.TestCase):
    def test_optional_local_corpus_files_have_basic_integrity(self):
        root = _corpus_root()
        if not root.exists():
            self.skipTest(
                f"No presentation corpus directory found. Set {CORPUS_ENV_VAR} "
                f"or create {DEFAULT_CORPUS_DIR.as_posix()} for local corpus runs."
            )
        files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in CORPUS_SUFFIXES
        )
        if not files:
            self.skipTest(f"No supported corpus files found under {root}")
        checked_files = []
        for path in files:
            rel_name = _relative_corpus_name(path, root)
            with self.subTest(corpus_file=rel_name):
                checked_files.append(rel_name)
                suffix = path.suffix.lower()
                if suffix == ".ost":
                    parsed = ET.parse(path)
                    self.assertIsNotNone(parsed.getroot())
                elif suffix == ".osp":
                    names = list(osp_importer_module.ost_cab.list_cab(str(path)))
                    self.assertTrue(names, f"{rel_name} has no CAB members")
                    self.assertTrue(
                        any(name.lower().endswith(".ost") for name in names),
                        f"{rel_name} has no .ost member",
                    )
                    unsafe = [name for name in names if not _is_safe_cab_member(name)]
                    self.assertEqual(unsafe, [])
                elif suffix == ".pdf":
                    info = NativePdfMetadataProvider().get_page_info(str(path), 0)
                    self.assertEqual(info.status, "ok", rel_name)
                    self.assertGreater(info.page_count, 0, rel_name)
                elif suffix == ".mdb":
                    self.assertGreater(path.stat().st_size, 0, rel_name)
        self.assertEqual(len(checked_files), len(files), checked_files)
