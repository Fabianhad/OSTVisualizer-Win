import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from ...domain.entities.condition import Condition
from ...domain.entities.file_results import BidLoadResult
from ...domain.services.condition_quantity_service import compute_page_quantities
from ...domain.services.takeoff_domain_service import is_takeoff_visible
from ...domain.services.takeoff_summary_service import summarize_takeoffs_by_page
from ...domain.services.uom_service import get_uom_label
from ..dtos.mcp_context_dtos import (
    MCP_STATUS_DUPLICATE_REF_NO,
    MCP_STATUS_OK,
    McpBidComparisonCountsDto,
    McpBidComparisonDetailDto,
    McpBidComparisonDto,
    McpBidComparisonGroupDto,
    McpBidComparisonMetaDto,
    McpBidComparisonQuantityDto,
    McpBidDto,
    McpBidMetadataChangeDto,
    McpDuplicateRefNoDto,
)

_QUANTITY_COMPARISON_ABS_TOLERANCE = 1e-9


@dataclass(frozen=True)
class _ConditionSnapshot:
    condition_name: str
    cdn_type_name: str
    metadata: Tuple[object, ...]
    quantities: Tuple[float, float, float]
    uom_labels: Tuple[str, str, str]
    takeoff_count: int
    visible_takeoff_count: int
    page_counts: Dict[str, int]


@dataclass(frozen=True)
class _ComparisonRecord:
    ref_no: int
    classification: str
    group_name: str
    old: Optional[_ConditionSnapshot]
    new: Optional[_ConditionSnapshot]
    page_changes: Tuple[str, ...] = ()
    metadata_changed: bool = False
    quantity_changed: bool = False
    takeoff_count_changed: bool = False
    visible_takeoff_count_changed: bool = False
    page_distribution_changed: bool = False


@dataclass
class _GroupAccumulator:
    counts: Dict[str, int] = field(default_factory=Counter)
    old_quantities: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    new_quantities: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    old_takeoff_count: int = 0
    new_takeoff_count: int = 0
    old_labels: List[Set[str]] = field(default_factory=lambda: [set(), set(), set()])
    new_labels: List[Set[str]] = field(default_factory=lambda: [set(), set(), set()])
    page_changes: Set[str] = field(default_factory=set)

    def add(self, record: _ComparisonRecord) -> None:
        self.counts[record.classification] += 1
        self.page_changes.update(record.page_changes)
        if record.old is not None:
            self.old_takeoff_count += record.old.takeoff_count
            self._add_snapshot(record.old, self.old_quantities, self.old_labels)
        if record.new is not None:
            self.new_takeoff_count += record.new.takeoff_count
            self._add_snapshot(record.new, self.new_quantities, self.new_labels)

    @staticmethod
    def _add_snapshot(
        snapshot: _ConditionSnapshot,
        quantities: List[float],
        labels: List[Set[str]],
    ) -> None:
        for index, quantity in enumerate(snapshot.quantities):
            quantities[index] += quantity
            label = snapshot.uom_labels[index]
            if label:
                labels[index].add(label)


@dataclass(frozen=True)
class BidComparisonResult:
    status: str
    data: McpBidComparisonDto
    meta: McpBidComparisonMetaDto


