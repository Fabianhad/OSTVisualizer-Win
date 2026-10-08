"""Subprocess worker for tools.ai_takeoff_corpus (one PDF or one page per process).
prepare <pdf> <work dir> <out json>: create a scratch Access bid with one page per
PDF page and write its page records.
page <prepared json> <page uid> <seeds json> <out json>: measure one page with the
app's AI takeoff read service and proposal service over that bid. Only read
calls and propose_element run; nothing is applied. The output holds metrics,
the sheet number and the sheet title only.
"""

import ctypes
import json
import math
import os
import sys
import tempfile
import time
from collections import Counter
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tools.ai_takeoff_corpus import (
    KIND_PLAN,
    TextRun,
    classify_page,
    page_scale,
    sheet_number,
    text_lines,
    width_bucket,
)

DEFAULT_SCALE = (0.125, 12.0)
MAX_GAP_IN = 36.0
OUTLINED_SYMBOL_SHARE = 0.3


class _Counters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def peak_mb() -> float:
    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL("psapi")
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_Counters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    )
    return round(counters.PeakWorkingSetSize / (1024.0 * 1024.0), 1)


def prepare(pdf: Path, work: Path, out: Path) -> int:
    import tests.helpers.mdb.schema_support as access
    from ost_visualizer.presentation.visualization.pdf import ost_pdf

    renderer = ost_pdf.PDFRenderer()
    if not renderer.open(str(pdf)):
        raise RuntimeError("PDF did not open")
    try:
        infos = list(renderer.all_page_info())
    finally:
        renderer.close()
    db = work / f"{pdf.stem}.mdb"
    if db.exists():
        db.unlink()
    if not access.DatabaseCreator().create_database(db, "CorpusScratch"):
        raise RuntimeError("scratch Access database was not created")
    connections = access.MdbConnectionManager()
    try:
        writer = access.MdbWriter(connections)
        bid_uid = writer.create_bid(
            str(db),
            None,
            {
                "job_name": "Corpus scratch",
                "pages": [
                    dict(
                        name=f"Page {index + 1}",
                        width=info.effective_width_pts / 72.0,
                        height=info.effective_height_pts / 72.0,
                        scale_factor1=DEFAULT_SCALE[0],
                        scale_factor2=DEFAULT_SCALE[1],
                        image_path=str(pdf),
                        index=index + 1,
                    )
                    for index, info in enumerate(infos)
                ],
            },
        )
        pages = access.MdbReader(connections).get_bid_data(str(db), bid_uid)[3]
    finally:
        connections.close()
    records = sorted(
        (
            {"uid": str(uid), "index": int(page.page_index)}
            for uid, page in pages.items()
        ),
        key=lambda item: item["index"],
    )
    out.write_text(
        json.dumps(
            {"db": str(db), "bid_uid": str(bid_uid), "pdf": str(pdf), "pages": records}
        ),
        encoding="utf-8",
    )
    return 0


class _ScratchProject:
    def __init__(self, bid_ref, bid, pages):
        self._bid_ref = bid_ref
        self._bid = bid
        self._pages = pages

    def get_current_bid_ref(self):
        return self._bid_ref

    def get_current_bid(self):
        return self._bid

    def get_all_pages(self):
        return list(self._pages)

    def get_page(self, page_uid):
        return next((page for page in self._pages if page.uid == page_uid), None)

    def get_bid_conditions(self):
        return {}

    def get_all_takeoffs(self):
        return []

    def get_page_takeoffs(self, page_uid):
        return []


def _timed(call):
    started = time.perf_counter()
    try:
        result = call()
    except Exception as exc:
        code = _error_code(exc)
        return {
            "status": code,
            "seconds": round(time.perf_counter() - started, 3),
        }, None
    return {
        "status": result["status"],
        "seconds": round(time.perf_counter() - started, 3),
    }, result


def _error_code(exc) -> str:
    from ost_visualizer.application.dtos.ai_takeoff_dtos import AiTakeoffRequestError

    if isinstance(exc, AiTakeoffRequestError):
        return exc.code
    return f"exception:{type(exc).__name__}"


def _region_summary(prefix: str, timing: dict, result) -> dict:
    data = {} if result is None else result["data"]
    regions = data.get("regions", [])
    return {
        f"{prefix}_status": timing["status"],
        f"{prefix}_seconds": timing["seconds"],
        f"{prefix}_regions": data.get("total_count", len(regions)),
        f"{prefix}_leaks": sum(1 for region in regions if region["leak_risk"]),
        f"{prefix}_gaps": sum(len(region["gaps"]) for region in regions),
        f"{prefix}_suppressed": data.get("suppressed_symbol_count", ""),
        f"{prefix}_excluded": json.dumps(data.get("excluded", {}), sort_keys=True),
    }


