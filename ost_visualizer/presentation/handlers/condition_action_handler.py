import logging
import weakref
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from types import SimpleNamespace
from typing import Optional
from PySide6.QtCore import QSignalBlocker
from ...application.dtos.create_condition_spec_dto import CreateConditionSpec
from ...application.dtos.collaboration_dtos import (
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ...application.dtos.update_condition_dto import (
    UpdateConditionDto,
    UpdateConditionResultDto,
)
from ...domain.entities.condition import Condition
from ...domain.entities.layer import Layer
from ...domain.entities.pattern import TRANSPARENT as PAT_TRANSPARENT
from ..dialogs.edit_condition_dialog import TYPE_DEFAULTS, EditConditionDialog
from ..managers.ui_access_manager import Feature
from ..utils.messagebox import (
    DB_LOCKED_HINT,
    confirm,
    confirm_delete_conditions,
    confirm_multi_delete,
    show_warning,
)
from ..utils.ost_blocking import exec_with_ost_blocking

logger = logging.getLogger(__name__)


class ConditionActionHandler:
    def __init__(
        self,
        coordinator,
        project_write_service,
        project_read_service,
        project_data,
        ui_state_manager,
        workspace_state_model,
    ):
        self._coordinator = coordinator
        self._write_service = project_write_service
        self._read_service = project_read_service
        self._project_data = project_data
        self._ui_state = ui_state_manager
        self._workspace_state_model = workspace_state_model
        self._pending_sql_operations: set[tuple[str, ...]] = set()

    def _get_bid_ref_and_write_service(self):
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return None, None
        return bid_ref, self._write_service

    def _flush_deferred_for_bid(self, bid_ref) -> bool:
        return self._coordinator.flush_deferred_for_file(bid_ref.file_path)

    def _is_metric(self) -> bool:
        bid = self._project_data.get_current_bid()
        return bool(bid and bid.measure_base == 1)

    def _uses_sql_queue(self, bid_ref) -> bool:
        return self._write_service.uses_sql_collaboration_mutations(bid_ref.file_path)

    def _submit_sql_condition_operation(
        self,
        bid_ref,
        operation_key: tuple[str, ...],
        title: str,
        submit,
        on_committed=None,
        on_failed=None,
    ) -> bool:
        key = tuple(str(value) for value in operation_key)
        if key in self._pending_sql_operations:
            return False
        self._pending_sql_operations.add(key)
        handler_ref = weakref.ref(self)

        def complete(result: QueuedMutationResult) -> None:
            handler = handler_ref()
            if handler is None:
                return
            handler._pending_sql_operations.discard(key)
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                if on_committed is not None:
                    on_committed(result)
                return
            if (
                result.outcome_status
                == MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED
            ):
                return
            handler._coordinator.present_queued_mutation_error(
                bid_ref.file_path,
                title,
                result,
            )
            if on_failed is not None:
                on_failed(result)

        try:
            submit(complete)
        except (RuntimeError, ValueError) as exc:
            self._pending_sql_operations.discard(key)
            show_warning(
                self._coordinator.conditions_sidebar.window(),
                title,
                str(exc),
            )
            return False
        return True

    def _layer_dialog_callbacks(self, bid_ref, write_service) -> dict:
        uses_sql_queue = self._uses_sql_queue(bid_ref)
        callbacks = {
            "layer_reload_fn": (
                self._project_data.get_bid_layer_snapshot
                if uses_sql_queue
                else lambda: self._read_service.get_merged_bid_layers(
                    bid_ref.file_path, bid_ref.bid_uid
                )
            ),
            "layer_used_uids_fn": (
                self._project_data.get_layer_uids_in_use
                if uses_sql_queue
                else lambda: self._read_service.get_layer_uids_in_use(
                    bid_ref.file_path, bid_ref.bid_uid
                )
            ),
            "layer_insert_fn": lambda name, after_sequence: (
                self._insert_layer_from_dialog(
                    bid_ref, write_service, name, after_sequence
                )
            ),
            "layer_delete_many_fn": lambda layer_uids: write_service.delete_layers(
                bid_ref.file_path, layer_uids
            ),
            "layer_update_show_fn": lambda layer_uid, show: (
                self._coordinator.update_layer_visibility_deferred(layer_uid, show)
            ),
            "layer_update_all_show_fn": lambda show: (
                self._coordinator.update_all_layers_visibility_deferred(show)
            ),
            "layer_update_name_fn": lambda layer_uid, name: (
                write_service.update_layer_name(bid_ref.file_path, layer_uid, name)
            ),
            "layer_move_fn": lambda layer_uid, neighbor_uid: (
                write_service.swap_layer_sequence(
                    bid_ref.file_path, layer_uid, neighbor_uid
                )
            ),
        }
        if uses_sql_queue:
            callbacks.update(
                {
                    "insert_async_fn": lambda name, after_sequence, completed: (
                        self._submit_sql_layer_operation(
                            bid_ref,
                            ("insert_layer", str(name)),
                            "New Layer",
                            lambda callback: write_service.queue_layer_insert(
                                bid_ref.file_path,
                                bid_ref.bid_uid,
                                name,
                                after_sequence,
                                callback,
                            ),
                            completed,
                            lambda result: (
                                result.authoritative_result.created_resource_ids[0]
                                if result.authoritative_result
                                and len(
                                    result.authoritative_result.created_resource_ids
                                )
                                == 1
                                else None
                            ),
                        )
                    ),
                    "delete_many_async_fn": lambda layer_uids, completed: (
                        self._submit_sql_layer_operation(
                            bid_ref,
                            ("delete_layers", *layer_uids),
                            "Delete Layer",
                            lambda callback: write_service.queue_layers_delete(
                                bid_ref.file_path,
                                bid_ref.bid_uid,
                                layer_uids,
                                callback,
                            ),
                            completed,
                        )
                    ),
                    "update_name_async_fn": lambda layer_uid, name, completed: (
                        self._submit_sql_layer_operation(
                            bid_ref,
                            ("rename_layer", str(layer_uid)),
                            "Rename Layer",
                            lambda callback: write_service.queue_layer_rename(
                                bid_ref.file_path,
                                bid_ref.bid_uid,
                                layer_uid,
                                name,
                                callback,
                            ),
                            completed,
                        )
                    ),
                    "move_async_fn": lambda layer_uid, neighbor_uid, completed: (
                        self._submit_sql_layer_operation(
                            bid_ref,
                            ("move_layer", str(layer_uid)),
                            "Move Layer",
                            lambda callback: write_service.queue_layer_reorder(
                                bid_ref.file_path,
                                bid_ref.bid_uid,
                                layer_uid,
                                neighbor_uid,
                                callback,
                            ),
                            completed,
                        )
                    ),
                }
            )
        return callbacks

    def _submit_sql_layer_operation(
        self,
        bid_ref,
        operation_key: tuple[str, ...],
        title: str,
        submit,
        completed,
        value_from_result=lambda _result: None,
    ) -> bool:
        return self._submit_sql_condition_operation(
            bid_ref,
            operation_key,
            title,
            submit,
            lambda result: completed(True, value_from_result(result)),
            lambda _result: completed(False, None),
        )

    def _insert_layer_from_dialog(
        self, bid_ref, write_service, name: str, after_sequence: int
    ) -> Optional[str]:
        result = write_service.insert_layer_result(
            bid_ref.file_path, bid_ref.bid_uid, name, after_sequence
        )
        if not result.write_success or not result.value:
            return None
        if result.refresh_failed:
            self._warn_layer_refresh_failed()
        return str(result.value)

    def _warn_layer_refresh_failed(self) -> None:
        parent = (
            self._coordinator.conditions_sidebar.window()
            if self._coordinator.conditions_sidebar
            else None
        )
        show_warning(
            parent,
            "Refresh Error",
            "The layer was created, but the layer list could not be refreshed. "
            "Reopen the database to see the new layer.",
        )

    def _save_condition_types_from_dialog(self, bid_ref, write_service, changes):
        if not self._flush_deferred_for_bid(bid_ref):
            return None
        result = write_service.save_condition_types_result(bid_ref.file_path, changes)
        if not result.write_success:
            return None
        if result.refresh_failed:
            self._warn_condition_type_refresh_failed()
        return result.value

    def _save_condition_types_async_from_dialog(
        self,
        bid_ref,
        write_service,
        changes,
        completed,
    ) -> bool:
        def committed(result: QueuedMutationResult) -> None:
            authoritative = result.authoritative_result
            maps = dict(authoritative.created_uid_maps) if authoritative else {}
            completed(True, dict(maps.get("condition_types", ())))

        return self._submit_sql_condition_operation(
            bid_ref,
            ("condition_types",),
            "Condition Types",
            lambda callback: write_service.queue_condition_types_save(
                bid_ref.file_path,
                changes,
                callback,
            ),
            committed,
            lambda _result: completed(False, None),
        )

    def _warn_condition_type_refresh_failed(self) -> None:
        parent = (
            self._coordinator.conditions_sidebar.window()
            if self._coordinator.conditions_sidebar
            else None
        )
        show_warning(
            parent,
            "Refresh Error",
            "The condition type changes were saved, but the condition type list "
            "could not be refreshed. Reopen the database to see the latest "
            "condition types.",
        )

    def _blocked_condition_type_delete_uids_from_dialog(
        self, bid_ref, write_service, condition_type_uids: list
    ):
        result = write_service.validate_condition_types_delete(
            bid_ref.file_path, condition_type_uids
        )
        return {str(uid) for uid in result.blocked_uids}

    def _delete_condition_types_from_dialog(
        self, bid_ref, write_service, condition_type_uids: list
    ):
        if not self._flush_deferred_for_bid(bid_ref):
            return None
        result = write_service.delete_condition_types_result(
            bid_ref.file_path, condition_type_uids
        )
        if result.refresh_failed:
            self._warn_condition_type_refresh_failed()
        return result

    def on_create_requested(self, folder_uid: str = "") -> None:
        if not self._coordinator.ui_access_manager.is_allowed(Feature.EDIT_CONDITION):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        sidebar = self._coordinator.conditions_sidebar
        if not sidebar:
            return
        uses_sql_queue = self._uses_sql_queue(bid_ref)
        cdn_types = (
            self._project_data.get_cdn_types()
            if uses_sql_queue
            else self._read_service.get_cdn_types(bid_ref.file_path)
        )
        save_condition_types = lambda changes: self._save_condition_types_from_dialog(
            bid_ref, write_service, changes
        )
        reload_condition_types = (
            (lambda: list(self._project_data.get_cdn_types().values()))
            if uses_sql_queue
            else (
                lambda: list(
                    self._read_service.get_cdn_types(bid_ref.file_path).values()
                )
            )
        )
        blocked_condition_type_delete_uids = (
            (lambda _uids: set())
            if uses_sql_queue
            else lambda uids: self._blocked_condition_type_delete_uids_from_dialog(
                bid_ref, write_service, uids
            )
        )
        delete_condition_types = lambda uids: (
            self._delete_condition_types_from_dialog(bid_ref, write_service, uids)
        )
        all_layers = (
            self._project_data.get_bid_layer_snapshot()
            if uses_sql_queue
            else self._read_service.get_merged_bid_layers(
                bid_ref.file_path, bid_ref.bid_uid
            )
        )
        layers = {
            bl.uid: Layer(uid=bl.uid, name=bl.name, visible=bl.show)
            for bl in all_layers
        }
        default_layer_uid = None
        for bl in all_layers:
            if bl.name == "Default":
                default_layer_uid = bl.uid
                break
        synthetic = Condition(
            uid="__new__",
            name="",
            condition_type=Condition.TYPE_LINEAR,
            thickness=4.0,
            pattern=PAT_TRANSPARENT,
            display_size=100.0,
            width=12.0,
            height=0.0,
            depth=0.0,
            rise=0.0,
            run=0.0,
            spacing=4.0,
            color_fill=13353215,
            shape=-1,
            layer_uid=default_layer_uid,
            uom1=2,
            uom2=-1,
            uom3=-1,
            calc_type1=1,
            calc_type2=0,
            calc_type3=0,
            round_up=0.0,
            drop_run=False,
            drop_value=0.0,
            round_quantity=False,
            grid=False,
            grid_size1=0.0,
            grid_size2=0.0,
            gap=0.0,
            trim=False,
            is_curved_segment=False,
            display_dimension=False,
            display_name=False,
            display_grid_while_drawing=False,
        )
        created_uid = [None]
        created_refresh_failed = [False]

        def build_spec(dto) -> CreateConditionSpec:
            changes = dto.get_changes()
            cond_type = changes.get("condition_type", synthetic.condition_type)
            td = TYPE_DEFAULTS.get(cond_type, {})
            spec = CreateConditionSpec(
                name="Untitled",
                condition_type=cond_type,
                thickness=td.get("thickness", 4.0),
                pattern=PAT_TRANSPARENT,
                spacing=td.get("spacing", 4.0),
                color_fill=synthetic.color_fill,
                shape=td.get("shape", -1),
                layer_uid=default_layer_uid,
                uom1=td.get("uom1", 0),
                calc_type1=td.get("calc_type1", 0),
                display_grid_while_drawing=td.get("display_grid_while_drawing", False),
                backout=td.get("backout", False),
                display_dimension=False,
            )
            spec_field_names = {f.name for f in dataclass_fields(CreateConditionSpec)}
            spec_updates = {
                key: val for key, val in changes.items() if key in spec_field_names
            }
            if spec_updates:
                spec = replace(spec, **spec_updates)
            spec.folder_uid = folder_uid or None
            return spec

        def save_new_condition(_cond_uid, dto):
            if not self._flush_deferred_for_bid(bid_ref):
                return UpdateConditionResultDto(
                    success=False, error="Failed to save pending visual state."
                )
            spec = build_spec(dto)
            with QSignalBlocker(sidebar):
                result = write_service.create_condition_result(
                    bid_ref.file_path, bid_ref.bid_uid, spec
                )
            if result.write_success and result.value:
                created_uid[0] = str(result.value)
                created_refresh_failed[0] = result.refresh_failed
                return UpdateConditionResultDto(success=True)
            return UpdateConditionResultDto(
                success=False, error="Failed to create condition."
            )

        def save_new_condition_async(_cond_uid, dto, completed) -> bool:
            if not self._flush_deferred_for_bid(bid_ref):
                completed(
                    UpdateConditionResultDto(
                        success=False,
                        error="Failed to save pending visual state.",
                    )
                )
                return False
            spec = build_spec(dto)

            def committed(result: QueuedMutationResult) -> None:
                authoritative = result.authoritative_result
                new_uids = list(
                    authoritative.created_resource_ids if authoritative else ()
                )
                if len(new_uids) != 1:
                    completed(
                        UpdateConditionResultDto(
                            success=False,
                            error="The committed condition result was incomplete.",
                        )
                    )
                    return
                created_uid[0] = str(new_uids[0])
                completed(UpdateConditionResultDto(success=True))

            def failed(result: QueuedMutationResult) -> None:
                completed(
                    UpdateConditionResultDto(
                        success=False,
                        error=result.message or "Failed to create condition.",
                        error_presented=True,
                    )
                )

            return self._submit_sql_condition_operation(
                bid_ref,
                ("create_condition",),
                "Create Condition",
                lambda callback: write_service.queue_condition_create(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    spec,
                    callback,
                ),
                committed,
                failed,
            )

        dialog = EditConditionDialog(
            icon_provider=self._coordinator.main_window.icon_provider,
            parent=sidebar.window(),
            condition=synthetic,
            condition_uids=["__new__"],
            conditions_map={"__new__": synthetic},
            cdn_types=cdn_types,
            layers=layers,
            has_takeoffs_fn=lambda _: False,
            save_fn=save_new_condition,
            save_async_fn=(
                save_new_condition_async if self._uses_sql_queue(bid_ref) else None
            ),
            condition_type_save_fn=save_condition_types,
            condition_type_save_async_fn=(
                (
                    lambda changes, completed: (
                        self._save_condition_types_async_from_dialog(
                            bid_ref,
                            write_service,
                            changes,
                            completed,
                        )
                    )
                )
                if uses_sql_queue
                else None
            ),
            condition_type_reload_fn=reload_condition_types,
            condition_type_blocked_delete_uids_fn=blocked_condition_type_delete_uids,
            condition_type_delete_fn=delete_condition_types,
            **self._layer_dialog_callbacks(bid_ref, write_service),
            read_service=self._read_service,
            read_only=False,
            metric=self._is_metric(),
            workspace_state_model=self._workspace_state_model,
        )
        dialog._dirty = True
        dialog.set_apply_allowed(False)
        try:
            exec_with_ost_blocking(dialog, self._coordinator.event_bus)
        finally:
            dialog.deleteLater()
        if not self._uses_sql_queue(bid_ref):
            self._coordinator.refresh_conditions_ui()
        if created_refresh_failed[0]:
            show_warning(
                sidebar.window(),
                "Refresh Error",
                "The condition was created, but the conditions list could not be "
                "refreshed. Reopen the database to see the new condition.",
            )
            return
        if created_uid[0]:
            self._coordinator.highlight_sidebar({created_uid[0]})

    def on_duplicate_requested(self, condition_uids: list) -> None:
        if not condition_uids:
            return
        if not self._coordinator.ui_access_manager.is_allowed(
            Feature.DUPLICATE_CONDITION
        ):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        sidebar = self._coordinator.conditions_sidebar
        if self._uses_sql_queue(bid_ref):
            if not self._flush_deferred_for_bid(bid_ref):
                return

            def committed(result: QueuedMutationResult) -> None:
                authoritative = result.authoritative_result
                new_uids = list(
                    authoritative.created_resource_ids if authoritative else ()
                )
                if new_uids:
                    self._finish_condition_duplicate(
                        new_uids, sidebar, refresh_conditions=False
                    )

            self._submit_sql_condition_operation(
                bid_ref,
                ("duplicate", *condition_uids),
                "Duplicate Conditions",
                lambda callback: write_service.queue_conditions_duplicate(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    condition_uids,
                    callback,
                ),
                committed,
            )
            return
        result = self._duplicate_conditions_result(
            bid_ref, write_service, condition_uids, sidebar
        )
        new_uids = list(result.value or [])
        if not new_uids:
            logger.warning("Failed to duplicate conditions %s", condition_uids)
            return
        if result.refresh_failed:
            self._warn_condition_refresh_failed("duplicated")
            return
        self._finish_condition_duplicate(new_uids, sidebar)

    def on_paste_requested(self, condition_uids: list, target: object) -> None:
        if not condition_uids or not isinstance(target, dict):
            return
        target_kind = target.get("kind")
        if target_kind not in ("root", "folder", "cdn_type"):
            return
        is_cut = bool(target.get("cut"))
        required_feature = (
            Feature.EDIT_CONDITION_STRUCTURE if is_cut else Feature.DUPLICATE_CONDITION
        )
        if not self._coordinator.ui_access_manager.is_allowed(required_feature):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        sidebar = self._coordinator.conditions_sidebar
        if self._uses_sql_queue(bid_ref):
            if not self._flush_deferred_for_bid(bid_ref):
                return
            target_changes = {"folder_uid": target.get("folder_uid") or None}
            if target_kind == "cdn_type":
                target_changes["cdn_type_uid"] = target.get("cdn_type_uid") or None
            if is_cut:
                self._submit_sql_condition_operation(
                    bid_ref,
                    ("move", *condition_uids),
                    "Move Conditions",
                    lambda callback: write_service.queue_conditions_update(
                        bid_ref.file_path,
                        bid_ref.bid_uid,
                        condition_uids,
                        target_changes,
                        callback,
                    ),
                    lambda _result: (
                        self._coordinator.highlight_sidebar(set(condition_uids))
                        if sidebar
                        else None
                    ),
                )
                return

            def committed(result: QueuedMutationResult) -> None:
                authoritative = result.authoritative_result
                new_uids = list(
                    authoritative.created_resource_ids if authoritative else ()
                )
                if new_uids:
                    self._finish_condition_duplicate(
                        new_uids, sidebar, refresh_conditions=False
                    )

            self._submit_sql_condition_operation(
                bid_ref,
                ("paste", *condition_uids),
                "Paste Conditions",
                lambda callback: write_service.queue_conditions_duplicate(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    condition_uids,
                    callback,
                    target_changes=target_changes,
                ),
                committed,
            )
            return
        if is_cut:
            self._move_conditions_to_target(
                bid_ref, write_service, condition_uids, target, sidebar
            )
            return
        result = self._duplicate_conditions_result(
            bid_ref, write_service, condition_uids, sidebar
        )
        new_uids = list(result.value or [])
        if not new_uids:
            logger.warning("Failed to paste duplicate conditions %s", condition_uids)
            return
        if result.refresh_failed:
            self._warn_condition_refresh_failed("duplicated")
            return
        target_applied = False
        for condition_uid in new_uids:
            dto = UpdateConditionDto()
            dto.set("folder_uid", target.get("folder_uid") or None)
            if target_kind == "cdn_type":
                dto.set("cdn_type_uid", target.get("cdn_type_uid") or None)
            result = write_service.update_condition(
                bid_ref.file_path,
                bid_ref.bid_uid,
                condition_uid,
                dto,
                publish_database_refreshed_after_write=False,
            )
            if not result.success:
                logger.warning(
                    "Failed to apply paste target to condition %s: %s",
                    condition_uid,
                    result.error,
                )
            else:
                target_applied = True
        if target_applied:
            write_service.reload_and_notify(bid_ref.file_path)
        self._finish_condition_duplicate(new_uids, sidebar)

    def _move_conditions_to_target(
        self, bid_ref, write_service, condition_uids: list, target: dict, sidebar
    ) -> None:
        if not self._flush_deferred_for_bid(bid_ref):
            return
        moved_uids = []
        target_kind = target.get("kind")
        for condition_uid in condition_uids:
            dto = UpdateConditionDto()
            dto.set("folder_uid", target.get("folder_uid") or None)
            if target_kind == "cdn_type":
                dto.set("cdn_type_uid", target.get("cdn_type_uid") or None)
            result = write_service.update_condition(
                bid_ref.file_path,
                bid_ref.bid_uid,
                condition_uid,
                dto,
                publish_database_refreshed_after_write=False,
            )
            if result.success:
                moved_uids.append(condition_uid)
                continue
            logger.warning(
                "Failed to move condition %s to paste target: %s",
                condition_uid,
                result.error,
            )
        if not moved_uids:
            return
        if not write_service.reload_and_notify(bid_ref.file_path):
            self._warn_condition_refresh_failed("moved")
            return
        self._coordinator.refresh_conditions_ui()
        if sidebar:
            self._coordinator.highlight_sidebar(set(moved_uids))

    def _duplicate_conditions_result(
        self, bid_ref, write_service, condition_uids: list, sidebar
    ):
        if not self._flush_deferred_for_bid(bid_ref):
            return SimpleNamespace(value=[], refresh_failed=False, write_success=False)
        if sidebar:
            with QSignalBlocker(sidebar):
                return write_service.duplicate_conditions_result(
                    bid_ref.file_path, bid_ref.bid_uid, condition_uids
                )
        return write_service.duplicate_conditions_result(
            bid_ref.file_path, bid_ref.bid_uid, condition_uids
        )

    def _warn_condition_refresh_failed(self, action: str) -> None:
        parent = (
            self._coordinator.conditions_sidebar.window()
            if self._coordinator.conditions_sidebar
            else None
        )
        show_warning(
            parent,
            "Refresh Error",
            f"The condition was {action}, but the conditions list could not be "
            "refreshed. Reopen the database to see the latest conditions.",
        )

    def _finish_condition_duplicate(
        self, new_uids: list, sidebar, *, refresh_conditions: bool = True
    ) -> None:
        if refresh_conditions:
            self._coordinator.refresh_conditions_ui()
        if self._coordinator._is_takeoff_2d_view_active():
            self._coordinator.placement.enter(new_uids[-1], new_uids)
        if sidebar:
            self._coordinator.highlight_sidebar(set(new_uids), reveal=False)

    def on_delete_requested(self, condition_uids: list) -> None:
        if not condition_uids:
            return
        if not self._coordinator.ui_access_manager.is_allowed(Feature.DELETE_CONDITION):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        sidebar = self._coordinator.conditions_sidebar
        if not sidebar:
            return
        names = [(uid, sidebar.get_condition_name(uid)) for uid in condition_uids]
        confirmed_uids = confirm_delete_conditions(sidebar.window(), names)
        if not confirmed_uids:
            return
        replacement_uid = sidebar.condition_selection_after_delete(confirmed_uids)
        if not self._flush_deferred_for_bid(bid_ref):
            return
        if self._uses_sql_queue(bid_ref):
            self._submit_sql_condition_operation(
                bid_ref,
                ("delete", *confirmed_uids),
                "Delete Conditions",
                lambda callback: write_service.queue_conditions_delete(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    confirmed_uids,
                    callback,
                ),
                lambda _result: self._finish_queued_condition_delete(replacement_uid),
            )
            return
        success = write_service.delete_conditions(
            bid_ref.file_path, bid_ref.bid_uid, confirmed_uids
        )
        if not success:
            logger.warning("Failed to delete conditions %s", confirmed_uids)
            return
        self._coordinator.placement.force_exit()
        self._coordinator.ensure_select_mode()
        self._coordinator.refresh_conditions_ui()
        self._coordinator.highlight_sidebar(
            {replacement_uid} if replacement_uid else set(), reveal=False
        )

    def _finish_queued_condition_delete(self, replacement_uid: Optional[str]) -> None:
        self._coordinator.placement.force_exit()
        self._coordinator.ensure_select_mode()
        self._coordinator.highlight_sidebar(
            {replacement_uid} if replacement_uid else set(), reveal=False
        )

    def can_renumber_conditions(self) -> bool:
        return bool(
            self._ui_state.get_selected_bid_ref()
            and self._coordinator.ui_access_manager.is_allowed(Feature.EDIT_CONDITION)
            and self._project_data.get_bid_conditions()
        )

    def on_renumber_requested(self) -> None:
        if not self.can_renumber_conditions():
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        sidebar = self._coordinator.conditions_sidebar
        if not bid_ref or not write_service or not sidebar:
            return
        self._coordinator.refresh_conditions_ui()
        ordered_uids = sidebar.collect_ordered_condition_uids()
        if not ordered_uids:
            return
        if not confirm(
            sidebar.window(),
            "Renumber Conditions",
            "Renumber all the conditions using the current sort order?\n"
            "This cannot be undone",
        ):
            return
        if not self._flush_deferred_for_bid(bid_ref):
            return
        if self._uses_sql_queue(bid_ref):
            self._submit_sql_condition_operation(
                bid_ref,
                ("renumber", *ordered_uids),
                "Renumber Conditions",
                lambda callback: write_service.queue_conditions_renumber(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    ordered_uids,
                    callback,
                ),
            )
            return
        success = write_service.renumber_conditions(
            bid_ref.file_path, bid_ref.bid_uid, ordered_uids
        )
        if not success:
            show_warning(
                sidebar.window(),
                "Renumber Conditions",
                f"Failed to renumber conditions. {DB_LOCKED_HINT}",
            )

    def on_create_folder_requested(self, parent_uid: str) -> None:
        if not self._coordinator.ui_access_manager.is_allowed(
            Feature.EDIT_CONDITION_STRUCTURE
        ):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        sidebar = self._coordinator.conditions_sidebar
        if not sidebar:
            return
        parent = parent_uid or None
        if not self._flush_deferred_for_bid(bid_ref):
            return
        if self._uses_sql_queue(bid_ref):
            self._submit_sql_condition_operation(
                bid_ref,
                ("create_folder", str(parent or "root")),
                "Create Condition Folder",
                lambda callback: write_service.queue_condition_folder_create(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    "New Folder",
                    parent,
                    callback,
                ),
                lambda result: self._finish_queued_folder_create(result, sidebar),
            )
            return
        result = write_service.create_condition_folder_result(
            bid_ref.file_path, bid_ref.bid_uid, "New Folder", parent
        )
        if not result.write_success or not result.value:
            logger.warning("Failed to create condition folder under parent %s", parent)
            return
        if result.refresh_failed:
            self._warn_condition_refresh_failed("created")
            return
        sidebar.set_pending_folder_edit(str(result.value))

    @staticmethod
    def _finish_queued_folder_create(result: QueuedMutationResult, sidebar) -> None:
        authoritative = result.authoritative_result
        created = authoritative.created_resource_ids if authoritative else ()
        if created:
            sidebar.set_pending_folder_edit(str(created[0]))

    def on_folder_renamed(self, folder_uid: str, new_name: str) -> None:
        if not self._coordinator.ui_access_manager.is_allowed(
            Feature.EDIT_CONDITION_STRUCTURE
        ):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        if not self._flush_deferred_for_bid(bid_ref):
            return
        if self._uses_sql_queue(bid_ref):
            self._submit_sql_condition_operation(
                bid_ref,
                ("rename_folder", str(folder_uid)),
                "Rename Condition Folder",
                lambda callback: write_service.queue_condition_folder_rename(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    folder_uid,
                    new_name,
                    callback,
                ),
            )
            return
        success = write_service.rename_condition_folder(
            bid_ref.file_path, folder_uid, new_name
        )
        if not success:
            logger.warning("Failed to rename condition folder %s", folder_uid)
            self._coordinator.refresh_conditions_ui()

    def on_condition_renamed(self, condition_uid: str, new_name: str) -> None:
        if not self._coordinator.ui_access_manager.is_allowed(Feature.EDIT_CONDITION):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        sidebar = self._coordinator.conditions_sidebar
        if sidebar:
            sidebar.set_pending_condition_selection(condition_uid)
        dto = UpdateConditionDto()
        dto.set("name", new_name)
        if not self._flush_deferred_for_bid(bid_ref):
            return
        if self._uses_sql_queue(bid_ref):
            self._submit_sql_condition_operation(
                bid_ref,
                ("rename_condition", str(condition_uid)),
                "Rename Condition",
                lambda callback: write_service.queue_conditions_update(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    [condition_uid],
                    {"name": new_name},
                    callback,
                ),
                lambda _result: self._coordinator.highlight_sidebar({condition_uid}),
            )
            return
        result = write_service.update_condition(
            bid_ref.file_path,
            bid_ref.bid_uid,
            condition_uid,
            dto,
        )
        if not result.success:
            logger.warning(
                "Failed to rename condition %s: %s", condition_uid, result.error
            )
            self._coordinator.refresh_conditions_ui()
            if sidebar:
                self._coordinator.highlight_sidebar({condition_uid})

    def on_folder_delete_requested(self, folder_uids: list) -> None:
        if not folder_uids:
            return
        if not self._coordinator.ui_access_manager.is_allowed(
            Feature.EDIT_CONDITION_STRUCTURE
        ):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        if not self._flush_deferred_for_bid(bid_ref):
            return
        validation = write_service.validate_condition_folder_delete(
            bid_ref.file_path, bid_ref.bid_uid, folder_uids
        )
        folder_names = {
            str(uid): folder.name
            for uid, folder in self._project_data.get_bid_condition_folders().items()
        }
        items = [
            (folder_names.get(str(uid), str(uid)), str(uid)) for uid in folder_uids
        ]
        to_delete = confirm_multi_delete(
            self._coordinator.conditions_sidebar.window(),
            "Delete Folder",
            items,
            set(validation.blocked_uids),
        )
        if not to_delete:
            return
        delete_uids = [uid for _, uid in to_delete]
        if self._uses_sql_queue(bid_ref):
            self._submit_sql_condition_operation(
                bid_ref,
                ("delete_folders", *delete_uids),
                "Delete Condition Folders",
                lambda callback: write_service.queue_condition_folders_delete(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    delete_uids,
                    callback,
                ),
            )
            return
        result = write_service.delete_condition_folders_result(
            bid_ref.file_path, bid_ref.bid_uid, delete_uids
        )
        if not result.write_success:
            logger.warning("Failed to delete condition folders %s", folder_uids)

    def on_move_condition_to_folder(self, condition_uid: str, folder_uid: str) -> None:
        if not self._coordinator.ui_access_manager.is_allowed(
            Feature.EDIT_CONDITION_STRUCTURE
        ):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        dto = UpdateConditionDto()
        dto.set("folder_uid", folder_uid or None)
        if not self._flush_deferred_for_bid(bid_ref):
            return
        if self._uses_sql_queue(bid_ref):
            self._submit_sql_condition_operation(
                bid_ref,
                ("move_condition", str(condition_uid)),
                "Move Condition",
                lambda callback: write_service.queue_conditions_update(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    [condition_uid],
                    {"folder_uid": folder_uid or None},
                    callback,
                ),
                lambda _result: self._coordinator.highlight_sidebar({condition_uid}),
            )
            return
        result = write_service.update_condition(
            bid_ref.file_path, bid_ref.bid_uid, condition_uid, dto
        )
        if not result.success:
            logger.warning(
                "Failed to move condition %s to folder %s", condition_uid, folder_uid
            )

    def on_condition_layer_change_requested(
        self, condition_uids: list, layer_uid: str
    ) -> None:
        self._update_conditions_field(condition_uids, "layer_uid", layer_uid or None)

    def on_condition_type_change_requested(
        self, condition_uids: list, cdn_type_uid: str
    ) -> None:
        self._update_conditions_field(
            condition_uids, "cdn_type_uid", cdn_type_uid or None
        )

    def _update_conditions_field(
        self, condition_uids: list, field_name: str, value
    ) -> None:
        if not condition_uids:
            return
        if not self._coordinator.ui_access_manager.is_allowed(Feature.EDIT_CONDITION):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        sidebar = self._coordinator.conditions_sidebar
        changed_uids = []
        if not self._flush_deferred_for_bid(bid_ref):
            return
        if self._uses_sql_queue(bid_ref):
            self._submit_sql_condition_operation(
                bid_ref,
                ("bulk_update", field_name, *condition_uids),
                "Update Conditions",
                lambda callback: write_service.queue_conditions_update(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    condition_uids,
                    {field_name: value},
                    callback,
                ),
                lambda _result: (
                    self._coordinator.highlight_sidebar(set(condition_uids))
                    if sidebar
                    else None
                ),
            )
            return
        for condition_uid in condition_uids:
            dto = UpdateConditionDto()
            dto.set(field_name, value)
            result = write_service.update_condition(
                bid_ref.file_path,
                bid_ref.bid_uid,
                condition_uid,
                dto,
                publish_database_refreshed_after_write=False,
            )
            if result.success:
                changed_uids.append(condition_uid)
                continue
            logger.warning(
                "Failed to update condition %s %s: %s",
                condition_uid,
                field_name,
                result.error,
            )
        if not changed_uids:
            return
        if not write_service.reload_and_notify(bid_ref.file_path):
            self._warn_condition_refresh_failed("updated")
            return
        self._coordinator.refresh_conditions_ui()
        if sidebar:
            self._coordinator.highlight_sidebar(set(changed_uids))

    def on_edit_requested(self, condition_uids: list) -> None:
        if not condition_uids:
            return
        bid_locked = self._project_data.is_current_bid_locked()
        can_edit = self._coordinator.ui_access_manager.is_allowed(
            Feature.EDIT_CONDITION
        )
        if not can_edit and not (
            bid_locked and self._coordinator.ui_access_manager.has_license()
        ):
            return
        bid_ref, write_service = self._get_bid_ref_and_write_service()
        if not bid_ref or not write_service:
            return
        sidebar = self._coordinator.conditions_sidebar
        if not sidebar:
            return
        conditions = self._project_data.get_bid_conditions()
        selected_conds = [
            conditions[uid] for uid in condition_uids if uid in conditions
        ]
        if not selected_conds:
            return
        ordered_uids = sidebar.collect_ordered_condition_uids()
        uses_sql_queue = self._uses_sql_queue(bid_ref)
        cdn_types = (
            self._project_data.get_cdn_types()
            if uses_sql_queue
            else self._read_service.get_cdn_types(bid_ref.file_path)
        )
        save_condition_types = lambda changes: self._save_condition_types_from_dialog(
            bid_ref, write_service, changes
        )
        reload_condition_types = (
            (lambda: list(self._project_data.get_cdn_types().values()))
            if uses_sql_queue
            else (
                lambda: list(
                    self._read_service.get_cdn_types(bid_ref.file_path).values()
                )
            )
        )
        blocked_condition_type_delete_uids = (
            (lambda _uids: set())
            if uses_sql_queue
            else lambda uids: self._blocked_condition_type_delete_uids_from_dialog(
                bid_ref, write_service, uids
            )
        )
        delete_condition_types = lambda uids: (
            self._delete_condition_types_from_dialog(bid_ref, write_service, uids)
        )
        all_bid_layers = (
            self._project_data.get_bid_layer_snapshot()
            if uses_sql_queue
            else self._read_service.get_merged_bid_layers(
                bid_ref.file_path, bid_ref.bid_uid
            )
        )
        layers = {
            bl.uid: Layer(uid=bl.uid, name=bl.name, visible=bl.show)
            for bl in all_bid_layers
        }
        all_takeoffs = self._project_data.get_all_takeoffs()
        cond_uids_with_takeoffs = {t.condition_uid for t in all_takeoffs}

        def has_takeoffs(cond_uid: str) -> bool:
            return cond_uid in cond_uids_with_takeoffs

        def save_condition(cond_uid, dto):
            if not self._flush_deferred_for_bid(bid_ref):
                return UpdateConditionResultDto(
                    success=False, error="Failed to save pending visual state."
                )
            with QSignalBlocker(sidebar):
                result = write_service.update_condition(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    cond_uid,
                    dto,
                )
                if result.success:
                    self._coordinator.refresh_conditions_ui()
                    dialog.refresh_condition_data(
                        self._project_data.get_bid_conditions()
                    )
            if result.success:
                self._coordinator.highlight_sidebar({cond_uid})
            return result

        def save_condition_async(cond_uid, dto, completed) -> bool:
            if not self._flush_deferred_for_bid(bid_ref):
                completed(
                    UpdateConditionResultDto(
                        success=False,
                        error="Failed to save pending visual state.",
                    )
                )
                return False

            def committed(_result: QueuedMutationResult) -> None:
                dialog.refresh_condition_data(self._project_data.get_bid_conditions())
                self._coordinator.highlight_sidebar({cond_uid})
                completed(UpdateConditionResultDto(success=True))

            def failed(result: QueuedMutationResult) -> None:
                completed(
                    UpdateConditionResultDto(
                        success=False,
                        error=result.message or "Failed to save condition.",
                        error_presented=True,
                    )
                )

            return self._submit_sql_condition_operation(
                bid_ref,
                ("edit_condition", str(cond_uid)),
                "Save Condition",
                lambda callback: write_service.queue_conditions_update(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    [cond_uid],
                    dto.get_changes(),
                    callback,
                ),
                committed,
                failed,
            )

        dialog = EditConditionDialog(
            icon_provider=self._coordinator.main_window.icon_provider,
            parent=sidebar.window(),
            condition=selected_conds[0],
            condition_uids=ordered_uids,
            conditions_map=conditions,
            cdn_types=cdn_types,
            layers=layers,
            has_takeoffs_fn=has_takeoffs,
            save_fn=save_condition,
            save_async_fn=(
                save_condition_async if self._uses_sql_queue(bid_ref) else None
            ),
            condition_type_save_fn=save_condition_types,
            condition_type_save_async_fn=(
                (
                    lambda changes, completed: (
                        self._save_condition_types_async_from_dialog(
                            bid_ref,
                            write_service,
                            changes,
                            completed,
                        )
                    )
                )
                if uses_sql_queue
                else None
            ),
            condition_type_reload_fn=reload_condition_types,
            condition_type_blocked_delete_uids_fn=blocked_condition_type_delete_uids,
            condition_type_delete_fn=delete_condition_types,
            **self._layer_dialog_callbacks(bid_ref, write_service),
            read_service=self._read_service,
            read_only=bid_locked,
            metric=self._is_metric(),
            workspace_state_model=self._workspace_state_model,
        )

        def _on_navigated(uid):
            self._coordinator.highlight_sidebar({uid})
            if (
                self._coordinator.placement.is_active
                and self._coordinator._is_takeoff_2d_view_active()
            ):
                self._coordinator.placement.enter(uid, [uid])

        dialog.condition_navigated.connect(_on_navigated)
        bid_uid = int(bid_ref.bid_uid) if str(bid_ref.bid_uid).isdecimal() else None
        edit_resources = tuple(
            ResourceRef("condition", uid, bid_uid) for uid in condition_uids
        )

        def resolved(result: EditLeaseResult) -> None:
            try:
                if result.granted:
                    exec_with_ost_blocking(dialog, self._coordinator.event_bus)
            finally:
                if result.handle is not None:
                    self._coordinator.end_collaboration_edit(result.handle)
                dialog.deleteLater()

        self._coordinator.request_collaboration_edit(
            bid_ref.file_path,
            edit_resources,
            resolved,
            operation_id="edit-condition-dialog",
            owning_surface="condition-sidebar",
        )
