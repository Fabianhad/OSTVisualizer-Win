import logging
from typing import Dict, List, Optional
from PySide6 import QtWidgets
from ...application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ...application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ...application.dtos.paste_ref_remap_dto import PasteRefRemap
from ...application.events.app_events import AppEvents
from ...domain.entities.annotation import BidAnnotation, int_color_to_hex
from ...domain.entities.named_view import (
    build_named_view_from_annotation,
    normalize_named_view_position,
)
from ...domain.entities.takeoff import Takeoff
from ..dialogs.select_named_view_dialog import SelectNamedViewDialog
from ..managers.ui_access_manager import Feature
from ..resolvers.entity_resolver import EntityResolver
from ..services.selection_clipboard_service import SelectionClipboardService
from ..services.selection_commands import (
    DeleteAnnotationsCommand,
    DeleteTakeoffsCommand,
    InsertTakeoffsCommand,
    PasteAnnotationsCommand,
    PasteTakeoffsCommand,
)
from ..utils.annotation_delete import (
    NAMED_VIEW_HOTLINK_DELETE_MESSAGE,
    order_annotations_for_delete,
)
from ..utils.annotation_defaults import (
    build_placed_annotation_spec,
)
from ..utils.messagebox import confirm
from ..utils.named_view_validation import (
    named_view_name_exists,
    show_duplicate_named_view_name,
)

logger = logging.getLogger(__name__)
_SAME_BID_FAST_TAKEOFF_EXTRA_COLUMNS = frozenset(
    {
        "BidZoneUID",
        "BidTypAreaUID",
        "No",
        "Quantity",
        "Count",
        "GridOffsetX",
        "GridOffsetY",
        "GridRotation",
        "FontName",
        "FontColor",
        "FontSize",
        "FontBold",
        "FontItalic",
        "FontUnderline",
        "TypGroupTakeoffUID",
        "TypPageTakeoffUID",
        "TakeoffModified",
        "TypGroupUID",
        "TypGroupMarkerUID",
        "FlipX",
        "FlipY",
        "GUID",
        "NameFontName",
        "NameFontColor",
        "NameFontSize",
        "NameFontBold",
        "NameFontItalic",
        "NameFontUnderline",
    }
)


