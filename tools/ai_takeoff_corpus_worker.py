"""Subprocess worker for tools.ai_takeoff_corpus (one PDF or one page per process).
prepare <pdf> <work dir> <out json>: create a scratch Access bid with one page per
PDF page and write its page records.
sheets <prepared json> <out json>: read every page's sheet number and scale hints
with the app's list_sheets(text_hints=true), so sheet numbers are made
consistent across the PDF as in the app.
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
    PROXY_TIMEOUT_S,
    TextRun,
    spread,
    classify_page,
    page_scale,
    sheet_number,
    text_lines,
    width_bucket,
)

DEFAULT_SCALE = (0.125, 12.0)
MAX_GAP_IN = 36.0
OUTLINED_SYMBOL_SHARE = 0.3
LONG_LINE_PTS = 72.0
MIN_LONG_LINES = 4
EDGE_TOLERANCE_PTS = 1.0
BOX_SHARE_LIMIT = 0.8
FRAME_SHARE = 0.5
TITLE_BLOCK_X = 0.7
TITLE_BLOCK_Y = 0.8
CALLOUT_MIN_RUNS = 10
CALLOUT_MIN_SEGMENTS = 500


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


def _scratch_read_service(prepared: dict, sidecar_dir: str, source, pages=None):
    from ost_visualizer.application.services.ai_takeoff_read_service import (
        AiTakeoffReadService,
    )
    from ost_visualizer.domain.entities.bid import Bid
    from ost_visualizer.domain.entities.database_descriptor import DatabaseDescriptor
    from ost_visualizer.domain.entities.identity_refs import BidRef
    from ost_visualizer.domain.entities.page import build_pages_from_bid_data
    from ost_visualizer.infrastructure.mdb.connection_manager import (
        MdbConnectionManager,
    )
    from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
    from ost_visualizer.infrastructure.persistence.repositories.json_ai_takeoff_sidecar_repository import (
        JsonAiTakeoffSidecarRepository,
    )

    db = prepared["db"]
    if pages is None:
        connections = MdbConnectionManager()
        try:
            records = MdbReader(connections).get_bid_data(db, prepared["bid_uid"])[3]
        finally:
            connections.close()
        pages = list(build_pages_from_bid_data(records, []).values())
    service = AiTakeoffReadService(
        _ScratchProject(
            BidRef(db, prepared["bid_uid"]),
            Bid(uid=prepared["bid_uid"], name="Corpus scratch"),
            pages,
        ),
        source,
        JsonAiTakeoffSidecarRepository(Path(sidecar_dir)),
        {db: DatabaseDescriptor.for_access(db, database_id="corpus")}.get,
    )
    return service, pages


def page_runs(read, snapshot) -> list:
    runs = []
    cursor = None
    while True:
        page = read.list_text(snapshot, cursor=cursor, limit=500)
        for item in page["data"]["runs"]:
            left, top, right, bottom = item["bbox_pts"]
            runs.append(TextRun(item["text"]["value"], left, top, right, bottom))
        cursor = page["meta"].get("next_cursor")
        if not cursor:
            return runs


def page_kind(read, snapshot) -> str:
    lines = text_lines(page_runs(read, snapshot))
    return classify_page(lines, snapshot.width_pts, snapshot.height_pts)[0]


def sheet_hint_row(index: int, hints: dict) -> dict:
    plan = hints["plan_scale"]
    views = Counter(
        candidate["view_kind"] or "none" for candidate in hints["scale_candidates"]
    )
    number = hints["sheet_number"]
    return {
        "index": index,
        "sheet_number": "" if number is None else number["value"],
        "sheet_number_source": hints["sheet_number_source"] or "",
        "text_extractable": hints["text_extractable"],
        "text_reason": hints["reason"] or "",
        "plan_scale_status": plan["status"],
        "plan_scale_label": plan["label"] or "",
        "scale_candidates": len(hints["scale_candidates"]),
        "scale_views": json.dumps(dict(views), sort_keys=True),
        "title_block_crop": bool(hints["title_block_crop_pts"]),
    }


def sheets(prepared: dict, out: Path) -> int:
    from PySide6 import QtWidgets
    from ost_visualizer.presentation.services.ai_takeoff_pdf_source import (
        PageCachePdfSource,
    )
    from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    cache = PageCache()
    sidecars = tempfile.TemporaryDirectory()
    try:
        read, _pages = _scratch_read_service(
            prepared, sidecars.name, PageCachePdfSource(cache)
        )
        order = {page["uid"]: page["index"] for page in prepared["pages"]}
        rows = []
        cursor = None
        while True:
            listed = read.list_sheets(cursor=cursor, text_hints=True)
            hinted = read.sheet_text_hints(listed, read.sheet_hint_snapshots(listed))
            for sheet in hinted["data"]["sheets"]:
                row = sheet_hint_row(order[sheet["page_uid"]], sheet["text_hints"])
                snapshot = read.page_snapshot(sheet["page_uid"])
                row["kind"] = page_kind(read, snapshot) if snapshot.is_pdf else ""
                rows.append(row)
            cursor = listed["meta"].get("next_cursor")
            if not cursor:
                break
    finally:
        cache.clear()
        sidecars.cleanup()
    rows.sort(key=lambda row: row["index"])
    out.write_text(json.dumps(rows), encoding="utf-8")
    return 0


def wall_profile(lines) -> dict:
    from ost_visualizer.domain.services.ai_linework import heavy_width_threshold

    heavy = heavy_width_threshold(lines) if lines else 0.0
    lengths: dict = {}
    counts: Counter = Counter()
    for line in lines:
        if not line.stroked or line.width is None or line.has_dash or line.length < LONG_LINE_PTS:
            continue
        key = round(float(line.width), 2)
        lengths[key] = lengths.get(key, 0.0) + line.length
        counts[key] += 1
    common = [key for key in lengths if counts[key] >= MIN_LONG_LINES]
    walls = [key for key in common if key >= heavy - 1e-9]
    return {
        "dominant_wall_width": max(walls, key=lambda key: lengths[key]) if walls else None,
        "heaviest_long_width": max(common) if common else None,
        "long_width_histogram": json.dumps(
            {str(key): round(value, 1) for key, value in sorted(lengths.items())},
            sort_keys=True,
        ),
    }


def seed_region(regions, k: float, width: float, height: float):
    for region in regions:
        if region_shape(region["polygon_ost"], k, width, height)[1] <= FRAME_SHARE:
            return region
    return None


def removes_dominant(suggested, dominant) -> bool:
    return suggested is not None and dominant is not None and suggested > dominant + 1e-9


def region_shape(polygon_ost, k: float, width: float, height: float) -> tuple:
    points = [(polygon_ost[i] / k, polygon_ost[i + 1] / k) for i in range(0, len(polygon_ost) - 1, 2)]
    if len(points) < 3 or width <= 0.0 or height <= 0.0:
        return False, 0.0
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    touches = (
        min(xs) <= EDGE_TOLERANCE_PTS
        or min(ys) <= EDGE_TOLERANCE_PTS
        or max(xs) >= width - EDGE_TOLERANCE_PTS
        or max(ys) >= height - EDGE_TOLERANCE_PTS
    )
    area = abs(
        sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
    ) / 2.0
    return touches, round(area / (width * height), 4)


def wall_filter_failure(touches: bool, box_ratio: float, segment_count: int) -> bool:
    return touches or box_ratio > BOX_SHARE_LIMIT or segment_count == 0


def drawing_text_runs(runs, width: float, height: float) -> int:
    return sum(
        1
        for run in runs
        if (run.left + run.right) / 2.0 < TITLE_BLOCK_X * width
        and (run.top + run.bottom) / 2.0 < TITLE_BLOCK_Y * height
    )


def _seeded_variant(prefix, proposal, snapshot, whole, seed, min_width, k) -> dict:
    timing, result = _timed(
        lambda: proposal.find_regions(
            snapshot, whole, seed_pts=seed, min_width=min_width, max_gap_in=MAX_GAP_IN
        )
    )
    row = {
        f"{prefix}_status": timing["status"],
        f"{prefix}_seconds": timing["seconds"],
        f"{prefix}_min_width": min_width,
        f"{prefix}_found": False,
    }
    if result is None:
        return row
    data = result["data"]
    segments = data.get("segment_count", 0)
    row[f"{prefix}_segments"] = segments
    if not data["regions"]:
        row[f"{prefix}_wall_failure"] = segments == 0
        return row
    region = data["regions"][0]
    touches, ratio = region_shape(region["polygon_ost"], k, whole[2], whole[3])
    row.update(
        {
            f"{prefix}_found": True,
            f"{prefix}_method": region["method"],
            f"{prefix}_area_sf": region["area_sf"],
            f"{prefix}_touches_edge": touches,
            f"{prefix}_box_ratio": ratio,
            f"{prefix}_leak": region["leak_risk"],
            f"{prefix}_open_gaps": len(region.get("open_gaps") or []),
            f"{prefix}_dashed_outline": region.get("dashed_outline") is not None,
            f"{prefix}_wall_failure": wall_filter_failure(touches, ratio, segments),
        }
    )
    return row


def quadrants(width: float, height: float) -> list:
    half_w, half_h = width / 2.0, height / 2.0
    return [
        (x, y, x + half_w, y + half_h) for y in (0.0, half_h) for x in (0.0, half_w)
    ]


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
    from ost_visualizer.domain.services.ai_linework import (
        classify_linework,
        heavy_width_threshold,
        suggested_min_width,
    )
    from ost_visualizer.domain.services.ai_sheet_text import (
        plan_scale,
        scale_candidates,
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
    row = {"status": "ok"}
    cache = PageCache()
    source = PageCachePdfSource(cache)
    sidecars = tempfile.TemporaryDirectory()
    try:
        read, page_list = _scratch_read_service(prepared, sidecars.name, source)

        def service(pages_now):
            return _scratch_read_service(prepared, sidecars.name, source, pages_now)[0]

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
        runs = page_runs(read, snapshot)
        lines = text_lines(runs)
        kind, title = classify_page(lines, width, height)
        status, legacy_scale, hits = page_scale(lines)
        _text_status, domain_lines = read.page_text_lines(snapshot)
        plan = plan_scale(scale_candidates(domain_lines))
        scale = plan.candidate if plan.status == "resolved" else None
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
            sheet_number_legacy=sheet_number(lines, width, height),
            scale_status=status,
            scale_label="" if legacy_scale is None else legacy_scale.label,
            scale_hits=hits,
            plan_scale_status=plan.status,
            plan_scale_label="" if scale is None else scale.label,
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
        profile = wall_profile(line_items)
        suggested = suggested_min_width(line_items)
        drawing_runs = drawing_text_runs(runs, width, height)
        row.update(
            profile,
            suggested_min_width=suggested,
            suggestion_removes_dominant=removes_dominant(
                suggested, profile["dominant_wall_width"]
            ),
            drawing_text_runs=drawing_runs,
            callouts_as_lines=drawing_runs < CALLOUT_MIN_RUNS
            and len(line_items) >= CALLOUT_MIN_SEGMENTS,
        )
        row["scale_used"] = "default 1/8" if scale is None else scale.label
        row["box_quadrants_truncated"] = ""
        if truncated:
            row["box_quadrants_truncated"] = sum(
                1
                for box in quadrants(width, height)
                if read.page_linework_scoped(snapshot, box)[2]
            )
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
        if listed is not None:
            row.update(
                list_min_width=listed["data"]["filters"]["min_width"],
                list_min_width_source=listed["data"]["filters"]["min_width_source"],
                list_extraction_scope=listed["data"]["extraction_scope"],
            )
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
        elif filtered is not None and seed_region(filtered["data"]["regions"], k, width, height):
            region = seed_region(filtered["data"]["regions"], k, width, height)
            seed = _interior_point(region["polygon_ost"], k)
            row["seed_source"] = "largest_region"
        if seed is None:
            row["seed_status"] = "skipped"
            return row
        row.update(_seeded_variant("default", proposal, snapshot, whole, seed, None, k))
        row.update(_seeded_variant("zero", proposal, snapshot, whole, seed, 0.0, k))
        if profile["heaviest_long_width"] is not None:
            row.update(
                _seeded_variant(
                    "heavy", proposal, snapshot, whole, seed, profile["heaviest_long_width"], k
                )
            )
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
            geometry = proposed["data"]["geometry"]
            row.update(
                proposal_subjects=json.dumps(
                    Counter(item["subject"] for item in proposed["data"]["assumptions"]),
                    sort_keys=True,
                ),
                proposal_assumptions=len(proposed["data"]["assumptions"]),
                proposal_outline_vertices=geometry["outline_vertices"][1],
                proposal_hole_vertices=geometry["hole_vertices"][1],
                proposal_area_change_pct=geometry["area_change_pct"],
                proposal_holes_dropped=geometry["holes_dropped"],
            )
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
    if command == "sheets":
        return sheets(prepared, Path(argv[1]))
    row = measure_page(prepared, argv[1], json.loads(argv[2]))
    row["peak_mb"] = peak_mb()
    Path(argv[3]).write_text(json.dumps(row, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
