import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.domain.entities.ai_takeoff import (
    SIDECAR_LOAD_CORRUPT,
    SIDECAR_LOAD_FOUND,
    SIDECAR_LOAD_MISSING,
    SIDECAR_SCHEMA_VERSION,
    AiTakeoffSidecar,
)
from ost_visualizer.infrastructure.persistence.repositories.json_ai_takeoff_sidecar_repository import (
    MAX_SIDECAR_BYTES,
    JsonAiTakeoffSidecarRepository,
)

KEY = "0123456789abcdef0123456789abcdef"


def _valid(bid_key=KEY):
    return {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "bid_key": bid_key,
        "fingerprint": {
            "database_id": "db-1",
            "bid_name": "Tower",
            "page_count": 2,
            "first_page_pdf_source": "S-101.pdf",
        },
        "levels": [],
        "registrations": [],
        "assumptions": [],
    }


class JsonAiTakeoffSidecarRepositoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name) / "bids"
        self.repository = JsonAiTakeoffSidecarRepository(self.directory)

    def write(self, content, key=KEY):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{key}.json"
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(json.dumps(content), encoding="utf-8")
        return path

    def assert_untouched(self, path, before_bytes, before_mtime):
        self.assertEqual(path.read_bytes(), before_bytes)
        self.assertEqual(os.stat(path).st_mtime_ns, before_mtime)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), [path.name])

    def test_missing_file_and_missing_directory(self):
        result = self.repository.load(KEY)
        self.assertEqual(result.state, SIDECAR_LOAD_MISSING)
        self.assertIsNone(result.sidecar)
        self.assertFalse(self.directory.exists())

    def test_valid_file_is_found(self):
        self.write(_valid())
        result = self.repository.load(KEY)
        self.assertEqual(result.state, SIDECAR_LOAD_FOUND)
        self.assertEqual(result.sidecar.fingerprint.bid_name, "Tower")

    def test_corrupt_files_are_reported_and_never_rewritten(self):
        cases = {
            "not json": b"{not json",
            "not utf8": b"\xff\xfe\x00",
            "wrong schema": json.dumps(dict(_valid(), schema_version=99)).encode(),
            "other bid key inside": json.dumps(_valid(bid_key="f" * 32)).encode(),
            "invalid shape": json.dumps({"schema_version": 1}).encode(),
            "too large": b" " * (MAX_SIDECAR_BYTES + 1),
            "valid json over the size cap": json.dumps(_valid()).encode()
            + b" " * MAX_SIDECAR_BYTES,
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                path = self.write(content)
                before = path.read_bytes()
                mtime = os.stat(path).st_mtime_ns
                result = self.repository.load(KEY)
                self.assertEqual(result.state, SIDECAR_LOAD_CORRUPT)
                self.assertIsNone(result.sidecar)
                self.assert_untouched(path, before, mtime)

    def test_found_files_are_never_rewritten(self):
        path = self.write(_valid())
        before = path.read_bytes()
        mtime = os.stat(path).st_mtime_ns
        for _ in range(3):
            self.repository.load(KEY)
        self.assert_untouched(path, before, mtime)

    def test_keys_that_could_escape_the_directory_are_rejected(self):
        for key in ("../" + KEY[:29], KEY.upper(), KEY[:31], "", "a" * 33, "..\\x"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.repository.load(key)

    def test_repository_offers_only_load_and_save(self):
        public = {name for name in dir(self.repository) if not name.startswith("_")}
        self.assertEqual(public, {"load", "save"})


class JsonAiTakeoffSidecarSaveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name) / "bids"
        self.repository = JsonAiTakeoffSidecarRepository(self.directory)
        self.sidecar = AiTakeoffSidecar.from_dict(_valid())

    def test_save_round_trips_atomically_without_leftovers(self):
        self.repository.save(self.sidecar)
        self.assertEqual(
            sorted(p.name for p in self.directory.iterdir()), [f"{KEY}.json"]
        )
        loaded = self.repository.load(KEY)
        self.assertEqual(
            (loaded.state, loaded.sidecar), (SIDECAR_LOAD_FOUND, self.sidecar)
        )
        data = json.loads((self.directory / f"{KEY}.json").read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)

    def test_a_failed_replace_keeps_the_previous_file_and_removes_the_temp(self):
        self.repository.save(self.sidecar)
        before = (self.directory / f"{KEY}.json").read_bytes()
        changed = AiTakeoffSidecar.from_dict(
            dict(
                _valid(), levels=[{"uid": "L1", "name": "Changed", "top_elev_in": 1.0}]
            )
        )
        with patch("os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.repository.save(changed)
        self.assertEqual((self.directory / f"{KEY}.json").read_bytes(), before)
        self.assertEqual(
            sorted(p.name for p in self.directory.iterdir()), [f"{KEY}.json"]
        )

    def test_invalid_keys_and_oversized_sidecars_are_refused(self):
        from dataclasses import replace

        with self.assertRaises(ValueError):
            self.repository.save(replace(self.sidecar, bid_key="../x"))
        huge = AiTakeoffSidecar.from_dict(
            dict(
                _valid(),
                levels=[
                    {"uid": f"L{index}", "name": "x" * 2000, "top_elev_in": 1.0}
                    for index in range(3000)
                ],
            )
        )
        with self.assertRaises(ValueError):
            self.repository.save(huge)
        self.assertFalse(self.directory.exists())


if __name__ == "__main__":
    unittest.main()
