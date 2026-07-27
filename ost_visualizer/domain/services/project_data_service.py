from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple
from ...domain.aggregates.ost_aggregate import OstAggregate
from ...domain.entities.area import BidArea, is_unassigned_area_uid, normalize_area_uid
from ...domain.entities.bid import Bid
from ...domain.entities.cdn_type import CdnType
from ...domain.entities.condition import Condition
from ...domain.entities.hierarchy_data import HierarchyData, HierarchyFileEntry
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.file_results import BidLoadResult
from ...domain.entities.page import Page
from ...domain.entities.project_factory import build_bid, build_projects
from ...domain.entities.takeoff import Takeoff
from ..entities.annotation import BidAnnotation
from ..entities.condition_folder import BidConditionFolder
from ..entities.layer import (
    ANNOTATION_LAYER_NAME,
    IMAGE_LAYER_NAME,
    BidLayer,
    Layer,
    LayerSet,
    is_comments_layer_name,
    merge_layers_for_bid,
    normalize_layer_name,
)
from .condition_quantity_service import compute_page_quantities
from .takeoff_domain_service import (
    is_takeoff_relevant_for_area_usage,
    is_takeoff_visible,
    takeoffs_can_reassign_to_condition,
)


@dataclass
class CollectedTakeoffsResult:
    takeoffs: List[Takeoff] = field(default_factory=list)
    valid_page_uids: List[str] = field(default_factory=list)
    page_count: int = 0
    total_takeoffs: int = 0

    def __post_init__(self) -> None:
        if self.page_count == 0:
            self.page_count = len(self.valid_page_uids)
        if self.total_takeoffs == 0:
            self.total_takeoffs = len(self.takeoffs)

    def is_empty(self) -> bool:
        return not self.takeoffs


