import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

Box = Tuple[float, float, float, float]
TITLE_BLOCK_X = 0.70
TITLE_BLOCK_Y = 0.80
CORNER_Y = 0.70
LINE_TOLERANCE = 0.5
WORD_GAP = 2.0
LOCATION_CELL = 0.05
LOCATION_REACH = 0.06
DOMINANT_SHARE = 0.4
REPEAT_SHARE = 0.5
SOURCE_LABEL = "label"
SOURCE_TITLE_BLOCK = "title_block"
VIEW_KINDS = (
    ("schedule", re.compile(r"\bSCHEDULES?\b")),
    ("detail", re.compile(r"\bDETAILS?\b")),
    ("section", re.compile(r"\bSECTIONS?\b")),
    ("elevation", re.compile(r"\bELEVATIONS?\b(?!\s*[:=]?\s*[+-]?\d)")),
    ("plan", re.compile(r"\bPLANS?\b")),
)
_SHEET = re.compile(
    r"^(S(?:[A-Z]{1,2}(?=-?\d))?)\s*-?\s*(\d{1,3})((?:\.\d{1,3})?)([A-Z]?)$"
)
_LABEL = r"(?:SHEET|DRAWING|DWG)(?:\s*(?:NO\.?|NUMBER|NUM\.?|#))?\s*:?"
_LABEL_ONLY = re.compile(rf"^{_LABEL}$")
_LABEL_WITH_NUMBER = re.compile(rf"^{_LABEL}\s*(\S.*)$")
_QUOTES = str.maketrans({"”": '"', "″": '"', "’": "'", "′": "'"})
_FRACTION = r"(?:(\d+)(?:\s+|\s*-\s*))?(\d+)\s*/\s*(\d+)|(\d+(?:\.\d+)?)"
_INCH = r"\s*(?:\"|''|IN\.?)"
_FOOT = r"\s*(?:'|FT\.?)"
_ARCH_SCALE = re.compile(
    rf"(?:{_FRACTION}){_INCH}\s*=\s*1{_FOOT}(?:\s*-?\s*0{_INCH}?)?", re.IGNORECASE
)
_ENGINEER_SCALE = re.compile(
    rf"\b1{_INCH}\s*=\s*(\d+(?:\.\d+)?){_FOOT}(?:\s*-?\s*0{_INCH}?)?", re.IGNORECASE
)
_NTS = re.compile(r"\bN\.?\s*T\.?\s*S\b\.?|\bNOT\s+TO\s+SCALE\b", re.IGNORECASE)
_GRAPHIC = re.compile(r"\bGRAPHIC\s+SCALE\b", re.IGNORECASE)
_SCALE_WORD = re.compile(r"\bSCALE\b", re.IGNORECASE)
_REFERENCE = re.compile(r"^\s*(?:SEE|REFER|REF\b)", re.IGNORECASE)
_FEET_INCHES = re.compile(
    r"^(\d+)\s*'\s*(?:-\s*)?(?:(\d+)(?:\s+(\d+)\s*/\s*(\d+))?\s*\")?$"
)
_INCHES = re.compile(r"^(\d+)(?:\s+(\d+)\s*/\s*(\d+))?\s*\"$")


@dataclass(frozen=True)
class TextLine:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    height: float


@dataclass(frozen=True)
class SheetCandidate:
    number: str
    bbox: Box
    score: float
    source: str


@dataclass(frozen=True)
class ScaleCandidate:
    label: str
    sf1: Optional[float]
    sf2: Optional[float]
    bbox: Box
    view_title: str
    view_kind: str
    view_bbox: Optional[Box]

    @property
    def ost_per_point(self) -> Optional[float]:
        if not self.sf1 or not self.sf2:
            return None
        return self.sf2 / (72.0 * self.sf1)


@dataclass(frozen=True)
class PlanScale:
    status: str
    candidate: Optional[ScaleCandidate]


def text_lines(
    runs: Sequence[Tuple[str, float, float, float, float]],
) -> List[TextLine]:
    items = [
        (str(text), float(left), float(top), float(right), float(bottom))
        for text, left, top, right, bottom in runs
        if str(text).strip()
    ]
    items.sort(key=lambda item: ((item[2] + item[4]) / 2.0, item[1]))
    groups: List[list] = []
    for item in items:
        middle = (item[2] + item[4]) / 2.0
        height = abs(item[4] - item[2])
        if groups:
            last = groups[-1]
            last_middle = sum((r[2] + r[4]) / 2.0 for r in last) / len(last)
            reach = LINE_TOLERANCE * max(
                max(abs(r[4] - r[2]) for r in last), height, 1e-6
            )
            if abs(middle - last_middle) <= reach:
                last.append(item)
                continue
        groups.append([item])
    pieces: List[list] = []
    for group in groups:
        group.sort(key=lambda item: item[1])
        size = max(max(abs(item[4] - item[2]) for item in group), 1e-6)
        pieces.append([group[0]])
        for item in group[1:]:
            if item[1] - max(r[3] for r in pieces[-1]) > WORD_GAP * size:
                pieces.append([item])
            else:
                pieces[-1].append(item)
    lines = []
    for group in pieces:
        lines.append(
            TextLine(
                " ".join(item[0].strip() for item in group),
                min(item[1] for item in group),
                min(item[2] for item in group),
                max(item[3] for item in group),
                max(item[4] for item in group),
                max(abs(item[4] - item[2]) for item in group),
            )
        )
    return lines


