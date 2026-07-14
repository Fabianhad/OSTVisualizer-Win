from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping
from ..entities.condition import Condition
from ..entities.page import Page
from ..entities.takeoff import Takeoff
from .takeoff_domain_service import is_takeoff_visible


@dataclass(frozen=True)
class PageTakeoffSummary:
    page_uid: str
    page_name: str
    takeoff_count: int = 0
    visible_takeoff_count: int = 0


def summarize_takeoffs_by_page(
    takeoffs: Iterable[Takeoff],
    pages: Mapping[str, Page],
    conditions: Mapping[str, Condition],
) -> List[PageTakeoffSummary]:
    counts: Dict[str, int] = defaultdict(int)
    visible_counts: Dict[str, int] = defaultdict(int)
    for takeoff in takeoffs:
        counts[takeoff.page_uid] += 1
        if is_takeoff_visible(takeoff, conditions):
            visible_counts[takeoff.page_uid] += 1
    result = []
    for page_uid, count in counts.items():
        page = pages.get(page_uid)
        result.append(
            PageTakeoffSummary(
                page_uid=page_uid,
                page_name=page.name if page else "",
                takeoff_count=count,
                visible_takeoff_count=visible_counts.get(page_uid, 0),
            )
        )
    return sorted(
        result,
        key=lambda item: (
            pages.get(item.page_uid).page_index if item.page_uid in pages else 0,
            item.page_name.lower(),
            item.page_uid,
        ),
    )