class ProjectDataService:
    def __init__(self, model: OstAggregate):
        self.model = model

    def reset(self) -> None:
        self.model.clear_bid()
        self.model.cdn_types = {}
        self.model.projects = []
        self.model.set_hierarchy(HierarchyData())

    def has_loaded_files(self) -> bool:
        return bool(self.model.get_hierarchy_data().loaded_files)

    def has_takeoffs_for_pages(self, page_uids: Iterable[str]) -> bool:
        return self.model.has_takeoffs_for_pages(page_uids)

    def collect_takeoffs_for_pages(
        self, page_uids: List[str], visible_only: bool = True
    ) -> CollectedTakeoffsResult:
        all_takeoffs: List[Takeoff] = []
        valid_pages: List[str] = []
        bid_conditions = self.model.bid_conditions
        for page_uid in page_uids:
            takeoffs = self.model.get_page_takeoffs(page_uid)
            if takeoffs:
                page_takeoffs = (
                    [t for t in takeoffs if is_takeoff_visible(t, bid_conditions)]
                    if visible_only
                    else list(takeoffs)
                )
                if page_takeoffs:
                    all_takeoffs.extend(page_takeoffs)
                    valid_pages.append(page_uid)
        return CollectedTakeoffsResult(
            takeoffs=all_takeoffs, valid_page_uids=valid_pages
        )

    def get_selected_page_uids(self) -> List[str]:
        return self.model.get_selected_pages()

    def get_current_bid(self) -> Optional[Bid]:
        return self.model.current_bid

    def get_hierarchy(self) -> HierarchyData:
        return self.model.get_hierarchy_data()

    def replace_database_hierarchy(
        self,
        file_entry: HierarchyFileEntry,
        cdn_types: Dict[str, CdnType],
    ) -> None:
        hierarchy = self.model.file_manager.register_loaded_hierarchy(
            file_entry,
            cdn_types,
        )
        self.model.cdn_types = (
            self.model.file_manager.project_repository.get_merged_cdn_types()
        )
        self.model.set_hierarchy(hierarchy)
        self.model.projects = build_projects(hierarchy)

    def get_current_file_path(self) -> Optional[str]:
        return self.model.get_current_file_path()

    def clear_page_selection(self) -> None:
        self.model.clear_page_selection()

    def clear_bid(self) -> None:
        self.model.clear_bid()

    def deselect_pages(self) -> None:
        self.model.deselect_pages()

    def select_pages(self, page_uids: List[str]) -> List[str]:
        return self.model.select_pages(page_uids)

    def get_page(self, page_uid: str) -> Optional[Page]:
        return self.model.get_page(page_uid)

    def get_all_pages(self) -> List[Page]:
        return self.model.get_all_pages()

    def get_bid(self, bid_ref: BidRef) -> Optional[Bid]:
        if self.model.current_bid_ref == bid_ref and self.model.current_bid:
            return self.model.current_bid
        bid_info = self.model.find_bid_info(bid_ref)
        if not bid_info:
            return None
        return build_bid(bid_info)

    def get_bid_conditions(self) -> Dict[str, Condition]:
        return self.model.bid_conditions

    def replace_condition_family(
        self,
        bid_ref: BidRef,
        conditions: Dict[str, Condition],
        folders: Dict[str, BidConditionFolder],
    ) -> bool:
        if self.model.current_bid_ref != bid_ref:
            return False
        self.model.bid_conditions = dict(conditions)
        self.model.bid_condition_folders = dict(folders)
        return True

    def replace_bid_areas(self, bid_ref: BidRef, areas: Iterable[BidArea]) -> bool:
        if self.model.current_bid_ref != bid_ref:
            return False
        self.model.bid_areas = {str(area.uid): area for area in areas}
        return True

    def replace_remote_bid_families(
        self,
        bid_ref: BidRef,
        bid_data: BidLoadResult,
        families: set[str],
    ) -> bool:
        if self.model.current_bid_ref != bid_ref:
            return False
        if "takeoffs" in families:
            self.model.bid_takeoffs = list(bid_data.bid_takeoffs)
            self.model.bid_takeoff_extras = dict(bid_data.takeoff_extras)
            for page in self.model.get_all_pages():
                refreshed = bid_data.pages.get(page.uid)
                page.takeoffs = list(refreshed.takeoffs) if refreshed else []
        if "annotations" in families:
            self.model.set_annotations(list(bid_data.bid_annotations))
        if "pages" in families:
            self.model.set_pages(dict(bid_data.pages))
            self.model.page_area_selections = dict(bid_data.page_area_selections)
        if "layers" in families:
            self.set_bid_layer_visibility(bid_data.bid_layers)
        return True

    def set_bid_layer_visibility(self, layers: Iterable[BidLayer]) -> None:
        layer_list = list(layers)
        self.model.bid_layers = layer_list
        self.model.bid_layer_visibility = {}
        self.model.bid_layer_names_by_uid = {}
        self.model.bid_layer_visibility_by_name = {}
        for layer in layer_list:
            if not layer.uid:
                continue
            layer_uid = str(layer.uid)
            layer_name = normalize_layer_name(layer.name)
            visible = bool(layer.show)
            self.model.bid_layer_visibility[layer_uid] = visible
            if layer_name:
                self.model.bid_layer_names_by_uid[layer_uid] = layer_name
                self.model.bid_layer_visibility_by_name[layer_name] = visible

    def get_hidden_layer_uids(self) -> set[str]:
        return {
            layer_uid
            for layer_uid, visible in self.model.bid_layer_visibility.items()
            if not visible
        }

    def get_bid_layer_snapshot(self) -> List[BidLayer]:
        layers = list(self.model.bid_layers or [])
        if layers:
            return [
                layer
                for layer in merge_layers_for_bid(layers)
                if not is_comments_layer_name(layer.name)
            ]
        current_bid_ref = self.model.current_bid_ref
        bid_uid = current_bid_ref.bid_uid if current_bid_ref else ""
        snapshot = []
        for sequence, (layer_uid, layer_name) in enumerate(
            self.model.bid_layer_names_by_uid.items()
        ):
            if is_comments_layer_name(layer_name):
                continue
            snapshot.append(
                BidLayer(
                    uid=str(layer_uid),
                    bid_uid=bid_uid,
                    name=layer_name or str(layer_uid),
                    show=self.model.bid_layer_visibility.get(str(layer_uid), True),
                    sequence=sequence,
                )
            )
        return snapshot

    def get_layer_uids_in_use(self) -> set[str]:
        used = {
            str(condition.layer_uid)
            for takeoff in self.model.get_all_takeoffs()
            if (condition := self.model.bid_conditions.get(takeoff.condition_uid))
            and condition.layer_uid
        }
        used.update(
            str(annotation.layer_uid)
            for annotation in self.model.get_all_annotations()
            if annotation.layer_uid
        )
        return used

    def get_bid_area_snapshot(
        self, takeoffs: Optional[Iterable[Takeoff]] = None
    ) -> List[BidArea]:
        used_area_uids: Optional[set[str]] = None
        if takeoffs is not None:
            used_area_uids = {
                normalize_area_uid(takeoff.area_uid)
                for takeoff in takeoffs
                if not is_unassigned_area_uid(takeoff.area_uid)
            }
        areas = list(self.model.bid_areas.values())
        if used_area_uids is not None:
            areas = [area for area in areas if str(area.uid) in used_area_uids]
        return sorted(areas, key=lambda area: int(area.sequence or 0))

    def _set_named_layer_visibility(self, layer_uid: str, visible: bool) -> None:
        layer_name = self.model.bid_layer_names_by_uid.get(layer_uid)
        if layer_name:
            self.model.bid_layer_visibility_by_name[layer_name] = visible

    def _bid_layer_set(self) -> LayerSet:
        layers = {}
        for layer_uid, layer_name in self.model.bid_layer_names_by_uid.items():
            normalized_uid = str(layer_uid)
            layers[normalized_uid] = Layer(
                uid=normalized_uid,
                name=layer_name,
                visible=self.model.bid_layer_visibility.get(normalized_uid, True),
            )
        return LayerSet(layers)

    def is_annotation_layer_visible(self) -> bool:
        layer_set = self._bid_layer_set()
        if layer_set.annotation_layer_uid() is not None:
            return layer_set.annotation_layer_visible()
        return self.model.bid_layer_visibility_by_name.get(ANNOTATION_LAYER_NAME, True)

    def get_annotation_layer_uid(self) -> Optional[str]:
        return self._bid_layer_set().annotation_layer_uid()

    def is_image_layer_uid(self, layer_uid: str) -> bool:
        layer_name = self.model.bid_layer_names_by_uid.get(str(layer_uid))
        return normalize_layer_name(layer_name or "") == IMAGE_LAYER_NAME

    def get_image_layer_uid(self) -> Optional[str]:
        return self._bid_layer_set().uid_by_name(IMAGE_LAYER_NAME)

    def update_layer_visibility(self, layer_uid: str, show: bool) -> List[str]:
        changed_pages: List[str] = []
        layer_key = str(layer_uid)
        visible = bool(show)
        self.model.bid_layer_visibility[layer_key] = visible
        self._set_named_layer_visibility(layer_key, visible)
        for condition in self.model.bid_conditions.values():
            if str(condition.layer_uid or "") == layer_key:
                condition.layer_visible = visible
        for layer in self.model.bid_layers or []:
            if str(layer.uid) == layer_key:
                layer.show = visible
        if self.is_image_layer_uid(layer_key):
            for page in self.model.get_all_pages():
                page.layer_visible = visible
                changed_pages.append(page.uid)
        return changed_pages

    def update_all_layer_visibility(self, show: bool) -> List[str]:
        visible = bool(show)
        for layer_uid in list(self.model.bid_layer_visibility):
            self.model.bid_layer_visibility[layer_uid] = visible
            self._set_named_layer_visibility(layer_uid, visible)
        for condition in self.model.bid_conditions.values():
            condition.layer_visible = visible
        for layer in self.model.bid_layers or []:
            layer.show = visible
        changed_pages: List[str] = []
        for page in self.model.get_all_pages():
            page.layer_visible = visible
            changed_pages.append(page.uid)
        return changed_pages

    def get_page_takeoffs(self, page_uid: str) -> List[Takeoff]:
        return self.model.get_page_takeoffs(page_uid)

    def get_takeoff_extras(self, takeoff_uid: str) -> Dict[str, object]:
        return self.model.get_takeoff_extras(takeoff_uid)

    def get_page_annotations(self, page_uid: str) -> List[BidAnnotation]:
        return self.model.get_page_annotations(page_uid)

    def get_page_area_selections(self) -> Dict[str, Optional[str]]:
        return self.model.page_area_selections

    def set_current_file(self, file_path: str) -> None:
        self.model.set_current_file_path(file_path)

    def get_page_name(self, page_uid: str) -> str:
        return self.model.get_page_name(page_uid)

    def get_all_annotations(self) -> List[BidAnnotation]:
        return self.model.get_all_annotations()

    def add_annotations(self, annotations: List[BidAnnotation]) -> None:
        if annotations:
            self.model.add_annotations(annotations)

    def remove_annotations_by_keys(
        self, annotation_keys: Iterable[Tuple[str, str]]
    ) -> List[str]:
        return self.model.remove_annotations_by_keys(annotation_keys)

    def get_page_uids_for_annotation_keys(
        self, annotation_keys: Iterable[Tuple[str, str]]
    ) -> List[str]:
        wanted = {
            (str(uid), str(annotation_type)) for uid, annotation_type in annotation_keys
        }
        if not wanted:
            return []
        page_uids: List[str] = []
        seen = set()
        for annotation in self.model.get_all_annotations():
            key = (str(annotation.uid), str(annotation.annotation_type))
            if (
                key in wanted
                and annotation.page_uid
                and annotation.page_uid not in seen
            ):
                page_uids.append(annotation.page_uid)
                seen.add(annotation.page_uid)
        return page_uids

    def update_annotation_positions(
        self, positions: Iterable[Tuple[str, str, List[float]]]
    ) -> List[str]:
        changes = [
            (str(uid), str(annotation_type), list(position))
            for uid, annotation_type, position in positions
        ]
        page_uids = self.get_page_uids_for_annotation_keys(
            (uid, annotation_type) for uid, annotation_type, _pos in changes
        )
        by_key = {
            (uid, annotation_type): position
            for uid, annotation_type, position in changes
        }
        for annotation in self.model.get_all_annotations():
            position = by_key.get((annotation.uid, annotation.annotation_type))
            if position is not None:
                annotation.position = list(position)
        return page_uids

    def update_annotation_text_properties(
        self, updates: Iterable[Tuple[str, str, Dict[str, object]]]
    ) -> List[str]:
        changes = [
            (str(uid), str(annotation_type), dict(properties))
            for uid, annotation_type, properties in updates
        ]
        page_uids = self.get_page_uids_for_annotation_keys(
            (uid, annotation_type) for uid, annotation_type, _props in changes
        )
        by_key = {
            (uid, annotation_type): properties
            for uid, annotation_type, properties in changes
        }
        for annotation in self.model.get_all_annotations():
            properties = by_key.get((annotation.uid, annotation.annotation_type))
            if properties is not None:
                annotation.properties.update(properties)
        return page_uids

    def update_annotation_styles(
        self, updates: Iterable[Tuple[str, str, Dict[str, object]]]
    ) -> List[str]:
        changes = [
            (str(uid), str(annotation_type), dict(style))
            for uid, annotation_type, style in updates
        ]
        page_uids = self.get_page_uids_for_annotation_keys(
            (uid, annotation_type) for uid, annotation_type, _style in changes
        )
        by_key = {
            (uid, annotation_type): style for uid, annotation_type, style in changes
        }
        for annotation in self.model.get_all_annotations():
            style = by_key.get((annotation.uid, annotation.annotation_type))
            if style is None:
                continue
            if "Color" in style:
                annotation.color = str(style["Color"])
            if "Width" in style:
                annotation.width = float(style["Width"] or 0.0)
        return page_uids

    def update_named_view_names(self, updates: Iterable[Tuple[str, str]]) -> List[str]:
        changes = [(str(uid), str(name)) for uid, name in updates]
        by_uid = {uid: name for uid, name in changes}
        page_uids: List[str] = []
        seen_pages = set()
        if not by_uid:
            return page_uids
        for annotation in self.model.get_all_annotations():
            if not annotation.is_namedview:
                continue
            name = by_uid.get(annotation.uid)
            if name is None:
                continue
            annotation.properties["Text"] = name
            if annotation.page_uid and annotation.page_uid not in seen_pages:
                page_uids.append(annotation.page_uid)
                seen_pages.add(annotation.page_uid)
        return page_uids

    def find_hotlinks_targeting(
        self, namedview_uids: Iterable[str]
    ) -> List[BidAnnotation]:
        target_uids = {str(uid) for uid in namedview_uids if uid}
        if not target_uids:
            return []
        return [
            a
            for a in self.model.get_all_annotations()
            if a.is_hotlink and a.hotlink_target_view_uid in target_uids
        ]

    def get_current_bid_ref(self) -> Optional[BidRef]:
        return self.model.current_bid_ref

    def get_current_bid_file_path(self) -> Optional[str]:
        return self.model.current_bid_file_path

    def get_all_selected_takeoffs(self) -> List[Takeoff]:
        return self.model.get_all_selected_takeoffs()

    def is_current_bid_locked(self) -> bool:
        return self.model.current_bid_locked

    def set_current_bid_locked(self, locked: bool) -> None:
        self.model.current_bid_locked = locked

    def get_last_selected_page_uid(self) -> Optional[str]:
        return self.model.last_selected_page_uid

    def get_all_takeoffs(self) -> List[Takeoff]:
        return self.model.get_all_takeoffs()

    def add_takeoffs(self, takeoffs: List[Takeoff]) -> None:
        if not takeoffs:
            return
        self.model.bid_takeoffs.extend(takeoffs)
        for takeoff in takeoffs:
            page = self.model.get_page(takeoff.page_uid)
            if page is not None:
                page.takeoffs.append(takeoff)

    def get_page_uids_for_takeoffs(self, takeoff_uids: Iterable[str]) -> List[str]:
        wanted = {str(uid) for uid in takeoff_uids if uid}
        if not wanted:
            return []
        page_uids = []
        seen = set()
        for takeoff in self.model.get_all_takeoffs():
            if takeoff.uid in wanted and takeoff.page_uid not in seen:
                page_uids.append(takeoff.page_uid)
                seen.add(takeoff.page_uid)
        return page_uids

    def get_condition_uids_for_takeoffs(self, takeoff_uids: Iterable[str]) -> List[str]:
        wanted = {str(uid) for uid in takeoff_uids if uid}
        if not wanted:
            return []
        condition_uids = []
        seen = set()
        for takeoff in self.model.get_all_takeoffs():
            if takeoff.uid in wanted and takeoff.condition_uid not in seen:
                condition_uids.append(takeoff.condition_uid)
                seen.add(takeoff.condition_uid)
        return condition_uids

    def update_takeoffs_area(
        self, takeoff_uids: Iterable[str], area_uid: str
    ) -> List[str]:
        wanted = {str(uid) for uid in takeoff_uids if uid}
        page_uids = self.get_page_uids_for_takeoffs(wanted)
        if not wanted:
            return page_uids
        target_area_uid = normalize_area_uid(area_uid)
        for takeoff in self.model.get_all_takeoffs():
            if takeoff.uid in wanted:
                takeoff.area_uid = target_area_uid
        return page_uids

    def update_takeoffs_condition(
        self, takeoff_uids: Iterable[str], condition_uid: str
    ) -> List[str]:
        wanted = {str(uid) for uid in takeoff_uids if uid}
        if not wanted:
            return []
        all_takeoffs = self.model.get_all_takeoffs()
        selected_takeoffs = [
            takeoff for takeoff in all_takeoffs if takeoff.uid in wanted
        ]
        if {takeoff.uid for takeoff in selected_takeoffs} != wanted:
            return []
        if not takeoffs_can_reassign_to_condition(
            selected_takeoffs,
            self.model.bid_conditions,
            str(condition_uid),
        ):
            return []
        page_uids = []
        seen_page_uids = set()
        target_condition_uid = str(condition_uid)
        for takeoff in selected_takeoffs:
            takeoff.condition_uid = target_condition_uid
            if takeoff.page_uid not in seen_page_uids:
                page_uids.append(takeoff.page_uid)
                seen_page_uids.add(takeoff.page_uid)
        return page_uids

    def update_takeoffs_negative(
        self, takeoff_uids: Iterable[str], is_negative: bool
    ) -> List[str]:
        wanted = {str(uid) for uid in takeoff_uids if uid}
        page_uids = self.get_page_uids_for_takeoffs(wanted)
        if not wanted:
            return page_uids
        for takeoff in self.model.get_all_takeoffs():
            if takeoff.uid in wanted:
                takeoff.is_negative = bool(is_negative)
        return page_uids

    def update_takeoff_curve(
        self, takeoff_uid: str, position: List[float], curve: int
    ) -> List[str]:
        page_uids = self.get_page_uids_for_takeoffs([takeoff_uid])
        for takeoff in self.model.get_all_takeoffs():
            if takeoff.uid == str(takeoff_uid):
                takeoff.position = list(position)
                takeoff.curve = int(curve)
                break
        return page_uids

    def update_takeoff_positions(
        self, positions: Iterable[Tuple[str, List[float]]]
    ) -> List[str]:
        changes = [(str(uid), list(position)) for uid, position in positions]
        page_uids = self.get_page_uids_for_takeoffs(uid for uid, _ in changes)
        by_uid = {uid: position for uid, position in changes}
        for takeoff in self.model.get_all_takeoffs():
            position = by_uid.get(takeoff.uid)
            if position is not None:
                takeoff.position = position
        return page_uids

    def update_takeoff_rotations(
        self, rotations: Iterable[Tuple[str, float]]
    ) -> List[str]:
        changes = [(str(uid), rotation) for uid, rotation in rotations]
        page_uids = self.get_page_uids_for_takeoffs(uid for uid, _ in changes)
        by_uid = {uid: rotation for uid, rotation in changes}
        for takeoff in self.model.get_all_takeoffs():
            if takeoff.uid in by_uid:
                takeoff.rotation = by_uid[takeoff.uid]
        return page_uids

    def update_takeoff_text_properties(
        self, updates: Iterable[Tuple[str, Dict[str, object]]]
    ) -> List[str]:
        changes = [(str(uid), dict(properties)) for uid, properties in updates]
        page_uids = self.get_page_uids_for_takeoffs(uid for uid, _ in changes)
        by_uid = {uid: properties for uid, properties in changes}
        for takeoff in self.model.get_all_takeoffs():
            properties = by_uid.get(takeoff.uid)
            if properties is not None:
                self._apply_takeoff_text_properties(takeoff, properties)
        return page_uids

    def _apply_takeoff_text_properties(
        self, takeoff: Takeoff, properties: Dict[str, object]
    ) -> None:
        if "dimension_font_name" in properties:
            takeoff.dimension_font_name = str(properties["dimension_font_name"])
        if "dimension_font_color" in properties:
            takeoff.dimension_font_color = int(properties["dimension_font_color"])
        if "dimension_font_size" in properties:
            takeoff.dimension_font_size = int(properties["dimension_font_size"])
        if "dimension_font_bold" in properties:
            takeoff.dimension_font_bold = bool(properties["dimension_font_bold"])
        if "dimension_font_italic" in properties:
            takeoff.dimension_font_italic = bool(properties["dimension_font_italic"])
        if "dimension_font_underline" in properties:
            takeoff.dimension_font_underline = bool(
                properties["dimension_font_underline"]
            )
        if "name_font_name" in properties:
            takeoff.name_font_name = str(properties["name_font_name"])
        if "name_font_color" in properties:
            takeoff.name_font_color = int(properties["name_font_color"])
        if "name_font_size" in properties:
            takeoff.name_font_size = int(properties["name_font_size"])
        if "name_font_bold" in properties:
            takeoff.name_font_bold = bool(properties["name_font_bold"])
        if "name_font_italic" in properties:
            takeoff.name_font_italic = bool(properties["name_font_italic"])
        if "name_font_underline" in properties:
            takeoff.name_font_underline = bool(properties["name_font_underline"])

    def remove_takeoffs(self, takeoff_uids: Iterable[str]) -> List[str]:
        wanted = {str(uid) for uid in takeoff_uids if uid}
        if not wanted:
            return []
        page_uids = self.get_page_uids_for_takeoffs(wanted)
        self.model.bid_takeoffs = [
            takeoff for takeoff in self.model.bid_takeoffs if takeoff.uid not in wanted
        ]
        for takeoff_uid in wanted:
            self.model.bid_takeoff_extras.pop(takeoff_uid, None)
        for page_uid in page_uids:
            page = self.model.get_page(page_uid)
            if page is not None:
                page.takeoffs = [
                    takeoff for takeoff in page.takeoffs if takeoff.uid not in wanted
                ]
        return page_uids

    def get_takeoff(self, uid: str) -> Optional[Takeoff]:
        for t in self.model.get_all_takeoffs():
            if t.uid == uid:
                return t
        return None

    def get_condition(self, uid: str) -> Optional[Condition]:
        return self.model.bid_conditions.get(uid)

    def get_area_uids_with_takeoff(self) -> set:
        bid_conditions = self.model.bid_conditions
        return {
            normalize_area_uid(t.area_uid)
            for t in self.model.get_all_takeoffs()
            if is_takeoff_relevant_for_area_usage(t, bid_conditions)
        }

    def get_assigned_area_uids_with_stored_takeoff(self) -> set:
        return {
            normalize_area_uid(t.area_uid)
            for t in self.model.get_all_takeoffs()
            if not is_unassigned_area_uid(t.area_uid)
        }

    def get_area_uids_with_takeoff_for_page(self, page_uid: str) -> set:
        page = self.model.get_page(page_uid)
        if not page:
            return set()
        bid_conditions = self.model.bid_conditions
        return {
            normalize_area_uid(t.area_uid)
            for t in page.takeoffs
            if is_takeoff_relevant_for_area_usage(t, bid_conditions)
        }

    def get_bid_condition_folders(self) -> Dict[str, BidConditionFolder]:
        return self.model.bid_condition_folders

    def get_cdn_types(self) -> dict:
        return self.model.cdn_types

    def find_project_uid_for_bid(self, bid_ref: BidRef) -> Optional[str]:
        hierarchy = self.model.get_hierarchy_data()
        for file_entry in hierarchy.loaded_files:
            if file_entry.file_path != bid_ref.file_path:
                continue
            for project_uid, project_info in file_entry.bid_projects.items():
                if any(b.uid == bid_ref.bid_uid for b in project_info.bids):
                    return project_uid
        return None

    def compute_quantities_for_pages(
        self, page_uids: List[str], only_condition_uids: Optional[set] = None
    ) -> Dict[str, Tuple[float, float, float]]:
        conditions = self.model.bid_conditions
        all_takeoffs: List[Takeoff] = []
        for uid in page_uids:
            all_takeoffs.extend(self.model.get_page_takeoffs(uid))
        return compute_page_quantities(conditions, all_takeoffs, only_condition_uids)

    def project_has_bids(
        self, project_uid: str, file_path: Optional[str] = None
    ) -> bool:
        hierarchy = self.model.get_hierarchy_data()
        for file_entry in hierarchy.loaded_files:
            if file_path is not None and file_entry.file_path != file_path:
                continue
            project_info = file_entry.bid_projects.get(project_uid)
            if project_info is not None:
                return len(project_info.bids) > 0
        return False

    def project_exists(self, project_uid: str, file_path: str) -> bool:
        hierarchy = self.model.get_hierarchy_data()
        return any(
            file_entry.file_path == file_path and project_uid in file_entry.bid_projects
            for file_entry in hierarchy.loaded_files
        )

    def get_project_bid_uids(
        self, file_path: str, project_uids: Iterable[str]
    ) -> List[str]:
        wanted = set(project_uids)
        hierarchy = self.model.get_hierarchy_data()
        for file_entry in hierarchy.loaded_files:
            if file_entry.file_path != file_path:
                continue
            return [
                bid.uid
                for project_uid, project in file_entry.bid_projects.items()
                if project_uid in wanted
                for bid in project.bids
            ]
        return []
