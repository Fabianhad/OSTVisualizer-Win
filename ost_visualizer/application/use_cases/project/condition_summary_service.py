from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
from ....domain.entities.area import BidArea, UNASSIGNED_AREA_UID, normalize_area_uid
from ....domain.entities.condition import Condition
from ....domain.entities.condition_folder import BidConditionFolder
from ....domain.entities.page import Page
from ....domain.entities.takeoff import Takeoff
from ....domain.services.condition_quantity_service import compute_page_quantities
from ....domain.services.dimension_format_service import inches_to_display
from ...dtos.condition_summary_dtos import (
    SUMMARY_COLUMN_AREA,
    SUMMARY_GROUP_AREA,
    SUMMARY_GROUP_PAGE,
    SUMMARY_GROUP_TYPE,
    SUMMARY_MULTI_AREA_TOTAL_LABEL,
    SUMMARY_NO_PAGE_LABEL,
    SUMMARY_NODE_AREA_DETAIL,
    SUMMARY_NODE_CONDITION,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_GROUP,
    SUMMARY_NODE_MULTI_AREA_TOTAL,
    SUMMARY_NODE_ROOT,
    SUMMARY_QUANTITY_COLUMNS,
    SUMMARY_UNASSIGNED_LABEL,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
    ConditionSummaryValues,
)

_ROOT_FOLDER_UID: Optional[str] = None
_PRIMARY_PARENT_VALUES = {"", "0", "None"}
_NO_PAGE_UID = "NO_PAGE_ID"
_SORT_LAST_SEQUENCE = 10**9


@dataclass(frozen=True)
class _SummaryTakeoffContext:
    condition_uid: str
    page_uid: str
    area_uid: str
    takeoffs: Tuple[Takeoff, ...]


