from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple
from ...domain.entities.file_state import normalize_path
from ...domain.services.takeoff_domain_service import (
    takeoffs_can_reassign_to_condition,
)
from ..dtos.create_condition_spec_dto import CreateConditionSpec
from ..dtos.collaboration_dtos import (
    ChangeOperation,
    QueuedMutationResult,
    ResourceRef,
)
from ..dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ..dtos.update_condition_dto import UpdateConditionDto, UpdateConditionResultDto
from ..interfaces.i_mdb_connection_manager import IMdbConnectionManager
from ..interfaces.i_database_mutation_executor import IDatabaseMutationExecutor
from ..interfaces.i_database_session_registry import IDatabaseSessionRegistry
from ..use_cases.project.create_bid_use_case import CreateBidUseCase
from ..use_cases.project.create_project_use_case import CreateProjectUseCase
from ..use_cases.project.delete_bids_use_case import DeleteBidsUseCase
from ..use_cases.project.delete_condition_folders_use_case import (
    DeleteConditionFoldersUseCase,
)
from ..use_cases.project.delete_conditions_use_case import DeleteConditionsUseCase
from ..use_cases.project.delete_layer_use_case import DeleteLayerUseCase
from ..use_cases.project.delete_pages_use_case import DeletePagesUseCase
from ..use_cases.project.delete_projects_use_case import DeleteProjectsUseCase
from ..use_cases.project.delete_takeoffs_use_case import DeleteTakeoffsUseCase
from ..use_cases.project.duplicate_bid_use_case import DuplicateBidUseCase
from ..use_cases.project.duplicate_conditions_use_case import DuplicateConditionsUseCase
from ..use_cases.project.insert_condition_folder_use_case import (
    InsertConditionFolderUseCase,
)
from ..use_cases.project.insert_condition_use_case import InsertConditionUseCase
from ..use_cases.project.insert_layer_use_case import InsertLayerUseCase
from ..use_cases.project.insert_takeoffs_use_case import InsertTakeoffsUseCase
from ..use_cases.project.move_bids_use_case import MoveBidsUseCase
from ..use_cases.project.rename_condition_folder_use_case import (
    RenameConditionFolderUseCase,
)
from ..use_cases.project.rename_project_use_case import RenameProjectUseCase
from ..use_cases.project.renumber_conditions_use_case import RenumberConditionsUseCase
from ..use_cases.project.save_bid_areas_use_case import SaveBidAreasUseCase
from ..use_cases.project.save_bid_selected_page_use_case import (
    SaveBidSelectedPageUseCase,
)
from ..use_cases.project.save_condition_types_use_case import SaveConditionTypesUseCase
from ..use_cases.project.save_cover_sheet_use_case import SaveCoverSheetUseCase
from ..use_cases.project.save_employees_use_case import SaveEmployeesUseCase
from ..use_cases.project.save_job_statuses_use_case import SaveJobStatusesUseCase
from ..use_cases.project.save_page_area_use_case import SavePageAreaUseCase
from ..use_cases.project.save_page_bitonal_use_case import SavePageBitonalUseCase
from ..use_cases.project.save_page_image_adjustments_use_case import (
    SavePageImageAdjustmentsUseCase,
)
from ..use_cases.project.save_page_invert_use_case import SavePageInvertUseCase
from ..use_cases.project.save_page_name_use_case import SavePageNameUseCase
from ..use_cases.project.save_page_overlay_image_use_case import (
    SavePageOverlayImageUseCase,
)
from ..use_cases.project.save_page_overlay_rect_use_case import (
    SavePageOverlayRectUseCase,
)
from ..use_cases.project.save_page_scale_use_case import SavePageScaleUseCase
from ..use_cases.project.save_page_show_mode_use_case import SavePageShowModeUseCase
from ..use_cases.project.save_page_view_state_use_case import SavePageViewStateUseCase
from ..use_cases.project.save_pay_classes_use_case import SavePayClassesUseCase
from ..use_cases.project.save_takeoff_positions_use_case import (
    SaveTakeoffPositionsUseCase,
)
from ..use_cases.project.save_takeoff_rotations_use_case import (
    SaveTakeoffRotationsUseCase,
)
from ..use_cases.project.save_takeoff_text_properties_use_case import (
    SaveTakeoffTextPropertiesUseCase,
)
from ..use_cases.project.save_takeoffs_area_use_case import SaveTakeoffsAreaUseCase
from ..use_cases.project.save_takeoffs_condition_use_case import (
    SaveTakeoffsConditionUseCase,
)
from ..use_cases.project.set_takeoff_curve_use_case import SetTakeoffCurveUseCase
from ..use_cases.project.set_takeoffs_negative_use_case import (
    SetTakeoffsNegativeUseCase,
)
from ..use_cases.project.swap_layer_sequence_use_case import SwapLayerSequenceUseCase
from ..use_cases.project.update_all_layers_show_use_case import (
    UpdateAllLayersShowUseCase,
)
from ..use_cases.project.update_bid_job_status_use_case import UpdateBidJobStatusUseCase
from ..use_cases.project.update_condition_use_case import UpdateConditionUseCase
from ..use_cases.project.update_layer_name_use_case import UpdateLayerNameUseCase
from ..use_cases.project.update_layer_show_use_case import UpdateLayerShowUseCase
from .active_bid_write_guard import ActiveBidWriteGuard
from .base_write_service import DatabaseMutationWriteService
from .database_concurrency_token_service import DatabaseConcurrencyTokenService
from .database_capability_service import DatabaseCapabilityService

if TYPE_CHECKING:
    from .sql_collaboration_coordinator import SqlCollaborationCoordinator


@dataclass
class BatchWriteResult:
    requested_uids: List[str] = field(default_factory=list)
    succeeded_uids: List[str] = field(default_factory=list)
    failed_uids: List[str] = field(default_factory=list)
    reload_success: bool = True

    @property
    def any_success(self) -> bool:
        return bool(self.succeeded_uids)

    @property
    def partial_success(self) -> bool:
        return bool(self.succeeded_uids and self.failed_uids)

    @property
    def success(self) -> bool:
        return (
            bool(self.requested_uids) and not self.failed_uids and self.reload_success
        )

    def __bool__(self) -> bool:
        return self.success


@dataclass
class WriteReloadResult:
    value: object = None
    write_success: bool = False
    reload_success: bool = False
    failure_reason: Optional[str] = None
    blocked_uids: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return (
            self.write_success
            and self.reload_success
            and not self.failure_reason
            and not self.blocked_uids
        )

    @property
    def refresh_failed(self) -> bool:
        return self.write_success and not self.reload_success

    def __bool__(self) -> bool:
        return self.success


@dataclass
class DeleteValidationResult:
    requested_uids: List[str] = field(default_factory=list)
    blocked_uids: List[str] = field(default_factory=list)
    failure_reason: Optional[str] = None


