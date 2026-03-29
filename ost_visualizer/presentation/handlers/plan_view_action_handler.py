from typing import List
from ...application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ...application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ...application.dtos.paste_ref_remap_dto import PasteRefRemap
from ...application.events.app_events import AppEvents
from ...domain.entities.takeoff import Takeoff
from ..resolvers.entity_resolver import EntityResolver
from ..services.selection_clipboard_service import SelectionClipboardService
from ..services.selection_commands import (
    DeleteAnnotationsCommand,
    DeleteTakeoffsCommand,
    InsertTakeoffsCommand,
    PasteAnnotationsCommand,
    PasteTakeoffsCommand,
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
    ):
        self._plan_view = plan_view
        self._ui_state = ui_state_manager
        self._data_svc = project_data_svc
        self._write_svc = project_write_svc
        self._ann_write_svc = annotation_write_svc
        self._page_settings_bar = page_settings_bar
        self._undo_svc = undo_svc
        self._event_bus = event_bus
        self._clipboard_svc = SelectionClipboardService()
        self._resolver = EntityResolver(plan_view, project_data_svc)

    def connect_signals(self) -> None:
        pv = self._plan_view
        pv.assign_to_area_requested.connect(self.on_assign_to_area)
        pv.set_negative_requested.connect(self.on_set_negative)
        pv.set_curved_requested.connect(self.on_set_curved)
        pv.positions_flushed.connect(self.on_positions_flushed)
        pv.rotations_flushed.connect(self.on_rotations_flushed)
        pv.group_rotation_flushed.connect(self.on_group_rotation_flushed)
        pv.takeoff_created.connect(self.on_takeoff_created)
        pv.hole_created.connect(self.on_hole_created)
        pv.elements_deleted.connect(self.on_elements_deleted)
        pv.undo_requested.connect(self._undo_svc.undo)
        pv.redo_requested.connect(self._undo_svc.redo)
        pv.copy_requested.connect(self.on_copy_requested)
        pv.paste_requested.connect(self.on_paste_requested)
        pv.paste_backouts_placed.connect(self.on_paste_backouts_placed)

    def can_paste_to_current_bid(self) -> bool:
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not self._clipboard_svc.has_content():
            return False
        return self._clipboard_svc.source_bid_uid == bid_ref.bid_uid

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
        page_uids = []
        if positions:
            page_uids.extend(self._data_svc.update_takeoff_positions(positions))
        if rotations:
            page_uids.extend(self._data_svc.update_takeoff_rotations(rotations))
        changed_uids = [uid for uid, _position in positions]
        changed_uids.extend(uid for uid, _rotation in rotations)
        self._publish_takeoffs_changed_for_pages(page_uids, changed_uids)
        return True

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

    def on_assign_to_area(self, uids: list) -> None:
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if not db_path or not takeoff_uids:
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        self._write_svc.save_takeoffs_area(db_path, takeoff_uids, area_uid)

    def on_set_negative(self, uids: list, is_negative: bool) -> None:
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if not db_path or not takeoff_uids:
            return
        self._write_svc.set_takeoffs_negative(db_path, takeoff_uids, is_negative)

    def on_set_curved(self, uids: list, make_curved: bool) -> None:
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if not db_path or not takeoff_uids:
            return
        cs = self._plan_view.get_coordinate_system()
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
                self._write_svc.set_takeoff_curve(
                    db_path, uid, pos, Takeoff.CURVE_ENABLED
                )
            else:
                pos = list(pos[:4])
                self._write_svc.set_takeoff_curve(
                    db_path, uid, pos, Takeoff.CURVE_DISABLED
                )

    def on_positions_flushed(self, takeoff_changes: list, ann_changes: list) -> None:
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or (not takeoff_changes and not ann_changes):
            return
        ok_t = True
        if takeoff_changes:
            new_positions = [
                (uid, list(new_pos)) for uid, _old, new_pos in takeoff_changes
            ]
            if ann_changes:
                ok_t = self._write_svc.save_takeoff_positions(db_path, new_positions)
            else:
                ok_t = self._save_takeoff_positions_fast(db_path, new_positions)
        ok_a = True
        if ann_changes:
            ok_a = self._ann_write_svc.save_annotation_positions(
                db_path,
                [
                    (uid, ann_type, new_pos)
                    for uid, ann_type, _old, new_pos in ann_changes
                ],
            )
        if not ok_t or not ok_a:
            return
        t_old = [(uid, list(old)) for uid, old, _ in takeoff_changes if old]
        t_new = [(uid, list(new)) for uid, _, new in takeoff_changes]
        a_old = [(uid, t, list(old)) for uid, t, old, _ in ann_changes if old]
        a_new = [(uid, t, list(new)) for uid, t, _, new in ann_changes]
        if not (t_old or a_old):
            return

        def _undo_move():
            if t_old:
                if a_old:
                    self._write_svc.save_takeoff_positions(db_path, t_old)
                else:
                    self._save_takeoff_positions_fast(db_path, t_old)
            if a_old:
                self._ann_write_svc.save_annotation_positions(db_path, a_old)

        def _redo_move():
            if t_new:
                if a_new:
                    self._write_svc.save_takeoff_positions(db_path, t_new)
                else:
                    self._save_takeoff_positions_fast(db_path, t_new)
            if a_new:
                self._ann_write_svc.save_annotation_positions(db_path, a_new)

        self._undo_svc.push(_undo_move, _redo_move)

    def on_rotations_flushed(self, rotation_changes: list) -> None:
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or not rotation_changes:
            return
        new_rotations = [(uid, new_rot) for uid, _old, new_rot in rotation_changes]
        if not self._save_takeoff_rotations_fast(db_path, new_rotations):
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
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path:
            return
        t_new = [(uid, list(new)) for uid, _, new in takeoff_changes]
        r_new = [(uid, new) for uid, _, new in rotation_changes]
        ok_t = True
        ok_r = True
        if ann_changes:
            if t_new:
                ok_t = self._write_svc.save_takeoff_positions(db_path, t_new)
            ok_a = self._ann_write_svc.save_annotation_positions(
                db_path,
                [
                    (uid, ann_type, new_pos)
                    for uid, ann_type, _old, new_pos in ann_changes
                ],
            )
            if r_new:
                ok_r = self._write_svc.save_takeoff_rotations(db_path, r_new)
            if not (ok_t and ok_a and ok_r):
                return
        elif not self._save_takeoff_position_rotation_fast(db_path, t_new, r_new):
            return
        t_old = [(uid, list(old)) for uid, old, _ in takeoff_changes if old]
        a_old = [(uid, t, list(old)) for uid, t, old, _ in ann_changes if old]
        a_new = [(uid, t, list(new)) for uid, t, _, new in ann_changes]
        r_old = [(uid, old) for uid, old, _ in rotation_changes if old is not None]

        def _undo_group():
            if a_old:
                if t_old:
                    self._write_svc.save_takeoff_positions(db_path, t_old)
                self._ann_write_svc.save_annotation_positions(db_path, a_old)
                if r_old:
                    self._write_svc.save_takeoff_rotations(db_path, r_old)
            else:
                self._save_takeoff_position_rotation_fast(db_path, t_old, r_old)

        def _redo_group():
            if a_new:
                if t_new:
                    self._write_svc.save_takeoff_positions(db_path, t_new)
                self._ann_write_svc.save_annotation_positions(db_path, a_new)
                if r_new:
                    self._write_svc.save_takeoff_rotations(db_path, r_new)
            else:
                self._save_takeoff_position_rotation_fast(db_path, t_new, r_new)

        if t_old or a_old or r_old:
            self._undo_svc.push(_undo_group, _redo_group)

    def on_takeoff_created(
        self, condition_uid: str, position: list, page_uid: str
    ) -> None:
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

    def on_hole_created(
        self, condition_uid: str, position: list, page_uid: str, parent_uid: str
    ) -> None:
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

    def on_paste_backouts_placed(self, placements: list, source_bid_uid) -> None:
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not placements:
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        specs = [
            InsertTakeoffSpec(
                condition_uid=p["condition_uid"],
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
    ) -> None:
        use_fast_refresh = fast_refresh and all(not spec.raw_extras for spec in specs)
        new_uids = self._write_svc.insert_takeoffs(
            bid_ref.file_path,
            bid_ref.bid_uid,
            specs,
            reload_database=not use_fast_refresh,
        )
        if not new_uids:
            return
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
            return
        cmd = InsertTakeoffsCommand(
            uids=new_uids,
            bid_ref=bid_ref,
            specs=specs,
            write_svc=self._write_svc,
            plan_view=self._plan_view,
        )
        self._undo_svc.push(cmd.undo, cmd.redo)

    def _add_inserted_takeoffs_to_model(
        self, new_uids: List[str], specs: List[InsertTakeoffSpec]
    ) -> None:
        takeoffs = []
        for uid, spec in zip(new_uids, specs):
            takeoffs.append(
                Takeoff(
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
            )
        self._data_svc.add_takeoffs(takeoffs)

    def on_elements_deleted(self, uids: list) -> None:
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
            for a in self._data_svc.find_hotlinks_targeting(deleted_namedview_uids):
                if (a.uid, a.annotation_type) not in existing_ann_uids:
                    saved_annotations.append(a)
                    existing_ann_uids.add((a.uid, a.annotation_type))
        takeoff_uids = list(takeoff_uids)
        takeoffs_deleted = False
        annotations_deleted = False
        simple_takeoff_delete = bool(saved_takeoffs) and not saved_annotations
        if simple_takeoff_delete:
            for takeoff in saved_takeoffs:
                if takeoff.parent_uid not in ("0", "", None):
                    simple_takeoff_delete = False
                    break
                extras = self._data_svc.get_takeoff_extras(takeoff.uid)
                if extras:
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
                )
                for t in saved_takeoffs
            ]
            if not self._delete_takeoffs_fast(db_path, takeoff_uids):
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
            return

        def _undo():
            for cmd in delete_cmds:
                cmd.undo()

        def _redo():
            for cmd in delete_cmds:
                cmd.redo()

        self._undo_svc.push(_undo, _redo)

    def on_copy_requested(self, uids: list) -> None:
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
                takeoff_extras=takeoff_extras,
            )
            self._plan_view.clipboard_changed.emit()

    def on_paste_requested(self) -> None:
        if not self._clipboard_svc.has_content():
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return
        page_uid = self._plan_view.current_page_uid or ""
        if not page_uid:
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        step = (
            self._plan_view.snap_increments
            if self._plan_view.snap_increments > 0
            else 1.0
        )
        source_bid_uid = self._clipboard_svc.source_bid_uid
        all_items = list(self._clipboard_svc.items)
        regulars = [t for t in all_items if not t.is_hole]
        holes = [t for t in all_items if t.is_hole]
        if holes and not regulars:
            extras_by_uid = {
                h.uid: dict(self._clipboard_svc.get_extras(h.uid)) for h in holes
            }
            self._plan_view.begin_paste_backout(holes, extras_by_uid, source_bid_uid)
            holes = []
        regular_specs = [
            InsertTakeoffSpec(
                condition_uid=t.condition_uid,
                page_uid=page_uid,
                area_uid=area_uid,
                position=[v + step for v in t.position],
                parent_uid=t.parent_uid,
                curve=t.curve,
                rotation=t.rotation,
                is_negative=t.is_negative,
                raw_extras=dict(self._clipboard_svc.get_extras(t.uid)),
                source_bid_uid=source_bid_uid,
            )
            for t in regulars
        ]
        new_regular_uids = (
            self._write_svc.insert_takeoffs(
                bid_ref.file_path, bid_ref.bid_uid, regular_specs
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
                condition_uid=t.condition_uid,
                page_uid=page_uid,
                area_uid=area_uid,
                position=[v + step for v in t.position],
                parent_uid=parent_remap.get(str(t.parent_uid), t.parent_uid),
                curve=t.curve,
                rotation=t.rotation,
                is_negative=t.is_negative,
                raw_extras=dict(self._clipboard_svc.get_extras(t.uid)),
                source_bid_uid=source_bid_uid,
            )
            for t in holes
        ]
        new_hole_uids = (
            self._write_svc.insert_takeoffs(
                bid_ref.file_path, bid_ref.bid_uid, hole_specs
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
        pasted_takeoffs = [
            Takeoff(
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
            for i in range(len(new_takeoff_uids))
        ]
        pasted_takeoff_extras = {
            pasted_source_items[i].uid: dict(
                self._clipboard_svc.get_extras(pasted_source_items[i].uid)
            )
            for i in range(len(new_takeoff_uids))
        }
        clipboard_anns = self._clipboard_svc.annotations
        ann_specs = []
        for a in clipboard_anns:
            pos = list(a.position)
            if a.is_text and len(pos) >= 4:
                pos[0] += step
                pos[1] += step
            elif a.is_ink:
                start = 1 if len(pos) % 2 == 1 else 0
                for i in range(start, len(pos) - 1, 2):
                    pos[i] += step
                    pos[i + 1] += step
            else:
                n = len(pos) // 2
                for i in range(n):
                    pos[i * 2] += step
                    pos[i * 2 + 1] += step
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
            new_ann_uids = self._ann_write_svc.insert_annotations(
                bid_ref.file_path,
                bid_ref.bid_uid,
                ann_specs,
                ref_remap=PasteRefRemap(takeoff_uids=dict(takeoff_uid_remap)),
            )
            ann_specs = ann_specs[: len(new_ann_uids)]
        takeoff_uids = {t.uid for t in pasted_takeoffs}
        ann_uid_type_set = set()
        for i, uid in enumerate(new_ann_uids):
            ann_uid_type_set.add((uid, ann_specs[i].annotation_type))
        ann_keys = self._plan_view.find_annotation_keys_by_uid_type(ann_uid_type_set)
        all_new_keys = takeoff_uids | ann_keys
        if not all_new_keys:
            return
        self._plan_view.set_selected_uids(all_new_keys)
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