def _sheet_text(text: str) -> Optional[str]:
    candidate = text.strip().upper()
    match = _SHEET.match(candidate)
    if match is None:
        return None
    if not match.group(3) and int(match.group(2)) == 0:
        return None
    return candidate


def _in_title_block(line: TextLine, width: float, height: float) -> bool:
    right_strip = line.left >= TITLE_BLOCK_X * width and line.top >= CORNER_Y * height
    return right_strip or line.top >= TITLE_BLOCK_Y * height


def _near_label(line: TextLine, label: TextLine) -> bool:
    size = max(label.height, line.height, 1e-6)
    below = (
        line.top >= label.top
        and line.top - label.bottom <= 3.0 * size
        and line.left < label.right + 2.0 * size
        and line.right > label.left - 2.0 * size
    )
    beside = (
        abs((line.top + line.bottom) - (label.top + label.bottom)) / 2.0 <= size
        and line.left >= label.right
        and line.left - label.right <= 6.0 * size
    )
    return below or beside


def sheet_number_candidates(
    lines: Sequence[TextLine], width: float, height: float
) -> List[SheetCandidate]:
    if not lines or width <= 0.0 or height <= 0.0:
        return []
    tallest = max(line.height for line in lines) or 1.0
    labels = [line for line in lines if _LABEL_ONLY.match(line.text.strip().upper())]
    candidates = []
    for line in lines:
        upper = line.text.strip().upper()
        number = _sheet_text(upper)
        labelled = False
        if number is None:
            match = _LABEL_WITH_NUMBER.match(upper)
            number = None if match is None else _sheet_text(match.group(1))
            labelled = number is not None
        if number is None:
            continue
        labelled = labelled or any(_near_label(line, label) for label in labels)
        in_block = _in_title_block(line, width, height)
        if not labelled and not in_block:
            continue
        score = 2.0 * line.height / tallest
        if labelled:
            score += 4.0
        if in_block:
            score += 2.0
        if line.left >= TITLE_BLOCK_X * width and line.top >= CORNER_Y * height:
            score += 1.0
        candidates.append(
            SheetCandidate(
                number,
                (line.left, line.top, line.right, line.bottom),
                score,
                SOURCE_LABEL if labelled else SOURCE_TITLE_BLOCK,
            )
        )
    candidates.sort(key=lambda candidate: -candidate.score)
    return candidates


def sheet_number(
    lines: Sequence[TextLine], width: float, height: float
) -> Optional[SheetCandidate]:
    candidates = sheet_number_candidates(lines, width, height)
    return candidates[0] if candidates else None


def _center(
    candidate: SheetCandidate, width: float, height: float
) -> Tuple[float, float]:
    left, top, right, bottom = candidate.bbox
    return ((left + right) / 2.0 / width, (top + bottom) / 2.0 / height)


def consistent_sheet_numbers(
    pages: Sequence[Tuple[float, float, Sequence[SheetCandidate]]],
) -> List[Optional[SheetCandidate]]:
    chosen: List[Optional[SheetCandidate]] = [
        candidates[0] if candidates else None for _w, _h, candidates in pages
    ]
    with_number = [index for index, candidate in enumerate(chosen) if candidate]
    if len(pages) < 3 or not with_number:
        return chosen
    cells = Counter(
        tuple(
            round(value / LOCATION_CELL) for value in _center(chosen[i], *pages[i][:2])
        )
        for i in with_number
    )
    cell, count = cells.most_common(1)[0]
    if count >= max(2, DOMINANT_SHARE * len(with_number)):
        target = (cell[0] * LOCATION_CELL, cell[1] * LOCATION_CELL)
        for index, (width, height, candidates) in enumerate(pages):
            near = [
                candidate
                for candidate in candidates
                if math.dist(_center(candidate, width, height), target)
                <= LOCATION_REACH
            ]
            if near:
                chosen[index] = max(near, key=lambda candidate: candidate.score)
            elif chosen[index] is not None and chosen[index].source != SOURCE_LABEL:
                chosen[index] = None
    repeats = Counter(
        candidate.number
        for candidate in chosen
        if candidate is not None and candidate.source != SOURCE_LABEL
    )
    limit = max(3, REPEAT_SHARE * len(pages))
    return [
        (
            None
            if candidate is not None
            and candidate.source != SOURCE_LABEL
            and repeats[candidate.number] >= limit
            else candidate
        )
        for candidate in chosen
    ]


def _fraction(match) -> Tuple[Optional[float], str]:
    whole, numerator, denominator, decimal = match.groups()[:4]
    if decimal is not None:
        return float(decimal), decimal
    if not float(denominator):
        return None, ""
    value = float(numerator) / float(denominator) + (float(whole) if whole else 0.0)
    label = f"{numerator}/{denominator}"
    return value, f"{whole} {label}" if whole else label