class ProjectWriteService(DatabaseMutationWriteService):
    def __init__(
        self,
        delete_bids: DeleteBidsUseCase,
        delete_projects: DeleteProjectsUseCase,
        create_project: CreateProjectUseCase,
        rename_project: RenameProjectUseCase,
        move_bids: MoveBidsUseCase,
        duplicate_bid: DuplicateBidUseCase,
        create_bid: CreateBidUseCase,
        delete_conditions: DeleteConditionsUseCase,
        duplicate_conditions: DuplicateConditionsUseCase,
        update_condition: UpdateConditionUseCase,
        renumber_conditions: RenumberConditionsUseCase,
        insert_condition: InsertConditionUseCase,
        insert_condition_folder: InsertConditionFolderUseCase,
        rename_condition_folder: RenameConditionFolderUseCase,
        delete_condition_folders: DeleteConditionFoldersUseCase,
        save_takeoff_positions: SaveTakeoffPositionsUseCase,
        save_takeoff_rotations: SaveTakeoffRotationsUseCase,
        save_takeoff_text_properties: SaveTakeoffTextPropertiesUseCase,
        save_takeoffs_area: SaveTakeoffsAreaUseCase,
        save_takeoffs_condition: SaveTakeoffsConditionUseCase,
        set_takeoffs_negative: SetTakeoffsNegativeUseCase,
        set_takeoff_curve: SetTakeoffCurveUseCase,
        insert_takeoffs: InsertTakeoffsUseCase,
        delete_takeoffs: DeleteTakeoffsUseCase,
        delete_pages: DeletePagesUseCase,
        save_cover_sheet: SaveCoverSheetUseCase,
        update_bid_job_status: UpdateBidJobStatusUseCase,
        save_job_statuses: SaveJobStatusesUseCase,
        save_bid_areas: SaveBidAreasUseCase,
        save_page_name: SavePageNameUseCase,
        save_page_scale: SavePageScaleUseCase,
        save_page_show_mode: SavePageShowModeUseCase,
        save_page_overlay_image: SavePageOverlayImageUseCase,
        save_page_overlay_rect: SavePageOverlayRectUseCase,
        save_page_invert: SavePageInvertUseCase,
        save_page_bitonal: SavePageBitonalUseCase,
        save_page_image_adjustments: SavePageImageAdjustmentsUseCase,
        save_page_area: SavePageAreaUseCase,
        save_employees: SaveEmployeesUseCase,
        save_pay_classes: SavePayClassesUseCase,
        save_condition_types: SaveConditionTypesUseCase,
        update_layer_show: UpdateLayerShowUseCase,
        update_all_layers_show: UpdateAllLayersShowUseCase,
        update_layer_name: UpdateLayerNameUseCase,
        insert_layer: InsertLayerUseCase,
        delete_layer: DeleteLayerUseCase,
        swap_layer_sequence: SwapLayerSequenceUseCase,
        save_bid_selected_page: SaveBidSelectedPageUseCase,
        save_page_view_state: SavePageViewStateUseCase,
        mutation_executor: IDatabaseMutationExecutor,
        session_registry: IDatabaseSessionRegistry,
        concurrency_tokens: DatabaseConcurrencyTokenService,
        database_capability_service: DatabaseCapabilityService,
        sql_collaboration_provider: Callable[[], "SqlCollaborationCoordinator"],
        connection_manager: Optional[IMdbConnectionManager] = None,
        reload_database=None,
        event_bus=None,
        logger=None,
        bid_write_guard: Optional[ActiveBidWriteGuard] = None,
        project_data_service=None,
        condition_type_uids_in_use_provider: Optional[Callable[[str], set]] = None,
    ) -> None:
        if bid_write_guard is None:
            raise ValueError("ProjectWriteService requires bid_write_guard")
        if project_data_service is None:
            raise ValueError("ProjectWriteService requires project_data_service")
        if mutation_executor is None:
            raise ValueError("ProjectWriteService requires mutation_executor")
        if session_registry is None:
            raise ValueError("ProjectWriteService requires session_registry")
        if concurrency_tokens is None:
            raise ValueError("ProjectWriteService requires concurrency_tokens")
        if sql_collaboration_provider is None:
            raise ValueError("ProjectWriteService requires sql_collaboration_provider")
        super().__init__(
            reload_database=reload_database,
            event_bus=event_bus,
            mutation_executor=mutation_executor,
            session_registry=session_registry,
            concurrency_tokens=concurrency_tokens,
            database_capability_service=database_capability_service,
            logger=logger,
        )
        self._bid_write_guard = bid_write_guard
        self._connection_manager = connection_manager
        self._project_data = project_data_service
        self._condition_type_uids_in_use_provider = condition_type_uids_in_use_provider
        self._sql_collaboration_provider = sql_collaboration_provider
        self._delete_bids = delete_bids
        self._delete_projects = delete_projects
        self._create_project = create_project
        self._rename_project = rename_project
        self._move_bids = move_bids
        self._duplicate_bid = duplicate_bid
        self._create_bid = create_bid
        self._delete_conditions = delete_conditions
        self._duplicate_conditions = duplicate_conditions
        self._update_condition = update_condition
        self._renumber_conditions = renumber_conditions
        self._insert_condition = insert_condition
        self._insert_condition_folder = insert_condition_folder
        self._rename_condition_folder = rename_condition_folder
        self._delete_condition_folders = delete_condition_folders
        self._save_takeoff_positions = save_takeoff_positions
        self._save_takeoff_rotations = save_takeoff_rotations
        self._save_takeoff_text_properties = save_takeoff_text_properties
        self._save_takeoffs_area = save_takeoffs_area
        self._save_takeoffs_condition = save_takeoffs_condition
        self._set_takeoffs_negative = set_takeoffs_negative
        self._set_takeoff_curve = set_takeoff_curve
        self._insert_takeoffs = insert_takeoffs
        self._delete_takeoffs = delete_takeoffs
        self._delete_pages = delete_pages
        self._save_cover_sheet = save_cover_sheet
        self._update_bid_job_status = update_bid_job_status
        self._save_job_statuses = save_job_statuses
        self._save_bid_areas = save_bid_areas
        self._save_page_name = save_page_name
        self._save_page_scale = save_page_scale
        self._save_page_show_mode = save_page_show_mode
        self._save_page_overlay_image = save_page_overlay_image
        self._save_page_overlay_rect = save_page_overlay_rect
        self._save_page_invert = save_page_invert
        self._save_page_bitonal = save_page_bitonal
        self._save_page_image_adjustments = save_page_image_adjustments
        self._save_page_area = save_page_area
        self._save_employees = save_employees
        self._save_pay_classes = save_pay_classes
        self._save_condition_types = save_condition_types
        self._update_layer_show = update_layer_show
        self._update_all_layers_show = update_all_layers_show
        self._update_layer_name = update_layer_name
        self._insert_layer = insert_layer
        self._delete_layer = delete_layer
        self._swap_layer_sequence = swap_layer_sequence
        self._save_bid_selected_page = save_bid_selected_page
        self._save_page_view_state = save_page_view_state

    def _is_write_blocked(self) -> bool:
        return bool(
            self._connection_manager and self._connection_manager.is_write_blocked()
        )

    def _active_bid_uid_for(self, db_path: str) -> Optional[int]:
        bid_ref = self._project_data.get_current_bid_ref()
        if bid_ref is None or normalize_path(db_path) != normalize_path(
            bid_ref.file_path
        ):
            return None
        return int(bid_ref.bid_uid)

    def _execute_boolean_resource_mutation(
        self,
        db_path: str,
        resources: tuple[ResourceRef, ...],
        change_operation: ChangeOperation,
        operation,
        changed_fields: tuple[str, ...] = (),
        *,
        block_bid_child_locks: bool = False,
        block_bid_active_editors: bool = False,
    ) -> bool:
        if not resources:
            return False

        def execute(recorder):
            success = bool(operation())
            if success:
                for resource in resources:
                    recorder.record(
                        resource,
                        change_operation,
                        changed_fields=changed_fields,
                    )
            return success

        result = self._execute_database_mutation(
            db_path,
            resources,
            execute,
            block_bid_child_locks=block_bid_child_locks,
            block_bid_active_editors=block_bid_active_editors,
        )
        return bool(result.success and result.value)

    def is_expected_deferred_write_blocked(
        self, db_path: str, bid_uid: Optional[str] = None
    ) -> bool:
        if not self._database_capability_service.is_editable(db_path):
            return True
        if self._is_write_blocked():
            return True
        return self._bid_write_guard.is_active_locked_bid_write_blocked(
            db_path, bid_uid
        )

    def _reload_after_success(
        self,
        db_path: str,
        success: bool,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if not success:
            return False
        if not publish_database_refreshed_after_write:
            return True
        return self.reload_and_notify(db_path)

    def delete_bids(
        self,
        db_path: str,
        bid_uids: List[str],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if not bid_uids:
            return True
        resources = tuple(ResourceRef("bid", str(uid), int(uid)) for uid in bid_uids)
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.DELETE,
            lambda: self._delete_bids.execute(db_path, bid_uids),
            block_bid_child_locks=True,
            block_bid_active_editors=True,
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def delete_projects(self, db_path: str, project_uids: List[str]) -> bool:
        if not project_uids:
            return True
        if self._bid_write_guard.blocks_active_locked_bid_project_delete(
            db_path, project_uids
        ):
            return False
        project_resources = tuple(
            ResourceRef("project", str(uid)) for uid in project_uids
        )
        bid_resources = tuple(
            ResourceRef("bid", uid, int(uid))
            for uid in self._project_data.get_project_bid_uids(db_path, project_uids)
        )
        collection = ResourceRef("projects_collection", "database")
        resources = project_resources + bid_resources + (collection,)

        def delete(recorder):
            success = self._delete_projects.execute(db_path, project_uids)
            if success:
                for resource in project_resources:
                    recorder.record(resource, ChangeOperation.DELETE)
                for resource in bid_resources:
                    recorder.record(
                        resource,
                        ChangeOperation.MOVE,
                        changed_fields=("project_uid",),
                    )
                recorder.record(collection, ChangeOperation.UPDATE)
            return success

        mutation = self._execute_database_mutation(
            db_path,
            resources,
            delete,
            block_bid_child_locks=True,
            block_bid_active_editors=True,
        )
        success = bool(mutation.success and mutation.value)
        return self._reload_after_success(db_path, success)

    def create_project(self, db_path: str, name: str) -> Optional[str]:
        result = self.create_project_result(db_path, name)
        return str(result.value) if result.success and result.value else None

    def create_project_result(self, db_path: str, name: str) -> WriteReloadResult:
        collection = ResourceRef("projects_collection", "database")

        def create(recorder):
            new_uid = self._create_project.execute(db_path, name)
            if new_uid is not None:
                recorder.record(
                    ResourceRef("project", str(new_uid)),
                    ChangeOperation.CREATE,
                    changed_fields=("name",),
                )
                recorder.record(collection, ChangeOperation.UPDATE)
            return new_uid

        mutation = self._execute_database_mutation(db_path, (collection,), create)
        if not mutation.success or mutation.value is None:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        new_uid = mutation.value
        return WriteReloadResult(
            new_uid,
            write_success=True,
            reload_success=self.reload_and_notify(db_path),
        )

    def rename_project(self, db_path: str, project_uid: str, new_name: str) -> bool:
        success = self._execute_boolean_resource_mutation(
            db_path,
            (ResourceRef("project", project_uid),),
            ChangeOperation.UPDATE,
            lambda: self._rename_project.execute(db_path, project_uid, new_name),
            ("name",),
        )
        return self._reload_after_success(db_path, success)

    def move_bids(
        self,
        db_path: str,
        bid_uids: List[str],
        target_project_uid: Optional[str],
        orig_project_uid: Optional[str] = None,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if not bid_uids:
            return True
        if any(
            self._bid_write_guard.blocks_active_locked_bid_write(db_path, uid)
            for uid in bid_uids
        ):
            return False
        resources = tuple(
            ResourceRef("bid", str(uid), int(uid)) for uid in bid_uids
        ) + tuple(
            ResourceRef("project_bids", project_uid)
            for project_uid in sorted(
                {
                    target_project_uid or "orphan",
                    orig_project_uid or "orphan",
                }
            )
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.MOVE,
            lambda: self._move_bids.execute(
                db_path, bid_uids, target_project_uid, orig_project_uid
            ),
            ("project_uid",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def duplicate_bid(
        self, db_path: str, bid_uid: str, reload: bool = True
    ) -> Optional[str]:
        result = self.duplicate_bid_result(db_path, bid_uid, reload=reload)
        return str(result.value) if result.success and result.value else None

    def duplicate_bid_result(
        self, db_path: str, bid_uid: str, reload: bool = True
    ) -> WriteReloadResult:
        source = ResourceRef("bid", bid_uid, int(bid_uid))

        def duplicate(recorder):
            new_uid = self._duplicate_bid.execute(db_path, bid_uid)
            if new_uid is not None:
                recorder.record(
                    ResourceRef("bid", str(new_uid)),
                    ChangeOperation.CREATE,
                )
            return new_uid

        mutation = self._execute_database_mutation(
            db_path,
            (source,),
            duplicate,
            block_bid_child_locks=True,
        )
        if not mutation.success or mutation.value is None:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        new_uid = mutation.value
        reload_success = self.reload_and_notify(db_path) if reload else True
        return WriteReloadResult(
            new_uid,
            write_success=True,
            reload_success=reload_success,
        )

    def create_bid(
        self, db_path: str, project_uid: Optional[str], updates: dict
    ) -> Optional[str]:
        result = self.create_bid_result(db_path, project_uid, updates)
        return str(result.value) if result.success and result.value else None

    def create_bid_result(
        self, db_path: str, project_uid: Optional[str], updates: dict
    ) -> WriteReloadResult:
        collection = ResourceRef("project_bids", project_uid or "orphan")

        def create(recorder):
            new_uid = self._create_bid.execute(db_path, project_uid, updates)
            if new_uid is not None:
                recorder.record(
                    ResourceRef("bid", str(new_uid)),
                    ChangeOperation.CREATE,
                )
                recorder.record(collection, ChangeOperation.UPDATE)
            return new_uid

        mutation = self._execute_database_mutation(db_path, (collection,), create)
        if not mutation.success or mutation.value is None:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        new_uid = mutation.value
        return WriteReloadResult(
            new_uid,
            write_success=True,
            reload_success=self.reload_and_notify(db_path),
        )

    def delete_conditions(
        self, db_path: str, bid_uid: str, condition_uids: List[str]
    ) -> bool:
        if not condition_uids:
            return True
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return False
        parsed_bid_uid = int(bid_uid) if bid_uid else None
        collection = ResourceRef(
            "conditions_collection", bid_uid or "unknown", parsed_bid_uid
        )

        def delete(recorder):
            success = self._delete_conditions.execute(db_path, bid_uid, condition_uids)
            if success:
                for condition_uid in condition_uids:
                    recorder.record(
                        ResourceRef("condition", str(condition_uid), parsed_bid_uid),
                        ChangeOperation.DELETE,
                    )
                recorder.record(collection, ChangeOperation.UPDATE)
            return success

        success = self._execute_database_mutation(db_path, (collection,), delete).value
        return self._reload_after_success(db_path, success)

    def create_condition_result(
        self, db_path: str, bid_uid: str, spec: CreateConditionSpec
    ) -> WriteReloadResult:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return WriteReloadResult(None, write_success=False, reload_success=False)
        parsed_bid_uid = int(bid_uid) if bid_uid else None
        collection = ResourceRef(
            "conditions_collection", bid_uid or "unknown", parsed_bid_uid
        )

        def create(recorder):
            new_uid = self._insert_condition.execute(db_path, bid_uid, spec)
            if new_uid is not None:
                recorder.record(
                    ResourceRef("condition", str(new_uid), int(bid_uid)),
                    ChangeOperation.CREATE,
                )
                recorder.record(collection, ChangeOperation.UPDATE)
            return new_uid

        mutation = self._execute_database_mutation(db_path, (collection,), create)
        new_uid = mutation.value if mutation.success else None
        if new_uid is None:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        return WriteReloadResult(
            new_uid,
            write_success=True,
            reload_success=self.reload_and_notify(db_path),
        )

    def create_condition_folder_result(
        self,
        db_path: str,
        bid_uid: str,
        name: str,
        parent_uid: Optional[str] = None,
    ) -> WriteReloadResult:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return WriteReloadResult(None, write_success=False, reload_success=False)
        collection = ResourceRef("conditions_collection", bid_uid, int(bid_uid))

        def create_folder(recorder):
            new_uid = self._insert_condition_folder.execute(
                db_path, bid_uid, name, parent_uid
            )
            if new_uid is not None:
                recorder.record(
                    ResourceRef("condition_folder", str(new_uid), int(bid_uid)),
                    ChangeOperation.CREATE,
                )
                recorder.record(collection, ChangeOperation.UPDATE)
            return new_uid

        mutation = self._execute_database_mutation(
            db_path, (collection,), create_folder
        )
        new_uid = mutation.value if mutation.success else None
        if new_uid is None:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        return WriteReloadResult(
            new_uid,
            write_success=True,
            reload_success=self.reload_and_notify(db_path),
        )

    def rename_condition_folder(self, db_path: str, folder_uid: str, name: str) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        bid_ref = self._project_data.get_current_bid_ref()
        bid_uid = int(bid_ref.bid_uid) if bid_ref else None
        resource = ResourceRef("condition_folder", folder_uid, bid_uid)

        def rename(recorder):
            success = self._rename_condition_folder.execute(db_path, folder_uid, name)
            if success:
                recorder.record(resource, ChangeOperation.UPDATE)
            return success

        success = self._execute_database_mutation(db_path, (resource,), rename).value
        return self._reload_after_success(db_path, success)

    def validate_condition_folder_delete(
        self, db_path: str, bid_uid: str, folder_uids: List[str]
    ) -> DeleteValidationResult:
        requested = [str(uid) for uid in (folder_uids or [])]
        blocked = self._condition_folder_uids_in_use(requested)
        return DeleteValidationResult(
            requested_uids=requested,
            blocked_uids=blocked,
            failure_reason="condition_folder_in_use" if blocked else None,
        )

    def delete_condition_folders_result(
        self, db_path: str, bid_uid: str, folder_uids: List[str]
    ) -> WriteReloadResult:
        if not folder_uids:
            return WriteReloadResult([], write_success=True, reload_success=True)
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return WriteReloadResult(None, write_success=False, reload_success=False)
        validation = self.validate_condition_folder_delete(
            db_path, bid_uid, folder_uids
        )
        blocked = set(validation.blocked_uids)
        deletable_uids = [
            uid for uid in validation.requested_uids if uid not in blocked
        ]
        if not deletable_uids:
            return WriteReloadResult(
                None,
                write_success=False,
                reload_success=False,
                failure_reason=validation.failure_reason,
                blocked_uids=validation.blocked_uids,
            )
        parsed_bid_uid = int(bid_uid) if bid_uid else None
        collection = ResourceRef(
            "conditions_collection", bid_uid or "unknown", parsed_bid_uid
        )

        def delete_folders(recorder):
            success = self._delete_condition_folders.execute(db_path, deletable_uids)
            if success:
                for folder_uid in deletable_uids:
                    recorder.record(
                        ResourceRef("condition_folder", folder_uid, parsed_bid_uid),
                        ChangeOperation.DELETE,
                    )
                recorder.record(collection, ChangeOperation.UPDATE)
            return success

        success = self._execute_database_mutation(
            db_path, (collection,), delete_folders
        ).value
        reload_success = self.reload_and_notify(db_path) if success else False
        return WriteReloadResult(
            deletable_uids,
            write_success=success,
            reload_success=reload_success,
            failure_reason=validation.failure_reason,
            blocked_uids=validation.blocked_uids,
        )

    def delete_condition_folders(self, db_path: str, folder_uids: List[str]) -> bool:
        bid_ref = self._project_data.get_current_bid_ref()
        bid_uid = bid_ref.bid_uid if bid_ref else ""
        result = self.delete_condition_folders_result(db_path, bid_uid, folder_uids)
        return result.success

    def _condition_folder_uids_in_use(self, folder_uids: List[str]) -> List[str]:
        folders = self._project_data.get_bid_condition_folders()
        folder_keys = {str(uid) for uid in folders}
        selected = {str(uid) for uid in folder_uids}
        parent_by_uid = {
            str(uid): str(folder.parent_uid) if folder.parent_uid else None
            for uid, folder in folders.items()
        }
        blocked: set[str] = set()
        for condition in self._project_data.get_bid_conditions().values():
            current = str(condition.folder_uid) if condition.folder_uid else None
            if current not in folder_keys:
                continue
            while current:
                if current in selected:
                    blocked.add(current)
                current = parent_by_uid.get(current)
        return [uid for uid in folder_uids if uid in blocked]

    def duplicate_conditions(
        self, db_path: str, bid_uid: str, condition_uids: list
    ) -> list:
        result = self.duplicate_conditions_result(db_path, bid_uid, condition_uids)
        return list(result.value or []) if result.success else []

    def duplicate_conditions_result(
        self, db_path: str, bid_uid: str, condition_uids: list
    ) -> WriteReloadResult:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return WriteReloadResult([], write_success=False, reload_success=False)
        collection = ResourceRef("conditions_collection", bid_uid, int(bid_uid))

        def duplicate(recorder):
            new_uids = self._duplicate_conditions.execute(
                db_path, bid_uid, condition_uids
            )
            for new_uid in new_uids or ():
                recorder.record(
                    ResourceRef("condition", str(new_uid), int(bid_uid)),
                    ChangeOperation.CREATE,
                )
            if new_uids:
                recorder.record(collection, ChangeOperation.UPDATE)
            return new_uids

        mutation = self._execute_database_mutation(db_path, (collection,), duplicate)
        new_uids = mutation.value if mutation.success else None
        if not new_uids:
            return WriteReloadResult([], write_success=False, reload_success=False)
        return WriteReloadResult(
            list(new_uids),
            write_success=True,
            reload_success=self.reload_and_notify(db_path),
        )

    def duplicate_conditions_to_bid(
        self,
        db_path: str,
        source_bid_uid: str,
        destination_bid_uid: str,
        condition_uids: list,
        publish_database_refreshed_after_write: bool = True,
    ) -> dict:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            db_path, destination_bid_uid
        ):
            return {}
        collection = ResourceRef(
            "conditions_collection", destination_bid_uid, int(destination_bid_uid)
        )

        def duplicate_to_bid(recorder):
            uid_map = self._duplicate_conditions.execute_to_bid(
                db_path, source_bid_uid, destination_bid_uid, condition_uids
            )
            for new_uid in uid_map.values():
                recorder.record(
                    ResourceRef("condition", str(new_uid), int(destination_bid_uid)),
                    ChangeOperation.CREATE,
                )
            if uid_map:
                recorder.record(collection, ChangeOperation.UPDATE)
            return uid_map

        mutation = self._execute_database_mutation(
            db_path, (collection,), duplicate_to_bid
        )
        uid_map = mutation.value if mutation.success else {}
        if (
            uid_map
            and publish_database_refreshed_after_write
            and not self.reload_and_notify(db_path)
        ):
            return {}
        return uid_map

    def update_condition(
        self,
        db_path: str,
        bid_uid: str,
        condition_uid: str,
        updates: UpdateConditionDto,
        all_conditions=None,
        publish_database_refreshed_after_write: bool = True,
    ) -> UpdateConditionResultDto:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return UpdateConditionResultDto(
                success=False, error="The active bid is locked"
            )
        resource = ResourceRef("condition", condition_uid, int(bid_uid))

        def update(recorder):
            result = self._update_condition.execute(
                db_path, bid_uid, condition_uid, updates, all_conditions
            )
            if result.success:
                recorder.record(resource, ChangeOperation.UPDATE)
            return result

        mutation = self._execute_database_mutation(db_path, (resource,), update)
        if not mutation.success or mutation.value is None:
            error = (
                mutation.conflict.reason
                if mutation.conflict is not None
                else "The condition update could not be completed"
            )
            return UpdateConditionResultDto(
                success=False,
                error=error,
            )
        result = mutation.value
        if (
            result.success
            and publish_database_refreshed_after_write
            and not self.reload_and_notify(db_path)
        ):
            result.success = False
            result.error = "Database reload failed after saving condition"
        return result

    def renumber_conditions(
        self, db_path: str, bid_uid: str, ordered_condition_uids: List[str]
    ) -> bool:
        if not ordered_condition_uids:
            return True
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return False
        collection = ResourceRef("conditions_collection", bid_uid, int(bid_uid))

        def reorder(recorder):
            success = self._renumber_conditions.execute(
                db_path, bid_uid, ordered_condition_uids
            )
            if success:
                recorder.record(collection, ChangeOperation.REORDER)
            return success

        success = self._execute_database_mutation(db_path, (collection,), reorder).value
        return self._reload_after_success(db_path, success)

    def set_takeoff_curve(
        self,
        db_path: str,
        takeoff_uid: str,
        position: List[float],
        curve: int,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef(
            "takeoff", takeoff_uid, self._active_bid_uid_for(db_path)
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._set_takeoff_curve.execute(
                db_path, takeoff_uid, position, curve
            ),
            ("position", "curve"),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def save_takeoff_positions(
        self,
        db_path: str,
        positions: List[Tuple[str, List[float]]],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resources = tuple(
            ResourceRef("takeoff", str(uid), self._active_bid_uid_for(db_path))
            for uid, _position in positions
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.UPDATE,
            lambda: self._save_takeoff_positions.execute(db_path, positions),
            ("position",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def save_takeoff_rotations(
        self,
        db_path: str,
        rotations: List[Tuple[str, float]],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resources = tuple(
            ResourceRef("takeoff", str(uid), self._active_bid_uid_for(db_path))
            for uid, _rotation in rotations
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.UPDATE,
            lambda: self._save_takeoff_rotations.execute(db_path, rotations),
            ("rotation",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def save_takeoff_text_properties(
        self,
        db_path: str,
        updates: List[Tuple[str, dict]],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resources = tuple(
            ResourceRef("takeoff", str(uid), self._active_bid_uid_for(db_path))
            for uid, _properties in updates
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.UPDATE,
            lambda: self._save_takeoff_text_properties.execute(db_path, updates),
            ("text_properties",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def save_takeoffs_area(
        self,
        db_path: str,
        takeoff_uids: List[str],
        area_uid: str,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        return self._save_takeoffs_assignment(
            self._save_takeoffs_area,
            db_path,
            takeoff_uids,
            area_uid,
            publish_database_refreshed_after_write,
        )

    def save_takeoffs_condition(
        self,
        db_path: str,
        takeoff_uids: List[str],
        condition_uid: str,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        if takeoff_uids and not self._can_reassign_takeoffs_condition(
            db_path, takeoff_uids, condition_uid
        ):
            return False
        resources = tuple(
            ResourceRef("takeoff", str(uid), self._active_bid_uid_for(db_path))
            for uid in takeoff_uids
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.UPDATE,
            lambda: self._save_takeoffs_condition.execute(
                db_path, takeoff_uids, condition_uid
            ),
            ("condition",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def _can_reassign_takeoffs_condition(
        self,
        db_path: str,
        takeoff_uids: List[str],
        condition_uid: str,
    ) -> bool:
        bid_ref = self._project_data.get_current_bid_ref()
        if bid_ref is None or normalize_path(db_path) != normalize_path(
            bid_ref.file_path
        ):
            self.logger.warning(
                "Cannot reassign takeoffs outside the active bid: %s", db_path
            )
            return False
        takeoffs_by_uid = {
            str(takeoff.uid): takeoff
            for takeoff in self._project_data.get_all_takeoffs()
        }
        selected_takeoffs = []
        for uid in takeoff_uids:
            takeoff = takeoffs_by_uid.get(str(uid))
            if takeoff is None:
                self.logger.warning(
                    "Cannot reassign unknown takeoff %s in %s", uid, db_path
                )
                return False
            selected_takeoffs.append(takeoff)
        if not takeoffs_can_reassign_to_condition(
            selected_takeoffs,
            self._project_data.get_bid_conditions(),
            str(condition_uid),
        ):
            self.logger.warning(
                "Rejected incompatible takeoff condition reassignment to %s",
                condition_uid,
            )
            return False
        return True

    def _save_takeoffs_assignment(
        self,
        use_case,
        db_path: str,
        takeoff_uids: List[str],
        target_uid: str,
        publish_database_refreshed_after_write: bool,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resources = tuple(
            ResourceRef("takeoff", str(uid), self._active_bid_uid_for(db_path))
            for uid in takeoff_uids
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.UPDATE,
            lambda: use_case.execute(db_path, takeoff_uids, target_uid),
            ("assignment",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def set_takeoffs_negative(
        self,
        db_path: str,
        takeoff_uids: List[str],
        is_negative: bool,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resources = tuple(
            ResourceRef("takeoff", str(uid), self._active_bid_uid_for(db_path))
            for uid in takeoff_uids
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.UPDATE,
            lambda: self._set_takeoffs_negative.execute(
                db_path, takeoff_uids, is_negative
            ),
            ("negative",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def insert_takeoffs(
        self,
        db_path: str,
        bid_uid: str,
        takeoff_specs: List[InsertTakeoffSpec],
        publish_database_refreshed_after_write: bool = True,
        *,
        consistency_resources: tuple[ResourceRef, ...] = (),
    ) -> List[str]:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return []
        collection = ResourceRef("takeoffs_collection", bid_uid, int(bid_uid))

        def insert(recorder):
            new_uids = self._insert_takeoffs.execute(db_path, bid_uid, takeoff_specs)
            for new_uid in new_uids:
                recorder.record(
                    ResourceRef("takeoff", str(new_uid), int(bid_uid)),
                    ChangeOperation.CREATE,
                )
            if new_uids:
                recorder.record(collection, ChangeOperation.UPDATE)
            return new_uids

        mutation_resources = tuple(sorted({collection, *consistency_resources}))
        mutation = self._execute_database_mutation(db_path, mutation_resources, insert)
        new_uids = mutation.value if mutation.success else []
        if (
            new_uids
            and publish_database_refreshed_after_write
            and not self.reload_and_notify(db_path)
        ):
            return []
        return new_uids

    def uses_queued_takeoff_mutations(self, database_id: str) -> bool:
        return self._sql_collaboration_provider().uses_sql_collaboration(database_id)

    def queue_takeoff_insert(
        self,
        database_id: str,
        bid_uid: str,
        takeoff_specs: List[InsertTakeoffSpec],
        operation_id: str,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        collection = ResourceRef("takeoffs_collection", bid_uid, bid_value)
        dependencies = tuple(
            sorted(
                {
                    ResourceRef("page", str(spec.page_uid), bid_value)
                    for spec in takeoff_specs
                }.union(
                    {
                        ResourceRef("condition", str(spec.condition_uid), bid_value)
                        for spec in takeoff_specs
                    }
                )
            )
        )
        return self._sql_collaboration_provider().queue_mutation(
            database_id,
            (collection,),
            lambda: tuple(
                self.insert_takeoffs(
                    database_id,
                    bid_uid,
                    takeoff_specs,
                    publish_database_refreshed_after_write=False,
                    consistency_resources=dependencies,
                )
            ),
            callback,
            dependency_resources=dependencies,
            expected_created_count=len(takeoff_specs),
            operation_id=operation_id,
            owning_surface="main-plan",
        )

    def delete_takeoffs(
        self,
        db_path: str,
        takeoff_uids: List[str],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resources = tuple(
            ResourceRef("takeoff", str(uid), self._active_bid_uid_for(db_path))
            for uid in takeoff_uids
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.DELETE,
            lambda: self._delete_takeoffs.execute(db_path, takeoff_uids),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def save_page_scale(
        self, db_path: str, page_uid: str, sf1: float, sf2: float
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("page", page_uid, self._active_bid_uid_for(db_path))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._save_page_scale.execute(db_path, page_uid, sf1, sf2),
            ("scale",),
        )
        return self._reload_after_success(db_path, success)

    def save_page_name(self, db_path: str, page_uid: str, name: str) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("page", page_uid, self._active_bid_uid_for(db_path))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._save_page_name.execute(db_path, page_uid, name),
            ("name",),
        )
        return self._reload_after_success(db_path, success)

    def save_page_scales(
        self, db_path: str, page_uids: List[str], sf1: float, sf2: float
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        valid_page_uids = self._unique_page_uids(page_uids)
        if not valid_page_uids:
            return False
        bid_uid = self._active_bid_uid_for(db_path)

        def save_all(recorder):
            all_saved = True
            any_saved = False
            for page_uid in valid_page_uids:
                saved = self._save_page_scale.execute(db_path, page_uid, sf1, sf2)
                if saved:
                    any_saved = True
                    recorder.record(
                        ResourceRef("page", page_uid, bid_uid),
                        ChangeOperation.UPDATE,
                        changed_fields=("scale",),
                    )
                all_saved = saved and all_saved
            return any_saved, all_saved

        mutation = self._execute_database_mutation(
            db_path,
            tuple(ResourceRef("page", uid, bid_uid) for uid in valid_page_uids),
            save_all,
        )
        any_success, all_success = (
            mutation.value if mutation.success and mutation.value else (False, False)
        )
        if any_success and not self.reload_and_notify(db_path):
            return False
        return all_success

    def save_page_show_mode(
        self,
        db_path: str,
        page_uid: str,
        show_mode: int,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("page", page_uid, self._active_bid_uid_for(db_path))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._save_page_show_mode.execute(db_path, page_uid, show_mode),
            ("show_mode",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def save_page_overlay_image(
        self, db_path: str, page_uid: str, overlay_image_path: str
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("page", page_uid, self._active_bid_uid_for(db_path))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._save_page_overlay_image.execute(
                db_path, page_uid, overlay_image_path
            ),
            ("overlay_image",),
        )
        return self._reload_after_success(db_path, success)

    def save_page_overlay_rect_result(
        self,
        db_path: str,
        page_uid: str,
        overlay_rect: Tuple[float, float, float, float],
        publish_database_refreshed_after_write: bool = True,
    ) -> WriteReloadResult:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return WriteReloadResult(None, write_success=False, reload_success=False)
        resource = ResourceRef("page", page_uid, self._active_bid_uid_for(db_path))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._save_page_overlay_rect.execute(
                db_path, page_uid, overlay_rect
            ),
            ("overlay_rect",),
        )
        if not success:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        reload_success = True
        if publish_database_refreshed_after_write:
            reload_success = self.reload_and_notify(db_path)
        return WriteReloadResult(
            None,
            write_success=True,
            reload_success=reload_success,
        )

    def save_page_invert(self, db_path: str, page_uid: str, invert: bool) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("page", page_uid, self._active_bid_uid_for(db_path))
        return self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._save_page_invert.execute(db_path, page_uid, invert),
            ("invert",),
        )

    def save_page_bitonal(self, db_path: str, page_uid: str, bitonal: bool) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("page", page_uid, self._active_bid_uid_for(db_path))
        return self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._save_page_bitonal.execute(db_path, page_uid, bitonal),
            ("bitonal",),
        )

    def save_page_image_adjustments(
        self,
        db_path: str,
        page_uids: List[str],
        rotation: int,
        flip_x: bool,
        flip_y: bool,
        invert: bool,
        bitonal: bool,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        valid_page_uids = self._unique_page_uids(page_uids)
        if not valid_page_uids:
            return False
        resources = tuple(
            ResourceRef("page", uid, self._active_bid_uid_for(db_path))
            for uid in valid_page_uids
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.UPDATE,
            lambda: self._save_page_image_adjustments.execute(
                db_path,
                valid_page_uids,
                rotation,
                flip_x,
                flip_y,
                invert,
                bitonal,
            ),
            ("image_adjustments",),
        )
        return self._reload_after_success(db_path, success)

    @staticmethod
    def _unique_page_uids(page_uids: List[str]) -> List[str]:
        valid_page_uids = []
        seen_page_uids = set()
        for uid in page_uids:
            if uid and uid not in seen_page_uids:
                valid_page_uids.append(uid)
                seen_page_uids.add(uid)
        return valid_page_uids

    def save_page_area(
        self,
        db_path: str,
        page_uid: str,
        area_uid: str,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("page", page_uid, self._active_bid_uid_for(db_path))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._save_page_area.execute(db_path, page_uid, area_uid),
            ("area",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def update_layer_show(
        self,
        db_path: str,
        layer_uid: str,
        show: bool,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("layer", layer_uid, self._active_bid_uid_for(db_path))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._update_layer_show.execute(db_path, layer_uid, show),
            ("show",),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def insert_layer(
        self, db_path: str, bid_uid: str, name: str, after_sequence: int
    ) -> Optional[str]:
        result = self.insert_layer_result(db_path, bid_uid, name, after_sequence)
        return str(result.value) if result.success and result.value else None

    def insert_layer_result(
        self, db_path: str, bid_uid: str, name: str, after_sequence: int
    ) -> WriteReloadResult:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return WriteReloadResult(None, write_success=False, reload_success=False)
        collection = ResourceRef("layers_collection", bid_uid, int(bid_uid))

        def insert(recorder):
            new_uid = self._insert_layer.execute(db_path, bid_uid, name, after_sequence)
            if new_uid is not None:
                recorder.record(
                    ResourceRef("layer", str(new_uid), int(bid_uid)),
                    ChangeOperation.CREATE,
                )
                recorder.record(collection, ChangeOperation.UPDATE)
            return new_uid

        mutation = self._execute_database_mutation(db_path, (collection,), insert)
        new_uid = mutation.value if mutation.success else None
        if new_uid is None:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        return WriteReloadResult(
            new_uid,
            write_success=True,
            reload_success=self.reload_and_notify(db_path),
        )

    def insert_default_layer_result(
        self, db_path: str, name: str, after_sequence: int
    ) -> WriteReloadResult:
        if self._is_write_blocked():
            return WriteReloadResult(None, write_success=False, reload_success=False)
        collection = ResourceRef("default_layers_collection", "database")

        def insert(recorder):
            new_uid = self._insert_layer.execute_default(db_path, name, after_sequence)
            if new_uid is not None:
                recorder.record(collection, ChangeOperation.UPDATE)
            return new_uid

        mutation = self._execute_database_mutation(db_path, (collection,), insert)
        if not mutation.success or mutation.value is None:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        new_uid = mutation.value
        return WriteReloadResult(
            new_uid,
            write_success=True,
            reload_success=self.reload_and_notify(db_path),
        )

    def delete_layer(
        self,
        db_path: str,
        layer_uid: str,
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("layer", layer_uid, self._active_bid_uid_for(db_path))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.DELETE,
            lambda: self._delete_layer.execute(db_path, layer_uid),
        )
        return self._reload_after_success(
            db_path, success, publish_database_refreshed_after_write
        )

    def delete_layers(self, db_path: str, layer_uids: List[str]) -> BatchWriteResult:
        unique_uids = self._unique_nonempty_uids(layer_uids)
        result = BatchWriteResult(requested_uids=list(unique_uids))
        if not unique_uids:
            result.reload_success = False
            return result
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            result.failed_uids = list(unique_uids)
            return result
        bid_uid = self._active_bid_uid_for(db_path)

        def delete_all(recorder):
            for uid in unique_uids:
                success = self._delete_layer.execute(db_path, uid)
                if success:
                    result.succeeded_uids.append(uid)
                    recorder.record(
                        ResourceRef("layer", uid, bid_uid),
                        ChangeOperation.DELETE,
                    )
                else:
                    result.failed_uids.append(uid)
                    break
            return result.any_success

        self._execute_database_mutation(
            db_path,
            tuple(ResourceRef("layer", uid, bid_uid) for uid in unique_uids),
            delete_all,
        )
        if result.any_success:
            result.reload_success = self.reload_and_notify(db_path)
        return result

    def delete_default_layers(
        self, db_path: str, layer_uids: List[str]
    ) -> BatchWriteResult:
        unique_uids = self._unique_nonempty_uids(layer_uids)
        result = BatchWriteResult(requested_uids=list(unique_uids))
        if not unique_uids:
            result.reload_success = False
            return result
        if self._is_write_blocked():
            result.failed_uids = list(unique_uids)
            return result
        collection = ResourceRef("default_layers_collection", "database")

        def delete_all(recorder):
            for uid in unique_uids:
                success = self._delete_layer.execute_default(db_path, uid)
                if success:
                    result.succeeded_uids.append(uid)
                else:
                    result.failed_uids.append(uid)
                    break
            if result.any_success:
                recorder.record(collection, ChangeOperation.UPDATE)
            return result.any_success

        self._execute_database_mutation(db_path, (collection,), delete_all)
        if result.any_success:
            result.reload_success = self.reload_and_notify(db_path)
        return result

    def update_all_layers_show(self, db_path: str, bid_uid: str, show: bool) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return False
        collection = ResourceRef("layers_collection", bid_uid, int(bid_uid))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (collection,),
            ChangeOperation.UPDATE,
            lambda: self._update_all_layers_show.execute(db_path, bid_uid, show),
            ("show",),
        )
        return self._reload_after_success(db_path, success)

    def update_all_default_layers_show(self, db_path: str, show: bool) -> bool:
        if self._is_write_blocked():
            return False
        success = self._execute_boolean_resource_mutation(
            db_path,
            (ResourceRef("default_layers_collection", "database"),),
            ChangeOperation.UPDATE,
            lambda: self._update_all_layers_show.execute_default(db_path, show),
            ("show",),
        )
        return self._reload_after_success(db_path, success)

    def swap_layer_sequence(
        self, db_path: str, layer_uid_a: str, layer_uid_b: str
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        collection = ResourceRef(
            "layers_collection",
            str(self._active_bid_uid_for(db_path) or "database"),
            self._active_bid_uid_for(db_path),
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            (collection,),
            ChangeOperation.REORDER,
            lambda: self._swap_layer_sequence.execute(
                db_path, layer_uid_a, layer_uid_b
            ),
        )
        return self._reload_after_success(db_path, success)

    def swap_default_layer_sequence(
        self, db_path: str, layer_uid_a: str, layer_uid_b: str
    ) -> bool:
        if self._is_write_blocked():
            return False
        success = self._execute_boolean_resource_mutation(
            db_path,
            (ResourceRef("default_layers_collection", "database"),),
            ChangeOperation.REORDER,
            lambda: self._swap_layer_sequence.execute_default(
                db_path, layer_uid_a, layer_uid_b
            ),
        )
        return self._reload_after_success(db_path, success)

    def update_layer_name(self, db_path: str, layer_uid: str, name: str) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resource = ResourceRef("layer", layer_uid, self._active_bid_uid_for(db_path))
        success = self._execute_boolean_resource_mutation(
            db_path,
            (resource,),
            ChangeOperation.UPDATE,
            lambda: self._update_layer_name.execute(db_path, layer_uid, name),
            ("name",),
        )
        return self._reload_after_success(db_path, success)

    def update_default_layer_name(
        self, db_path: str, layer_uid: str, name: str
    ) -> bool:
        if self._is_write_blocked():
            return False
        success = self._execute_boolean_resource_mutation(
            db_path,
            (ResourceRef("default_layers_collection", "database"),),
            ChangeOperation.UPDATE,
            lambda: self._update_layer_name.execute_default(db_path, layer_uid, name),
            ("name",),
        )
        return self._reload_after_success(db_path, success)

    def update_default_layer_show(
        self, db_path: str, layer_uid: str, show: bool
    ) -> bool:
        if self._is_write_blocked():
            return False
        success = self._execute_boolean_resource_mutation(
            db_path,
            (ResourceRef("default_layers_collection", "database"),),
            ChangeOperation.UPDATE,
            lambda: self._update_layer_show.execute_default(db_path, layer_uid, show),
            ("show",),
        )
        return self._reload_after_success(db_path, success)

    @staticmethod
    def _unique_nonempty_uids(uids: List[str]) -> List[str]:
        unique_uids = []
        seen = set()
        for uid in uids:
            if uid and uid not in seen:
                seen.add(uid)
                unique_uids.append(uid)
        return unique_uids

    def save_page_view_state(
        self,
        db_path: str,
        page_uid: str,
        zoom_fac: float,
        current_x: float,
        current_y: float,
    ) -> bool:
        if self._is_write_blocked():
            return False
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        return self._save_page_view_state.execute(
            db_path, page_uid, zoom_fac, current_x, current_y
        )

    def save_bid_selected_page(self, db_path: str, bid_uid: str, page_uid: str) -> bool:
        if self._is_write_blocked():
            return False
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return False
        return self._save_bid_selected_page.execute(db_path, bid_uid, page_uid)

    def save_cover_sheet(self, db_path: str, bid_uid: str, updates: dict) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return False
        success = self._execute_boolean_resource_mutation(
            db_path,
            (ResourceRef("cover_sheet", bid_uid, int(bid_uid)),),
            ChangeOperation.UPDATE,
            lambda: self._save_cover_sheet.execute(db_path, bid_uid, updates),
            tuple(sorted(str(key) for key in updates)),
        )
        return self._reload_after_success(db_path, success)

    def delete_pages(self, db_path: str, page_uids: List[str]) -> bool:
        valid_page_uids = self._unique_page_uids(page_uids)
        if not valid_page_uids:
            return False
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        resources = tuple(
            ResourceRef("page", uid, self._active_bid_uid_for(db_path))
            for uid in valid_page_uids
        )
        success = self._execute_boolean_resource_mutation(
            db_path,
            resources,
            ChangeOperation.DELETE,
            lambda: self._delete_pages.execute(db_path, valid_page_uids),
        )
        return self._reload_after_success(db_path, success)

    def update_bid_job_status(
        self, db_path: str, bid_uid: str, job_status_uid: Optional[str]
    ) -> bool:
        success = self._execute_boolean_resource_mutation(
            db_path,
            (ResourceRef("bid", bid_uid, int(bid_uid)),),
            ChangeOperation.UPDATE,
            lambda: self._update_bid_job_status.execute(
                db_path, bid_uid, job_status_uid
            ),
            ("job_status",),
        )
        return self._reload_after_success(db_path, success)

    def save_job_statuses(self, db_path: str, changes: dict) -> bool:
        success = self._execute_boolean_resource_mutation(
            db_path,
            (ResourceRef("job_statuses_collection", "database"),),
            ChangeOperation.UPDATE,
            lambda: self._save_job_statuses.execute(db_path, changes),
        )
        return self._reload_after_success(db_path, success)

    def save_employees(self, db_path: str, changes: dict) -> bool:
        return bool(self.save_employees_result(db_path, changes))

    def save_employees_result(
        self,
        db_path: str,
        changes: dict,
        publish_database_refreshed_after_write: bool = True,
    ) -> WriteReloadResult:
        changes_to_write = changes or {}
        has_changes = any(
            changes_to_write.get(key) for key in ("new", "updated", "deleted_uids")
        )
        if not has_changes:
            return WriteReloadResult({}, write_success=True, reload_success=True)
        collection = ResourceRef("employees_collection", "database")

        def save(recorder):
            result = self._save_employees.execute(db_path, changes_to_write)
            if result is not None and result is not False and has_changes:
                recorder.record(collection, ChangeOperation.UPDATE)
            return result

        mutation = self._execute_database_mutation(db_path, (collection,), save)
        result = mutation.value if mutation.success else None
        if result is None or result is False:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        reload_success = (
            self.reload_and_notify(db_path)
            if has_changes and publish_database_refreshed_after_write
            else True
        )
        return WriteReloadResult(
            result if isinstance(result, dict) else {},
            write_success=True,
            reload_success=reload_success,
        )

    def save_pay_classes(self, db_path: str, changes: dict) -> bool:
        success = self._execute_boolean_resource_mutation(
            db_path,
            (ResourceRef("pay_classes_collection", "database"),),
            ChangeOperation.UPDATE,
            lambda: self._save_pay_classes.execute(db_path, changes),
        )
        return self._reload_after_success(db_path, success)

    def save_condition_types(self, db_path: str, changes: dict) -> Optional[dict]:
        result = self.save_condition_types_result(db_path, changes)
        return result.value if result.success else None

    def validate_condition_types_delete(
        self, db_path: str, condition_type_uids: List[str]
    ) -> DeleteValidationResult:
        requested = [str(uid) for uid in (condition_type_uids or [])]
        used_uids = self._condition_type_uids_in_use(db_path)
        blocked = [uid for uid in requested if uid in used_uids]
        return DeleteValidationResult(
            requested_uids=requested,
            blocked_uids=blocked,
            failure_reason="condition_type_in_use" if blocked else None,
        )

    def delete_condition_types_result(
        self, db_path: str, condition_type_uids: List[str]
    ) -> WriteReloadResult:
        return self.save_condition_types_result(
            db_path,
            {"new": [], "updated": [], "deleted_uids": list(condition_type_uids or [])},
        )

    def save_condition_types_result(
        self,
        db_path: str,
        changes: dict,
        publish_database_refreshed_after_write: bool = True,
    ) -> WriteReloadResult:
        changes_to_write = dict(changes or {})
        deleted_uids = [
            str(uid) for uid in (changes_to_write.get("deleted_uids") or [])
        ]
        validation = self.validate_condition_types_delete(db_path, deleted_uids)
        blocked = set(validation.blocked_uids)
        changes_to_write["deleted_uids"] = [
            uid for uid in validation.requested_uids if uid not in blocked
        ]
        has_changes = any(
            changes_to_write.get(key) for key in ("new", "updated", "deleted_uids")
        )
        if not has_changes and validation.blocked_uids:
            return WriteReloadResult(
                None,
                write_success=False,
                reload_success=False,
                failure_reason=validation.failure_reason,
                blocked_uids=validation.blocked_uids,
            )
        if not has_changes:
            return WriteReloadResult({}, write_success=True, reload_success=True)
        collection = ResourceRef("condition_types_collection", "database")

        def save(recorder):
            result = self._save_condition_types.execute(db_path, changes_to_write)
            if result is not None and result is not False and has_changes:
                recorder.record(collection, ChangeOperation.UPDATE)
            return result

        mutation = self._execute_database_mutation(db_path, (collection,), save)
        result = mutation.value if mutation.success else None
        if result is None or result is False:
            return WriteReloadResult(
                None,
                write_success=False,
                reload_success=False,
                failure_reason=validation.failure_reason,
                blocked_uids=validation.blocked_uids,
            )
        reload_success = (
            self.reload_and_notify(db_path)
            if has_changes and publish_database_refreshed_after_write
            else True
        )
        return WriteReloadResult(
            result,
            write_success=True,
            reload_success=reload_success,
            failure_reason=validation.failure_reason,
            blocked_uids=validation.blocked_uids,
        )

    def _condition_type_uids_in_use(self, db_path: str) -> set[str]:
        if self._condition_type_uids_in_use_provider is None:
            return set()
        try:
            return {
                str(uid)
                for uid in self._condition_type_uids_in_use_provider(db_path)
                if uid is not None
            }
        except Exception:
            self.logger.warning(
                "Failed to validate condition type usage before delete",
                exc_info=True,
            )
            return set()

    def save_bid_areas(self, db_path: str, bid_uid: str, changes) -> Optional[dict]:
        result = self.save_bid_areas_result(db_path, bid_uid, changes)
        return result.value if result.success else None

    def save_bid_areas_result(
        self,
        db_path: str,
        bid_uid: str,
        changes,
        publish_database_refreshed_after_write: bool = True,
    ) -> WriteReloadResult:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return WriteReloadResult(None, write_success=False, reload_success=False)
        collection = ResourceRef("areas_collection", bid_uid, int(bid_uid))

        def save(recorder):
            result = self._save_bid_areas.execute(db_path, bid_uid, changes)
            if result is None or result is False:
                return result
            for area in changes.new:
                saved_uid = result.get(area.uid)
                if saved_uid is not None:
                    recorder.record(
                        ResourceRef("area", str(saved_uid), int(bid_uid)),
                        ChangeOperation.CREATE,
                    )
            for area in changes.updated:
                recorder.record(
                    ResourceRef("area", str(area.uid), int(bid_uid)),
                    ChangeOperation.UPDATE,
                )
            for area_uid in changes.deleted_uids:
                recorder.record(
                    ResourceRef("area", str(area_uid), int(bid_uid)),
                    ChangeOperation.DELETE,
                )
            if changes.new or changes.updated or changes.deleted_uids:
                recorder.record(collection, ChangeOperation.UPDATE)
            return result

        mutation = self._execute_database_mutation(db_path, (collection,), save)
        result = mutation.value if mutation.success else None
        if result is None or result is False:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        uid_map = result
        missing_new_uids = [area.uid for area in changes.new if area.uid not in uid_map]
        if missing_new_uids:
            return WriteReloadResult(None, write_success=False, reload_success=False)
        has_changes = bool(changes.new or changes.updated or changes.deleted_uids)
        reload_success = (
            self.reload_and_notify(db_path)
            if has_changes and publish_database_refreshed_after_write
            else True
        )
        return WriteReloadResult(
            uid_map,
            write_success=True,
            reload_success=reload_success,
        )