class ConditionSummaryService:
    def build_summary(
        self,
        *,
        conditions: Dict[str, Condition],
        folders: Dict[str, BidConditionFolder],
        takeoffs: Sequence[Takeoff],
        pages: Sequence[Page],
        areas: Sequence[BidArea],
        project_name: str = "",
        grouping: ConditionSummaryGrouping | None = None,
        metric: bool = False,
    ) -> ConditionSummaryNode:
        grouping = grouping or ConditionSummaryGrouping()
        page_labels, page_sorts = self._page_metadata(pages)
        area_labels, area_sorts = self._area_metadata(areas)
        contexts = self._build_takeoff_contexts(conditions, takeoffs)
        root = ConditionSummaryNode(
            kind=SUMMARY_NODE_ROOT,
            label=f"Conditions - {project_name}" if project_name else "Conditions",
        )
        conditions_by_folder = self._conditions_by_folder(conditions, folders)
        children_by_parent = self._folders_by_parent(folders)
        self._append_folder_nodes(
            root,
            parent_uid=_ROOT_FOLDER_UID,
            children_by_parent=children_by_parent,
            conditions_by_folder=conditions_by_folder,
            contexts=contexts,
            conditions=conditions,
            grouping=grouping,
            page_labels=page_labels,
            page_sorts=page_sorts,
            area_labels=area_labels,
            area_sorts=area_sorts,
            metric=metric,
        )
        direct_conditions = conditions_by_folder.get(_ROOT_FOLDER_UID, [])
        if direct_conditions:
            root.children.extend(
                self._build_grouped_nodes(
                    direct_conditions,
                    contexts,
                    conditions,
                    grouping,
                    page_labels,
                    page_sorts,
                    area_labels,
                    area_sorts,
                    metric,
                )
            )
        return root

    def _build_takeoff_contexts(
        self, conditions: Dict[str, Condition], takeoffs: Sequence[Takeoff]
    ) -> List[_SummaryTakeoffContext]:
        children_by_parent: Dict[str, List[Takeoff]] = defaultdict(list)
        for takeoff in takeoffs:
            parent_uid = str(takeoff.parent_uid or "")
            if parent_uid not in _PRIMARY_PARENT_VALUES:
                children_by_parent[parent_uid].append(takeoff)
        contexts: List[_SummaryTakeoffContext] = []
        for takeoff in takeoffs:
            parent_uid = str(takeoff.parent_uid or "")
            if parent_uid not in _PRIMARY_PARENT_VALUES:
                continue
            condition_uid = str(takeoff.condition_uid or "")
            if condition_uid not in conditions:
                continue
            page_uid = str(takeoff.page_uid or "") or _NO_PAGE_UID
            area_uid = normalize_area_uid(takeoff.area_uid)
            contexts.append(
                _SummaryTakeoffContext(
                    condition_uid=condition_uid,
                    page_uid=page_uid,
                    area_uid=area_uid,
                    takeoffs=(takeoff, *children_by_parent.get(takeoff.uid, [])),
                )
            )
        return contexts

    def _conditions_by_folder(
        self,
        conditions: Dict[str, Condition],
        folders: Dict[str, BidConditionFolder],
    ) -> Dict[Optional[str], List[Condition]]:
        result: Dict[Optional[str], List[Condition]] = defaultdict(list)
        for condition in conditions.values():
            folder_uid = condition.folder_uid
            key = (
                folder_uid if folder_uid and folder_uid in folders else _ROOT_FOLDER_UID
            )
            result[key].append(condition)
        for folder_conditions in result.values():
            folder_conditions.sort(key=self._condition_sort_key)
        return result

    def _folders_by_parent(
        self, folders: Dict[str, BidConditionFolder]
    ) -> Dict[Optional[str], List[BidConditionFolder]]:
        result: Dict[Optional[str], List[BidConditionFolder]] = defaultdict(list)
        for folder in folders.values():
            parent_uid = (
                folder.parent_uid if folder.parent_uid in folders else _ROOT_FOLDER_UID
            )
            result[parent_uid].append(folder)
        for children in result.values():
            children.sort(key=lambda folder: ((folder.name or "").lower(), folder.uid))
        return result

    def _append_folder_nodes(
        self,
        parent_node: ConditionSummaryNode,
        *,
        parent_uid: Optional[str],
        children_by_parent: Dict[Optional[str], List[BidConditionFolder]],
        conditions_by_folder: Dict[Optional[str], List[Condition]],
        contexts: Sequence[_SummaryTakeoffContext],
        conditions: Dict[str, Condition],
        grouping: ConditionSummaryGrouping,
        page_labels: Dict[str, str],
        page_sorts: Dict[str, Tuple[int, str]],
        area_labels: Dict[str, str],
        area_sorts: Dict[str, Tuple[int, str]],
        metric: bool,
    ) -> None:
        for folder in children_by_parent.get(parent_uid, []):
            folder_node = ConditionSummaryNode(
                kind=SUMMARY_NODE_FOLDER,
                label=folder.name or "",
                folder_uid=folder.uid,
            )
            self._append_folder_nodes(
                folder_node,
                parent_uid=folder.uid,
                children_by_parent=children_by_parent,
                conditions_by_folder=conditions_by_folder,
                contexts=contexts,
                conditions=conditions,
                grouping=grouping,
                page_labels=page_labels,
                page_sorts=page_sorts,
                area_labels=area_labels,
                area_sorts=area_sorts,
                metric=metric,
            )
            folder_conditions = conditions_by_folder.get(folder.uid, [])
            if folder_conditions:
                folder_node.children.extend(
                    self._build_grouped_nodes(
                        folder_conditions,
                        contexts,
                        conditions,
                        grouping,
                        page_labels,
                        page_sorts,
                        area_labels,
                        area_sorts,
                        metric,
                    )
                )
            if folder_node.children:
                parent_node.children.append(folder_node)

    def _build_grouped_nodes(
        self,
        scoped_conditions: Sequence[Condition],
        contexts: Sequence[_SummaryTakeoffContext],
        conditions: Dict[str, Condition],
        grouping: ConditionSummaryGrouping,
        page_labels: Dict[str, str],
        page_sorts: Dict[str, Tuple[int, str]],
        area_labels: Dict[str, str],
        area_sorts: Dict[str, Tuple[int, str]],
        metric: bool,
    ) -> List[ConditionSummaryNode]:
        condition_uids = {condition.uid for condition in scoped_conditions}
        scoped_contexts = [
            context for context in contexts if context.condition_uid in condition_uids
        ]
        return self._build_level_nodes(
            scoped_contexts,
            conditions,
            grouping.active_levels(),
            grouping,
            page_labels,
            page_sorts,
            area_labels,
            area_sorts,
            metric,
        )

    def _build_level_nodes(
        self,
        contexts: Sequence[_SummaryTakeoffContext],
        conditions: Dict[str, Condition],
        levels: Tuple[str, ...],
        grouping: ConditionSummaryGrouping,
        page_labels: Dict[str, str],
        page_sorts: Dict[str, Tuple[int, str]],
        area_labels: Dict[str, str],
        area_sorts: Dict[str, Tuple[int, str]],
        metric: bool,
    ) -> List[ConditionSummaryNode]:
        if not levels:
            return self._build_condition_nodes(
                contexts, conditions, grouping, area_labels, area_sorts, metric
            )
        level = levels[0]
        buckets: Dict[str, List[_SummaryTakeoffContext]] = defaultdict(list)
        for context in contexts:
            buckets[self._group_key(context, conditions, level)].append(context)
        nodes: List[ConditionSummaryNode] = []
        for key, bucket in sorted(
            buckets.items(),
            key=lambda item: self._group_sort_key(
                item[0],
                item[1],
                conditions,
                level,
                page_labels,
                page_sorts,
                area_labels,
                area_sorts,
            ),
        ):
            group_node = ConditionSummaryNode(
                kind=SUMMARY_NODE_GROUP,
                label=self._group_label(
                    key, bucket, conditions, level, page_labels, area_labels
                ),
                group_level=level,
            )
            group_node.children.extend(
                self._build_level_nodes(
                    bucket,
                    conditions,
                    levels[1:],
                    grouping,
                    page_labels,
                    page_sorts,
                    area_labels,
                    area_sorts,
                    metric,
                )
            )
            nodes.append(group_node)
        return nodes

    def _build_condition_nodes(
        self,
        contexts: Sequence[_SummaryTakeoffContext],
        conditions: Dict[str, Condition],
        grouping: ConditionSummaryGrouping,
        area_labels: Dict[str, str],
        area_sorts: Dict[str, Tuple[int, str]],
        metric: bool,
    ) -> List[ConditionSummaryNode]:
        contexts_by_condition: Dict[str, List[_SummaryTakeoffContext]] = defaultdict(
            list
        )
        for context in contexts:
            contexts_by_condition[context.condition_uid].append(context)
        nodes: List[ConditionSummaryNode] = []
        for condition_uid in sorted(
            contexts_by_condition,
            key=lambda uid: self._condition_sort_key(conditions[uid]),
        ):
            condition = conditions[condition_uid]
            condition_contexts = contexts_by_condition[condition_uid]
            if grouping.by_area:
                quantities = self._quantities_for_contexts(
                    conditions, condition_uid, condition_contexts
                )
                nodes.append(
                    self._make_condition_node(
                        condition, "", quantities, metric, SUMMARY_NODE_CONDITION
                    )
                )
                continue
            contexts_by_area: Dict[str, List[_SummaryTakeoffContext]] = defaultdict(
                list
            )
            for context in condition_contexts:
                contexts_by_area[context.area_uid].append(context)
            if len(contexts_by_area) > 1:
                total_quantities = self._quantities_for_contexts(
                    conditions, condition_uid, condition_contexts
                )
                parent = self._make_condition_node(
                    condition,
                    SUMMARY_MULTI_AREA_TOTAL_LABEL,
                    total_quantities,
                    metric,
                    SUMMARY_NODE_MULTI_AREA_TOTAL,
                    bold_columns=(SUMMARY_COLUMN_AREA, *SUMMARY_QUANTITY_COLUMNS),
                )
                for area_uid, area_contexts in sorted(
                    contexts_by_area.items(),
                    key=lambda item: area_sorts.get(
                        item[0],
                        (
                            _SORT_LAST_SEQUENCE,
                            area_labels.get(item[0], SUMMARY_UNASSIGNED_LABEL).lower(),
                        ),
                    ),
                ):
                    parent.children.append(
                        self._make_area_detail_node(
                            condition,
                            area_labels.get(area_uid, SUMMARY_UNASSIGNED_LABEL),
                            self._quantities_for_contexts(
                                conditions, condition_uid, area_contexts
                            ),
                        )
                    )
                nodes.append(parent)
                continue
            area_uid = next(iter(contexts_by_area), UNASSIGNED_AREA_UID)
            quantities = self._quantities_for_contexts(
                conditions, condition_uid, condition_contexts
            )
            nodes.append(
                self._make_condition_node(
                    condition,
                    area_labels.get(area_uid, SUMMARY_UNASSIGNED_LABEL),
                    quantities,
                    metric,
                    SUMMARY_NODE_CONDITION,
                )
            )
        return nodes

    def _make_condition_node(
        self,
        condition: Condition,
        area_label: str,
        quantities: Tuple[float, float, float],
        metric: bool,
        kind: str,
        bold_columns: Tuple[str, ...] = (),
    ) -> ConditionSummaryNode:
        return ConditionSummaryNode(
            kind=kind,
            condition_uid=condition.uid,
            values=self._condition_values(condition, area_label, quantities, metric),
            bold_columns=bold_columns,
            copyable=True,
            deletable=True,
            color_fill=condition.color_fill,
            pattern=condition.pattern,
            layer_visible=condition.layer_visible,
        )

    def _make_area_detail_node(
        self,
        condition: Condition,
        area_label: str,
        quantities: Tuple[float, float, float],
    ) -> ConditionSummaryNode:
        return ConditionSummaryNode(
            kind=SUMMARY_NODE_AREA_DETAIL,
            condition_uid=condition.uid,
            values=ConditionSummaryValues(
                area=area_label,
                quantity1=quantities[0],
                uom1=condition.uom1,
                quantity2=quantities[1],
                uom2=condition.uom2,
                quantity3=quantities[2],
                uom3=condition.uom3,
            ),
            copyable=True,
            deletable=False,
        )

    def _condition_values(
        self,
        condition: Condition,
        area_label: str,
        quantities: Tuple[float, float, float],
        metric: bool,
    ) -> ConditionSummaryValues:
        return ConditionSummaryValues(
            number=str(condition.ref_no) if condition.ref_no else "",
            name=condition.name or "",
            type_name=condition.cdn_type_name or SUMMARY_UNASSIGNED_LABEL,
            height=inches_to_display(float(condition.height or 0.0), metric),
            height_inches=float(condition.height or 0.0),
            area=area_label,
            quantity1=quantities[0],
            uom1=condition.uom1,
            quantity2=quantities[1],
            uom2=condition.uom2,
            quantity3=quantities[2],
            uom3=condition.uom3,
            notes=condition.notes or "",
        )

    def _quantities_for_contexts(
        self,
        conditions: Dict[str, Condition],
        condition_uid: str,
        contexts: Sequence[_SummaryTakeoffContext],
    ) -> Tuple[float, float, float]:
        takeoffs = [takeoff for context in contexts for takeoff in context.takeoffs]
        quantities = compute_page_quantities(conditions, takeoffs, {condition_uid})
        return quantities[condition_uid]

    def _group_key(
        self,
        context: _SummaryTakeoffContext,
        conditions: Dict[str, Condition],
        level: str,
    ) -> str:
        if level == SUMMARY_GROUP_PAGE:
            return context.page_uid or _NO_PAGE_UID
        if level == SUMMARY_GROUP_AREA:
            return normalize_area_uid(context.area_uid)
        if level == SUMMARY_GROUP_TYPE:
            condition = conditions[context.condition_uid]
            return str(condition.cdn_type_uid or "")
        raise ValueError(f"Unknown summary grouping level: {level!r}")

    def _group_label(
        self,
        key: str,
        bucket: Sequence[_SummaryTakeoffContext],
        conditions: Dict[str, Condition],
        level: str,
        page_labels: Dict[str, str],
        area_labels: Dict[str, str],
    ) -> str:
        if level == SUMMARY_GROUP_PAGE:
            return page_labels.get(key, f"Page {key}")
        if level == SUMMARY_GROUP_AREA:
            return area_labels.get(key, SUMMARY_UNASSIGNED_LABEL)
        if level == SUMMARY_GROUP_TYPE:
            first_condition = conditions[bucket[0].condition_uid]
            if first_condition.cdn_type_uid:
                return first_condition.cdn_type_name or SUMMARY_UNASSIGNED_LABEL
            return SUMMARY_UNASSIGNED_LABEL
        raise ValueError(f"Unknown summary grouping level: {level!r}")

    def _group_sort_key(
        self,
        key: str,
        bucket: Sequence[_SummaryTakeoffContext],
        conditions: Dict[str, Condition],
        level: str,
        page_labels: Dict[str, str],
        page_sorts: Dict[str, Tuple[int, str]],
        area_labels: Dict[str, str],
        area_sorts: Dict[str, Tuple[int, str]],
    ) -> Tuple:
        if level == SUMMARY_GROUP_PAGE:
            return page_sorts.get(
                key, (_SORT_LAST_SEQUENCE, page_labels.get(key, key).lower())
            )
        if level == SUMMARY_GROUP_AREA:
            return area_sorts.get(
                key, (_SORT_LAST_SEQUENCE, area_labels.get(key, key).lower())
            )
        if level == SUMMARY_GROUP_TYPE:
            label = self._group_label(
                key, bucket, conditions, level, page_labels, area_labels
            )
            return (label.lower(), key)
        raise ValueError(f"Unknown summary grouping level: {level!r}")

    def _page_metadata(
        self, pages: Sequence[Page]
    ) -> Tuple[Dict[str, str], Dict[str, Tuple[int, str]]]:
        labels = {_NO_PAGE_UID: SUMMARY_NO_PAGE_LABEL, "": SUMMARY_NO_PAGE_LABEL}
        sorts = {_NO_PAGE_UID: (_SORT_LAST_SEQUENCE, SUMMARY_NO_PAGE_LABEL.lower())}
        for page in pages:
            uid = str(page.uid or _NO_PAGE_UID)
            label = page.name or f"Page {uid}"
            labels[uid] = label
            sorts[uid] = (int(page.sequence or 0), label.lower())
        return labels, sorts

    def _area_metadata(
        self, areas: Sequence[BidArea]
    ) -> Tuple[Dict[str, str], Dict[str, Tuple[int, str]]]:
        labels = {
            "": SUMMARY_UNASSIGNED_LABEL,
            UNASSIGNED_AREA_UID: SUMMARY_UNASSIGNED_LABEL,
        }
        sorts = {
            "": (_SORT_LAST_SEQUENCE, SUMMARY_UNASSIGNED_LABEL),
            UNASSIGNED_AREA_UID: (_SORT_LAST_SEQUENCE, SUMMARY_UNASSIGNED_LABEL),
        }
        for area in areas:
            uid = normalize_area_uid(area.uid)
            label = area.name or SUMMARY_UNASSIGNED_LABEL
            labels[uid] = label
            sorts[uid] = (int(area.sequence or 0), label.lower())
        return labels, sorts

    @staticmethod
    def _condition_sort_key(condition: Condition) -> Tuple[int, str, str]:
        return (
            int(condition.ref_no or 0),
            (condition.name or "").lower(),
            condition.uid,
        )