class PlanViewActionHandler:
    def __init__(
        self,
        plan_view,
        ui_state_manager,
        project_data_svc,
        project_write_svc,
        annotation_write_svc,
        page_settings_bar,
        undo_svc,
        event_bus,
        ui_access_manager=None,
    ):
        self._plan_view = plan_view
        self._ui_state = ui_state_manager
        self._data_svc = project_data_svc
        self._write_svc = project_write_svc
        self._ann_write_svc = annotation_write_svc
        self._page_settings_bar = page_settings_bar
        self._undo_svc = undo_svc
        self._event_bus = event_bus
        self._ui_access_manager = ui_access_manager
        self._clipboard_svc = SelectionClipboardService()
        self._resolver = EntityResolver(plan_view, project_data_svc)

    def _is_allowed(self, feature: Feature) -> bool:
        return bool(
            self._ui_access_manager is None
            or self._ui_access_manager.is_allowed(feature)
        )

    def connect_signals(self) -> None:
        pv = self._plan_view
        pv.set_overlay_rect_save_handler(self.save_current_page_overlay_rect)
        pv.assign_to_area_requested.connect(self.on_assign_to_area)
        pv.reassign_condition_requested.connect(self.on_reassign_condition)
        pv.set_negative_requested.connect(self.on_set_negative)
        pv.set_curved_requested.connect(self.on_set_curved)
        pv.positions_flushed.connect(self.on_positions_flushed)
        pv.annotation_text_properties_flushed.connect(
            self.on_annotation_text_properties_flushed
        )
        pv.annotation_text_and_positions_flushed.connect(
            self.on_annotation_text_and_positions_flushed
        )
        pv.annotation_styles_flushed.connect(self.on_annotation_styles_flushed)
        pv.condition_text_properties_flushed.connect(
            self.on_condition_text_properties_flushed
        )
        pv.rotations_flushed.connect(self.on_rotations_flushed)
        pv.group_rotation_flushed.connect(self.on_group_rotation_flushed)
        pv.takeoff_created.connect(self.on_takeoff_created)
        pv.annotation_created.connect(self.on_annotation_created)
        pv.text_annotation_created.connect(self.on_text_annotation_created)
        pv.named_view_created.connect(self.on_named_view_created)
        pv.hotlink_placement_requested.connect(self.on_hotlink_placement_requested)
        pv.set_named_view_name_validator(self._validate_named_view_name)
        pv.hole_created.connect(self.on_hole_created)
        pv.elements_deleted.connect(self.on_elements_deleted)
        pv.undo_requested.connect(self._undo_svc.undo)
        pv.redo_requested.connect(self._undo_svc.redo)
        pv.copy_requested.connect(self.on_copy_requested)
        pv.paste_requested.connect(self.on_paste_requested)
        pv.paste_backouts_placed.connect(self.on_paste_backouts_placed)

    def save_current_page_overlay_rect(self, overlay_rect: tuple):
        if not self._is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return None
        bid_ref = self._ui_state.get_selected_bid_ref()
        page_uid = self._ui_state.active_page_uid
        if not bid_ref or not page_uid:
            return None
        result = self._write_svc.save_page_overlay_rect_result(
            bid_ref.file_path, page_uid, overlay_rect
        )
        if result.write_success:
            page = self._data_svc.get_page(page_uid)
            if page is not None:
                page.overlay_rect = tuple(float(value) for value in overlay_rect)
        return result

    def can_paste_to_current_bid(self) -> bool:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return False
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not self._clipboard_svc.has_content():
            return False
        if self._clipboard_svc.source_file_path != bid_ref.file_path:
            return False
        if self._clipboard_svc.source_bid_uid == bid_ref.bid_uid:
            return True
        return bool(self._clipboard_svc.items)

    def on_condition_text_properties_flushed(self, changes: list) -> None:
        if not changes or not self._is_allowed(Feature.EDIT_CONDITION):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return
        new_updates = [
            (takeoff_uid, dict(new_props))
            for takeoff_uid, _label_kind, _old_props, new_props in changes
        ]
        if not self._write_svc.save_takeoff_text_properties(
            bid_ref.file_path, new_updates, reload_database=False
        ):
            self._plan_view.restore_condition_text_properties(changes)
            return
        page_uids = self._data_svc.update_takeoff_text_properties(new_updates)
        self._publish_takeoffs_changed_for_pages(
            page_uids, [uid for uid, _props in new_updates]
        )

    def _takeoff_uids_only(self, uids: list) -> list:
        return [u for u in uids if self._resolver.resolve_takeoff(u)]

    def _publish_takeoffs_changed_for_pages(
        self, page_uids: List[str], takeoff_uids: List[str]
    ) -> None:
        seen = set()
        for page_uid in page_uids:
            if not page_uid or page_uid in seen:
                continue
            seen.add(page_uid)
            self._event_bus.publish(
                AppEvents.TAKEOFFS_CHANGED,
                page_uid=page_uid,
                takeoff_uids=takeoff_uids,
            )

    def _save_takeoff_positions_fast(
        self, db_path: str, positions: List[tuple]
    ) -> bool:
        if not positions:
            return True
        if not self._write_svc.save_takeoff_positions(
            db_path, positions, reload_database=False
        ):
            return False
        page_uids = self._data_svc.update_takeoff_positions(positions)
        self._publish_takeoffs_changed_for_pages(
            page_uids, [uid for uid, _position in positions]
        )
        return True

    def _save_takeoff_rotations_fast(
        self, db_path: str, rotations: List[tuple]
    ) -> bool:
        if not rotations:
            return True
        if not self._write_svc.save_takeoff_rotations(
            db_path, rotations, reload_database=False
        ):
            return False
        page_uids = self._data_svc.update_takeoff_rotations(rotations)
        self._publish_takeoffs_changed_for_pages(
            page_uids, [uid for uid, _rotation in rotations]
        )
        return True

    def _publish_saved_takeoff_position_rotation_changes(
        self, positions: List[tuple], rotations: List[tuple]
    ) -> None:
        page_uids = []
        if positions:
            page_uids.extend(self._data_svc.update_takeoff_positions(positions))
        if rotations:
            page_uids.extend(self._data_svc.update_takeoff_rotations(rotations))
        changed_uids = [uid for uid, _position in positions]
        changed_uids.extend(uid for uid, _rotation in rotations)
        self._publish_takeoffs_changed_for_pages(page_uids, changed_uids)

    def _save_takeoff_position_rotation_fast(
        self,
        db_path: str,
        positions: List[tuple],
        rotations: List[tuple],
    ) -> bool:
        if positions and not self._write_svc.save_takeoff_positions(
            db_path, positions, reload_database=False
        ):
            return False
        if rotations and not self._write_svc.save_takeoff_rotations(
            db_path, rotations, reload_database=False
        ):
            return False
        self._publish_saved_takeoff_position_rotation_changes(positions, rotations)
        return True

    def _save_annotation_positions_fast(
        self, db_path: str, positions: List[tuple]
    ) -> bool:
        if not positions:
            return True
        if not self._ann_write_svc.save_annotation_positions(
            db_path, positions, reload_database=False
        ):
            return False
        page_uids = self._data_svc.update_annotation_positions(positions)
        self._publish_annotations_changed_for_pages(
            page_uids,
            self._annotation_uids_from_changes(positions),
            self._annotation_types_from_changes(positions),
        )
        return True

    def _save_annotation_text_properties_fast(
        self, db_path: str, updates: List[tuple]
    ) -> bool:
        if not updates:
            return True
        if not self._ann_write_svc.save_annotation_text_properties(
            db_path, updates, reload_database=False
        ):
            return False
        page_uids = self._data_svc.update_annotation_text_properties(updates)
        self._publish_annotations_changed_for_pages(
            page_uids,
            self._annotation_uids_from_changes(updates),
            self._annotation_types_from_changes(updates),
        )
        return True

    def _save_annotation_styles_fast(self, db_path: str, updates: List[tuple]) -> bool:
        if not updates:
            return True
        if not self._ann_write_svc.save_annotation_styles(
            db_path, updates, reload_database=False
        ):
            return False
        page_uids = self._data_svc.update_annotation_styles(updates)
        self._publish_annotations_changed_for_pages(
            page_uids,
            self._annotation_uids_from_changes(updates),
            self._annotation_types_from_changes(updates),
        )
        return True

    def _save_annotation_text_and_positions_fast(
        self, db_path: str, updates: List[tuple], positions: List[tuple]
    ) -> bool:
        if not updates and not positions:
            return True
        if not self._ann_write_svc.save_annotation_text_properties_and_positions(
            db_path, updates, positions, reload_database=False
        ):
            return False
        page_uids = []
        if updates:
            page_uids.extend(self._data_svc.update_annotation_text_properties(updates))
        if positions:
            page_uids.extend(self._data_svc.update_annotation_positions(positions))
        annotation_uids = self._annotation_uids_from_changes(updates)
        annotation_uids.extend(self._annotation_uids_from_changes(positions))
        annotation_types = self._annotation_types_from_changes(updates)
        annotation_types.extend(self._annotation_types_from_changes(positions))
        self._publish_annotations_changed_for_pages(
            page_uids, annotation_uids, annotation_types
        )
        return True

    def _push_position_undo_for_committed_partial(
        self,
        db_path: str,
        t_old: List[tuple],
        t_new: List[tuple],
        a_old: Optional[List[tuple]] = None,
        a_new: Optional[List[tuple]] = None,
    ) -> None:
        a_old = a_old or []
        a_new = a_new or []
        if not (t_old or a_old):
            return

        def _save_takeoff_positions(positions: List[tuple]) -> None:
            if not positions:
                return
            self._save_takeoff_positions_fast(db_path, positions)

        def _undo_partial():
            _save_takeoff_positions(t_old)
            if a_old:
                self._save_annotation_positions_fast(db_path, a_old)

        def _redo_partial():
            _save_takeoff_positions(t_new)
            if a_new:
                self._save_annotation_positions_fast(db_path, a_new)

        self._undo_svc.push(_undo_partial, _redo_partial)

    def _delete_takeoffs_fast(self, db_path: str, takeoff_uids: List[str]) -> bool:
        if not takeoff_uids:
            return True
        if not self._write_svc.delete_takeoffs(
            db_path, takeoff_uids, reload_database=False
        ):
            return False
        page_uids = self._data_svc.remove_takeoffs(takeoff_uids)
        self._publish_takeoffs_changed_for_pages(page_uids, list(takeoff_uids))
        return True

    def _insert_takeoffs_fast(
        self, bid_ref, specs: List[InsertTakeoffSpec]
    ) -> List[str]:
        new_uids = self._write_svc.insert_takeoffs(
            bid_ref.file_path,
            bid_ref.bid_uid,
            specs,
            reload_database=False,
        )
        if not new_uids:
            return []
        self._add_inserted_takeoffs_to_model(new_uids, specs)
        page_uids = []
        for spec in specs:
            if spec.page_uid not in page_uids:
                page_uids.append(spec.page_uid)
        self._publish_takeoffs_changed_for_pages(page_uids, list(new_uids))
        return new_uids

    def _same_bid_takeoff_extras_allow_fast_refresh(self, extras: dict) -> bool:
        return set(extras).issubset(_SAME_BID_FAST_TAKEOFF_EXTRA_COLUMNS)

    def _takeoff_specs_allow_fast_refresh(self, specs: List[InsertTakeoffSpec]) -> bool:
        return all(not spec.raw_extras for spec in specs)

    def on_assign_to_area(self, uids: list) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if not db_path or not takeoff_uids:
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        self._write_svc.save_takeoffs_area(db_path, takeoff_uids, area_uid)

    def on_reassign_condition(self, uids: list, condition_uid: str) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if (
            not db_path
            or not takeoff_uids
            or condition_uid not in self._data_svc.get_bid_conditions()
        ):
            return
        self._write_svc.save_takeoffs_condition(
            db_path, takeoff_uids, str(condition_uid)
        )

    def on_set_negative(self, uids: list, is_negative: bool) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if not db_path or not takeoff_uids:
            return
        self._write_svc.set_takeoffs_negative(db_path, takeoff_uids, is_negative)

    def on_set_curved(self, uids: list, make_curved: bool) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if not db_path or not takeoff_uids:
            return
        cs = self._plan_view.get_coordinate_system()
        changed = False
        for uid in takeoff_uids:
            takeoff = self._resolver.resolve_takeoff(uid)
            if not takeoff:
                continue
            pos = cs.parse_position(takeoff.position)
            if not pos or len(pos) < 4:
                continue
            if make_curved:
                x1, y1, x2, y2 = pos[:4]
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                pos = [x1, y1, x2, y2, cx, cy, 0.0]
                changed = (
                    self._write_svc.set_takeoff_curve(
                        db_path,
                        uid,
                        pos,
                        Takeoff.CURVE_ENABLED,
                        reload_database=False,
                    )
                    or changed
                )
            else:
                pos = list(pos[:4])
                changed = (
                    self._write_svc.set_takeoff_curve(
                        db_path,
                        uid,
                        pos,
                        Takeoff.CURVE_DISABLED,
                        reload_database=False,
                    )
                    or changed
                )
        if changed:
            self._write_svc.reload_and_notify(db_path)

    def on_positions_flushed(self, takeoff_changes: list, ann_changes: list) -> None:
        if (takeoff_changes or ann_changes) and not self._is_allowed(
            Feature.SELECT_PLAN_ITEMS
        ):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or (not takeoff_changes and not ann_changes):
            return
        t_old = [(uid, list(old)) for uid, old, _ in takeoff_changes if old]
        t_new = [(uid, list(new)) for uid, _, new in takeoff_changes]
        a_old = [(uid, t, list(old)) for uid, t, old, _ in ann_changes if old]
        a_new = [(uid, t, list(new)) for uid, t, _, new in ann_changes]
        ok_t = True
        if takeoff_changes:
            ok_t = self._save_takeoff_positions_fast(db_path, t_new)
            if not ok_t:
                self._plan_view.restore_flushed_positions(takeoff_changes, ann_changes)
                return
        ok_a = True
        if ann_changes:
            ok_a = self._save_annotation_positions_fast(
                db_path,
                [
                    (uid, ann_type, new_pos)
                    for uid, ann_type, _old, new_pos in ann_changes
                ],
            )
        if not ok_a:
            self._push_position_undo_for_committed_partial(db_path, t_old, t_new)
            self._plan_view.restore_flushed_positions([], ann_changes)
            return
        if not (t_old or a_old):
            return

        def _undo_move():
            if t_old:
                self._save_takeoff_positions_fast(db_path, t_old)
            if a_old:
                self._save_annotation_positions_fast(db_path, a_old)

        def _redo_move():
            if t_new:
                self._save_takeoff_positions_fast(db_path, t_new)
            if a_new:
                self._save_annotation_positions_fast(db_path, a_new)

        self._undo_svc.push(_undo_move, _redo_move)

    def on_annotation_text_properties_flushed(self, changes: list) -> None:
        if not self._is_allowed(Feature.EDIT_ANNOTATION_TEXT):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or not changes:
            return
        new_updates = [
            (uid, ann_type, dict(new_props))
            for uid, ann_type, _old_props, new_props in changes
        ]
        success = self._save_annotation_text_properties_fast(db_path, new_updates)
        if not success:
            self._plan_view.restore_annotation_text_properties(changes)
            return
        self._publish_named_view_renames(new_updates)
        old_updates = [
            (uid, ann_type, dict(old_props))
            for uid, ann_type, old_props, _new_props in changes
            if old_props
        ]
        if not old_updates:
            return

        def _undo_text_properties():
            if self._save_annotation_text_properties_fast(db_path, old_updates):
                self._publish_named_view_renames(old_updates)

        def _redo_text_properties():
            if self._save_annotation_text_properties_fast(db_path, new_updates):
                self._publish_named_view_renames(new_updates)

        self._undo_svc.push(_undo_text_properties, _redo_text_properties)

    def on_annotation_styles_flushed(self, changes: list) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or not changes:
            return
        new_updates = [
            (uid, ann_type, dict(new_style))
            for uid, ann_type, _old_style, new_style in changes
        ]
        success = self._save_annotation_styles_fast(db_path, new_updates)
        if not success:
            self._plan_view.restore_annotation_styles(changes)
            return
        old_updates = [
            (uid, ann_type, dict(old_style))
            for uid, ann_type, old_style, _new_style in changes
            if old_style
        ]
        if not old_updates:
            return

        def _undo_styles():
            self._save_annotation_styles_fast(db_path, old_updates)

        def _redo_styles():
            self._save_annotation_styles_fast(db_path, new_updates)

        self._undo_svc.push(_undo_styles, _redo_styles)

    def _publish_named_view_renames(self, updates: list) -> None:
        renames = [
            (str(uid), str(properties["Text"] or ""))
            for uid, ann_type, properties in updates
            if ann_type == "namedview" and "Text" in properties
        ]
        if not renames:
            return
        self._data_svc.update_named_view_names(renames)
        for uid, name in renames:
            self._event_bus.publish(
                AppEvents.NAMED_VIEW_RENAMED,
                named_view_uid=uid,
                name=name,
            )

    def on_annotation_text_and_positions_flushed(
        self, text_changes: list, ann_position_changes: list
    ) -> None:
        if not self._is_allowed(Feature.EDIT_ANNOTATION_TEXT):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or (not text_changes and not ann_position_changes):
            return
        new_updates = [
            (uid, ann_type, dict(new_props))
            for uid, ann_type, _old_props, new_props in text_changes
        ]
        new_positions = [
            (uid, ann_type, list(new_pos))
            for uid, ann_type, _old_pos, new_pos in ann_position_changes
        ]
        success = self._save_annotation_text_and_positions_fast(
            db_path, new_updates, new_positions
        )
        if not success:
            self._plan_view.restore_annotation_text_and_positions(
                text_changes, ann_position_changes
            )
            return
        old_updates = [
            (uid, ann_type, dict(old_props))
            for uid, ann_type, old_props, _new_props in text_changes
            if old_props
        ]
        old_positions = [
            (uid, ann_type, list(old_pos))
            for uid, ann_type, old_pos, _new_pos in ann_position_changes
            if old_pos
        ]
        if not (old_updates or old_positions):
            return

        def _undo_text_and_position():
            self._save_annotation_text_and_positions_fast(
                db_path, old_updates, old_positions
            )

        def _redo_text_and_position():
            self._save_annotation_text_and_positions_fast(
                db_path, new_updates, new_positions
            )

        self._undo_svc.push(_undo_text_and_position, _redo_text_and_position)

    def on_rotations_flushed(self, rotation_changes: list) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or not rotation_changes:
            return
        new_rotations = [(uid, new_rot) for uid, _old, new_rot in rotation_changes]
        if not self._save_takeoff_rotations_fast(db_path, new_rotations):
            self._plan_view.restore_flushed_rotations(rotation_changes)
            return
        r_old = [(uid, old) for uid, old, _ in rotation_changes if old is not None]
        r_new = [(uid, new) for uid, _, new in rotation_changes]
        if not r_old:
            return

        def _undo_rotate():
            self._save_takeoff_rotations_fast(db_path, r_old)

        def _redo_rotate():
            self._save_takeoff_rotations_fast(db_path, r_new)

        self._undo_svc.push(_undo_rotate, _redo_rotate)

    def on_group_rotation_flushed(
        self, takeoff_changes: list, ann_changes: list, rotation_changes: list
    ) -> None:
        if (
            takeoff_changes or ann_changes or rotation_changes
        ) and not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path:
            return
        t_new = [(uid, list(new)) for uid, _, new in takeoff_changes]
        r_new = [(uid, new) for uid, _, new in rotation_changes]
        t_old = [(uid, list(old)) for uid, old, _ in takeoff_changes if old]
        a_old = [(uid, t, list(old)) for uid, t, old, _ in ann_changes if old]
        a_new = [(uid, t, list(new)) for uid, t, _, new in ann_changes]
        r_old = [(uid, old) for uid, old, _ in rotation_changes if old is not None]
        ok_t = True
        ok_r = True
        if ann_changes:
            if t_new:
                ok_t = self._save_takeoff_positions_fast(db_path, t_new)
            ok_a = self._save_annotation_positions_fast(
                db_path,
                [
                    (uid, ann_type, new_pos)
                    for uid, ann_type, _old, new_pos in ann_changes
                ],
            )
            if r_new:
                ok_r = self._save_takeoff_rotations_fast(db_path, r_new)
            if not (ok_t and ok_a and ok_r):
                if not ok_t:
                    self._plan_view.restore_flushed_positions(
                        takeoff_changes, ann_changes
                    )
                    self._plan_view.restore_flushed_rotations(rotation_changes)
                elif not ok_a:
                    self._push_position_undo_for_committed_partial(
                        db_path, t_old, t_new
                    )
                    self._plan_view.restore_flushed_positions([], ann_changes)
                    if not ok_r:
                        self._plan_view.restore_flushed_rotations(rotation_changes)
                elif not ok_r:
                    self._push_position_undo_for_committed_partial(
                        db_path, t_old, t_new, a_old, a_new
                    )
                    self._plan_view.restore_flushed_rotations(rotation_changes)
                return
        else:
            positions_saved = False
            if t_new:
                if not self._write_svc.save_takeoff_positions(
                    db_path, t_new, reload_database=False
                ):
                    self._plan_view.restore_flushed_positions(takeoff_changes, [])
                    self._plan_view.restore_flushed_rotations(rotation_changes)
                    return
                positions_saved = True
            if r_new and not self._write_svc.save_takeoff_rotations(
                db_path, r_new, reload_database=False
            ):
                if positions_saved:
                    self._publish_saved_takeoff_position_rotation_changes(t_new, [])
                    self._push_position_undo_for_committed_partial(
                        db_path, t_old, t_new
                    )
                self._plan_view.restore_flushed_rotations(rotation_changes)
                return
            self._publish_saved_takeoff_position_rotation_changes(t_new, r_new)

        def _undo_group():
            if a_old:
                if t_old:
                    self._save_takeoff_positions_fast(db_path, t_old)
                self._save_annotation_positions_fast(db_path, a_old)
                if r_old:
                    self._save_takeoff_rotations_fast(db_path, r_old)
            else:
                self._save_takeoff_position_rotation_fast(db_path, t_old, r_old)

        def _redo_group():
            if a_new:
                if t_new:
                    self._save_takeoff_positions_fast(db_path, t_new)
                self._save_annotation_positions_fast(db_path, a_new)
                if r_new:
                    self._save_takeoff_rotations_fast(db_path, r_new)
            else:
                self._save_takeoff_position_rotation_fast(db_path, t_new, r_new)

        if t_old or a_old or r_old:
            self._undo_svc.push(_undo_group, _redo_group)

    def on_takeoff_created(
        self, condition_uid: str, position: list, page_uid: str
    ) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not condition_uid or not page_uid:
            return
        if not self._is_condition_placeable(condition_uid):
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        place_uids = self._ui_state.place_condition_uids
        target_uids = self._filter_same_type(condition_uid, place_uids)
        if len(target_uids) > 1:
            specs = [
                InsertTakeoffSpec(
                    condition_uid=cuid,
                    page_uid=page_uid,
                    area_uid=area_uid,
                    position=position,
                )
                for cuid in target_uids
            ]
        else:
            curve = (
                Takeoff.CURVE_ENABLED if len(position) >= 6 else Takeoff.CURVE_DISABLED
            )
            specs = [
                InsertTakeoffSpec(
                    condition_uid=condition_uid,
                    page_uid=page_uid,
                    area_uid=area_uid,
                    position=position,
                    curve=curve,
                )
            ]
        self._insert_takeoffs_with_undo(bid_ref, specs, fast_refresh=True)

    def on_annotation_created(
        self, annotation_type: str, position: list, page_uid: str
    ) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not annotation_type or not page_uid:
            return
        spec = build_placed_annotation_spec(annotation_type, page_uid, list(position))
        if spec is None:
            return
        self._insert_annotations_with_undo(bid_ref, [spec])

    def on_text_annotation_created(
        self, position: list, page_uid: str, properties: dict
    ) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not page_uid or not str(properties.get("Text", "")).strip():
            return
        spec = build_placed_annotation_spec("text", page_uid, list(position))
        if spec is None:
            return
        spec.properties = dict(properties)
        font_color = spec.properties.get("FontColor")
        if isinstance(font_color, int):
            spec.color = int_color_to_hex(font_color)
        self._insert_annotations_with_undo(bid_ref, [spec])

    def on_named_view_created(
        self, position: list, page_uid: str, properties: dict
    ) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        name = str(properties.get("Text", "") or "").strip()
        if not bid_ref or not page_uid or not name:
            return
        if not self._validate_named_view_name(name, None):
            return
        spec = build_placed_annotation_spec("namedview", page_uid, list(position))
        if spec is None:
            return
        spec.properties = {"Text": name}
        color = properties.get("Color")
        if isinstance(color, str) and color:
            spec.color = color
        new_uids = self._insert_annotations_with_undo(bid_ref, [spec])
        if new_uids:
            self._event_bus.publish(
                AppEvents.NAMED_VIEW_CREATED,
                named_view_uid=new_uids[0],
                page_uid=page_uid,
                name=name,
            )
            self._plan_view.activate_annotation_placement("namedview")

    def on_hotlink_placement_requested(self, position: list, page_uid: str) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not page_uid or len(position) < 2:
            return
        dialog = SelectNamedViewDialog(
            self._collect_named_view_choices(),
            parent=self._plan_view,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        result = dialog.result_data()
        if result.create_new:
            self._plan_view.activate_annotation_placement("namedview")
            return
        if not result.named_view_uid:
            return
        spec = build_placed_annotation_spec("hotlink", page_uid, list(position[:2]))
        if spec is None:
            return
        spec.properties = {"BidPageViewUID": result.named_view_uid}
        new_uids = self._insert_annotations_with_undo(bid_ref, [spec])
        if new_uids:
            self._plan_view.activate_annotation_placement("hotlink")

    def _validate_named_view_name(
        self, name: str, exclude_uid: Optional[str] = None
    ) -> bool:
        if named_view_name_exists(
            self._collect_named_view_choices(),
            name,
            exclude_uid=exclude_uid,
        ):
            show_duplicate_named_view_name(self._plan_view)
            return False
        return True

    def _collect_named_view_choices(self) -> List[tuple[str, str, str, str]]:
        choices: List[tuple[str, str, str, str]] = []
        for annotation in self._data_svc.get_all_annotations():
            named_view = build_named_view_from_annotation(annotation)
            if named_view is None:
                continue
            page_name = self._data_svc.get_page_name(named_view.bid_page_uid)
            choices.append(
                (
                    named_view.uid,
                    named_view.bid_page_uid,
                    page_name,
                    named_view.name or named_view.uid,
                )
            )
        return choices

    def on_hole_created(
        self, condition_uid: str, position: list, page_uid: str, parent_uid: str
    ) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not condition_uid or not page_uid or not parent_uid:
            return
        if not self._is_condition_placeable(condition_uid):
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        spec = InsertTakeoffSpec(
            condition_uid=condition_uid,
            page_uid=page_uid,
            area_uid=area_uid,
            position=position,
            parent_uid=parent_uid,
        )
        self._insert_takeoffs_with_undo(bid_ref, [spec], fast_refresh=True)

    def _insert_annotations_with_undo(
        self, bid_ref, specs: List[InsertAnnotationSpec]
    ) -> List[str]:
        new_uids = self._insert_annotations_fast(bid_ref, specs)
        if not new_uids:
            return []
        current_specs = specs[: len(new_uids)]
        uid_type_set = {
            (uid, current_specs[i].annotation_type) for i, uid in enumerate(new_uids)
        }
        keys = self._plan_view.find_annotation_keys_by_uid_type(uid_type_set)
        if keys:
            self._plan_view.set_selected_uids(keys)
        current_uids = list(new_uids)

        def _undo_insert():
            if self._delete_annotations_fast(
                bid_ref.file_path, list(current_uids), current_specs
            ):
                self._plan_view.clear_selection()

        def _redo_insert():
            redone_uids = self._insert_annotations_fast(bid_ref, current_specs)
            current_uids[:] = list(redone_uids)
            if redone_uids:
                uid_type_set = {
                    (uid, current_specs[i].annotation_type)
                    for i, uid in enumerate(redone_uids)
                }
                keys = self._plan_view.find_annotation_keys_by_uid_type(uid_type_set)
                self._plan_view.set_selected_uids(keys)

        self._undo_svc.push(_undo_insert, _redo_insert)
        return list(new_uids)

    def _insert_annotations_fast(
        self,
        bid_ref,
        specs: List[InsertAnnotationSpec],
        ref_remap: Optional[PasteRefRemap] = None,
    ) -> List[str]:
        new_uids = self._ann_write_svc.insert_annotations(
            bid_ref.file_path,
            bid_ref.bid_uid,
            specs,
            ref_remap=ref_remap,
            reload_database=False,
        )
        if not new_uids:
            return []
        inserted_specs = specs[: len(new_uids)]
        self._add_inserted_annotations_to_model(new_uids, inserted_specs)
        page_uids = self._annotation_page_uids_for_specs(inserted_specs)
        self._publish_annotations_changed_for_pages(
            page_uids, new_uids, self._annotation_types_from_specs(inserted_specs)
        )
        return list(new_uids)

    def _delete_annotations_fast(
        self, db_path: str, uids: List[str], specs: List[InsertAnnotationSpec]
    ) -> bool:
        if not uids:
            return True
        annotation_keys = [
            (uid, specs[i].annotation_type) for i, uid in enumerate(uids)
        ]
        if not self._ann_write_svc.delete_annotations(
            db_path, annotation_keys, reload_database=False
        ):
            return False
        page_uids = self._data_svc.remove_annotations_by_keys(annotation_keys)
        self._publish_annotations_changed_for_pages(
            page_uids, uids, self._annotation_types_from_specs(specs)
        )
        return True

    def _delete_saved_annotations_fast(
        self, db_path: str, saved_annotations: List[BidAnnotation]
    ) -> bool:
        if not saved_annotations:
            return True
        annotation_keys = [
            (annotation.uid, annotation.annotation_type)
            for annotation in saved_annotations
        ]
        if not self._ann_write_svc.delete_annotations(
            db_path, annotation_keys, reload_database=False
        ):
            return False
        annotation_uids = [annotation.uid for annotation in saved_annotations]
        annotation_types = [
            annotation.annotation_type for annotation in saved_annotations
        ]
        page_uids = self._data_svc.remove_annotations_by_keys(annotation_keys)
        self._publish_annotations_changed_for_pages(
            page_uids, annotation_uids, annotation_types
        )
        self._publish_named_view_deletes(saved_annotations)
        return True

    def _insert_saved_annotations_fast(
        self, bid_ref, saved_annotations: List[BidAnnotation]
    ) -> List[BidAnnotation]:
        if not saved_annotations:
            return []
        restored: List[BidAnnotation] = []
        ref_remap = PasteRefRemap()
        named_views = [
            annotation for annotation in saved_annotations if annotation.is_namedview
        ]
        others = [
            annotation
            for annotation in saved_annotations
            if not annotation.is_namedview
        ]
        if named_views:
            specs = self._annotation_specs_from_saved(named_views)
            new_uids = self._insert_annotations_fast(bid_ref, specs)
            for annotation, new_uid in zip(named_views, new_uids):
                ref_remap.namedview_uids[str(annotation.uid)] = str(new_uid)
                restored.append(self._annotation_with_uid(annotation, new_uid))
        if others:
            specs = self._annotation_specs_from_saved(others)
            new_uids = self._insert_annotations_fast(
                bid_ref, specs, ref_remap=ref_remap
            )
            for annotation, new_uid in zip(others, new_uids):
                restored.append(self._annotation_with_uid(annotation, new_uid))
        return restored

    @staticmethod
    def _annotation_specs_from_saved(
        annotations: List[BidAnnotation],
    ) -> List[InsertAnnotationSpec]:
        return [
            InsertAnnotationSpec(
                page_uid=annotation.page_uid,
                annotation_type=annotation.annotation_type,
                position=list(annotation.position),
                color=annotation.color,
                width=annotation.width,
                properties=dict(annotation.properties),
                layer_uid=annotation.layer_uid,
            )
            for annotation in annotations
        ]

    @staticmethod
    def _annotation_with_uid(annotation: BidAnnotation, uid: str) -> BidAnnotation:
        return BidAnnotation(
            uid=str(uid),
            annotation_type=annotation.annotation_type,
            page_uid=annotation.page_uid,
            layer_uid=annotation.layer_uid,
            position=list(annotation.position),
            color=annotation.color,
            width=annotation.width,
            properties=dict(annotation.properties),
            visible=annotation.visible,
        )

    def _add_inserted_annotations_to_model(
        self, new_uids: List[str], specs: List[InsertAnnotationSpec]
    ) -> None:
        annotations = []
        for uid, spec in zip(new_uids, specs):
            position = (
                normalize_named_view_position(spec.position)
                if spec.annotation_type == "namedview"
                else list(spec.position)
            )
            annotations.append(
                BidAnnotation(
                    uid=str(uid),
                    annotation_type=str(spec.annotation_type),
                    page_uid=str(spec.page_uid),
                    layer_uid=str(spec.layer_uid or ""),
                    position=position,
                    color=str(spec.color),
                    width=float(spec.width or 0.0),
                    properties=dict(spec.properties),
                    visible=True,
                )
            )
        self._data_svc.add_annotations(annotations)

    def _annotation_page_uids_for_specs(
        self, specs: List[InsertAnnotationSpec]
    ) -> List[str]:
        return self._unique_ordered(str(spec.page_uid) for spec in specs)

    @staticmethod
    def _annotation_uids_from_changes(changes: List[tuple]) -> List[str]:
        return [str(uid) for uid, _annotation_type, _payload in changes]

    @staticmethod
    def _annotation_types_from_changes(changes: List[tuple]) -> List[str]:
        return [str(annotation_type) for _uid, annotation_type, _payload in changes]

    @staticmethod
    def _annotation_types_from_specs(
        specs: List[InsertAnnotationSpec],
    ) -> List[str]:
        return [str(spec.annotation_type) for spec in specs]

    @staticmethod
    def _unique_ordered(values) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values:
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result

    def _publish_annotations_changed_for_pages(
        self,
        page_uids: List[str],
        annotation_uids: List[str],
        annotation_types: List[str],
    ) -> None:
        event_types = [str(t) for t in annotation_types]
        seen = set()
        for page_uid in page_uids:
            if not page_uid or page_uid in seen:
                continue
            seen.add(page_uid)
            self._event_bus.publish(
                AppEvents.ANNOTATIONS_CHANGED,
                page_uid=page_uid,
                annotation_uids=list(annotation_uids),
                annotation_types=list(event_types),
            )

    def _publish_named_view_deletes(self, annotations: List[BidAnnotation]) -> None:
        named_view_uids = [
            str(annotation.uid) for annotation in annotations if annotation.is_namedview
        ]
        if named_view_uids:
            self._event_bus.publish(
                AppEvents.NAMED_VIEW_DELETED,
                named_view_uids=named_view_uids,
            )

    def on_paste_backouts_placed(self, placements: list, source_bid_uid) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not placements:
            return
        condition_uid_map = self._condition_uid_map_for_paste(
            bid_ref, [p["condition_uid"] for p in placements]
        )
        if condition_uid_map is None:
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        specs = [
            InsertTakeoffSpec(
                condition_uid=condition_uid_map.get(
                    str(p["condition_uid"]), p["condition_uid"]
                ),
                page_uid=p["page_uid"],
                area_uid=area_uid,
                position=p["position"],
                parent_uid=p["parent_uid"],
                rotation=p["rotation"],
                is_negative=p["is_negative"],
                raw_extras=dict(p["extras"]),
                source_bid_uid=source_bid_uid,
            )
            for p in placements
        ]
        self._insert_takeoffs_with_undo(bid_ref, specs)

    def _insert_takeoffs_with_undo(
        self, bid_ref, specs: List[InsertTakeoffSpec], fast_refresh: bool = False
    ) -> bool:
        use_fast_refresh = fast_refresh and self._takeoff_specs_allow_fast_refresh(
            specs
        )
        new_uids = self._write_svc.insert_takeoffs(
            bid_ref.file_path,
            bid_ref.bid_uid,
            specs,
            reload_database=not use_fast_refresh,
        )
        if not new_uids:
            return False
        if use_fast_refresh:
            self._add_inserted_takeoffs_to_model(new_uids, specs)
            page_uids = []
            for spec in specs:
                if spec.page_uid not in page_uids:
                    page_uids.append(spec.page_uid)
            self._publish_takeoffs_changed_for_pages(page_uids, new_uids)
        self._plan_view.set_selected_uids(set(new_uids))
        if use_fast_refresh:
            current_uids = list(new_uids)

            def _undo_insert():
                if self._delete_takeoffs_fast(bid_ref.file_path, list(current_uids)):
                    self._plan_view.clear_selection()

            def _redo_insert():
                redone_uids = self._insert_takeoffs_fast(bid_ref, specs)
                for i, uid in enumerate(redone_uids):
                    if i < len(current_uids):
                        current_uids[i] = uid
                if redone_uids:
                    self._plan_view.set_selected_uids(set(redone_uids))

            self._undo_svc.push(_undo_insert, _redo_insert)
            return True
        cmd = InsertTakeoffsCommand(
            uids=new_uids,
            bid_ref=bid_ref,
            specs=specs,
            write_svc=self._write_svc,
            plan_view=self._plan_view,
        )
        self._undo_svc.push(cmd.undo, cmd.redo)
        return True

    def _add_inserted_takeoffs_to_model(
        self, new_uids: List[str], specs: List[InsertTakeoffSpec]
    ) -> None:
        takeoffs = []
        for uid, spec in zip(new_uids, specs):
            takeoff = Takeoff(
                uid=str(uid),
                condition_uid=str(spec.condition_uid),
                page_uid=str(spec.page_uid),
                area_uid=str(spec.area_uid or "0"),
                position=list(spec.position),
                rotation=spec.rotation,
                curve=spec.curve,
                parent_uid=str(spec.parent_uid or "0"),
                is_negative=spec.is_negative,
            )
            self._apply_takeoff_raw_extras(takeoff, spec.raw_extras)
            takeoffs.append(takeoff)
        self._data_svc.add_takeoffs(takeoffs)

    @staticmethod
    def _int_extra_or_none(extras: dict, key: str, *, abs_value: bool = False):
        value = extras.get(key)
        if value in (None, ""):
            return None
        value = int(value)
        return abs(value) if abs_value else value

    @staticmethod
    def _str_extra_or_none(extras: dict, key: str):
        value = extras.get(key)
        return str(value) if value else None

    def _apply_takeoff_raw_extras(self, takeoff: Takeoff, extras: dict) -> None:
        if not extras:
            return
        takeoff.dimension_font_name = self._str_extra_or_none(extras, "FontName")
        takeoff.dimension_font_color = self._int_extra_or_none(extras, "FontColor")
        takeoff.dimension_font_size = self._int_extra_or_none(
            extras, "FontSize", abs_value=True
        )
        takeoff.dimension_font_bold = bool(extras.get("FontBold", False))
        takeoff.dimension_font_italic = bool(extras.get("FontItalic", False))
        takeoff.dimension_font_underline = bool(extras.get("FontUnderline", False))
        takeoff.name_font_name = self._str_extra_or_none(extras, "NameFontName")
        takeoff.name_font_color = self._int_extra_or_none(extras, "NameFontColor")
        takeoff.name_font_size = self._int_extra_or_none(
            extras, "NameFontSize", abs_value=True
        )
        takeoff.name_font_bold = bool(extras.get("NameFontBold", False))
        takeoff.name_font_italic = bool(extras.get("NameFontItalic", False))
        takeoff.name_font_underline = bool(extras.get("NameFontUnderline", False))

    def on_elements_deleted(self, uids: list) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not uids:
            return
        db_path = bid_ref.file_path
        saved_takeoffs = []
        saved_annotations = []
        for uid in uids:
            t = self._resolver.resolve_takeoff(uid)
            if t:
                saved_takeoffs.append(t)
                continue
            a = self._plan_view.get_annotation(uid)
            if a and a.is_interactive:
                saved_annotations.append(a)
        takeoff_uids = set(t.uid for t in saved_takeoffs)
        all_takeoffs = self._data_svc.get_all_takeoffs()
        for t in list(saved_takeoffs):
            if t.parent_uid in ("0", "", None):
                for child in all_takeoffs:
                    if child.parent_uid == t.uid and child.uid not in takeoff_uids:
                        takeoff_uids.add(child.uid)
                        saved_takeoffs.append(child)
        deleted_namedview_uids = {
            str(a.uid) for a in saved_annotations if a.is_namedview
        }
        if deleted_namedview_uids:
            existing_ann_uids = {(a.uid, a.annotation_type) for a in saved_annotations}
            linked_hotlinks = self._data_svc.find_hotlinks_targeting(
                deleted_namedview_uids
            )
            if linked_hotlinks and not confirm(
                self._plan_view,
                "Delete Named View",
                NAMED_VIEW_HOTLINK_DELETE_MESSAGE,
            ):
                self._plan_view.set_selected_uids(set(uids))
                return
            for a in linked_hotlinks:
                if (a.uid, a.annotation_type) not in existing_ann_uids:
                    saved_annotations.append(a)
                    existing_ann_uids.add((a.uid, a.annotation_type))
            saved_annotations = order_annotations_for_delete(saved_annotations)
        takeoff_uids = list(takeoff_uids)
        takeoffs_deleted = False
        annotations_deleted = False
        simple_takeoff_delete = bool(saved_takeoffs) and not saved_annotations
        saved_takeoff_extras = {}
        if simple_takeoff_delete:
            for takeoff in saved_takeoffs:
                if takeoff.parent_uid not in ("0", "", None):
                    simple_takeoff_delete = False
                    break
                extras = self._data_svc.get_takeoff_extras(takeoff.uid)
                saved_takeoff_extras[takeoff.uid] = dict(extras)
                if not self._same_bid_takeoff_extras_allow_fast_refresh(extras):
                    simple_takeoff_delete = False
                    break
        if simple_takeoff_delete:
            specs = [
                InsertTakeoffSpec(
                    condition_uid=t.condition_uid,
                    page_uid=t.page_uid,
                    area_uid=t.area_uid,
                    position=list(t.position),
                    parent_uid=t.parent_uid,
                    curve=t.curve,
                    rotation=t.rotation,
                    is_negative=t.is_negative,
                    raw_extras=dict(saved_takeoff_extras.get(t.uid, {})),
                )
                for t in saved_takeoffs
            ]
            if not self._delete_takeoffs_fast(db_path, takeoff_uids):
                self._plan_view.set_selected_uids(set(uids))
                return
            current_uids = list(takeoff_uids)

            def _undo_delete():
                new_uids = self._insert_takeoffs_fast(bid_ref, specs)
                for i, uid in enumerate(new_uids):
                    if i < len(current_uids):
                        current_uids[i] = uid
                if new_uids:
                    self._plan_view.set_selected_uids(set(new_uids))

            def _redo_delete():
                if self._delete_takeoffs_fast(db_path, list(current_uids)):
                    self._plan_view.clear_selection()

            self._undo_svc.push(_undo_delete, _redo_delete)
            return
        if saved_annotations and not takeoff_uids:
            current_annotations = list(saved_annotations)
            if not self._delete_saved_annotations_fast(db_path, current_annotations):
                self._plan_view.set_selected_uids(set(uids))
                return

            def _undo_annotation_delete():
                nonlocal current_annotations
                restored = self._insert_saved_annotations_fast(
                    bid_ref, current_annotations
                )
                if restored:
                    current_annotations = restored
                    uid_type_set = {
                        (annotation.uid, annotation.annotation_type)
                        for annotation in current_annotations
                    }
                    keys = self._plan_view.find_annotation_keys_by_uid_type(
                        uid_type_set
                    )
                    self._plan_view.set_selected_uids(keys)

            def _redo_annotation_delete():
                if self._delete_saved_annotations_fast(db_path, current_annotations):
                    self._plan_view.clear_selection()

            self._undo_svc.push(_undo_annotation_delete, _redo_annotation_delete)
            return
        if takeoff_uids:
            takeoffs_deleted = self._write_svc.delete_takeoffs(db_path, takeoff_uids)
        if saved_annotations:
            annotations_deleted = self._ann_write_svc.delete_annotations(
                db_path,
                [(a.uid, a.annotation_type) for a in saved_annotations],
            )
        delete_cmds = []
        if saved_takeoffs and takeoffs_deleted:
            saved_takeoff_extras = {
                t.uid: self._data_svc.get_takeoff_extras(t.uid) for t in saved_takeoffs
            }
            delete_cmds.append(
                DeleteTakeoffsCommand(
                    saved_takeoffs=saved_takeoffs,
                    bid_ref=bid_ref,
                    write_svc=self._write_svc,
                    plan_view=self._plan_view,
                    takeoff_extras=saved_takeoff_extras,
                )
            )
        if saved_annotations and annotations_deleted:
            delete_cmds.append(
                DeleteAnnotationsCommand(
                    saved_annotations=saved_annotations,
                    bid_ref=bid_ref,
                    write_svc=self._ann_write_svc,
                    plan_view=self._plan_view,
                )
            )
        if not delete_cmds:
            self._plan_view.set_selected_uids(set(uids))
            return

        def _undo():
            for cmd in delete_cmds:
                cmd.undo()

        def _redo():
            for cmd in delete_cmds:
                cmd.redo()

        self._undo_svc.push(_undo, _redo)

    def on_copy_requested(self, uids: list) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        takeoffs = []
        annotations = []
        for uid in uids:
            t = self._resolver.resolve_takeoff(uid)
            if t:
                takeoffs.append(t)
                continue
            a = self._plan_view.get_annotation(uid)
            if a and a.is_interactive and not a.is_namedview:
                annotations.append(a)
        if takeoffs or annotations:
            bid_ref = self._ui_state.get_selected_bid_ref()
            takeoff_extras = {
                t.uid: self._data_svc.get_takeoff_extras(t.uid) for t in takeoffs
            }
            self._clipboard_svc.copy(
                takeoffs,
                annotations,
                source_bid_uid=bid_ref.bid_uid if bid_ref else None,
                source_file_path=bid_ref.file_path if bid_ref else None,
                takeoff_extras=takeoff_extras,
            )
            self._plan_view.clipboard_changed.emit()

    def _condition_uid_map_for_paste(
        self, bid_ref, condition_uids: List[str]
    ) -> Optional[Dict[str, str]]:
        source_bid_uid = self._clipboard_svc.source_bid_uid
        source_file_path = self._clipboard_svc.source_file_path
        if source_bid_uid == bid_ref.bid_uid and source_file_path == bid_ref.file_path:
            return {}
        if not source_bid_uid:
            return None
        if source_file_path != bid_ref.file_path:
            logger.warning(
                "Cannot paste takeoffs across database files: source=%s destination=%s",
                source_file_path,
                bid_ref.file_path,
            )
            return None
        source_condition_uids = list(
            dict.fromkeys(str(uid) for uid in condition_uids if uid)
        )
        if not source_condition_uids:
            return {}
        uid_map = self._write_svc.duplicate_conditions_to_bid(
            bid_ref.file_path,
            source_bid_uid,
            bid_ref.bid_uid,
            source_condition_uids,
            reload_database=False,
        )
        if len(uid_map) != len(source_condition_uids):
            logger.warning(
                "Failed to duplicate all conditions for cross-bid paste: %s -> %s",
                source_bid_uid,
                bid_ref.bid_uid,
            )
            return None
        return uid_map

    def on_paste_requested(self) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        if not self._clipboard_svc.has_content():
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return
        page_uid = self._plan_view.current_page_uid or ""
        if not page_uid:
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        source_bid_uid = self._clipboard_svc.source_bid_uid
        source_file_path = self._clipboard_svc.source_file_path
        all_items = list(self._clipboard_svc.items)
        clipboard_anns = self._clipboard_svc.annotations
        if not all_items and (
            source_bid_uid != bid_ref.bid_uid or source_file_path != bid_ref.file_path
        ):
            return
        regulars = [t for t in all_items if not t.is_hole]
        holes = [t for t in all_items if t.is_hole]
        if holes and not regulars:
            if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
                return
            extras_by_uid = {
                h.uid: dict(self._clipboard_svc.get_extras(h.uid)) for h in holes
            }
            self._plan_view.begin_paste_backout(holes, extras_by_uid, source_bid_uid)
            holes = []
        condition_uid_map = self._condition_uid_map_for_paste(
            bid_ref, [t.condition_uid for t in regulars + holes]
        )
        if condition_uid_map is None:
            return
        clipboard_takeoffs = regulars + holes
        takeoff_extras_by_uid = {
            str(t.uid): dict(self._clipboard_svc.get_extras(t.uid))
            for t in clipboard_takeoffs
        }
        same_bid_paste = (
            source_bid_uid == bid_ref.bid_uid and source_file_path == bid_ref.file_path
        )
        use_fast_takeoff_paste = (
            bool(clipboard_takeoffs)
            and not holes
            and same_bid_paste
            and all(
                self._same_bid_takeoff_extras_allow_fast_refresh(
                    takeoff_extras_by_uid[str(t.uid)]
                )
                for t in clipboard_takeoffs
            )
        )
        paste_dx, paste_dy, intelligent_source_anchor = self._paste_translation(
            regulars, clipboard_anns
        )
        regular_specs = [
            InsertTakeoffSpec(
                condition_uid=condition_uid_map.get(
                    str(t.condition_uid), t.condition_uid
                ),
                page_uid=page_uid,
                area_uid=area_uid,
                position=self._translate_position(t.position, paste_dx, paste_dy),
                parent_uid=t.parent_uid,
                curve=t.curve,
                rotation=t.rotation,
                is_negative=t.is_negative,
                raw_extras=dict(takeoff_extras_by_uid[str(t.uid)]),
                source_bid_uid=source_bid_uid,
            )
            for t in regulars
        ]
        new_regular_uids = (
            self._write_svc.insert_takeoffs(
                bid_ref.file_path,
                bid_ref.bid_uid,
                regular_specs,
                reload_database=not use_fast_takeoff_paste,
            )
            if regular_specs
            else []
        )
        parent_remap = {
            str(regulars[i].uid): str(new_regular_uids[i])
            for i in range(len(new_regular_uids))
        }
        hole_specs = [
            InsertTakeoffSpec(
                condition_uid=condition_uid_map.get(
                    str(t.condition_uid), t.condition_uid
                ),
                page_uid=page_uid,
                area_uid=area_uid,
                position=self._translate_position(t.position, paste_dx, paste_dy),
                parent_uid=parent_remap.get(str(t.parent_uid), t.parent_uid),
                curve=t.curve,
                rotation=t.rotation,
                is_negative=t.is_negative,
                raw_extras=dict(takeoff_extras_by_uid[str(t.uid)]),
                source_bid_uid=source_bid_uid,
            )
            for t in holes
        ]
        new_hole_uids = (
            self._write_svc.insert_takeoffs(
                bid_ref.file_path,
                bid_ref.bid_uid,
                hole_specs,
                reload_database=not use_fast_takeoff_paste,
            )
            if hole_specs
            else []
        )
        clipboard_items = regulars + holes
        takeoff_specs = regular_specs + hole_specs
        new_takeoff_uids = list(new_regular_uids) + list(new_hole_uids)
        pasted_source_items = clipboard_items[: len(new_takeoff_uids)]
        takeoff_uid_remap = {
            str(pasted_source_items[i].uid): str(new_takeoff_uids[i])
            for i in range(len(new_takeoff_uids))
        }
        pasted_takeoffs = []
        for i in range(len(new_takeoff_uids)):
            takeoff = Takeoff(
                uid=new_takeoff_uids[i],
                condition_uid=takeoff_specs[i].condition_uid,
                page_uid=page_uid,
                area_uid=area_uid,
                position=takeoff_specs[i].position,
                parent_uid=takeoff_specs[i].parent_uid,
                curve=pasted_source_items[i].curve,
                rotation=pasted_source_items[i].rotation,
                is_negative=pasted_source_items[i].is_negative,
            )
            self._apply_takeoff_raw_extras(takeoff, takeoff_specs[i].raw_extras)
            pasted_takeoffs.append(takeoff)
        if pasted_takeoffs and use_fast_takeoff_paste:
            self._data_svc.add_takeoffs(pasted_takeoffs)
            self._publish_takeoffs_changed_for_pages([page_uid], new_takeoff_uids)
        pasted_takeoff_extras = {
            pasted_source_items[i].uid: dict(takeoff_specs[i].raw_extras)
            for i in range(len(new_takeoff_uids))
        }
        ann_specs = []
        for a in clipboard_anns:
            pos = self._translate_annotation_position(a, paste_dx, paste_dy)
            ann_specs.append(
                InsertAnnotationSpec(
                    page_uid=page_uid,
                    annotation_type=a.annotation_type,
                    position=pos,
                    color=a.color,
                    width=a.width,
                    properties=dict(a.properties),
                    layer_uid=a.layer_uid,
                )
            )
        new_ann_uids: list = []
        if ann_specs:
            ref_remap = PasteRefRemap(takeoff_uids=dict(takeoff_uid_remap))
            use_fast_annotation_paste = not pasted_takeoffs or use_fast_takeoff_paste
            if use_fast_annotation_paste:
                new_ann_uids = self._insert_annotations_fast(
                    bid_ref, ann_specs, ref_remap=ref_remap
                )
            else:
                new_ann_uids = self._ann_write_svc.insert_annotations(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    ann_specs,
                    ref_remap=ref_remap,
                )
            ann_specs = ann_specs[: len(new_ann_uids)]
        else:
            use_fast_annotation_paste = False
        takeoff_uids = {t.uid for t in pasted_takeoffs}
        ann_uid_type_set = set()
        for i, uid in enumerate(new_ann_uids):
            ann_uid_type_set.add((uid, ann_specs[i].annotation_type))
        ann_keys = self._plan_view.find_annotation_keys_by_uid_type(ann_uid_type_set)
        all_new_keys = takeoff_uids | ann_keys
        if not all_new_keys:
            return
        self._plan_view.set_selected_uids(all_new_keys)
        pending_drag_uids = list(new_takeoff_uids)
        pending_drag_uids.extend(sorted(ann_keys))
        if intelligent_source_anchor and pending_drag_uids:
            self._plan_view.mark_intelligent_paste_drag_pending(
                pending_drag_uids, intelligent_source_anchor
            )
        paste_cmds = []
        takeoff_cmd = None
        if pasted_takeoffs:
            takeoff_cmd = PasteTakeoffsCommand(
                pasted_takeoffs=pasted_takeoffs,
                bid_ref=bid_ref,
                write_svc=self._write_svc,
                plan_view=self._plan_view,
                source_uids=[t.uid for t in pasted_source_items],
                source_parent_uids=[t.parent_uid for t in pasted_source_items],
                source_bid_uid=source_bid_uid,
                takeoff_extras=pasted_takeoff_extras,
                insert_takeoffs_fn=(
                    self._insert_takeoffs_fast if use_fast_takeoff_paste else None
                ),
                delete_takeoffs_fn=(
                    self._delete_takeoffs_fast if use_fast_takeoff_paste else None
                ),
            )
            paste_cmds.append(takeoff_cmd)
        if new_ann_uids and ann_specs:
            paste_cmds.append(
                PasteAnnotationsCommand(
                    specs=ann_specs,
                    new_uids=new_ann_uids,
                    bid_ref=bid_ref,
                    write_svc=self._ann_write_svc,
                    plan_view=self._plan_view,
                    sibling_takeoff_cmd=takeoff_cmd,
                    insert_annotations_fn=(
                        self._insert_annotations_fast
                        if use_fast_annotation_paste
                        else None
                    ),
                    delete_annotations_fn=(
                        self._delete_annotations_fast
                        if use_fast_annotation_paste
                        else None
                    ),
                )
            )
        if paste_cmds:
            cmds = paste_cmds

            def _undo():
                for cmd in cmds:
                    cmd.undo()

            def _redo():
                for cmd in cmds:
                    cmd.redo()
                combined = set()
                for cmd in cmds:
                    combined.update(cmd.get_result_keys())
                self._plan_view.set_selected_uids(combined)

            self._undo_svc.push(_undo, _redo)

    def _paste_translation(
        self, regulars: list, annotations: list
    ) -> tuple[float, float, Optional[tuple]]:
        step = (
            self._plan_view.snap_increments
            if self._plan_view.snap_increments > 0
            else 1.0
        )
        if not self._plan_view.intelligent_paste_enabled:
            return step, step, None
        source_anchor = self._paste_source_anchor(regulars, annotations)
        if source_anchor is None:
            return step, step, None
        mouse_anchor = self._plan_view.current_mouse_ost_position()
        if mouse_anchor is None:
            return 0.0, 0.0, source_anchor
        return (
            mouse_anchor[0] - source_anchor[0],
            mouse_anchor[1] - source_anchor[1],
            source_anchor,
        )

    def _paste_source_anchor(
        self, regulars: list, annotations: list
    ) -> Optional[tuple]:
        for takeoff in regulars:
            if len(takeoff.position) >= 2:
                return float(takeoff.position[0]), float(takeoff.position[1])
        for annotation in annotations:
            anchor = self._annotation_paste_anchor(annotation)
            if anchor is not None:
                return anchor
        return None

    def _annotation_paste_anchor(self, annotation) -> Optional[tuple]:
        pos = list(annotation.position)
        if annotation.is_ink:
            start = 1 if len(pos) % 2 == 1 else 0
            if len(pos) >= start + 2:
                return float(pos[start]), float(pos[start + 1])
            return None
        if len(pos) >= 2:
            return float(pos[0]), float(pos[1])
        return None

    def _translate_position(self, position: list, dx: float, dy: float) -> list:
        translated = list(position)
        for i in range(0, len(translated) - 1, 2):
            translated[i] += dx
            translated[i + 1] += dy
        return translated

    def _translate_annotation_position(self, annotation, dx: float, dy: float) -> list:
        pos = list(annotation.position)
        if annotation.is_text and len(pos) >= 4:
            pos[0] += dx
            pos[1] += dy
        elif annotation.is_ink:
            start = 1 if len(pos) % 2 == 1 else 0
            for i in range(start, len(pos) - 1, 2):
                pos[i] += dx
                pos[i + 1] += dy
        else:
            n = len(pos) // 2
            for i in range(n):
                pos[i * 2] += dx
                pos[i * 2 + 1] += dy
        return pos

    def _is_condition_placeable(self, condition_uid: str) -> bool:
        condition = self._data_svc.get_bid_conditions().get(condition_uid)
        return bool(condition and condition.layer_visible)

    def _filter_same_type(self, active_uid: str, place_uids: list) -> list:
        if len(place_uids) <= 1:
            return [active_uid]
        conditions = self._data_svc.get_bid_conditions()
        active = conditions.get(active_uid)
        if not active or not active.layer_visible:
            return [active_uid]
        return [
            uid
            for uid in place_uids
            if uid in conditions
            and conditions[uid].layer_visible
            and conditions[uid].condition_type == active.condition_type
        ] or [active_uid]