def _interior_point(polygon_ost, k):
    from ost_visualizer.domain.services.ai_planar_regions import point_in_ring

    ring = [
        (polygon_ost[i] / k, polygon_ost[i + 1] / k)
        for i in range(0, len(polygon_ost), 2)
    ]
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    steps = sorted((index + 0.5) / 20.0 for index in range(20))
    steps.sort(key=lambda value: abs(value - 0.5))
    for fx in steps:
        for fy in steps:
            point = (
                min(xs) + fx * (max(xs) - min(xs)),
                min(ys) + fy * (max(ys) - min(ys)),
            )
            if point_in_ring(point, ring):
                return [point[0], point[1]]
    return None


def measure_page(prepared: dict, page_uid: str, seeds: list) -> dict:
    from PySide6 import QtWidgets
    from ost_visualizer.application.services.ai_changeset_store import (
        AiChangesetProposals,
        AiChangesetStore,
    )
    from ost_visualizer.application.services.ai_takeoff_proposal_service import (
        AiTakeoffProposalService,
    )
    from ost_visualizer.application.services.ai_takeoff_read_service import (
        AiTakeoffReadService,
    )
    from ost_visualizer.domain.entities.bid import Bid
    from ost_visualizer.domain.entities.database_descriptor import DatabaseDescriptor
    from ost_visualizer.domain.entities.identity_refs import BidRef
    from ost_visualizer.domain.entities.page import build_pages_from_bid_data
    from ost_visualizer.domain.services.ai_linework import (
        classify_linework,
        heavy_width_threshold,
    )
    from ost_visualizer.infrastructure.mdb.connection_manager import (
        MdbConnectionManager,
    )
    from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
    from ost_visualizer.infrastructure.persistence.repositories.json_ai_takeoff_sidecar_repository import (
        JsonAiTakeoffSidecarRepository,
    )
    from ost_visualizer.presentation.services.ai_region_raster import raster_fill_region
    from ost_visualizer.presentation.services.ai_takeoff_pdf_source import (
        PageCachePdfSource,
    )
    from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
    from ost_visualizer.presentation.visualization.pdf.pdf_visible_origin import (
        read_visible_box_origin,
    )
    from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    db = prepared["db"]
    connections = MdbConnectionManager()
    try:
        pages = MdbReader(connections).get_bid_data(db, prepared["bid_uid"])[3]
    finally:
        connections.close()
    page_list = list(build_pages_from_bid_data(pages, []).values())
    row = {"status": "ok"}
    cache = PageCache()
    source = PageCachePdfSource(cache)
    sidecars = tempfile.TemporaryDirectory()
    try:
        bid_ref = BidRef(db, prepared["bid_uid"])

        def service(pages_now):
            return AiTakeoffReadService(
                _ScratchProject(
                    bid_ref,
                    Bid(uid=prepared["bid_uid"], name="Corpus scratch"),
                    pages_now,
                ),
                source,
                JsonAiTakeoffSidecarRepository(Path(sidecars.name)),
                {db: DatabaseDescriptor.for_access(db, database_id="corpus")}.get,
            )

        read = service(page_list)
        snapshot = read.page_snapshot(page_uid)
        info = source.get_page_info(snapshot.image_path, snapshot.page_index)
        width, height = snapshot.width_pts, snapshot.height_pts
        origin = read_visible_box_origin(
            snapshot.image_path, snapshot.page_index, ost_pdf_writer.PDFWriter
        )
        row.update(
            width_pts=round(width, 1),
            height_pts=round(height, 1),
            rotation=info.intrinsic_rotation,
            visible_offset=(
                "yes" if any(abs(value) > 0.01 for value in origin) else "no"
            ),
            page_size_class=_size_class(width, height),
        )
        raw_runs = source.get_text_runs(snapshot.image_path, snapshot.page_index)
        runs = []
        cursor = None
        while True:
            page = read.list_text(snapshot, cursor=cursor, limit=500)
            for item in page["data"]["runs"]:
                left, top, right, bottom = item["bbox_pts"]
                runs.append(TextRun(item["text"]["value"], left, top, right, bottom))
            cursor = page["meta"].get("next_cursor")
            if not cursor:
                break
        lines = text_lines(runs)
        kind, title = classify_page(lines, width, height)
        status, scale, hits = page_scale(lines)
        status_code, linework, truncated = read.page_linework(snapshot)
        line_items = [line for _segment_id, line in linework]
        kinds = classify_linework(line_items)
        kind_counts = Counter(kinds)
        symbol_share = kind_counts["symbol"] / max(1, len(line_items))
        row.update(
            text_runs=len(raw_runs),
            segments=len(line_items),
            curves=sum(1 for line in line_items if line.curve),
            extraction_truncated=truncated,
            content=_content(len(line_items), len(raw_runs)),
            outlined_text=len(raw_runs) == 0 and symbol_share >= OUTLINED_SYMBOL_SHARE,
            kind=kind,
            title=title[:80],
            sheet_number=sheet_number(lines, width, height),
            scale_status=status,
            scale_label="" if scale is None else scale.label,
            scale_hits=hits,
            kinds_wall=kind_counts["wall"],
            kinds_dashed=kind_counts["dashed"],
            kinds_thin=kind_counts["thin"],
            kinds_symbol=kind_counts["symbol"],
            dash_arrays=sum(1 for line in line_items if line.has_dash),
            widths=json.dumps(
                Counter(width_bucket(line.width) for line in line_items), sort_keys=True
            ),
            heavy_threshold=round(heavy_width_threshold(line_items), 3),
        )
        if kind != KIND_PLAN or not line_items:
            row.update(
                list_status="skipped", filtered_status="skipped", seed_status="skipped"
            )
            return row
        row["scale_used"] = "default 1/8" if scale is None else scale.label
        if scale is not None and scale.ost_per_point:
            page_list = [
                (
                    replace(page, scale_factor1=scale.sf1, scale_factor2=scale.sf2)
                    if page.uid == page_uid
                    else page
                )
                for page in page_list
            ]
            read = service(page_list)
            snapshot = read.page_snapshot(page_uid)
        k = snapshot.ost_per_page_point
        proposal = AiTakeoffProposalService(
            read, AiChangesetProposals(AiChangesetStore()), [], raster_fill_region
        )
        whole = [0.0, 0.0, width, height]
        timing, listed = _timed(
            lambda: proposal.find_regions(snapshot, whole, limit=50)
        )
        row.update(_region_summary("list", timing, listed))
        threshold = heavy_width_threshold(line_items)
        timing, filtered = _timed(
            lambda: proposal.find_regions(
                snapshot, whole, min_width=threshold, max_gap_in=MAX_GAP_IN, limit=50
            )
        )
        row.update(_region_summary("filtered", timing, filtered))
        seed = None
        expected = None
        if seeds:
            seed = seeds[0]["seed_pts"]
            expected = seeds[0]["expected_sf"]
            row["seed_source"] = "hand"
        elif filtered is not None and filtered["data"]["regions"]:
            seed = _interior_point(filtered["data"]["regions"][0]["polygon_ost"], k)
            row["seed_source"] = "largest_region"
        if seed is None:
            row["seed_status"] = "skipped"
            return row
        timing, seeded = _timed(
            lambda: proposal.find_regions(
                snapshot,
                whole,
                seed_pts=seed,
                min_width=threshold,
                max_gap_in=MAX_GAP_IN,
            )
        )
        row.update(seed_status=timing["status"], seed_seconds=timing["seconds"])
        if seeded is None or not seeded["data"]["regions"]:
            return row
        region = seeded["data"]["regions"][0]
        row.update(
            seed_method=region["method"],
            seed_area_sf=region["area_sf"],
            seed_gaps=len(region["gaps"]),
            seed_leak=region["leak_risk"],
            seed_unlocated=region.get("unlocated_gaps_up_to_in"),
        )
        if expected:
            row.update(
                hand_expected_sf=expected,
                hand_error_pct=round(
                    (region["area_sf"] - expected) / expected * 100.0, 3
                ),
            )
        timing, proposed = _timed(
            lambda: proposal.propose_element(
                "slab",
                page_uid,
                region_id=region["id"],
                thickness_in=4.0,
                top_elev_in=0.0,
            )
        )
        row["proposal_status"] = timing["status"]
        if proposed is not None:
            row["proposal_assumptions"] = len(proposed["data"]["assumptions"])
        return row
    finally:
        cache.clear()
        sidecars.cleanup()


def _content(segments: int, runs: int) -> str:
    if segments and runs:
        return "vector_and_text"
    if segments:
        return "vector"
    if runs:
        return "text_only"
    return "raster_only"


def _size_class(width: float, height: float) -> str:
    long_side, short_side = max(width, height) / 72.0, min(width, height) / 72.0
    for label, size in (
        ("ARCH E1 30x42", (42, 30)),
        ("ARCH D 24x36", (36, 24)),
        ("ARCH E 36x48", (48, 36)),
        ("ANSI D 22x34", (34, 22)),
        ("Tabloid 11x17", (17, 11)),
        ("Letter", (11, 8.5)),
    ):
        if math.isclose(long_side, size[0], abs_tol=0.6) and math.isclose(
            short_side, size[1], abs_tol=0.6
        ):
            return label
    return f"other {long_side:.0f}x{short_side:.0f}"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv.pop(0)
    if command == "prepare":
        return prepare(Path(argv[0]), Path(argv[1]), Path(argv[2]))
    prepared = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    row = measure_page(prepared, argv[1], json.loads(argv[2]))
    row["peak_mb"] = peak_mb()
    Path(argv[3]).write_text(json.dumps(row, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