def parse_scale_label(text: str) -> List[Tuple[str, Optional[float], Optional[float]]]:
    normalized = text.translate(_QUOTES)
    hits: List[Tuple[str, Optional[float], Optional[float]]] = []
    for match in _ARCH_SCALE.finditer(normalized):
        value, label = _fraction(match)
        if value and value > 0.0:
            hits.append((f'{label}"=1\'-0"', value, 12.0))
    ratios = {(sf1, sf2) for _label, sf1, sf2 in hits}
    for match in _ENGINEER_SCALE.finditer(normalized):
        feet = float(match.group(1))
        if feet > 0.0 and (1.0, feet * 12.0) not in ratios:
            hits.append((f"1\"={feet:g}'", 1.0, feet * 12.0))
    if _NTS.search(normalized):
        hits.append(("NTS", None, None))
    if _GRAPHIC.search(normalized):
        hits.append(("graphic", None, None))
    return hits


def view_kind(text: str) -> str:
    upper = text.upper()
    for kind, pattern in VIEW_KINDS:
        if pattern.search(upper):
            return kind
    return ""


def _view_above(line: TextLine, titles: Sequence[TextLine]) -> Optional[TextLine]:
    best = None
    best_gap = math.inf
    for title in titles:
        size = max(title.height, line.height, 1e-6)
        gap = line.top - title.bottom
        if title is line or gap < -0.5 * line.height or gap > 3.0 * size:
            continue
        if title.left > line.right + 2.0 * size or title.right < line.left - 2.0 * size:
            continue
        if gap < best_gap:
            best, best_gap = title, gap
    return best


def scale_candidates(lines: Sequence[TextLine]) -> List[ScaleCandidate]:
    hits_by_line = [(line, parse_scale_label(line.text)) for line in lines]
    titles = [
        line
        for line, hits in hits_by_line
        if not hits and view_kind(line.text) and not _REFERENCE.match(line.text)
    ]
    candidates = []
    for line, hits in hits_by_line:
        if not hits:
            continue
        before = _SCALE_WORD.split(line.text, maxsplit=1)[0].strip(" :")
        if before and view_kind(before):
            title_text, kind, view_box = (
                before,
                view_kind(before),
                (line.left, line.top, line.right, line.bottom),
            )
        else:
            title = _view_above(line, titles)
            if title is None:
                title_text, kind, view_box = "", "", None
            else:
                title_text = title.text
                kind = view_kind(title.text)
                view_box = (title.left, title.top, title.right, title.bottom)
        for label, sf1, sf2 in hits:
            candidates.append(
                ScaleCandidate(
                    label,
                    sf1,
                    sf2,
                    (line.left, line.top, line.right, line.bottom),
                    title_text,
                    kind,
                    view_box,
                )
            )
    return candidates


def plan_scale(candidates: Sequence[ScaleCandidate]) -> PlanScale:
    if not candidates:
        return PlanScale("none", None)
    plans = [candidate for candidate in candidates if candidate.view_kind == "plan"]
    if plans:
        numeric = [candidate for candidate in plans if candidate.sf1]
        labels = {candidate.label for candidate in numeric}
        if len(labels) == 1:
            return PlanScale("resolved", numeric[0])
        if len(labels) > 1:
            return PlanScale("ambiguous", None)
        if any(candidate.label == "NTS" for candidate in plans):
            return PlanScale("nts", None)
        return PlanScale("none", None)
    if any(candidate.view_kind for candidate in candidates):
        return PlanScale("no_plan_view", None)
    loose = [candidate for candidate in candidates if candidate.sf1]
    if len({candidate.label for candidate in loose}) == 1:
        return PlanScale("sheet", loose[0])
    return PlanScale("none", None)


def parse_dimension_in(text: str) -> Optional[float]:
    normalized = text.translate(_QUOTES).strip()
    match = _FEET_INCHES.match(normalized)
    if match is not None:
        feet, inches, numerator, denominator = match.groups()
        value = float(feet) * 12.0 + (float(inches) if inches else 0.0)
        if numerator and float(denominator):
            value += float(numerator) / float(denominator)
        return value if value > 0.0 else None
    match = _INCHES.match(normalized)
    if match is not None:
        inches, numerator, denominator = match.groups()
        value = float(inches)
        if numerator and float(denominator):
            value += float(numerator) / float(denominator)
        return value if value > 0.0 else None
    return None


def title_block_crop(
    width: float, height: float, candidate: Optional[SheetCandidate]
) -> List[float]:
    if candidate is None:
        if width >= height:
            return [0.78 * width, 0.0, 0.22 * width, height]
        return [0.0, 0.8 * height, width, 0.2 * height]
    left, top, right, bottom = candidate.bbox
    x0 = min(max(0.0, left - 0.15 * width), width)
    y0 = min(max(0.0, top - 0.15 * height), height)
    x1 = max(x0, min(width, right + 0.05 * width))
    y1 = max(y0, min(height, bottom + 0.05 * height))
    return [x0, y0, x1 - x0, y1 - y0]