class BidComparisonService:
    MAX_WARNINGS = 50

    def compare(
        self,
        old_bid: McpBidDto,
        new_bid: McpBidDto,
        old_data: BidLoadResult,
        new_data: BidLoadResult,
        limit: int,
        include_details: bool = False,
    ) -> BidComparisonResult:
        bid_changes = self._bid_metadata_changes(old_bid, new_bid)
        old_conditions, old_duplicates = self._index_conditions_by_ref_no(
            "old", old_data, limit
        )
        new_conditions, new_duplicates = self._index_conditions_by_ref_no(
            "new", new_data, limit
        )
        duplicates = sorted(
            old_duplicates + new_duplicates,
            key=lambda item: (item.bid, item.ref_no),
        )
        if duplicates:
            limited_duplicates = duplicates[:limit]
            duplicate_bids = sorted({item.bid for item in duplicates})
            warnings = [
                (
                    f"{bid_label} bid contains duplicate ref_no values; "
                    "comparison was not performed."
                )
                for bid_label in duplicate_bids
            ]
            truncated = len(limited_duplicates) < len(duplicates)
            return BidComparisonResult(
                status=MCP_STATUS_DUPLICATE_REF_NO,
                data=McpBidComparisonDto(
                    old_bid=old_bid,
                    new_bid=new_bid,
                    bid_metadata_changed=bool(bid_changes),
                    bid_metadata_changes=bid_changes,
                    duplicate_ref_nos=limited_duplicates,
                    warnings=warnings,
                ),
                meta=McpBidComparisonMetaDto(
                    limit=limit,
                    returned_count=len(limited_duplicates),
                    total_count=len(duplicates),
                    truncated=truncated,
                    has_more=truncated,
                    details_included=bool(include_details),
                ),
            )
        old_snapshots = self._snapshots_by_ref_no(old_data, old_conditions)
        new_snapshots = self._snapshots_by_ref_no(new_data, new_conditions)
        records = self._comparison_records(old_snapshots, new_snapshots)
        counts = Counter(record.classification for record in records)
        affected = [
            record for record in records if record.classification != "unchanged"
        ]
        groups, warnings = self._aggregate_groups(affected, limit)
        limited_groups = groups[:limit]
        groups_truncated = len(limited_groups) < len(groups)
        limited_details = (
            [self._detail_dto(record, limit) for record in affected[:limit]]
            if include_details
            else []
        )
        detail_total_count = len(affected) if include_details else 0
        details_truncated = bool(include_details and len(affected) > limit)
        return BidComparisonResult(
            status=MCP_STATUS_OK,
            data=McpBidComparisonDto(
                old_bid=old_bid,
                new_bid=new_bid,
                counts=McpBidComparisonCountsDto(
                    unchanged=counts["unchanged"],
                    changed=counts["changed"],
                    added=counts["added"],
                    removed=counts["removed"],
                ),
                bid_metadata_changed=bool(bid_changes),
                bid_metadata_changes=bid_changes,
                groups=limited_groups,
                details=limited_details,
                warnings=self._bounded_warnings(warnings),
            ),
            meta=McpBidComparisonMetaDto(
                limit=limit,
                returned_count=len(limited_groups),
                total_count=len(groups),
                truncated=groups_truncated,
                has_more=groups_truncated,
                details_included=bool(include_details),
                detail_returned_count=len(limited_details),
                detail_total_count=detail_total_count,
                details_truncated=details_truncated,
            ),
        )

    @staticmethod
    def _bid_metadata_changes(
        old_bid: McpBidDto, new_bid: McpBidDto
    ) -> List[McpBidMetadataChangeDto]:
        comparisons = (
            ("name", old_bid.name, new_bid.name),
            ("project_name", old_bid.project_name, new_bid.project_name),
            ("bid_no", old_bid.bid_no, new_bid.bid_no),
            ("job_id", old_bid.job_id, new_bid.job_id),
            ("status", old_bid.status, new_bid.status),
            ("estimator", old_bid.estimator, new_bid.estimator),
            ("page_count", old_bid.page_count, new_bid.page_count),
            ("condition_count", old_bid.condition_count, new_bid.condition_count),
        )
        return [
            McpBidMetadataChangeDto(field=field_name, old=old_value, new=new_value)
            for field_name, old_value, new_value in comparisons
            if old_value != new_value
        ]

    def _snapshots_by_ref_no(
        self,
        bid_data: BidLoadResult,
        conditions_by_ref_no: Dict[int, Condition],
    ) -> Dict[int, _ConditionSnapshot]:
        takeoffs_by_condition = defaultdict(list)
        for takeoff in bid_data.bid_takeoffs:
            takeoffs_by_condition[takeoff.condition_uid].append(takeoff)
        snapshots = {}
        for ref_no, condition in conditions_by_ref_no.items():
            takeoffs = takeoffs_by_condition.get(condition.uid, [])
            visible_takeoffs = [
                takeoff
                for takeoff in takeoffs
                if is_takeoff_visible(takeoff, bid_data.bid_conditions)
            ]
            quantities_by_condition = compute_page_quantities(
                bid_data.bid_conditions,
                visible_takeoffs,
                only_condition_uids={condition.uid},
            )
            page_counts = defaultdict(int)
            for page_summary in summarize_takeoffs_by_page(
                takeoffs, bid_data.pages, bid_data.bid_conditions
            ):
                page_counts[
                    page_summary.page_name or "Unknown page"
                ] += page_summary.takeoff_count
            snapshots[ref_no] = _ConditionSnapshot(
                condition_name=condition.name,
                cdn_type_name=condition.cdn_type_name or "Unknown",
                metadata=self._stable_condition_metadata(condition),
                quantities=quantities_by_condition[condition.uid],
                uom_labels=(
                    get_uom_label(condition.uom1),
                    get_uom_label(condition.uom2),
                    get_uom_label(condition.uom3),
                ),
                takeoff_count=len(takeoffs),
                visible_takeoff_count=len(visible_takeoffs),
                page_counts=dict(page_counts),
            )
        return snapshots

    @staticmethod
    def _stable_condition_metadata(condition: Condition) -> Tuple[object, ...]:
        return (
            condition.name,
            condition.condition_type,
            condition.thickness,
            condition.height,
            condition.width,
            condition.depth,
            condition.rise,
            condition.run,
            condition.shape,
            condition.color_fill,
            condition.z_value,
            condition.is_top,
            condition.cdn_type_name,
            condition.pattern,
            condition.spacing,
            condition.layer_visible,
            condition.uom1,
            condition.uom2,
            condition.uom3,
            condition.calc_type1,
            condition.calc_type2,
            condition.calc_type3,
            condition.display_size,
            condition.drop_run,
            condition.drop_value,
            condition.notes,
            condition.round_quantity,
            condition.round_up,
            condition.trim,
            condition.is_curved_segment,
            condition.grid,
            condition.grid_size1,
            condition.grid_size2,
            condition.gap,
            condition.display_dimension,
            condition.display_name,
            condition.display_grid_while_drawing,
        )

    @staticmethod
    def _comparison_records(
        old_snapshots: Dict[int, _ConditionSnapshot],
        new_snapshots: Dict[int, _ConditionSnapshot],
    ) -> List[_ComparisonRecord]:
        records = []
        for ref_no in sorted(set(old_snapshots) | set(new_snapshots)):
            old = old_snapshots.get(ref_no)
            new = new_snapshots.get(ref_no)
            if old is None:
                records.append(
                    _ComparisonRecord(
                        ref_no=ref_no,
                        classification="added",
                        group_name=new.cdn_type_name,
                        old=None,
                        new=new,
                        page_changes=tuple(sorted(new.page_counts)),
                    )
                )
                continue
            if new is None:
                records.append(
                    _ComparisonRecord(
                        ref_no=ref_no,
                        classification="removed",
                        group_name=old.cdn_type_name,
                        old=old,
                        new=None,
                        page_changes=tuple(sorted(old.page_counts)),
                    )
                )
                continue
            metadata_changed = old.metadata != new.metadata
            quantity_changed = any(
                not math.isclose(
                    old_value,
                    new_value,
                    rel_tol=0.0,
                    abs_tol=_QUANTITY_COMPARISON_ABS_TOLERANCE,
                )
                for old_value, new_value in zip(old.quantities, new.quantities)
            )
            takeoff_count_changed = old.takeoff_count != new.takeoff_count
            visible_count_changed = (
                old.visible_takeoff_count != new.visible_takeoff_count
            )
            page_changes = BidComparisonService._changed_page_names(
                old.page_counts, new.page_counts
            )
            page_distribution_changed = bool(page_changes)
            changed = any(
                (
                    metadata_changed,
                    quantity_changed,
                    takeoff_count_changed,
                    visible_count_changed,
                    page_distribution_changed,
                )
            )
            records.append(
                _ComparisonRecord(
                    ref_no=ref_no,
                    classification="changed" if changed else "unchanged",
                    group_name=new.cdn_type_name,
                    old=old,
                    new=new,
                    page_changes=page_changes,
                    metadata_changed=metadata_changed,
                    quantity_changed=quantity_changed,
                    takeoff_count_changed=takeoff_count_changed,
                    visible_takeoff_count_changed=visible_count_changed,
                    page_distribution_changed=page_distribution_changed,
                )
            )
        return records

    @staticmethod
    def _changed_page_names(
        old_counts: Dict[str, int], new_counts: Dict[str, int]
    ) -> Tuple[str, ...]:
        return tuple(
            sorted(
                page_name
                for page_name in set(old_counts) | set(new_counts)
                if old_counts.get(page_name, 0) != new_counts.get(page_name, 0)
            )
        )

    def _aggregate_groups(
        self, records: List[_ComparisonRecord], page_limit: int
    ) -> Tuple[List[McpBidComparisonGroupDto], List[str]]:
        values: Dict[str, _GroupAccumulator] = defaultdict(_GroupAccumulator)
        for record in records:
            values[record.group_name].add(record)
        groups = []
        warnings = []
        for group_name in sorted(values, key=str.casefold):
            accumulator = values[group_name]
            quantities = [
                self._quantity_dto(group_name, accumulator, index, warnings)
                for index in range(3)
            ]
            counts = accumulator.counts
            page_changes = sorted(accumulator.page_changes)
            if len(page_changes) > page_limit:
                warnings.append(
                    f"{group_name} compact page changes truncated to "
                    f"{page_limit} of {len(page_changes)} pages."
                )
            groups.append(
                McpBidComparisonGroupDto(
                    cdn_type_name=group_name,
                    total_affected=(
                        counts["changed"] + counts["added"] + counts["removed"]
                    ),
                    changed=counts["changed"],
                    added=counts["added"],
                    removed=counts["removed"],
                    qty1=quantities[0],
                    qty2=quantities[1],
                    qty3=quantities[2],
                    takeoffs={
                        "old": accumulator.old_takeoff_count,
                        "new": accumulator.new_takeoff_count,
                    },
                    compact_page_changes=page_changes[:page_limit],
                )
            )
        return groups, warnings

    @staticmethod
    def _quantity_dto(
        group_name: str,
        accumulator: _GroupAccumulator,
        index: int,
        warnings: List[str],
    ) -> McpBidComparisonQuantityDto:
        target_labels = accumulator.new_labels[index]
        old_labels = accumulator.old_labels[index]
        labels = target_labels | old_labels
        selected_label = (
            sorted(target_labels)[0]
            if target_labels
            else (sorted(old_labels)[0] if old_labels else "")
        )
        if len(labels) > 1:
            warnings.append(
                f"{group_name} qty{index + 1} contains mixed UOM labels: "
                f"{', '.join(sorted(labels))}; reporting {selected_label}."
            )
        return McpBidComparisonQuantityDto(
            uom_label=selected_label,
            old=accumulator.old_quantities[index],
            new=accumulator.new_quantities[index],
        )

    @staticmethod
    def _detail_dto(
        record: _ComparisonRecord, page_limit: int
    ) -> McpBidComparisonDetailDto:
        return McpBidComparisonDetailDto(
            ref_no=record.ref_no,
            classification=record.classification,
            cdn_type_name=record.group_name,
            old_condition_name=(
                record.old.condition_name if record.old is not None else None
            ),
            new_condition_name=(
                record.new.condition_name if record.new is not None else None
            ),
            metadata_changed=record.metadata_changed,
            quantity_changed=record.quantity_changed,
            takeoff_count_changed=record.takeoff_count_changed,
            visible_takeoff_count_changed=record.visible_takeoff_count_changed,
            page_distribution_changed=record.page_distribution_changed,
            compact_page_changes=list(record.page_changes[:page_limit]),
        )

    @staticmethod
    def _index_conditions_by_ref_no(
        bid_label: str,
        bid_data: BidLoadResult,
        condition_name_limit: int,
    ) -> Tuple[Dict[int, Condition], List[McpDuplicateRefNoDto]]:
        by_ref_no = defaultdict(list)
        for condition in bid_data.bid_conditions.values():
            by_ref_no[condition.ref_no].append(condition)
        unique_conditions = {}
        duplicates = []
        for ref_no, conditions in by_ref_no.items():
            if len(conditions) == 1:
                unique_conditions[ref_no] = conditions[0]
            else:
                duplicates.append(
                    McpDuplicateRefNoDto(
                        bid=bid_label,
                        ref_no=ref_no,
                        condition_count=len(conditions),
                        condition_names=sorted(
                            (condition.name for condition in conditions),
                            key=str.casefold,
                        )[:condition_name_limit],
                    )
                )
        return unique_conditions, sorted(
            duplicates, key=lambda item: (item.bid, item.ref_no)
        )

    def _bounded_warnings(self, warnings: List[str]) -> List[str]:
        if len(warnings) <= self.MAX_WARNINGS:
            return warnings
        return warnings[: self.MAX_WARNINGS - 1] + [
            f"{len(warnings) - self.MAX_WARNINGS + 1} additional warnings omitted."
        ]
