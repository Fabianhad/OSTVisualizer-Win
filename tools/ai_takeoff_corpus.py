"""Offline corpus harness for the AI takeoff tools (measurement only).
Confidentiality: the corpus is client drawings. This tool never writes to the
source share, copies sampled files to a local folder outside the repository
(default %LOCALAPPDATA%\\ostv_corpus), and its CSV and report contain only
metrics, relative paths, page numbers, sheet numbers and sheet titles.
Commands (run from the repository root with the repo venv):
  python -m tools.ai_takeoff_corpus inventory --source <share root>
  python -m tools.ai_takeoff_corpus sample --source <share root> [--count 30]
  python -m tools.ai_takeoff_corpus run [--timeout 180]
  python -m tools.ai_takeoff_corpus report --run <run csv>
Each page is measured by tools.ai_takeoff_corpus_worker in its own subprocess
with a timeout, against a scratch Access bid created for the PDF. Only read
tools and propose_* are called; apply_changeset is never called.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ostv_corpus"
STRUCTURAL_PARTS = ("01. Drawings", "1. Drawings", "3. Structural")
YEARS = tuple(str(year) for year in range(2023, 2028))
HAND_VALUE_COLUMNS = ("pdf", "page", "seed_x", "seed_y", "expected_sf")
TITLE_BLOCK_X = 0.70
TITLE_BLOCK_Y = 0.75
LINE_TOLERANCE_FRACTION = 0.5
KIND_PLAN = "plan"
KIND_SECTION = "section"
KIND_DETAIL = "detail"
KIND_SCHEDULE = "schedule"
KIND_NOTES = "general_notes"
KIND_ELEVATION = "elevation"
KIND_UNKNOWN = "unknown"
PAGE_KINDS = (
    KIND_PLAN,
    KIND_SECTION,
    KIND_DETAIL,
    KIND_SCHEDULE,
    KIND_NOTES,
    KIND_ELEVATION,
)
_KIND_PATTERNS = (
    (
        KIND_NOTES,
        re.compile(
            r"\b(GENERAL\s+(STRUCTURAL\s+)?NOTES|STRUCTURAL\s+NOTES|SPECIFICATIONS)\b"
        ),
    ),
    (KIND_SCHEDULE, re.compile(r"\bSCHEDULES?\b")),
    (KIND_PLAN, re.compile(r"\bPLANS?\b")),
    (KIND_SECTION, re.compile(r"\bSECTIONS?\b")),
    (KIND_DETAIL, re.compile(r"\bDETAILS?\b")),
    (KIND_ELEVATION, re.compile(r"\bELEVATIONS?\b")),
)
_KIND_ORDER = {kind: index for index, kind in enumerate(PAGE_KINDS)}
_SHEET_PATTERN = re.compile(r"\b(S[A-Z]?|PS)\s*-?\s*(\d{1,3}(?:\.\d{1,2})?[A-Z]?)\b")
_FRACTION = r"(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)|(\d+(?:\.\d+)?)"
_INCH = r"\s*(?:\"|''|”|″|IN\.?)"
_FOOT = r"\s*(?:'|’|′|FT\.?)"
_ARCH_SCALE = re.compile(
    rf"(?:{_FRACTION}){_INCH}\s*=\s*1{_FOOT}(?:\s*-?\s*0{_INCH}?)?", re.IGNORECASE
)
_ENGINEER_SCALE = re.compile(
    rf"\b1{_INCH}\s*=\s*(\d+(?:\.\d+)?){_FOOT}(?:\s*-?\s*0{_INCH}?)?", re.IGNORECASE
)
_NTS = re.compile(r"\bN\.?\s*T\.?\s*S\b\.?|\bNOT\s+TO\s+SCALE\b", re.IGNORECASE)
_GRAPHIC = re.compile(r"\bGRAPHIC\s+SCALE\b", re.IGNORECASE)
_FILE_PATTERNS = (
    ("S-###", re.compile(r"^S-\d", re.IGNORECASE)),
    ("S#.#", re.compile(r"^S\d+\.\d", re.IGNORECASE)),
    ("S###", re.compile(r"^S\d", re.IGNORECASE)),
    ("set", re.compile(r"(STRUCT|SET|DRAWINGS|PERMIT|BID|IFC|CD)", re.IGNORECASE)),
)
WIDTH_BUCKETS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)


@dataclass(frozen=True)
class TextRun:
    text: str
    left: float
    top: float
    right: float
    bottom: float

    @property
    def height(self) -> float:
        return abs(self.bottom - self.top)


@dataclass(frozen=True)
class TextLine:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    height: float


@dataclass(frozen=True)
class ScaleHit:
    label: str
    sf1: Optional[float]
    sf2: Optional[float]

    @property
    def ost_per_point(self) -> Optional[float]:
        if not self.sf1 or not self.sf2:
            return None
        return self.sf2 / (72.0 * self.sf1)


def text_lines(runs: Sequence[TextRun]) -> List[TextLine]:
    ordered = sorted(runs, key=lambda run: ((run.top + run.bottom) / 2.0, run.left))
    lines: List[List[TextRun]] = []
    for run in ordered:
        middle = (run.top + run.bottom) / 2.0
        if lines:
            last = lines[-1]
            last_middle = sum((r.top + r.bottom) / 2.0 for r in last) / len(last)
            tolerance = LINE_TOLERANCE_FRACTION * max(
                max(r.height for r in last), run.height, 1e-6
            )
            if abs(middle - last_middle) <= tolerance:
                last.append(run)
                continue
        lines.append([run])
    result = []
    for line in lines:
        line.sort(key=lambda run: run.left)
        result.append(
            TextLine(
                " ".join(run.text.strip() for run in line if run.text.strip()),
                min(run.left for run in line),
                min(run.top for run in line),
                max(run.right for run in line),
                max(run.bottom for run in line),
                max(run.height for run in line),
            )
        )
    return [line for line in result if line.text]


def in_title_block(line: TextLine, width: float, height: float) -> bool:
    if width <= 0.0 or height <= 0.0:
        return False
    return line.left >= TITLE_BLOCK_X * width or line.top >= TITLE_BLOCK_Y * height


def classify_page(
    lines: Sequence[TextLine], width: float, height: float
) -> Tuple[str, str]:
    scores: Dict[str, float] = defaultdict(float)
    titles: Dict[str, Tuple[float, str]] = {}
    for line in lines:
        upper = line.text.upper()
        weight = 3.0 if in_title_block(line, width, height) else 1.0
        for kind, pattern in _KIND_PATTERNS:
            if pattern.search(upper):
                scores[kind] += weight
                if weight > 1.0 and len(upper) <= 80:
                    best = titles.get(kind)
                    if best is None or line.height > best[0]:
                        titles[kind] = (line.height, upper)
                break
    if not scores:
        return KIND_UNKNOWN, ""
    kind = max(scores, key=lambda key: (scores[key], -_KIND_ORDER[key]))
    return kind, titles.get(kind, (0.0, ""))[1]


def sheet_number(lines: Sequence[TextLine], width: float, height: float) -> str:
    best: Optional[Tuple[float, float, str]] = None
    for line in lines:
        upper = line.text.upper()
        for match in _SHEET_PATTERN.finditer(upper):
            if len(upper) > 24 and match.group(0) != upper.strip():
                continue
            label = (
                f"{match.group(1)}-{match.group(2)}"
                if "-" in match.group(0)
                else f"{match.group(1)}{match.group(2)}"
            )
            key = (1.0 if in_title_block(line, width, height) else 0.0, line.height)
            if best is None or key > best[:2]:
                best = (key[0], key[1], label)
    return "" if best is None else best[2]


def _fraction_value(whole, numerator, denominator, decimal) -> Optional[float]:
    if decimal is not None:
        return float(decimal)
    value = float(numerator) / float(denominator) if float(denominator) else 0.0
    return value + (float(whole) if whole else 0.0)


def parse_scales(text: str) -> List[ScaleHit]:
    hits = []
    for match in _ARCH_SCALE.finditer(text):
        value = _fraction_value(*match.groups()[:4])
        if value and value > 0.0:
            hits.append(ScaleHit(f'{_fraction_label(match)}"=1\'-0"', value, 12.0))
    for match in _ENGINEER_SCALE.finditer(text):
        feet = float(match.group(1))
        if feet > 0.0:
            hits.append(ScaleHit(f"1\"={feet:g}'", 1.0, feet * 12.0))
    if _NTS.search(text):
        hits.append(ScaleHit("NTS", None, None))
    if _GRAPHIC.search(text):
        hits.append(ScaleHit("graphic", None, None))
    return hits


def _fraction_label(match) -> str:
    whole, numerator, denominator, decimal = match.groups()[:4]
    if decimal is not None:
        return decimal
    fraction = f"{numerator}/{denominator}"
    return f"{whole} {fraction}" if whole else fraction


def page_scale(lines: Sequence[TextLine]) -> Tuple[str, Optional[ScaleHit], int]:
    hits = [hit for line in lines for hit in parse_scales(line.text)]
    numeric = [hit for hit in hits if hit.sf1]
    if numeric:
        common = Counter(hit.label for hit in numeric).most_common(1)[0][0]
        chosen = next(hit for hit in numeric if hit.label == common)
        status = "single" if len({hit.label for hit in numeric}) == 1 else "multiple"
        return status, chosen, len(numeric)
    if any(hit.label == "NTS" for hit in hits):
        return "nts", None, 0
    if any(hit.label == "graphic" for hit in hits):
        return "graphic_only", None, 0
    return "none", None, 0


def width_bucket(width: Optional[float]) -> str:
    if width is None:
        return "fill"
    for low, high in zip(WIDTH_BUCKETS, WIDTH_BUCKETS[1:]):
        if width < high:
            return f"<{high:g}"
    return f">={WIDTH_BUCKETS[-1]:g}"


def file_pattern(name: str) -> str:
    stem = Path(name).stem
    for label, pattern in _FILE_PATTERNS:
        if pattern.search(stem):
            return label
    return "other"


def percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def structural_parts(relative: str) -> Optional[Tuple[str, str]]:
    parts = Path(relative).parts
    if len(parts) < 6 or parts[0] not in YEARS:
        return None
    if tuple(parts[2:5]) != STRUCTURAL_PARTS:
        return None
    return parts[0], parts[1]


def stratified_sample(
    rows: Sequence[dict], count: int, seed: int = 20261008, max_bytes: float = math.inf
) -> List[dict]:
    rng = random.Random(seed)
    groups: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        parts = structural_parts(row["rel"])
        if parts is None or int(row["size"]) > max_bytes:
            continue
        groups[parts[0]][parts[1]].append(row)
    years = sorted(groups)
    if not years:
        return []
    chosen: List[dict] = []
    seen = set()
    large = sorted(
        (row for year in years for project in groups[year].values() for row in project),
        key=lambda row: -int(row["size"]),
    )
    large_projects = set()
    for row in large:
        if len(chosen) >= max(1, count // 6):
            break
        project = structural_parts(row["rel"])
        if project in large_projects:
            continue
        large_projects.add(project)
        chosen.append(row)
        seen.add(row["rel"])
    used = set(large_projects)
    queues = {}
    for year in years:
        projects = list(groups[year])
        rng.shuffle(projects)
        queues[year] = projects
    pattern_counts: Counter = Counter(file_pattern(row["rel"]) for row in chosen)

    def fresh(year: str) -> List[str]:
        return [name for name in queues[year] if (year, name) not in used]

    while len(chosen) < count:
        progressed = False
        any_fresh = any(fresh(year) for year in years)
        for year in years:
            if len(chosen) >= count:
                break
            options = fresh(year) if any_fresh else list(queues[year])
            if not options:
                continue
            project = options[0]
            queues[year].remove(project)
            candidates = [
                row for row in groups[year][project] if row["rel"] not in seen
            ]
            if candidates:
                candidates.sort(
                    key=lambda row: (
                        pattern_counts[file_pattern(row["rel"])],
                        rng.random(),
                    )
                )
                row = candidates[0]
                chosen.append(row)
                seen.add(row["rel"])
                used.add((year, project))
                pattern_counts[file_pattern(row["rel"])] += 1
                progressed = True
            if any(r["rel"] not in seen for r in groups[year][project]):
                queues[year].append(project)
        if not progressed:
            break
    return chosen


def local_name(relative: str) -> str:
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
    return f"{digest}.pdf"


def read_csv(path: Path) -> List[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[dict], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def hand_values(path: Path) -> Dict[Tuple[str, int], List[dict]]:
    values: Dict[Tuple[str, int], List[dict]] = defaultdict(list)
    if not path.is_file():
        return values
    for row in read_csv(path):
        try:
            values[(row["pdf"], int(row["page"]))].append(
                {
                    "seed_pts": [float(row["seed_x"]), float(row["seed_y"])],
                    "expected_sf": float(row["expected_sf"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return values


def inventory(source: Path, out: Path) -> List[dict]:
    rows = []
    for year in YEARS:
        year_dir = source / year
        if not year_dir.is_dir():
            continue
        for project in sorted(path for path in year_dir.iterdir() if path.is_dir()):
            structural = project.joinpath(*STRUCTURAL_PARTS)
            if not structural.is_dir():
                continue
            for pdf in sorted(structural.rglob("*")):
                if pdf.is_file() and pdf.suffix.lower() == ".pdf":
                    rows.append(
                        {
                            "rel": str(pdf.relative_to(source)),
                            "size": pdf.stat().st_size,
                        }
                    )
    write_csv(out / "inventory.csv", rows, ("rel", "size"))
    return rows


def long_path(path: Path) -> str:
    text = str(path)
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def copy_sample(
    source: Path,
    out: Path,
    inventory_rows: Sequence[dict],
    count: int,
    max_bytes: float,
) -> List[dict]:
    files = out / "files"
    files.mkdir(parents=True, exist_ok=True)
    unreadable = set()
    while True:
        available = [row for row in inventory_rows if row["rel"] not in unreadable]
        chosen = stratified_sample(available, count, max_bytes=max_bytes)
        failed = False
        for row in chosen:
            target = files / local_name(row["rel"])
            if target.exists():
                continue
            try:
                with open(long_path(source / row["rel"]), "rb") as reader, open(
                    target, "wb"
                ) as writer:
                    shutil.copyfileobj(reader, writer)
            except OSError as exc:
                target.unlink(missing_ok=True)
                unreadable.add(row["rel"])
                print(
                    f"skipped (unreadable: {type(exc).__name__}): {row['rel']}",
                    flush=True,
                )
                failed = True
        if not failed or not chosen:
            break
    keep = {local_name(row["rel"]) for row in chosen}
    for path in files.iterdir():
        if path.name not in keep:
            path.unlink()
    rows = [
        {"rel": row["rel"], "local": local_name(row["rel"]), "size": row["size"]}
        for row in chosen
    ]
    write_csv(out / "sample.csv", rows, ("rel", "local", "size"))
    if not (out / "hand_values.csv").exists():
        write_csv(out / "hand_values.csv", [], HAND_VALUE_COLUMNS)
    return rows


RUN_COLUMNS = (
    "rel",
    "page",
    "status",
    "seconds",
    "peak_mb",
    "pages_in_pdf",
    "width_pts",
    "height_pts",
    "scale_used",
    "rotation",
    "visible_offset",
    "page_size_class",
    "text_runs",
    "segments",
    "curves",
    "extraction_truncated",
    "content",
    "outlined_text",
    "kind",
    "title",
    "sheet_number",
    "scale_status",
    "scale_label",
    "scale_hits",
    "kinds_wall",
    "kinds_dashed",
    "kinds_thin",
    "kinds_symbol",
    "dash_arrays",
    "widths",
    "heavy_threshold",
    "list_status",
    "list_seconds",
    "list_regions",
    "list_leaks",
    "list_gaps",
    "list_suppressed",
    "list_excluded",
    "filtered_status",
    "filtered_seconds",
    "filtered_regions",
    "filtered_leaks",
    "filtered_excluded",
    "filtered_gaps",
    "filtered_suppressed",
    "seed_source",
    "seed_status",
    "seed_seconds",
    "seed_method",
    "seed_area_sf",
    "seed_gaps",
    "seed_leak",
    "seed_unlocated",
    "proposal_status",
    "proposal_assumptions",
    "hand_expected_sf",
    "hand_error_pct",
    "error",
)


def run(out: Path, timeout: float, python: str) -> Path:
    sample = read_csv(out / "sample.csv")
    seeds = hand_values(out / "hand_values.csv")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = out / "work" / stamp
    work.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in sample:
        pdf = out / "files" / item["local"]
        prepared = work / f"{Path(item['local']).stem}.json"
        command = [
            python,
            "-m",
            "tools.ai_takeoff_corpus_worker",
            "prepare",
            str(pdf),
            str(work),
            str(prepared),
        ]
        done = _run_child(command, timeout)
        if done["status"] != "ok" or not prepared.exists():
            rows.append(
                {
                    "rel": item["rel"],
                    "page": "",
                    "status": f"prepare_{done['status']}",
                    "error": done["error"],
                }
            )
            continue
        bid = json.loads(prepared.read_text(encoding="utf-8"))
        for page in bid["pages"]:
            page_number = page["index"] + 1
            result_path = work / f"{Path(item['local']).stem}_p{page_number}.json"
            page_seeds = seeds.get((item["rel"], page_number), [])
            command = [
                python,
                "-m",
                "tools.ai_takeoff_corpus_worker",
                "page",
                str(prepared),
                page["uid"],
                json.dumps(page_seeds),
                str(result_path),
            ]
            started = time.perf_counter()
            done = _run_child(command, timeout)
            row = {
                "rel": item["rel"],
                "page": page_number,
                "pages_in_pdf": len(bid["pages"]),
            }
            if done["status"] == "ok" and result_path.exists():
                row.update(json.loads(result_path.read_text(encoding="utf-8")))
            else:
                row.update(status=done["status"], error=done["error"])
            row["seconds"] = round(time.perf_counter() - started, 2)
            rows.append(row)
            print(f"{item['rel']} p{page_number}: {row.get('status')}", flush=True)
    path = out / f"corpus_run_{stamp}.csv"
    write_csv(path, rows, RUN_COLUMNS)
    report(path, out / f"corpus_summary_{stamp}.md")
    return path


def _run_child(command: Sequence[str], timeout: float) -> dict:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        )
    except subprocess.TimeoutExpired:
        return {"status": "hang", "error": f"timeout after {timeout:g} s"}
    if completed.returncode != 0:
        last = [line for line in completed.stderr.splitlines() if line.strip()][
            -1:
        ] or [""]
        kind = (
            "crash"
            if completed.returncode < 0 or completed.returncode > 255
            else "error"
        )
        return {
            "status": kind,
            "error": f"exit {completed.returncode}: {_exception_name(last[0])}",
        }
    return {"status": "ok", "error": ""}


def _exception_name(line: str) -> str:
    match = re.match(
        r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt))", line.strip()
    )
    return match.group(1) if match else "no exception line"


def _number(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate(rows: Sequence[dict], predicate) -> str:
    if not rows:
        return "n/a"
    passed = sum(1 for row in rows if predicate(row))
    return f"{passed}/{len(rows)} ({100.0 * passed / len(rows):.0f}%)"


def _example(rows: Sequence[dict], limit: int = 3) -> str:
    return "; ".join(f"{row['rel']} p{row['page']}" for row in rows[:limit])


def failure_categories(rows: Sequence[dict]) -> List[Tuple[str, List[dict]]]:
    categories: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        status = row.get("status", "")
        if status != "ok":
            categories[f"page failed: {status} ({row.get('error', '')})"].append(row)
            continue
        if row.get("content") == "raster_only":
            categories["raster-only page (no vectors, no text)"].append(row)
        if row.get("outlined_text") == "True":
            categories["text drawn as outlines (no extractable text)"].append(row)
        if row.get("extraction_truncated") == "True":
            categories["extraction over 250,000 pieces"].append(row)
        if (
            row.get("scale_status") in ("none", "graphic_only")
            and row.get("kind") == KIND_PLAN
        ):
            categories["plan without a readable scale"].append(row)
        if row.get("scale_status") == "multiple" and row.get("kind") == KIND_PLAN:
            categories["plan with several scales"].append(row)
        if row.get("kind") == KIND_UNKNOWN:
            categories["page kind not recognised"].append(row)
        if not row.get("sheet_number"):
            categories["sheet number not found"].append(row)
        if row.get("kind") != KIND_PLAN:
            continue
        for prefix in ("list", "filtered", "seed"):
            status = row.get(f"{prefix}_status", "")
            if status and status not in ("ok", "empty", "truncated", "skipped"):
                categories[f"find_regions {prefix}: {status}"].append(row)
        if row.get("filtered_status") == "empty":
            categories["plan: no region with wall-width filter"].append(row)
        if row.get("seed_method") == "raster":
            categories["plan: seeded region fell back to raster"].append(row)
        if row.get("seed_unlocated") not in ("", None, "None"):
            categories["plan: raster may have closed unseen openings"].append(row)
        seconds = _number(row.get("filtered_seconds"))
        if seconds is not None and seconds > 10.0:
            categories["plan: find_regions slower than 10 s"].append(row)
        error = _number(row.get("hand_error_pct"))
        if error is not None and abs(error) > 0.5:
            categories["hand value off by more than 0.5%"].append(row)
    return sorted(categories.items(), key=lambda item: -len(item[1]))


def report(run_csv: Path, out: Path) -> Path:
    rows = read_csv(run_csv)
    ok = [row for row in rows if row.get("status") == "ok"]
    plans = [row for row in ok if row.get("kind") == KIND_PLAN]
    lines = [
        f"# AI takeoff corpus run {run_csv.stem}",
        "",
        "Metrics only: relative paths, page numbers, sheet numbers and sheet titles; no drawing content.",
        "",
        f"PDFs: {len({row['rel'] for row in rows})}; pages: {len(rows)}; plan-like pages: {len(plans)}.",
        "",
        "## Pass rates",
        "",
        "| Metric | Rate |",
        "| --- | --- |",
        f"| Page measured without crash, hang or error | {_rate(rows, lambda r: r.get('status') == 'ok')} |",
        f"| Vector content | {_rate(ok, lambda r: r.get('content') in ('vector', 'vector_and_text'))} |",
        f"| Extractable text | {_rate(ok, lambda r: (_number(r.get('text_runs')) or 0) > 0)} |",
        f"| Sheet number found | {_rate(ok, lambda r: bool(r.get('sheet_number')))} |",
        f"| Page kind recognised | {_rate(ok, lambda r: r.get('kind') != KIND_UNKNOWN)} |",
        f"| Plan: numeric scale read | {_rate(plans, lambda r: r.get('scale_status') in ('single', 'multiple'))} |",
        f"| Plan: under the 20,000 region cap (filtered) | {_rate(plans, lambda r: r.get('filtered_status') != 'invalid_argument')} |",
        f"| Plan: regions found with wall-width filter | {_rate(plans, lambda r: (_number(r.get('filtered_regions')) or 0) > 0)} |",
        f"| Plan: seeded call returned a vector region | {_rate([r for r in plans if r.get('seed_status') not in ('', 'skipped')], lambda r: r.get('seed_method') == 'vector')} |",
        f"| Plan: changeset proposed (never applied) | {_rate([r for r in plans if r.get('proposal_status')], lambda r: r.get('proposal_status') == 'ok')} |",
    ]
    hand = [row for row in ok if _number(row.get("hand_error_pct")) is not None]
    lines.append(
        f"| Hand values within 0.5% | {_rate(hand, lambda r: abs(_number(r['hand_error_pct'])) <= 0.5)} |"
    )
    lines += ["", "## Page mix", ""]
    for column in (
        "kind",
        "content",
        "scale_status",
        "page_size_class",
        "rotation",
        "visible_offset",
    ):
        counts = Counter(row.get(column, "") for row in ok)
        lines.append(
            f"- {column}: "
            + ", ".join(
                f"{key or 'blank'} {value}" for key, value in counts.most_common()
            )
        )
    lines += [
        "",
        "## Timing percentiles (seconds)",
        "",
        "| Measure | p50 | p90 | p99 | max |",
        "| --- | --- | --- | --- | --- |",
    ]
    for column in ("seconds", "list_seconds", "filtered_seconds", "seed_seconds"):
        values = [_number(row.get(column)) for row in rows]
        values = [value for value in values if value is not None]
        if values:
            lines.append(
                f"| {column} | {percentile(values, .5):.2f} | {percentile(values, .9):.2f} | "
                f"{percentile(values, .99):.2f} | {max(values):.2f} |"
            )
    memory = [_number(row.get("peak_mb")) for row in ok]
    memory = [value for value in memory if value is not None]
    if memory:
        lines.append(
            f"| peak_mb | {percentile(memory, .5):.0f} | {percentile(memory, .9):.0f} | {percentile(memory, .99):.0f} | {max(memory):.0f} |"
        )
    lines += ["", "## Failure categories (most frequent first)", ""]
    for name, members in failure_categories(rows):
        lines.append(
            f"- **{name}**: {len(members)} page(s). Examples: {_example(members)}"
        )
    lines += [
        "",
        "## Line kinds and widths by project (proxy for firm)",
        "",
        "| Project | Pages | wall | dashed | thin | symbol | width histogram |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    by_project: Dict[str, List[dict]] = defaultdict(list)
    for row in ok:
        parts = Path(row["rel"]).parts
        by_project[parts[1] if len(parts) > 1 else row["rel"]].append(row)
    for project, members in sorted(by_project.items()):
        totals = {
            kind: sum(int(_number(m.get(f"kinds_{kind}")) or 0) for m in members)
            for kind in ("wall", "dashed", "thin", "symbol")
        }
        widths: Counter = Counter()
        for member in members:
            widths.update(json.loads(member.get("widths") or "{}"))
        histogram = ", ".join(f"{key} {value}" for key, value in sorted(widths.items()))
        lines.append(
            f"| {project} | {len(members)} | {totals['wall']} | {totals['dashed']} | {totals['thin']} | {totals['symbol']} | {histogram} |"
        )
    lines += [
        "",
        "## Sheets",
        "",
        "| PDF | Page | Sheet | Kind | Title | Scale |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in ok:
        lines.append(
            f"| {row['rel']} | {row['page']} | {row.get('sheet_number', '')} | {row.get('kind', '')} | "
            f"{row.get('title', '')} | {row.get('scale_label', '') or row.get('scale_status', '')} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


REPO_ROOT = Path(__file__).resolve().parents[1]


def inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("inventory", "sample", "run", "report"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--max-mb", type=float, default=150.0)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--run", type=Path)
    args = parser.parse_args(argv)
    if inside_repository(args.out):
        parser.error(
            "--out must be outside the repository (the corpus is confidential)"
        )
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "inventory":
        rows = inventory(args.source, args.out)
        print(f"{len(rows)} PDFs")
    elif args.command == "sample":
        listed = args.out / "inventory.csv"
        rows = (
            read_csv(listed) if listed.is_file() else inventory(args.source, args.out)
        )
        max_bytes = args.max_mb * 1024 * 1024
        chosen = stratified_sample(rows, args.count, max_bytes=max_bytes)
        if args.source is not None:
            chosen = copy_sample(args.source, args.out, rows, args.count, max_bytes)
        for row in chosen:
            print(row["rel"])
    elif args.command == "run":
        print(run(args.out, args.timeout, sys.executable))
    else:
        print(
            report(
                args.run,
                args.run.with_name(
                    args.run.stem.replace("run_", "summary_", 1) + ".md"
                ),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
