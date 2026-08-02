from dataclasses import asdict, dataclass, field, replace
import uuid
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple
from ...domain.entities.file_state import normalize_path
from ...domain.services.takeoff_domain_service import (
    takeoffs_can_reassign_to_condition,
)
from ...domain.entities.annotation import ANNOTATION_TYPE_NAMED_VIEW
from ..dtos.create_condition_spec_dto import CreateConditionSpec
from ..dtos.collaboration_dtos import (
    ChangeOperation,
    CollaborationMutationType,
    AuthoritativeMutationResult,
    DatabaseMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    PageSettingsPayload,
    PlanGeometryPayload,
    PlanItemsDeletePayload,
    PlanItemsPastePayload,
    PlanPropertyPayload,
    ProjectImportPayload,
    ProjectWritePayload,
    QueuedMutationRequest,
    QueuedMutationResult,
    MutationExecutionResult,
    ResourceRef,
)
from ..dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ..dtos.paste_ref_remap_dto import PasteRefRemap
from ..dtos.update_condition_dto import UpdateConditionDto, UpdateConditionResultDto
from ..interfaces.i_mdb_connection_manager import IMdbConnectionManager
from ..interfaces.i_database_mutation_executor import IDatabaseMutationExecutor
from ..interfaces.i_database_session_registry import IDatabaseSessionRegistry
from ..use_cases.project.create_bid_use_case import CreateBidUseCase
from ..use_cases.project.create_project_use_case import CreateProjectUseCase
from ..use_cases.project.delete_bids_use_case import DeleteBidsUseCase
from ..use_cases.project.delete_annotations_use_case import DeleteAnnotationsUseCase
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
from ..use_cases.project.insert_annotations_use_case import InsertAnnotationsUseCase
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
from ..use_cases.project.save_annotation_positions_use_case import (
    SaveAnnotationPositionsUseCase,
)
from ..use_cases.project.save_annotation_styles_use_case import (
    SaveAnnotationStylesUseCase,
)
from ..use_cases.project.save_annotation_text_properties_use_case import (
    SaveAnnotationTextPropertiesUseCase,
)
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
        delete_annotations: DeleteAnnotationsUseCase,
        insert_annotations: InsertAnnotationsUseCase,
        save_annotation_positions: SaveAnnotationPositionsUseCase,
        save_annotation_text_properties: SaveAnnotationTextPropertiesUseCase,
        save_annotation_styles: SaveAnnotationStylesUseCase,
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
        if any(
            collaborator is None
            for collaborator in (
                delete_annotations,
                insert_annotations,
                save_annotation_positions,
                save_annotation_text_properties,
                save_annotation_styles,
            )
        ):
            raise ValueError("ProjectWriteService requires annotation write use cases")
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
        self._delete_annotations = delete_annotations
        self._insert_annotations = insert_annotations
        self._save_annotation_positions = save_annotation_positions
        self._save_annotation_text_properties = save_annotation_text_properties
        self._save_annotation_styles = save_annotation_styles

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
        return bool(
            result.outcome_status == MutationOutcomeStatus.COMMITTED and result.value
        )

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
        success = bool(
            mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            and mutation.value
        )
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
        if (
            mutation.outcome_status != MutationOutcomeStatus.COMMITTED
            or mutation.value is None
        ):
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
        if (
            mutation.outcome_status != MutationOutcomeStatus.COMMITTED
            or mutation.value is None
        ):
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
        if (
            mutation.outcome_status != MutationOutcomeStatus.COMMITTED
            or mutation.value is None
        ):
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
        new_uid = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else None
        )
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
        new_uid = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else None
        )
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
        new_uids = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else None
        )
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
        uid_map = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else {}
        )
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
        publish_database_refreshed_after_write: bool = True,
    ) -> UpdateConditionResultDto:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return UpdateConditionResultDto(
                success=False, error="The active bid is locked"
            )
        resource = ResourceRef("condition", condition_uid, int(bid_uid))

        def update(recorder):
            result = self._update_condition.execute(
                db_path, bid_uid, condition_uid, updates
            )
            if result.success:
                recorder.record(resource, ChangeOperation.UPDATE)
            return result

        mutation = self._execute_database_mutation(db_path, (resource,), update)
        if (
            mutation.outcome_status != MutationOutcomeStatus.COMMITTED
            or mutation.value is None
        ):
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
        mutation = self._insert_takeoffs_mutation(
            db_path,
            bid_uid,
            takeoff_specs,
            consistency_resources=consistency_resources,
        )
        new_uids = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else []
        )
        if (
            new_uids
            and publish_database_refreshed_after_write
            and not self.reload_and_notify(db_path)
        ):
            return []
        return new_uids

    def _insert_takeoffs_mutation(
        self,
        db_path: str,
        bid_uid: str,
        takeoff_specs: List[InsertTakeoffSpec],
        *,
        consistency_resources: tuple[ResourceRef, ...] = (),
        publish_conflict_event: bool = True,
        operation_id: str = "",
        request_hash: str = "",
    ) -> DatabaseMutationResult[List[str]]:
        operation_id = operation_id or str(uuid.uuid4())
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return DatabaseMutationResult(
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
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
        return self._execute_database_mutation(
            db_path,
            mutation_resources,
            insert,
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
            request_hash=request_hash,
            publish_conflict_event=publish_conflict_event,
        )

    def uses_sql_collaboration_mutations(self, database_id: str) -> bool:
        return self._sql_collaboration_provider().uses_sql_collaboration(database_id)

    def request_plan_edit_lease(
        self,
        database_id: str,
        resources: tuple[ResourceRef, ...],
        dependency_resources: tuple[ResourceRef, ...],
        callback: Callable[[EditLeaseResult], None],
        *,
        operation_id: str,
        owning_surface: str,
    ) -> None:
        self._sql_collaboration_provider().request_local_edit(
            database_id,
            resources,
            callback,
            dependency_resources=dependency_resources,
            operation_id=operation_id,
            owning_surface=owning_surface,
        )

    def end_plan_edit_lease(self, handle: EditLeaseHandle) -> None:
        self._sql_collaboration_provider().end_edit_lease(handle)

    def queue_takeoff_placement(
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

        def execute() -> MutationExecutionResult:
            mutation = self._insert_takeoffs_mutation(
                database_id,
                bid_uid,
                takeoff_specs,
                consistency_resources=dependencies,
                publish_conflict_event=False,
                operation_id=request.operation_id,
                request_hash=request.request_hash,
            )
            created_resource_ids = tuple(mutation.value or ())
            return MutationExecutionResult(
                outcome_status=mutation.outcome_status,
                created_resource_ids=created_resource_ids,
                authoritative_result=(
                    AuthoritativeMutationResult(
                        created_uid_maps=(
                            (
                                "takeoffs",
                                tuple(
                                    (
                                        str(index),
                                        str(uid),
                                    )
                                    for index, uid in enumerate(created_resource_ids)
                                ),
                            ),
                        ),
                        affected_page_uids=tuple(
                            dict.fromkeys(str(spec.page_uid) for spec in takeoff_specs)
                        ),
                        affected_condition_uids=tuple(
                            dict.fromkeys(
                                str(spec.condition_uid) for spec in takeoff_specs
                            )
                        ),
                        affected_families=("takeoffs",),
                    )
                    if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                    else None
                ),
                message=(
                    mutation.conflict.reason
                    if mutation.conflict is not None
                    else (
                        ""
                        if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                        else "The database rejected the placement."
                    )
                ),
                conflict=mutation.conflict,
                commit_attempted=mutation.commit_attempted,
            )

        request = QueuedMutationRequest(
            database_id=database_id,
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT,
            owning_surface="main-plan",
            resources=(collection,),
            dependency_resources=dependencies,
            bid_uid=bid_value,
            page_uid=(str(takeoff_specs[0].page_uid) if takeoff_specs else ""),
            payload=tuple(takeoff_specs),
        )

        def validate_result(result: MutationExecutionResult) -> str:
            if len(result.created_resource_ids) == len(takeoff_specs):
                return ""
            return "The SQL mutation returned an incomplete authoritative identity set."

        return self._sql_collaboration_provider().queue_request(
            request,
            execute,
            callback,
            result_validator=validate_result,
        )

    def queue_plan_items_delete(
        self,
        database_id: str,
        bid_uid: str,
        takeoff_uids: List[str],
        annotations: List[Tuple[str, str]],
        callback: Callable[[QueuedMutationResult], None],
        *,
        page_uids: tuple[str, ...] = (),
        dependency_resources: tuple[ResourceRef, ...] = (),
        owning_surface: str = "main-plan",
    ) -> int:
        bid_value = int(bid_uid)
        payload = PlanItemsDeletePayload(
            takeoff_uids=tuple(takeoff_uids),
            annotations=tuple(annotations),
        )
        resources = tuple(
            sorted(
                {
                    *(
                        ResourceRef("takeoff", uid, bid_value)
                        for uid in payload.takeoff_uids
                    ),
                    *(
                        ResourceRef(
                            "annotation",
                            f"{annotation_type}/{uid}",
                            bid_value,
                        )
                        for uid, annotation_type in payload.annotations
                    ),
                }
            )
        )
        dependencies = {
            *dependency_resources,
            *(ResourceRef("page", uid, bid_value) for uid in page_uids if uid),
        }
        if payload.takeoff_uids:
            dependencies.add(
                ResourceRef("takeoffs_collection", str(bid_uid), bid_value)
            )
        if payload.annotations:
            dependencies.add(
                ResourceRef("annotations_collection", str(bid_uid), bid_value)
            )
        operation_id = str(uuid.uuid4())
        request = QueuedMutationRequest(
            database_id=database_id,
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PLAN_ITEMS_DELETE,
            owning_surface=owning_surface,
            resources=resources,
            dependency_resources=tuple(sorted(dependencies)),
            bid_uid=bid_value,
            page_uid=page_uids[0] if len(page_uids) == 1 else "",
            payload=payload,
        )

        def execute() -> MutationExecutionResult:
            def delete(recorder):
                self._mutation_executor.verify_plan_items_exist(
                    database_id,
                    payload.takeoff_uids,
                    payload.annotations,
                )
                if payload.takeoff_uids and not self._delete_takeoffs.execute(
                    database_id,
                    list(payload.takeoff_uids),
                ):
                    raise RuntimeError("The takeoff deletion was incomplete.")
                if payload.annotations:
                    if not self._delete_annotations.execute(
                        database_id,
                        list(payload.annotations),
                    ):
                        raise RuntimeError("The annotation deletion was incomplete.")
                for resource in resources:
                    recorder.record(resource, ChangeOperation.DELETE)
                for dependency in dependencies:
                    if dependency.resource_type.endswith("_collection"):
                        recorder.record(dependency, ChangeOperation.UPDATE)
                return True

            mutation = self._execute_database_mutation(
                database_id,
                tuple(sorted({*resources, *dependencies})),
                delete,
                operation_id=request.operation_id,
                mutation_type=request.mutation_type.value,
                request_hash=request.request_hash,
                publish_conflict_event=False,
            )
            return MutationExecutionResult(
                outcome_status=mutation.outcome_status,
                authoritative_result=(
                    AuthoritativeMutationResult(
                        deleted_resources=resources,
                        affected_page_uids=tuple(page_uids),
                        affected_families=tuple(
                            family
                            for family, present in (
                                ("takeoffs", bool(payload.takeoff_uids)),
                                ("annotations", bool(payload.annotations)),
                            )
                            if present
                        ),
                    )
                    if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                    else None
                ),
                message=(
                    mutation.conflict.reason
                    if mutation.conflict is not None
                    else (
                        ""
                        if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                        else "The database rejected deletion."
                    )
                ),
                conflict=mutation.conflict,
                commit_attempted=mutation.commit_attempted,
            )

        return self._sql_collaboration_provider().queue_request(
            request,
            execute,
            callback,
        )

    def execute_plan_items_delete_local(
        self,
        database_id: str,
        bid_uid: str,
        takeoff_uids: List[str],
        annotations: List[Tuple[str, str]],
        *,
        page_uids: tuple[str, ...] = (),
        dependency_resources: tuple[ResourceRef, ...] = (),
        publish_database_refreshed_after_write: bool = True,
    ) -> MutationExecutionResult:
        if self.uses_sql_collaboration_mutations(database_id):
            raise ValueError("SQL plan-item deletion must use the collaboration queue")
        bid_value = int(bid_uid)
        payload = PlanItemsDeletePayload(
            takeoff_uids=tuple(takeoff_uids),
            annotations=tuple(annotations),
        )
        resources = tuple(
            sorted(
                {
                    *(
                        ResourceRef("takeoff", uid, bid_value)
                        for uid in payload.takeoff_uids
                    ),
                    *(
                        ResourceRef(
                            "annotation",
                            f"{annotation_type}/{uid}",
                            bid_value,
                        )
                        for uid, annotation_type in payload.annotations
                    ),
                }
            )
        )
        dependencies = {
            *dependency_resources,
            *(ResourceRef("page", uid, bid_value) for uid in page_uids if uid),
        }
        if payload.takeoff_uids:
            dependencies.add(
                ResourceRef("takeoffs_collection", str(bid_uid), bid_value)
            )
        if payload.annotations:
            dependencies.add(
                ResourceRef("annotations_collection", str(bid_uid), bid_value)
            )

        def delete(recorder):
            if payload.takeoff_uids and not self._delete_takeoffs.execute(
                database_id,
                list(payload.takeoff_uids),
            ):
                raise RuntimeError("The takeoff deletion was incomplete.")
            if payload.annotations and not self._delete_annotations.execute(
                database_id,
                list(payload.annotations),
            ):
                raise RuntimeError("The annotation deletion was incomplete.")
            for resource in resources:
                recorder.record(resource, ChangeOperation.DELETE)
            for dependency in dependencies:
                if dependency.resource_type.endswith("_collection"):
                    recorder.record(dependency, ChangeOperation.UPDATE)
            return True

        try:
            mutation = self._execute_database_mutation(
                database_id,
                tuple(sorted({*resources, *dependencies})),
                delete,
                mutation_type=CollaborationMutationType.PLAN_ITEMS_DELETE.value,
                publish_conflict_event=False,
            )
        except (RuntimeError, ValueError) as exc:
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                message=str(exc),
            )
        authoritative = (
            AuthoritativeMutationResult(
                deleted_resources=resources,
                affected_page_uids=tuple(page_uids),
                affected_families=tuple(
                    family
                    for family, present in (
                        ("takeoffs", bool(payload.takeoff_uids)),
                        ("annotations", bool(payload.annotations)),
                    )
                    if present
                ),
            )
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else None
        )
        if (
            authoritative is not None
            and publish_database_refreshed_after_write
            and not self.reload_and_notify(database_id)
        ):
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                authoritative_result=authoritative,
                message=(
                    "The deletion committed, but the local database projection "
                    "could not be refreshed."
                ),
                commit_attempted=True,
            )
        return MutationExecutionResult(
            outcome_status=mutation.outcome_status,
            authoritative_result=authoritative,
            message=(
                mutation.conflict.reason
                if mutation.conflict is not None
                else (
                    ""
                    if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                    else "The database rejected deletion."
                )
            ),
            conflict=mutation.conflict,
            commit_attempted=mutation.commit_attempted,
        )

    def queue_plan_geometry(
        self,
        database_id: str,
        bid_uid: str,
        callback: Callable[[QueuedMutationResult], None],
        *,
        takeoff_positions: List[Tuple[str, List[float]]] = (),
        takeoff_rotations: List[Tuple[str, float]] = (),
        annotation_positions: List[Tuple[str, str, List[float]]] = (),
        page_uids: tuple[str, ...] = (),
        dependency_resources: tuple[ResourceRef, ...] = (),
        owning_surface: str = "main-plan",
        edit_lease_handle: Optional[EditLeaseHandle] = None,
    ) -> int:
        bid_value = int(bid_uid)
        payload = PlanGeometryPayload(
            takeoff_positions=tuple(
                (str(uid), tuple(float(value) for value in position))
                for uid, position in takeoff_positions
            ),
            takeoff_rotations=tuple(
                (str(uid), float(rotation)) for uid, rotation in takeoff_rotations
            ),
            annotation_positions=tuple(
                (
                    str(uid),
                    str(annotation_type),
                    tuple(float(value) for value in position),
                )
                for uid, annotation_type, position in annotation_positions
            ),
        )
        resources = tuple(
            sorted(
                {
                    *(
                        ResourceRef("takeoff", uid, bid_value)
                        for uid, _position in payload.takeoff_positions
                    ),
                    *(
                        ResourceRef("takeoff", uid, bid_value)
                        for uid, _rotation in payload.takeoff_rotations
                    ),
                    *(
                        ResourceRef(
                            "annotation",
                            f"{annotation_type}/{uid}",
                            bid_value,
                        )
                        for uid, annotation_type, _position in (
                            payload.annotation_positions
                        )
                    ),
                }
            )
        )
        dependencies = {
            *dependency_resources,
            *(ResourceRef("page", uid, bid_value) for uid in page_uids if uid),
        }
        request = QueuedMutationRequest(
            database_id=database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
            owning_surface=owning_surface,
            resources=resources,
            dependency_resources=tuple(sorted(dependencies)),
            bid_uid=bid_value,
            page_uid=page_uids[0] if len(page_uids) == 1 else "",
            payload=payload,
            edit_lease_handle=edit_lease_handle,
        )

        def execute() -> MutationExecutionResult:
            def save(recorder):
                if (
                    payload.takeoff_positions
                    and not self._save_takeoff_positions.execute(
                        database_id,
                        [
                            (uid, list(position))
                            for uid, position in payload.takeoff_positions
                        ],
                    )
                ):
                    raise RuntimeError("The takeoff position update was incomplete.")
                if (
                    payload.takeoff_rotations
                    and not self._save_takeoff_rotations.execute(
                        database_id,
                        list(payload.takeoff_rotations),
                    )
                ):
                    raise RuntimeError("The takeoff rotation update was incomplete.")
                if payload.annotation_positions:
                    if not self._save_annotation_positions.execute(
                        database_id,
                        [
                            (uid, annotation_type, list(position))
                            for uid, annotation_type, position in (
                                payload.annotation_positions
                            )
                        ],
                    ):
                        raise RuntimeError(
                            "The annotation position update was incomplete."
                        )
                position_resources = {
                    ResourceRef("takeoff", uid, bid_value)
                    for uid, _position in payload.takeoff_positions
                }.union(
                    ResourceRef(
                        "annotation",
                        f"{annotation_type}/{uid}",
                        bid_value,
                    )
                    for uid, annotation_type, _position in (
                        payload.annotation_positions
                    )
                )
                rotation_resources = {
                    ResourceRef("takeoff", uid, bid_value)
                    for uid, _rotation in payload.takeoff_rotations
                }
                for resource in sorted(position_resources.union(rotation_resources)):
                    changed_fields = []
                    if resource in position_resources:
                        changed_fields.append("position")
                    if resource in rotation_resources:
                        changed_fields.append("rotation")
                    recorder.record(
                        resource,
                        ChangeOperation.UPDATE,
                        changed_fields=tuple(changed_fields),
                    )
                return True

            mutation = self._execute_database_mutation(
                database_id,
                tuple(sorted({*resources, *dependencies})),
                save,
                operation_id=request.operation_id,
                mutation_type=request.mutation_type.value,
                request_hash=request.request_hash,
                publish_conflict_event=False,
            )
            return MutationExecutionResult(
                outcome_status=mutation.outcome_status,
                authoritative_result=(
                    AuthoritativeMutationResult(
                        updated_resources=resources,
                        affected_page_uids=tuple(page_uids),
                        affected_families=tuple(
                            family
                            for family, present in (
                                (
                                    "takeoffs",
                                    bool(
                                        payload.takeoff_positions
                                        or payload.takeoff_rotations
                                    ),
                                ),
                                ("annotations", bool(payload.annotation_positions)),
                            )
                            if present
                        ),
                    )
                    if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                    else None
                ),
                message=(
                    mutation.conflict.reason
                    if mutation.conflict is not None
                    else (
                        ""
                        if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                        else "The database rejected the geometry update."
                    )
                ),
                conflict=mutation.conflict,
                commit_attempted=mutation.commit_attempted,
            )

        return self._sql_collaboration_provider().queue_request(
            request,
            execute,
            callback,
        )

    def queue_plan_properties(
        self,
        database_id: str,
        bid_uid: str,
        property_kind: str,
        updates: list,
        callback: Callable[[QueuedMutationResult], None],
        *,
        page_uids: tuple[str, ...] = (),
        dependency_resources: tuple[ResourceRef, ...] = (),
        owning_surface: str = "main-plan",
    ) -> int:
        bid_value = int(bid_uid)
        payload = PlanPropertyPayload.from_updates(property_kind, updates)
        is_annotation = property_kind.startswith("annotation_")
        if is_annotation:
            resources = tuple(
                sorted(
                    {
                        ResourceRef(
                            "annotation",
                            f"{str(update[1])}/{str(update[0])}",
                            bid_value,
                        )
                        for update in updates
                        if len(update) >= 2 and update[0] and update[1]
                    }
                )
            )
        else:
            resources = tuple(
                sorted(
                    {
                        ResourceRef("takeoff", str(update[0]), bid_value)
                        for update in updates
                        if update and update[0]
                    }
                )
            )
        dependencies = {
            *dependency_resources,
            *(ResourceRef("page", uid, bid_value) for uid in page_uids if uid),
        }
        mutation_type = (
            CollaborationMutationType.ANNOTATION_UPDATE
            if is_annotation
            else CollaborationMutationType.TAKEOFF_PROPERTIES
        )
        request = QueuedMutationRequest(
            database_id=database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=mutation_type,
            owning_surface=owning_surface,
            resources=resources,
            dependency_resources=tuple(sorted(dependencies)),
            bid_uid=bid_value,
            page_uid=page_uids[0] if len(page_uids) == 1 else "",
            payload=payload,
        )

        def execute() -> MutationExecutionResult:
            def save(recorder):
                decoded = payload.decoded_updates()
                if property_kind == "takeoff_text":
                    success = self._save_takeoff_text_properties.execute(
                        database_id,
                        [(str(uid), dict(properties)) for uid, properties in decoded],
                    )
                    changed_fields = ("text_properties",)
                elif property_kind in {"takeoff_area", "takeoff_condition"}:
                    target_uids = {str(update[1]) for update in decoded}
                    if len(target_uids) != 1:
                        raise ValueError("A property assignment requires one target")
                    takeoff_uids = [str(update[0]) for update in decoded]
                    target_uid = target_uids.pop()
                    use_case = (
                        self._save_takeoffs_area
                        if property_kind == "takeoff_area"
                        else self._save_takeoffs_condition
                    )
                    success = use_case.execute(
                        database_id,
                        takeoff_uids,
                        target_uid,
                    )
                    changed_fields = (
                        "area" if property_kind == "takeoff_area" else "condition",
                    )
                elif property_kind == "takeoff_negative":
                    values = {bool(update[1]) for update in decoded}
                    if len(values) != 1:
                        raise ValueError("A negative update requires one value")
                    success = self._set_takeoffs_negative.execute(
                        database_id,
                        [str(update[0]) for update in decoded],
                        values.pop(),
                    )
                    changed_fields = ("negative",)
                elif property_kind == "takeoff_curve":
                    success = all(
                        self._set_takeoff_curve.execute(
                            database_id,
                            str(uid),
                            [float(value) for value in position],
                            int(curve),
                        )
                        for uid, position, curve in decoded
                    )
                    changed_fields = ("position", "curve")
                elif property_kind == "annotation_text":
                    success = self._save_annotation_text_properties.execute(
                        database_id,
                        [
                            (str(uid), str(annotation_type), dict(properties))
                            for uid, annotation_type, properties in decoded
                        ],
                    )
                    changed_fields = ("text_properties",)
                elif property_kind == "annotation_style":
                    success = self._save_annotation_styles.execute(
                        database_id,
                        [
                            (str(uid), str(annotation_type), dict(properties))
                            for uid, annotation_type, properties in decoded
                        ],
                    )
                    changed_fields = ("style",)
                else:
                    raise ValueError("Unsupported plan property mutation")
                if not success:
                    raise RuntimeError("The plan property update was incomplete.")
                for resource in resources:
                    recorder.record(
                        resource,
                        ChangeOperation.UPDATE,
                        changed_fields=changed_fields,
                    )
                return True

            mutation = self._execute_database_mutation(
                database_id,
                tuple(sorted({*resources, *dependencies})),
                save,
                operation_id=request.operation_id,
                mutation_type=request.mutation_type.value,
                request_hash=request.request_hash,
                publish_conflict_event=False,
            )
            return MutationExecutionResult(
                outcome_status=mutation.outcome_status,
                authoritative_result=(
                    AuthoritativeMutationResult(
                        updated_resources=resources,
                        affected_page_uids=tuple(page_uids),
                        affected_families=(
                            "annotations" if is_annotation else "takeoffs",
                        ),
                    )
                    if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                    else None
                ),
                message=(
                    mutation.conflict.reason
                    if mutation.conflict is not None
                    else (
                        ""
                        if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                        else "The database rejected the property update."
                    )
                ),
                conflict=mutation.conflict,
                commit_attempted=mutation.commit_attempted,
            )

        return self._sql_collaboration_provider().queue_request(
            request,
            execute,
            callback,
        )

    def queue_plan_items_paste(
        self,
        database_id: str,
        payload: PlanItemsPastePayload,
        callback: Callable[[QueuedMutationResult], None],
        *,
        dependency_resources: tuple[ResourceRef, ...] = (),
        owning_surface: str = "main-plan",
    ) -> int:
        bid_value = int(payload.destination_bid_uid)
        families = tuple(
            family
            for family, present in (
                ("takeoffs", bool(payload.takeoff_specs)),
                ("annotations", bool(payload.annotation_specs)),
            )
            if present
        )
        resources = []
        if payload.takeoff_specs:
            resources.append(
                ResourceRef(
                    "takeoffs_collection", payload.destination_bid_uid, bid_value
                )
            )
        if payload.annotation_specs:
            resources.append(
                ResourceRef(
                    "annotations_collection", payload.destination_bid_uid, bid_value
                )
            )
        cross_bid = payload.source_bid_uid != payload.destination_bid_uid
        if cross_bid and payload.takeoff_specs:
            resources.append(
                ResourceRef(
                    "conditions_collection", payload.destination_bid_uid, bid_value
                )
            )
        page_uids = tuple(
            dict.fromkeys(
                str(spec.page_uid)
                for spec in (*payload.takeoff_specs, *payload.annotation_specs)
                if spec.page_uid
            )
        )
        dependencies = {
            *dependency_resources,
            *(ResourceRef("page", uid, bid_value) for uid in page_uids),
            *(
                ResourceRef("condition", str(spec.condition_uid), bid_value)
                for spec in payload.takeoff_specs
                if not cross_bid
            ),
            *(
                ResourceRef("takeoff", str(spec.parent_uid), bid_value)
                for spec in payload.takeoff_specs
                if str(spec.parent_uid or "0") not in {"", "0", "None"}
                and str(spec.parent_uid) not in set(payload.takeoff_source_uids)
            ),
            *(
                ResourceRef("layer", str(spec.layer_uid), bid_value)
                for spec in payload.annotation_specs
                if spec.layer_uid
            ),
        }
        operation_id = str(uuid.uuid4())
        request = QueuedMutationRequest(
            database_id=database_id,
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PLAN_ITEMS_PASTE,
            owning_surface=owning_surface,
            resources=tuple(sorted(resources)),
            dependency_resources=tuple(sorted(dependencies)),
            bid_uid=bid_value,
            page_uid=page_uids[0] if len(page_uids) == 1 else "",
            payload=payload,
        )

        def execute() -> MutationExecutionResult:
            def paste(recorder):
                condition_map = {}
                if cross_bid and payload.takeoff_specs:
                    source_condition_uids = list(
                        dict.fromkeys(
                            str(spec.condition_uid) for spec in payload.takeoff_specs
                        )
                    )
                    condition_map = self._duplicate_conditions.execute_to_bid(
                        database_id,
                        payload.source_bid_uid,
                        payload.destination_bid_uid,
                        source_condition_uids,
                    )
                    if set(condition_map) != set(source_condition_uids):
                        raise RuntimeError(
                            "The paste did not create every required condition."
                        )
                takeoff_specs = tuple(
                    replace(
                        spec,
                        condition_uid=condition_map.get(
                            str(spec.condition_uid), str(spec.condition_uid)
                        ),
                    )
                    for spec in payload.takeoff_specs
                )
                source_takeoff_uids = set(payload.takeoff_source_uids)
                regular_indexes = tuple(
                    index
                    for index, spec in enumerate(takeoff_specs)
                    if str(spec.parent_uid or "0") in {"", "0", "None"}
                    or str(spec.parent_uid) not in source_takeoff_uids
                )
                hole_indexes = tuple(
                    index
                    for index in range(len(takeoff_specs))
                    if index not in regular_indexes
                )
                regular_specs = [takeoff_specs[index] for index in regular_indexes]
                regular_uids = (
                    self._insert_takeoffs.execute(
                        database_id,
                        payload.destination_bid_uid,
                        regular_specs,
                    )
                    if regular_specs
                    else []
                )
                if len(regular_uids) != len(regular_specs):
                    raise RuntimeError(
                        "The paste returned an incomplete parent takeoff UID map."
                    )
                takeoff_map = {
                    payload.takeoff_source_uids[index]: str(uid)
                    for index, uid in zip(regular_indexes, regular_uids)
                }
                hole_specs = []
                for index in hole_indexes:
                    spec = takeoff_specs[index]
                    parent_uid = takeoff_map.get(str(spec.parent_uid))
                    if parent_uid is None:
                        raise RuntimeError(
                            "The paste contains a hole without its authoritative parent."
                        )
                    hole_specs.append(replace(spec, parent_uid=parent_uid))
                hole_uids = (
                    self._insert_takeoffs.execute(
                        database_id,
                        payload.destination_bid_uid,
                        hole_specs,
                    )
                    if hole_specs
                    else []
                )
                if len(hole_uids) != len(hole_specs):
                    raise RuntimeError(
                        "The paste returned an incomplete hole takeoff UID map."
                    )
                takeoff_map.update(
                    {
                        payload.takeoff_source_uids[index]: str(uid)
                        for index, uid in zip(hole_indexes, hole_uids)
                    }
                )
                annotation_map = {}
                if payload.annotation_specs:
                    ref_remap = PasteRefRemap(takeoff_uids=dict(takeoff_map))
                    named_indexes = tuple(
                        index
                        for index, spec in enumerate(payload.annotation_specs)
                        if spec.annotation_type == ANNOTATION_TYPE_NAMED_VIEW
                    )
                    other_indexes = tuple(
                        index
                        for index in range(len(payload.annotation_specs))
                        if index not in named_indexes
                    )
                    named_uids = (
                        self._insert_annotations.execute(
                            database_id,
                            payload.destination_bid_uid,
                            [
                                payload.annotation_specs[index]
                                for index in named_indexes
                            ],
                            ref_remap,
                        )
                        if named_indexes
                        else []
                    )
                    if len(named_uids) != len(named_indexes):
                        raise RuntimeError(
                            "The paste returned an incomplete named-view UID map."
                        )
                    for index, uid in zip(named_indexes, named_uids):
                        source_uid = payload.annotation_source_uids[index]
                        annotation_map[source_uid] = str(uid)
                        ref_remap.namedview_uids[source_uid] = str(uid)
                    other_uids = (
                        self._insert_annotations.execute(
                            database_id,
                            payload.destination_bid_uid,
                            [
                                payload.annotation_specs[index]
                                for index in other_indexes
                            ],
                            ref_remap,
                        )
                        if other_indexes
                        else []
                    )
                    if len(other_uids) != len(other_indexes):
                        raise RuntimeError(
                            "The paste returned an incomplete annotation UID map."
                        )
                    annotation_map.update(
                        {
                            payload.annotation_source_uids[index]: str(uid)
                            for index, uid in zip(other_indexes, other_uids)
                        }
                    )
                for new_uid in condition_map.values():
                    recorder.record(
                        ResourceRef("condition", str(new_uid), bid_value),
                        ChangeOperation.CREATE,
                    )
                for new_uid in takeoff_map.values():
                    recorder.record(
                        ResourceRef("takeoff", str(new_uid), bid_value),
                        ChangeOperation.CREATE,
                    )
                annotation_type_by_source = {
                    source_uid: spec.annotation_type
                    for source_uid, spec in zip(
                        payload.annotation_source_uids,
                        payload.annotation_specs,
                    )
                }
                for source_uid, new_uid in annotation_map.items():
                    recorder.record(
                        ResourceRef(
                            "annotation",
                            f"{annotation_type_by_source[source_uid]}/{new_uid}",
                            bid_value,
                        ),
                        ChangeOperation.CREATE,
                    )
                for resource in resources:
                    recorder.record(resource, ChangeOperation.UPDATE)
                return {
                    "takeoff_uids": takeoff_map,
                    "annotation_uids": annotation_map,
                    "condition_uids": condition_map,
                }

            mutation = self._execute_database_mutation(
                database_id,
                tuple(sorted({*resources, *dependencies})),
                paste,
                operation_id=request.operation_id,
                mutation_type=request.mutation_type.value,
                request_hash=request.request_hash,
                publish_conflict_event=False,
            )
            value = (
                mutation.value
                if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                and mutation.value
                else {}
            )
            takeoff_map = value.get("takeoff_uids", {})
            annotation_map = value.get("annotation_uids", {})
            condition_map = value.get("condition_uids", {})
            created_ids = tuple((*takeoff_map.values(), *annotation_map.values()))
            return MutationExecutionResult(
                outcome_status=mutation.outcome_status,
                created_resource_ids=created_ids,
                authoritative_result=(
                    AuthoritativeMutationResult(
                        created_resource_ids=created_ids,
                        created_uid_maps=(
                            (
                                "takeoffs",
                                tuple(sorted(takeoff_map.items())),
                            ),
                            (
                                "annotations",
                                tuple(sorted(annotation_map.items())),
                            ),
                            (
                                "conditions",
                                tuple(sorted(condition_map.items())),
                            ),
                        ),
                        affected_page_uids=page_uids,
                        affected_condition_uids=tuple(condition_map.values()),
                        affected_families=families,
                    )
                    if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                    else None
                ),
                message=(
                    mutation.conflict.reason
                    if mutation.conflict is not None
                    else (
                        ""
                        if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                        else "The database rejected paste."
                    )
                ),
                conflict=mutation.conflict,
                commit_attempted=mutation.commit_attempted,
            )

        expected_count = len(payload.takeoff_specs) + len(payload.annotation_specs)

        def validate_result(result: MutationExecutionResult) -> str:
            if len(result.created_resource_ids) == expected_count:
                return ""
            return "The paste returned an incomplete authoritative UID set."

        return self._sql_collaboration_provider().queue_request(
            request,
            execute,
            callback,
            result_validator=validate_result,
        )

    def execute_plan_items_paste_local(
        self,
        database_id: str,
        payload: PlanItemsPastePayload,
        *,
        dependency_resources: tuple[ResourceRef, ...] = (),
        publish_database_refreshed_after_write: bool = True,
    ) -> MutationExecutionResult:
        if self.uses_sql_collaboration_mutations(database_id):
            raise ValueError("SQL paste must use the collaboration queue")
        bid_value = int(payload.destination_bid_uid)
        families = tuple(
            family
            for family, present in (
                ("takeoffs", bool(payload.takeoff_specs)),
                ("annotations", bool(payload.annotation_specs)),
            )
            if present
        )
        resources = []
        if payload.takeoff_specs:
            resources.append(
                ResourceRef(
                    "takeoffs_collection", payload.destination_bid_uid, bid_value
                )
            )
        if payload.annotation_specs:
            resources.append(
                ResourceRef(
                    "annotations_collection", payload.destination_bid_uid, bid_value
                )
            )
        cross_bid = payload.source_bid_uid != payload.destination_bid_uid
        if cross_bid and payload.takeoff_specs:
            resources.append(
                ResourceRef(
                    "conditions_collection", payload.destination_bid_uid, bid_value
                )
            )
        page_uids = tuple(
            dict.fromkeys(
                str(spec.page_uid)
                for spec in (*payload.takeoff_specs, *payload.annotation_specs)
                if spec.page_uid
            )
        )
        dependencies = {
            *dependency_resources,
            *(ResourceRef("page", uid, bid_value) for uid in page_uids),
            *(
                ResourceRef("condition", str(spec.condition_uid), bid_value)
                for spec in payload.takeoff_specs
                if not cross_bid
            ),
            *(
                ResourceRef("layer", str(spec.layer_uid), bid_value)
                for spec in payload.annotation_specs
                if spec.layer_uid
            ),
        }

        def paste(recorder):
            condition_map = {}
            if cross_bid and payload.takeoff_specs:
                source_condition_uids = list(
                    dict.fromkeys(
                        str(spec.condition_uid) for spec in payload.takeoff_specs
                    )
                )
                condition_map = self._duplicate_conditions.execute_to_bid(
                    database_id,
                    payload.source_bid_uid,
                    payload.destination_bid_uid,
                    source_condition_uids,
                )
                if set(condition_map) != set(source_condition_uids):
                    raise RuntimeError(
                        "The paste did not create every required condition."
                    )
            takeoff_specs = tuple(
                replace(
                    spec,
                    condition_uid=condition_map.get(
                        str(spec.condition_uid), str(spec.condition_uid)
                    ),
                )
                for spec in payload.takeoff_specs
            )
            regular_indexes = tuple(
                index
                for index, spec in enumerate(takeoff_specs)
                if str(spec.parent_uid or "0") in {"", "0", "None"}
            )
            hole_indexes = tuple(
                index
                for index in range(len(takeoff_specs))
                if index not in regular_indexes
            )
            regular_specs = [takeoff_specs[index] for index in regular_indexes]
            regular_uids = (
                self._insert_takeoffs.execute(
                    database_id,
                    payload.destination_bid_uid,
                    regular_specs,
                )
                if regular_specs
                else []
            )
            if len(regular_uids) != len(regular_specs):
                raise RuntimeError(
                    "The paste returned an incomplete parent takeoff UID map."
                )
            takeoff_map = {
                payload.takeoff_source_uids[index]: str(uid)
                for index, uid in zip(regular_indexes, regular_uids)
            }
            hole_specs = []
            for index in hole_indexes:
                spec = takeoff_specs[index]
                parent_uid = takeoff_map.get(str(spec.parent_uid))
                if parent_uid is None:
                    raise RuntimeError(
                        "The paste contains a hole without its authoritative parent."
                    )
                hole_specs.append(replace(spec, parent_uid=parent_uid))
            hole_uids = (
                self._insert_takeoffs.execute(
                    database_id,
                    payload.destination_bid_uid,
                    hole_specs,
                )
                if hole_specs
                else []
            )
            if len(hole_uids) != len(hole_specs):
                raise RuntimeError(
                    "The paste returned an incomplete hole takeoff UID map."
                )
            takeoff_map.update(
                {
                    payload.takeoff_source_uids[index]: str(uid)
                    for index, uid in zip(hole_indexes, hole_uids)
                }
            )
            annotation_map = {}
            if payload.annotation_specs:
                ref_remap = PasteRefRemap(takeoff_uids=dict(takeoff_map))
                named_indexes = tuple(
                    index
                    for index, spec in enumerate(payload.annotation_specs)
                    if spec.annotation_type == ANNOTATION_TYPE_NAMED_VIEW
                )
                other_indexes = tuple(
                    index
                    for index in range(len(payload.annotation_specs))
                    if index not in named_indexes
                )
                named_uids = (
                    self._insert_annotations.execute(
                        database_id,
                        payload.destination_bid_uid,
                        [payload.annotation_specs[index] for index in named_indexes],
                        ref_remap,
                    )
                    if named_indexes
                    else []
                )
                if len(named_uids) != len(named_indexes):
                    raise RuntimeError(
                        "The paste returned an incomplete named-view UID map."
                    )
                for index, uid in zip(named_indexes, named_uids):
                    source_uid = payload.annotation_source_uids[index]
                    annotation_map[source_uid] = str(uid)
                    ref_remap.namedview_uids[source_uid] = str(uid)
                other_uids = (
                    self._insert_annotations.execute(
                        database_id,
                        payload.destination_bid_uid,
                        [payload.annotation_specs[index] for index in other_indexes],
                        ref_remap,
                    )
                    if other_indexes
                    else []
                )
                if len(other_uids) != len(other_indexes):
                    raise RuntimeError(
                        "The paste returned an incomplete annotation UID map."
                    )
                annotation_map.update(
                    {
                        payload.annotation_source_uids[index]: str(uid)
                        for index, uid in zip(other_indexes, other_uids)
                    }
                )
            for new_uid in condition_map.values():
                recorder.record(
                    ResourceRef("condition", str(new_uid), bid_value),
                    ChangeOperation.CREATE,
                )
            for new_uid in takeoff_map.values():
                recorder.record(
                    ResourceRef("takeoff", str(new_uid), bid_value),
                    ChangeOperation.CREATE,
                )
            annotation_type_by_source = {
                source_uid: spec.annotation_type
                for source_uid, spec in zip(
                    payload.annotation_source_uids,
                    payload.annotation_specs,
                )
            }
            for source_uid, new_uid in annotation_map.items():
                recorder.record(
                    ResourceRef(
                        "annotation",
                        f"{annotation_type_by_source[source_uid]}/{new_uid}",
                        bid_value,
                    ),
                    ChangeOperation.CREATE,
                )
            for resource in resources:
                recorder.record(resource, ChangeOperation.UPDATE)
            return {
                "takeoff_uids": takeoff_map,
                "annotation_uids": annotation_map,
                "condition_uids": condition_map,
            }

        try:
            mutation = self._execute_database_mutation(
                database_id,
                tuple(sorted({*resources, *dependencies})),
                paste,
                mutation_type=CollaborationMutationType.PLAN_ITEMS_PASTE.value,
                publish_conflict_event=False,
            )
        except (RuntimeError, ValueError) as exc:
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                message=str(exc),
            )
        value = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            and mutation.value
            else {}
        )
        takeoff_map = value.get("takeoff_uids", {})
        annotation_map = value.get("annotation_uids", {})
        condition_map = value.get("condition_uids", {})
        created_ids = tuple((*takeoff_map.values(), *annotation_map.values()))
        authoritative = (
            AuthoritativeMutationResult(
                created_resource_ids=created_ids,
                created_uid_maps=(
                    ("takeoffs", tuple(sorted(takeoff_map.items()))),
                    ("annotations", tuple(sorted(annotation_map.items()))),
                    ("conditions", tuple(sorted(condition_map.items()))),
                ),
                affected_page_uids=page_uids,
                affected_condition_uids=tuple(condition_map.values()),
                affected_families=families,
            )
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else None
        )
        if (
            authoritative is not None
            and publish_database_refreshed_after_write
            and not self.reload_and_notify(database_id)
        ):
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                created_resource_ids=created_ids,
                authoritative_result=authoritative,
                message=(
                    "The paste committed, but the local database projection could "
                    "not be refreshed."
                ),
                commit_attempted=True,
            )
        return MutationExecutionResult(
            outcome_status=mutation.outcome_status,
            created_resource_ids=created_ids,
            authoritative_result=authoritative,
            message=(
                mutation.conflict.reason
                if mutation.conflict is not None
                else (
                    ""
                    if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                    else "The database rejected paste."
                )
            ),
            conflict=mutation.conflict,
            commit_attempted=mutation.commit_attempted,
        )

    def queue_page_settings(
        self,
        database_id: str,
        bid_uid: str,
        setting_kind: str,
        updates: list,
        callback: Callable[[QueuedMutationResult], None],
        *,
        owning_surface: str = "main-plan",
    ) -> int:
        bid_value = int(bid_uid)
        payload = PageSettingsPayload.from_updates(setting_kind, updates)
        if setting_kind == "layer_show":
            page_uids = ()
            resources = tuple(
                ResourceRef("layer", str(update[0]), bid_value)
                for update in updates
                if update and update[0]
            )
        else:
            page_uids = tuple(
                dict.fromkeys(
                    str(update[0]) for update in updates if update and update[0]
                )
            )
            resources = tuple(
                ResourceRef("page", page_uid, bid_value) for page_uid in page_uids
            )
        request = QueuedMutationRequest(
            database_id=database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PAGE_SETTINGS,
            owning_surface=owning_surface,
            resources=resources,
            bid_uid=bid_value,
            page_uid=page_uids[0] if len(page_uids) == 1 else "",
            payload=payload,
            lifecycle_critical=setting_kind != "view_state",
        )

        def execute() -> MutationExecutionResult:
            def save(recorder):
                decoded = payload.decoded_updates()
                if setting_kind == "scale":
                    success = all(
                        self._save_page_scale.execute(
                            database_id,
                            str(page_uid),
                            float(sf1),
                            float(sf2),
                        )
                        for page_uid, sf1, sf2 in decoded
                    )
                elif setting_kind == "show_mode":
                    success = all(
                        self._save_page_show_mode.execute(
                            database_id,
                            str(page_uid),
                            int(show_mode),
                        )
                        for page_uid, show_mode in decoded
                    )
                elif setting_kind == "overlay_image":
                    success = all(
                        self._save_page_overlay_image.execute(
                            database_id,
                            str(page_uid),
                            str(path),
                        )
                        for page_uid, path in decoded
                    )
                elif setting_kind == "overlay_rect":
                    success = all(
                        self._save_page_overlay_rect.execute(
                            database_id,
                            str(page_uid),
                            tuple(float(value) for value in rect),
                        )
                        for page_uid, rect in decoded
                    )
                elif setting_kind == "invert":
                    success = all(
                        self._save_page_invert.execute(
                            database_id,
                            str(page_uid),
                            bool(invert),
                        )
                        for page_uid, invert in decoded
                    )
                elif setting_kind == "bitonal":
                    success = all(
                        self._save_page_bitonal.execute(
                            database_id,
                            str(page_uid),
                            bool(bitonal),
                        )
                        for page_uid, bitonal in decoded
                    )
                elif setting_kind == "image_adjustments":
                    values = {
                        (
                            int(rotation),
                            bool(flip_x),
                            bool(flip_y),
                            bool(invert),
                            bool(bitonal),
                        )
                        for (
                            _page_uid,
                            rotation,
                            flip_x,
                            flip_y,
                            invert,
                            bitonal,
                        ) in decoded
                    }
                    if len(values) != 1:
                        raise ValueError(
                            "A page-image batch requires one adjustment set"
                        )
                    rotation, flip_x, flip_y, invert, bitonal = values.pop()
                    success = self._save_page_image_adjustments.execute(
                        database_id,
                        [str(update[0]) for update in decoded],
                        rotation,
                        flip_x,
                        flip_y,
                        invert,
                        bitonal,
                    )
                elif setting_kind == "area":
                    success = all(
                        self._save_page_area.execute(
                            database_id,
                            str(page_uid),
                            str(area_uid),
                        )
                        for page_uid, area_uid in decoded
                    )
                elif setting_kind == "view_state":
                    success = all(
                        self._save_page_view_state.execute(
                            database_id,
                            str(page_uid),
                            float(zoom),
                            float(current_x),
                            float(current_y),
                        )
                        for page_uid, zoom, current_x, current_y in decoded
                    )
                elif setting_kind == "name":
                    success = all(
                        self._save_page_name.execute(
                            database_id,
                            str(page_uid),
                            str(name),
                        )
                        for page_uid, name in decoded
                    )
                elif setting_kind == "layer_show":
                    success = all(
                        self._update_layer_show.execute(
                            database_id,
                            str(layer_uid),
                            bool(show),
                        )
                        for layer_uid, show in decoded
                    )
                else: 
                    raise ValueError("Unsupported page setting mutation")
                if not success:
                    raise RuntimeError("The page setting update was incomplete.")
                for resource in resources:
                    recorder.record(
                        resource,
                        ChangeOperation.UPDATE,
                        changed_fields=(setting_kind,),
                    )
                return True

            mutation = self._execute_database_mutation(
                database_id,
                resources,
                save,
                operation_id=request.operation_id,
                mutation_type=request.mutation_type.value,
                request_hash=request.request_hash,
                publish_conflict_event=False,
            )
            return MutationExecutionResult(
                outcome_status=mutation.outcome_status,
                authoritative_result=(
                    AuthoritativeMutationResult(
                        updated_resources=resources,
                        affected_page_uids=page_uids,
                        affected_families=(
                            "layers" if setting_kind == "layer_show" else "pages",
                        ),
                    )
                    if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                    else None
                ),
                message=(
                    mutation.conflict.reason
                    if mutation.conflict is not None
                    else (
                        ""
                        if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                        else "The database rejected the page setting update."
                    )
                ),
                conflict=mutation.conflict,
                commit_attempted=mutation.commit_attempted,
            )

        return self._sql_collaboration_provider().queue_request(
            request,
            execute,
            callback,
        )

    def _queue_project_write(
        self,
        database_id: str,
        bid_uid: Optional[str],
        payload: object,
        resources: tuple[ResourceRef, ...],
        callback: Callable[[QueuedMutationResult], None],
        work,
        authoritative_result,
        *,
        dependency_resources: tuple[ResourceRef, ...] = (),
        page_uid: str = "",
        owning_surface: str = "desktop",
        block_bid_child_locks: bool = False,
        block_bid_active_editors: bool = False,
        mutation_type: CollaborationMutationType = (
            CollaborationMutationType.PROJECT_WRITE
        ),
    ) -> int:
        bid_value = int(bid_uid) if bid_uid else None
        request = QueuedMutationRequest(
            database_id=database_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=mutation_type,
            owning_surface=owning_surface,
            resources=resources,
            dependency_resources=dependency_resources,
            bid_uid=bid_value,
            page_uid=page_uid,
            payload=payload,
        )

        def execute() -> MutationExecutionResult:
            mutation = self._execute_database_mutation(
                database_id,
                tuple(sorted({*resources, *dependency_resources})),
                work,
                operation_id=request.operation_id,
                mutation_type=request.mutation_type.value,
                request_hash=request.request_hash,
                block_bid_child_locks=block_bid_child_locks,
                block_bid_active_editors=block_bid_active_editors,
                publish_conflict_event=False,
            )
            authoritative = (
                authoritative_result(mutation.value)
                if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                else None
            )
            return MutationExecutionResult(
                outcome_status=mutation.outcome_status,
                created_resource_ids=(
                    authoritative.created_resource_ids if authoritative else ()
                ),
                authoritative_result=authoritative,
                message=(
                    mutation.conflict.reason
                    if mutation.conflict is not None
                    else (
                        ""
                        if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
                        else "The database rejected the project update."
                    )
                ),
                conflict=mutation.conflict,
                commit_attempted=mutation.commit_attempted,
            )

        return self._sql_collaboration_provider().queue_request(
            request,
            execute,
            callback,
        )

    def queue_project_import(
        self,
        database_id: str,
        target_project_uid: Optional[str],
        payload: ProjectImportPayload,
        import_work,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        resources = (
            ResourceRef("project_bids", target_project_uid or "orphan"),
            ResourceRef("condition_types_collection", "database"),
            ResourceRef("job_statuses_collection", "database"),
            ResourceRef("employees_collection", "database"),
            ResourceRef("pay_classes_collection", "database"),
        )
        dependencies = (
            (ResourceRef("project", target_project_uid),) if target_project_uid else ()
        )

        def authoritative(value) -> AuthoritativeMutationResult:
            if not isinstance(value, dict):
                raise RuntimeError(
                    "The project import did not return authoritative identities."
                )
            mappings = []
            for result_name, projection_name in (
                ("project_uids", "projects"),
                ("bid_uids", "bids"),
                ("page_uids", "pages"),
                ("condition_uids", "conditions"),
                ("layer_uids", "layers"),
                ("area_uids", "areas"),
                ("takeoff_uids", "takeoffs"),
                ("annotation_uids", "annotations"),
            ):
                mapping = value.get(result_name)
                if not isinstance(mapping, dict):
                    raise RuntimeError(
                        f"The project import result is missing {result_name}."
                    )
                mappings.append(
                    (
                        projection_name,
                        tuple(
                            sorted(
                                (str(source), str(target))
                                for source, target in mapping.items()
                            )
                        ),
                    )
                )
            by_name = {name: values for name, values in mappings}
            created_ids = tuple(
                target
                for name, values in mappings
                if name != "projects"
                for _source, target in values
            )
            return AuthoritativeMutationResult(
                created_resource_ids=created_ids,
                created_uid_maps=tuple(mappings),
                updated_resources=resources,
                affected_page_uids=tuple(
                    target for _source, target in by_name["pages"]
                ),
                affected_condition_uids=tuple(
                    target for _source, target in by_name["conditions"]
                ),
                affected_families=(
                    "hierarchy",
                    "conditions",
                    "areas",
                    "pages",
                    "layers",
                    "takeoffs",
                    "annotations",
                    "cover_sheet",
                    "master_data",
                ),
            )

        return self._queue_project_write(
            database_id,
            None,
            payload,
            resources,
            callback,
            import_work,
            authoritative,
            dependency_resources=dependencies,
            owning_surface="project-import",
            mutation_type=CollaborationMutationType.PROJECT_IMPORT,
        )

    def queue_project_create(
        self,
        database_id: str,
        name: str,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        collection = ResourceRef("projects_collection", "database")
        payload = ProjectWritePayload.from_values("create_project", {"name": name})

        def create(recorder):
            new_uid = self._create_project.execute(database_id, name)
            if new_uid is None:
                raise RuntimeError("The project creation was incomplete.")
            resource = ResourceRef("project", str(new_uid))
            recorder.record(
                resource,
                ChangeOperation.CREATE,
                changed_fields=("name",),
            )
            recorder.record(collection, ChangeOperation.UPDATE)
            return str(new_uid)

        return self._queue_project_write(
            database_id,
            None,
            payload,
            (collection,),
            callback,
            create,
            lambda value: AuthoritativeMutationResult(
                created_resource_ids=(str(value),),
                created_uid_maps=(("projects", (("0", str(value)),)),),
                affected_families=("hierarchy",),
            ),
            owning_surface="project-tree",
        )

    def queue_bid_create(
        self,
        database_id: str,
        project_uid: Optional[str],
        updates: dict,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        collection = ResourceRef("project_bids", project_uid or "orphan")
        default_layers = ResourceRef("default_layers_collection", "database")
        master_dependencies = tuple(
            resource
            for resource in (
                (
                    ResourceRef("job_status", str(updates.get("job_status_uid")))
                    if updates.get("job_status_uid")
                    else None
                ),
                (
                    ResourceRef("employee", str(updates.get("estimator_uid")))
                    if updates.get("estimator_uid")
                    else None
                ),
            )
            if resource is not None
        )
        payload = ProjectWritePayload.from_values(
            "create_bid",
            {"project_uid": project_uid, "updates": dict(updates or {})},
        )

        def create(recorder):
            new_uid = self._create_bid.execute(database_id, project_uid, updates)
            if new_uid is None:
                raise RuntimeError("The bid creation was incomplete.")
            bid_resource = ResourceRef("bid", str(new_uid), int(new_uid))
            recorder.record(bid_resource, ChangeOperation.CREATE)
            recorder.record(collection, ChangeOperation.UPDATE)
            return str(new_uid)

        return self._queue_project_write(
            database_id,
            None,
            payload,
            (collection,),
            callback,
            create,
            lambda value: AuthoritativeMutationResult(
                created_resource_ids=(str(value),),
                created_uid_maps=(("bids", (("0", str(value)),)),),
                affected_families=("hierarchy",),
            ),
            dependency_resources=(default_layers, *master_dependencies),
            owning_surface="new-project-dialog",
        )

    def queue_project_rename(
        self,
        database_id: str,
        project_uid: str,
        name: str,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        resource = ResourceRef("project", str(project_uid))
        payload = ProjectWritePayload.from_values(
            "rename_project", {"project_uid": str(project_uid), "name": name}
        )

        def rename(recorder):
            if not self._rename_project.execute(database_id, project_uid, name):
                raise RuntimeError("The project rename was incomplete.")
            recorder.record(
                resource,
                ChangeOperation.UPDATE,
                changed_fields=("name",),
            )
            return True

        return self._queue_project_write(
            database_id,
            None,
            payload,
            (resource,),
            callback,
            rename,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=(resource,),
                affected_families=("hierarchy",),
            ),
            owning_surface="project-tree",
        )

    def queue_bids_move(
        self,
        database_id: str,
        bid_uids: List[str],
        target_project_uid: Optional[str],
        callback: Callable[[QueuedMutationResult], None],
        *,
        original_project_uid: Optional[str] = None,
    ) -> int:
        valid_uids = self._unique_nonempty_uids(bid_uids)
        if not valid_uids:
            raise ValueError("A queued bid move requires at least one bid")
        resources = tuple(ResourceRef("bid", uid, int(uid)) for uid in valid_uids)
        collections = tuple(
            ResourceRef("project_bids", project_uid or "orphan")
            for project_uid in dict.fromkeys((original_project_uid, target_project_uid))
        )
        payload = ProjectWritePayload.from_values(
            "move_bids",
            {
                "bid_uids": valid_uids,
                "target_project_uid": target_project_uid,
                "original_project_uid": original_project_uid,
            },
        )

        def move(recorder):
            if not self._move_bids.execute(
                database_id,
                valid_uids,
                target_project_uid,
                original_project_uid,
            ):
                raise RuntimeError("The bid move was incomplete.")
            for resource in resources:
                recorder.record(
                    resource,
                    ChangeOperation.MOVE,
                    changed_fields=("project_uid",),
                )
            for collection in collections:
                recorder.record(collection, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            valid_uids[0],
            payload,
            resources,
            callback,
            move,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=resources,
                affected_families=("hierarchy",),
            ),
            dependency_resources=collections,
            owning_surface="project-tree",
        )

    def queue_bids_duplicate(
        self,
        database_id: str,
        bid_uids: List[str],
        target_project_uid: Optional[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        valid_uids = self._unique_nonempty_uids(bid_uids)
        if not valid_uids:
            raise ValueError("A queued bid duplication requires at least one bid")
        sources = tuple(ResourceRef("bid", uid, int(uid)) for uid in valid_uids)
        collection = ResourceRef("project_bids", target_project_uid or "orphan")
        payload = ProjectWritePayload.from_values(
            "duplicate_bids",
            {
                "bid_uids": valid_uids,
                "target_project_uid": target_project_uid,
            },
        )

        def duplicate(recorder):
            new_uids = []
            for bid_uid in valid_uids:
                new_uid = self._duplicate_bid.execute(database_id, bid_uid)
                if new_uid is None:
                    raise RuntimeError("The bid duplication was incomplete.")
                new_uids.append(str(new_uid))
            if not self._move_bids.execute(
                database_id,
                new_uids,
                target_project_uid,
                None,
            ):
                raise RuntimeError("The duplicated bid assignment was incomplete.")
            for new_uid in new_uids:
                recorder.record(
                    ResourceRef("bid", new_uid, int(new_uid)),
                    ChangeOperation.CREATE,
                )
            recorder.record(collection, ChangeOperation.UPDATE)
            return tuple(new_uids)

        return self._queue_project_write(
            database_id,
            valid_uids[0],
            payload,
            sources,
            callback,
            duplicate,
            lambda values: AuthoritativeMutationResult(
                created_resource_ids=tuple(values),
                created_uid_maps=(
                    (
                        "bids",
                        tuple(zip(valid_uids, tuple(str(uid) for uid in values))),
                    ),
                ),
                affected_families=("hierarchy",),
            ),
            dependency_resources=(collection,),
            owning_surface="project-tree",
            block_bid_child_locks=True,
        )

    def queue_bids_delete(
        self,
        database_id: str,
        bid_uids: List[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        valid_uids = self._unique_nonempty_uids(bid_uids)
        if not valid_uids:
            raise ValueError("A queued bid deletion requires at least one bid")
        resources = tuple(ResourceRef("bid", uid, int(uid)) for uid in valid_uids)
        collection = ResourceRef("projects_collection", "database")
        payload = ProjectWritePayload.from_values(
            "delete_bids", {"bid_uids": valid_uids}
        )

        def delete(recorder):
            if not self._delete_bids.execute(database_id, valid_uids):
                raise RuntimeError("The bid deletion was incomplete.")
            for resource in resources:
                recorder.record(resource, ChangeOperation.DELETE)
            recorder.record(collection, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            valid_uids[0],
            payload,
            resources,
            callback,
            delete,
            lambda _value: AuthoritativeMutationResult(
                deleted_resources=resources,
                affected_families=("hierarchy",),
            ),
            dependency_resources=(collection,),
            owning_surface="project-tree",
            block_bid_child_locks=True,
            block_bid_active_editors=True,
        )

    def queue_projects_delete(
        self,
        database_id: str,
        project_uids: List[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        valid_uids = self._unique_nonempty_uids(project_uids)
        if not valid_uids:
            raise ValueError("A queued project deletion requires at least one project")
        project_resources = tuple(ResourceRef("project", uid) for uid in valid_uids)
        bid_resources = tuple(
            ResourceRef("bid", uid, int(uid))
            for uid in self._project_data.get_project_bid_uids(database_id, valid_uids)
        )
        collection = ResourceRef("projects_collection", "database")
        resources = project_resources + bid_resources
        payload = ProjectWritePayload.from_values(
            "delete_projects", {"project_uids": valid_uids}
        )

        def delete(recorder):
            if not self._delete_projects.execute(database_id, valid_uids):
                raise RuntimeError("The project deletion was incomplete.")
            for resource in project_resources:
                recorder.record(resource, ChangeOperation.DELETE)
            for resource in bid_resources:
                recorder.record(
                    resource,
                    ChangeOperation.MOVE,
                    changed_fields=("project_uid",),
                )
            recorder.record(collection, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            None,
            payload,
            resources or (collection,),
            callback,
            delete,
            lambda _value: AuthoritativeMutationResult(
                deleted_resources=project_resources,
                updated_resources=bid_resources,
                affected_families=("hierarchy",),
            ),
            dependency_resources=(collection,),
            owning_surface="project-tree",
            block_bid_child_locks=True,
            block_bid_active_editors=True,
        )

    def queue_bid_job_status_update(
        self,
        database_id: str,
        bid_uid: str,
        job_status_uid: str,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        resource = ResourceRef("bid", bid_uid, bid_value)
        payload = ProjectWritePayload.from_values(
            "update_bid_job_status",
            {"bid_uid": bid_uid, "job_status_uid": job_status_uid},
        )

        def update(recorder):
            if not self._update_bid_job_status.execute(
                database_id, bid_uid, job_status_uid
            ):
                raise RuntimeError("The bid job-status update was incomplete.")
            recorder.record(
                resource,
                ChangeOperation.UPDATE,
                changed_fields=("job_status_uid",),
            )
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            (resource,),
            callback,
            update,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=(resource,),
                affected_families=("hierarchy",),
            ),
            owning_surface="project-tree",
        )

    def queue_bid_areas_save(
        self,
        database_id: str,
        bid_uid: str,
        changes,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        collection = ResourceRef("areas_collection", bid_uid, bid_value)
        updated_resources = tuple(
            ResourceRef("area", str(area.uid), bid_value) for area in changes.updated
        )
        deleted_resources = tuple(
            ResourceRef("area", str(area_uid), bid_value)
            for area_uid in changes.deleted_uids
        )
        resources = updated_resources + deleted_resources
        payload = ProjectWritePayload.from_values(
            "save_bid_areas",
            {
                "new": [asdict(area) for area in changes.new],
                "updated": [asdict(area) for area in changes.updated],
                "deleted_uids": [str(uid) for uid in changes.deleted_uids],
            },
        )

        def save(recorder):
            uid_map = self._save_bid_areas.execute(database_id, bid_uid, changes)
            if uid_map is None or uid_map is False:
                raise RuntimeError("The bid-area update was incomplete.")
            missing = [area.uid for area in changes.new if area.uid not in uid_map]
            if missing:
                raise RuntimeError(
                    "The bid-area update returned an incomplete identity map."
                )
            created_resources = tuple(
                ResourceRef("area", str(uid_map[area.uid]), bid_value)
                for area in changes.new
            )
            for resource in created_resources:
                recorder.record(resource, ChangeOperation.CREATE)
            for resource in updated_resources:
                recorder.record(resource, ChangeOperation.UPDATE)
            for resource in deleted_resources:
                recorder.record(resource, ChangeOperation.DELETE)
            recorder.record(collection, ChangeOperation.UPDATE)
            return {
                "uid_map": {str(key): str(value) for key, value in uid_map.items()},
                "created_resources": created_resources,
            }

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            resources or (collection,),
            callback,
            save,
            lambda value: AuthoritativeMutationResult(
                created_resource_ids=tuple(
                    resource.resource_id for resource in value["created_resources"]
                ),
                created_uid_maps=(("areas", tuple(sorted(value["uid_map"].items()))),),
                updated_resources=updated_resources,
                deleted_resources=deleted_resources,
                affected_families=("areas",),
            ),
            dependency_resources=(collection,),
            owning_surface="bid-areas-dialog",
        )

    def queue_cover_sheet_save(
        self,
        database_id: str,
        bid_uid: str,
        updates: dict,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        bid_resource = ResourceRef("bid", bid_uid, bid_value)
        page_collection = ResourceRef("pages_collection", bid_uid, bid_value)
        condition_collection = ResourceRef("conditions_collection", bid_uid, bid_value)
        takeoff_collection = ResourceRef("takeoffs_collection", bid_uid, bid_value)
        annotation_collection = ResourceRef(
            "annotations_collection", bid_uid, bid_value
        )
        cover_sheet_lock = ResourceRef("cover_sheet", bid_uid, bid_value)
        master_dependencies = tuple(
            resource
            for resource in (
                (
                    ResourceRef("job_status", str(updates.get("job_status_uid")))
                    if updates.get("job_status_uid")
                    else None
                ),
                (
                    ResourceRef("employee", str(updates.get("estimator_uid")))
                    if updates.get("estimator_uid")
                    else None
                ),
            )
            if resource is not None
        )
        payload = ProjectWritePayload.from_values(
            "save_cover_sheet", dict(updates or {})
        )
        page_uids = tuple(
            dict.fromkeys(
                str(uid)
                for uid in (
                    list(updates.get("deleted_page_uids") or ())
                    + [
                        page.get("uid")
                        for page in (updates.get("pages") or ())
                        if page.get("uid") is not None
                    ]
                )
                if uid
            )
        )

        def save(recorder):
            if not self._save_cover_sheet.execute(database_id, bid_uid, updates):
                raise RuntimeError("The cover-sheet update was incomplete.")
            recorder.record(cover_sheet_lock, ChangeOperation.UPDATE)
            recorder.record(bid_resource, ChangeOperation.UPDATE)
            recorder.record(page_collection, ChangeOperation.UPDATE)
            recorder.record(condition_collection, ChangeOperation.UPDATE)
            recorder.record(takeoff_collection, ChangeOperation.UPDATE)
            recorder.record(annotation_collection, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            (cover_sheet_lock,),
            callback,
            save,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=(
                    cover_sheet_lock,
                    bid_resource,
                    page_collection,
                    condition_collection,
                    takeoff_collection,
                    annotation_collection,
                ),
                affected_page_uids=page_uids,
                affected_families=(
                    "hierarchy",
                    "pages",
                    "conditions",
                    "takeoffs",
                    "annotations",
                ),
            ),
            dependency_resources=(
                bid_resource,
                page_collection,
                condition_collection,
                takeoff_collection,
                annotation_collection,
                *master_dependencies,
            ),
            owning_surface="cover-sheet-dialog",
        )

    def queue_condition_types_save(
        self,
        database_id: str,
        changes: dict,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        values = dict(changes or {})
        new_items = list(values.get("new") or ())
        updated_items = list(values.get("updated") or ())
        deleted_uids = self._unique_nonempty_uids(values.get("deleted_uids") or [])
        if not new_items and not updated_items and not deleted_uids:
            raise ValueError("A queued condition-type update requires changes")
        collection = ResourceRef("condition_types_collection", "database")
        updated_resources = tuple(
            ResourceRef("condition_type", str(item["uid"])) for item in updated_items
        )
        deleted_resources = tuple(
            ResourceRef("condition_type", uid) for uid in deleted_uids
        )
        payload = ProjectWritePayload.from_values(
            "save_condition_types",
            {
                "new": new_items,
                "updated": updated_items,
                "deleted_uids": deleted_uids,
            },
        )

        def save(recorder):
            validation = self.validate_condition_types_delete(database_id, deleted_uids)
            if validation.blocked_uids:
                raise RuntimeError(
                    "A condition type is still referenced by a condition."
                )
            uid_map = self._save_condition_types.execute(
                database_id,
                {
                    "new": new_items,
                    "updated": updated_items,
                    "deleted_uids": deleted_uids,
                },
            )
            if uid_map is None or uid_map is False:
                raise RuntimeError("The condition-type update was incomplete.")
            missing = [
                str(item["uid"])
                for item in new_items
                if str(item["uid"]) not in uid_map
            ]
            if missing:
                raise RuntimeError(
                    "The condition-type update returned an incomplete identity map."
                )
            created_resources = tuple(
                ResourceRef("condition_type", str(uid_map[str(item["uid"])]))
                for item in new_items
            )
            for resource in created_resources:
                recorder.record(resource, ChangeOperation.CREATE)
            for resource in updated_resources:
                recorder.record(resource, ChangeOperation.UPDATE)
            for resource in deleted_resources:
                recorder.record(resource, ChangeOperation.DELETE)
            recorder.record(collection, ChangeOperation.UPDATE)
            return {
                "uid_map": {str(key): str(value) for key, value in uid_map.items()},
                "created_resources": created_resources,
            }

        resources = updated_resources + deleted_resources
        return self._queue_project_write(
            database_id,
            None,
            payload,
            resources or (collection,),
            callback,
            save,
            lambda value: AuthoritativeMutationResult(
                created_resource_ids=tuple(
                    resource.resource_id for resource in value["created_resources"]
                ),
                created_uid_maps=(
                    ("condition_types", tuple(sorted(value["uid_map"].items()))),
                ),
                updated_resources=updated_resources,
                deleted_resources=deleted_resources,
                affected_families=("hierarchy",),
            ),
            dependency_resources=(collection,),
            owning_surface="condition-types-dialog",
        )

    def queue_default_layer_insert(
        self,
        database_id: str,
        name: str,
        after_sequence: int,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        collection = ResourceRef("default_layers_collection", "database")
        payload = ProjectWritePayload.from_values(
            "save_default_layers",
            {"operation": "insert", "name": name, "after_sequence": after_sequence},
        )

        def insert(recorder):
            new_uid = self._insert_layer.execute_default(
                database_id, name, after_sequence
            )
            if new_uid is None:
                raise RuntimeError("The default-layer creation was incomplete.")
            recorder.record(collection, ChangeOperation.UPDATE)
            return str(new_uid)

        return self._queue_project_write(
            database_id,
            None,
            payload,
            (collection,),
            callback,
            insert,
            lambda value: AuthoritativeMutationResult(
                created_resource_ids=(str(value),),
                created_uid_maps=(("default_layers", (("0", str(value)),)),),
                affected_families=("default_layers",),
            ),
            owning_surface="default-layers-dialog",
        )

    def queue_default_layers_delete(
        self,
        database_id: str,
        layer_uids: List[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        valid_uids = self._unique_nonempty_uids(layer_uids)
        if not valid_uids:
            raise ValueError("A queued default-layer deletion requires layers")
        collection = ResourceRef("default_layers_collection", "database")
        payload = ProjectWritePayload.from_values(
            "save_default_layers",
            {"operation": "delete", "layer_uids": valid_uids},
        )

        def delete(recorder):
            for layer_uid in valid_uids:
                if not self._delete_layer.execute_default(database_id, layer_uid):
                    raise RuntimeError("The default-layer deletion was incomplete.")
            recorder.record(collection, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            None,
            payload,
            (collection,),
            callback,
            delete,
            lambda _value: AuthoritativeMutationResult(
                deleted_resources=tuple(
                    ResourceRef("default_layers_collection", uid) for uid in valid_uids
                ),
                affected_families=("default_layers",),
            ),
            owning_surface="default-layers-dialog",
        )

    def queue_default_layer_update(
        self,
        database_id: str,
        operation: str,
        values: dict,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        if operation not in {"rename", "show", "show_all", "reorder"}:
            raise ValueError("Unsupported default-layer update")
        collection = ResourceRef("default_layers_collection", "database")
        payload = ProjectWritePayload.from_values(
            "save_default_layers", {"operation": operation, **values}
        )

        def update(recorder):
            if operation == "rename":
                success = self._update_layer_name.execute_default(
                    database_id, str(values["layer_uid"]), str(values["name"])
                )
            elif operation == "show":
                success = self._update_layer_show.execute_default(
                    database_id, str(values["layer_uid"]), bool(values["show"])
                )
            elif operation == "show_all":
                success = self._update_all_layers_show.execute_default(
                    database_id, bool(values["show"])
                )
            else:
                success = self._swap_layer_sequence.execute_default(
                    database_id,
                    str(values["layer_uid"]),
                    str(values["neighbor_uid"]),
                )
            if not success:
                raise RuntimeError("The default-layer update was incomplete.")
            recorder.record(collection, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            None,
            payload,
            (collection,),
            callback,
            update,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=(collection,),
                affected_families=("default_layers",),
            ),
            owning_surface="default-layers-dialog",
        )

    def queue_job_statuses_save(
        self,
        database_id: str,
        changes: dict,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        return self._queue_master_data_save(
            database_id,
            "job_statuses",
            "job_status",
            changes,
            self._save_job_statuses.execute,
            callback,
        )

    def queue_employees_save(
        self,
        database_id: str,
        changes: dict,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        return self._queue_master_data_save(
            database_id,
            "employees",
            "employee",
            changes,
            self._save_employees.execute,
            callback,
        )

    def queue_pay_classes_save(
        self,
        database_id: str,
        changes: dict,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        return self._queue_master_data_save(
            database_id,
            "pay_classes",
            "pay_class",
            changes,
            self._save_pay_classes.execute,
            callback,
        )

    def _queue_master_data_save(
        self,
        database_id: str,
        family: str,
        entity_type: str,
        changes: dict,
        save_use_case,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        values = dict(changes or {})
        new_items = list(values.get("new") or ())
        updated_items = list(values.get("updated") or ())
        deleted_uids = self._unique_nonempty_uids(values.get("deleted_uids") or [])
        if not new_items and not updated_items and not deleted_uids:
            raise ValueError("A queued master-data update requires changes")

        def item_uid(item) -> str:
            if isinstance(item, dict):
                return str(item["uid"])
            return str(item.uid)

        serializable_new = [
            asdict(item) if not isinstance(item, dict) else dict(item)
            for item in new_items
        ]
        serializable_updated = [
            asdict(item) if not isinstance(item, dict) else dict(item)
            for item in updated_items
        ]
        collection_type = f"{family}_collection"
        collection = ResourceRef(collection_type, "database")
        hierarchy_collection = (
            ResourceRef("projects_collection", "database")
            if family in {"job_statuses", "employees"}
            else None
        )
        employee_collection = (
            ResourceRef("employees_collection", "database")
            if family == "pay_classes"
            else None
        )
        updated_resources = tuple(
            ResourceRef(entity_type, item_uid(item)) for item in updated_items
        )
        deleted_resources = tuple(ResourceRef(entity_type, uid) for uid in deleted_uids)
        payload = ProjectWritePayload.from_values(
            f"save_{family}",
            {
                "new": serializable_new,
                "updated": serializable_updated,
                "deleted_uids": deleted_uids,
            },
        )

        def save(recorder):
            uid_map = save_use_case(
                database_id,
                {
                    "new": new_items,
                    "updated": updated_items,
                    "deleted_uids": deleted_uids,
                },
            )
            if uid_map is None or uid_map is False:
                raise RuntimeError("The master-data update was incomplete.")
            normalized_map = {
                str(key): str(value) for key, value in dict(uid_map).items()
            }
            missing = [
                item_uid(item)
                for item in new_items
                if item_uid(item) not in normalized_map
            ]
            if missing:
                raise RuntimeError(
                    "The master-data update returned an incomplete identity map."
                )
            created_resources = tuple(
                ResourceRef(entity_type, normalized_map[item_uid(item)])
                for item in new_items
            )
            for resource in created_resources:
                recorder.record(resource, ChangeOperation.CREATE)
            for resource in updated_resources:
                recorder.record(resource, ChangeOperation.UPDATE)
            for resource in deleted_resources:
                recorder.record(resource, ChangeOperation.DELETE)
            recorder.record(collection, ChangeOperation.UPDATE)
            if hierarchy_collection is not None:
                recorder.record(hierarchy_collection, ChangeOperation.UPDATE)
            if employee_collection is not None:
                recorder.record(employee_collection, ChangeOperation.UPDATE)
            return {
                "uid_map": normalized_map,
                "created_resources": created_resources,
            }

        resources = updated_resources + deleted_resources
        return self._queue_project_write(
            database_id,
            None,
            payload,
            resources or (collection,),
            callback,
            save,
            lambda value: AuthoritativeMutationResult(
                created_resource_ids=tuple(
                    resource.resource_id for resource in value["created_resources"]
                ),
                created_uid_maps=((family, tuple(sorted(value["uid_map"].items()))),),
                updated_resources=updated_resources,
                deleted_resources=deleted_resources,
                affected_families=tuple(
                    [family]
                    + (["hierarchy"] if hierarchy_collection else [])
                    + (["employees"] if employee_collection else [])
                ),
            ),
            dependency_resources=tuple(
                resource
                for resource in (
                    collection,
                    hierarchy_collection,
                    employee_collection,
                )
                if resource is not None
            ),
            owning_surface=f"{family}-dialog",
        )

    def queue_pages_delete(
        self,
        database_id: str,
        bid_uid: str,
        page_uids: List[str],
        callback: Callable[[QueuedMutationResult], None],
        *,
        owning_surface: str = "main-plan",
    ) -> int:
        valid_page_uids = self._unique_nonempty_uids(page_uids)
        if not valid_page_uids:
            raise ValueError("A queued page deletion requires at least one page")
        bid_value = int(bid_uid)
        deleted_resources = {
            ResourceRef("page", page_uid, bid_value) for page_uid in valid_page_uids
        }
        for page_uid in valid_page_uids:
            deleted_resources.update(
                ResourceRef("takeoff", str(takeoff.uid), bid_value)
                for takeoff in self._project_data.get_page_takeoffs(page_uid)
            )
            deleted_resources.update(
                ResourceRef(
                    "annotation",
                    f"{annotation.annotation_type}/{annotation.uid}",
                    bid_value,
                )
                for annotation in self._project_data.get_page_annotations(page_uid)
            )
        resources = tuple(sorted(deleted_resources))
        dependency_resources = tuple(
            ResourceRef(resource_type, str(bid_uid), bid_value)
            for resource_type in (
                "pages_collection",
                "takeoffs_collection",
                "annotations_collection",
            )
        )
        payload = ProjectWritePayload.from_values(
            "delete_pages", {"page_uids": valid_page_uids}
        )

        def delete(recorder):
            if not self._delete_pages.execute(database_id, valid_page_uids):
                raise RuntimeError("The page deletion was incomplete.")
            for resource in resources:
                recorder.record(resource, ChangeOperation.DELETE)
            for resource in dependency_resources:
                recorder.record(resource, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            resources,
            callback,
            delete,
            lambda _value: AuthoritativeMutationResult(
                deleted_resources=resources,
                affected_page_uids=tuple(valid_page_uids),
                affected_families=("pages", "takeoffs", "annotations"),
            ),
            dependency_resources=dependency_resources,
            page_uid=valid_page_uids[0] if len(valid_page_uids) == 1 else "",
            owning_surface=owning_surface,
        )

    def queue_condition_create(
        self,
        database_id: str,
        bid_uid: str,
        spec: CreateConditionSpec,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        collection = ResourceRef("conditions_collection", bid_uid, bid_value)
        payload = ProjectWritePayload.from_values(
            "create_condition", {"spec": asdict(spec)}
        )

        def create(recorder):
            new_uid = self._insert_condition.execute(database_id, bid_uid, spec)
            if new_uid is None:
                raise RuntimeError("The condition insertion was incomplete.")
            resource = ResourceRef("condition", str(new_uid), bid_value)
            recorder.record(resource, ChangeOperation.CREATE)
            recorder.record(collection, ChangeOperation.UPDATE)
            return str(new_uid)

        dependencies = []
        if spec.cdn_type_uid:
            dependencies.extend(
                (
                    ResourceRef("condition_type", str(spec.cdn_type_uid)),
                    ResourceRef("condition_types_collection", "database"),
                )
            )
        if spec.layer_uid:
            dependencies.append(ResourceRef("layer", str(spec.layer_uid), bid_value))
        if spec.folder_uid:
            dependencies.append(
                ResourceRef("condition_folder", str(spec.folder_uid), bid_value)
            )
        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            (collection,),
            callback,
            create,
            lambda value: AuthoritativeMutationResult(
                created_resource_ids=(str(value),),
                created_uid_maps=(("conditions", (("0", str(value)),)),),
                affected_condition_uids=(str(value),),
                affected_families=("conditions",),
            ),
            dependency_resources=tuple(dependencies),
            owning_surface="condition-sidebar",
        )

    def queue_conditions_delete(
        self,
        database_id: str,
        bid_uid: str,
        condition_uids: List[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        valid_uids = self._unique_nonempty_uids(condition_uids)
        if not valid_uids:
            raise ValueError("A queued condition deletion requires a condition")
        bid_value = int(bid_uid)
        resources = tuple(
            ResourceRef("condition", uid, bid_value) for uid in valid_uids
        )
        collection = ResourceRef("conditions_collection", bid_uid, bid_value)
        payload = ProjectWritePayload.from_values(
            "delete_conditions", {"condition_uids": valid_uids}
        )

        def delete(recorder):
            if not self._delete_conditions.execute(database_id, bid_uid, valid_uids):
                raise RuntimeError("The condition deletion was incomplete.")
            for resource in resources:
                recorder.record(resource, ChangeOperation.DELETE)
            recorder.record(collection, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            resources,
            callback,
            delete,
            lambda _value: AuthoritativeMutationResult(
                deleted_resources=resources,
                affected_condition_uids=tuple(valid_uids),
                affected_families=("conditions",),
            ),
            dependency_resources=(collection,),
            owning_surface="condition-sidebar",
        )

    def queue_conditions_duplicate(
        self,
        database_id: str,
        bid_uid: str,
        condition_uids: List[str],
        callback: Callable[[QueuedMutationResult], None],
        *,
        target_changes: Optional[dict] = None,
    ) -> int:
        source_uids = self._unique_nonempty_uids(condition_uids)
        if not source_uids:
            raise ValueError("A queued condition duplicate requires a condition")
        bid_value = int(bid_uid)
        collection = ResourceRef("conditions_collection", bid_uid, bid_value)
        changes = dict(target_changes or {})
        payload = ProjectWritePayload.from_values(
            "duplicate_conditions",
            {"condition_uids": source_uids, "target_changes": changes},
        )
        dependencies = [ResourceRef("condition", uid, bid_value) for uid in source_uids]
        folder_uid = changes.get("folder_uid")
        if folder_uid:
            dependencies.append(
                ResourceRef("condition_folder", str(folder_uid), bid_value)
            )
        cdn_type_uid = changes.get("cdn_type_uid")
        if cdn_type_uid:
            dependencies.append(ResourceRef("condition_type", str(cdn_type_uid)))
            dependencies.append(ResourceRef("condition_types_collection", "database"))

        def duplicate(recorder):
            new_uids = list(
                self._duplicate_conditions.execute(database_id, bid_uid, source_uids)
                or ()
            )
            if len(new_uids) != len(source_uids):
                raise RuntimeError(
                    "The condition duplicate returned an incomplete identity map."
                )
            if changes:
                for new_uid in new_uids:
                    updates = UpdateConditionDto()
                    for field_name, value in changes.items():
                        updates.set(field_name, value)
                    result = self._update_condition.execute(
                        database_id, bid_uid, str(new_uid), updates
                    )
                    if not result.success:
                        raise RuntimeError(
                            result.error
                            or "The duplicated condition target update was incomplete."
                        )
            for new_uid in new_uids:
                recorder.record(
                    ResourceRef("condition", str(new_uid), bid_value),
                    ChangeOperation.CREATE,
                )
            recorder.record(collection, ChangeOperation.UPDATE)
            return tuple(str(uid) for uid in new_uids)

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            (collection,),
            callback,
            duplicate,
            lambda values: AuthoritativeMutationResult(
                created_resource_ids=tuple(values),
                created_uid_maps=(
                    ("conditions", tuple(zip(source_uids, tuple(values)))),
                ),
                affected_condition_uids=tuple(values),
                affected_families=("conditions",),
            ),
            dependency_resources=tuple(dependencies),
            owning_surface="condition-sidebar",
        )

    def queue_conditions_update(
        self,
        database_id: str,
        bid_uid: str,
        condition_uids: List[str],
        changes: dict,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        valid_uids = self._unique_nonempty_uids(condition_uids)
        if not valid_uids or not changes:
            raise ValueError("A queued condition update requires items and changes")
        bid_value = int(bid_uid)
        resources = tuple(
            ResourceRef("condition", uid, bid_value) for uid in valid_uids
        )
        dependencies = []
        if changes.get("folder_uid"):
            dependencies.append(
                ResourceRef("condition_folder", str(changes["folder_uid"]), bid_value)
            )
        if changes.get("layer_uid"):
            dependencies.append(
                ResourceRef("layer", str(changes["layer_uid"]), bid_value)
            )
        if "cdn_type_uid" in changes:
            dependencies.append(ResourceRef("condition_types_collection", "database"))
            if changes.get("cdn_type_uid"):
                dependencies.append(
                    ResourceRef("condition_type", str(changes["cdn_type_uid"]))
                )
        payload = ProjectWritePayload.from_values(
            "update_conditions",
            {"condition_uids": valid_uids, "changes": changes},
        )

        def update(recorder):
            for condition_uid in valid_uids:
                updates = UpdateConditionDto()
                for field_name, value in changes.items():
                    updates.set(field_name, value)
                result = self._update_condition.execute(
                    database_id, bid_uid, condition_uid, updates
                )
                if not result.success:
                    raise RuntimeError(
                        result.error or "The condition update was incomplete."
                    )
            changed_fields = tuple(sorted(str(field) for field in changes))
            for resource in resources:
                recorder.record(
                    resource,
                    ChangeOperation.UPDATE,
                    changed_fields=changed_fields,
                )
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            resources,
            callback,
            update,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=resources,
                affected_condition_uids=tuple(valid_uids),
                affected_families=("conditions",),
            ),
            dependency_resources=tuple(dependencies),
            owning_surface="condition-sidebar",
        )

    def queue_conditions_renumber(
        self,
        database_id: str,
        bid_uid: str,
        ordered_condition_uids: List[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        ordered_uids = self._unique_nonempty_uids(ordered_condition_uids)
        if not ordered_uids:
            raise ValueError("A queued condition reorder requires conditions")
        bid_value = int(bid_uid)
        collection = ResourceRef("conditions_collection", bid_uid, bid_value)
        resources = tuple(
            ResourceRef("condition", uid, bid_value) for uid in ordered_uids
        )
        payload = ProjectWritePayload.from_values(
            "renumber_conditions", {"condition_uids": ordered_uids}
        )

        def renumber(recorder):
            if not self._renumber_conditions.execute(
                database_id, bid_uid, ordered_uids
            ):
                raise RuntimeError("The condition reorder was incomplete.")
            for resource in resources:
                recorder.record(resource, ChangeOperation.REORDER)
            recorder.record(collection, ChangeOperation.REORDER)
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            (collection,),
            callback,
            renumber,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=resources,
                affected_condition_uids=tuple(ordered_uids),
                affected_families=("conditions",),
            ),
            dependency_resources=resources,
            owning_surface="condition-sidebar",
        )

    def queue_condition_folder_create(
        self,
        database_id: str,
        bid_uid: str,
        name: str,
        parent_uid: Optional[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        collection = ResourceRef("conditions_collection", bid_uid, bid_value)
        dependencies = (
            (ResourceRef("condition_folder", str(parent_uid), bid_value),)
            if parent_uid
            else ()
        )
        payload = ProjectWritePayload.from_values(
            "create_condition_folder",
            {"name": str(name), "parent_uid": parent_uid},
        )

        def create(recorder):
            new_uid = self._insert_condition_folder.execute(
                database_id, bid_uid, name, parent_uid
            )
            if new_uid is None:
                raise RuntimeError("The condition folder insertion was incomplete.")
            resource = ResourceRef("condition_folder", str(new_uid), bid_value)
            recorder.record(resource, ChangeOperation.CREATE)
            recorder.record(collection, ChangeOperation.UPDATE)
            return str(new_uid)

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            (collection,),
            callback,
            create,
            lambda value: AuthoritativeMutationResult(
                created_resource_ids=(str(value),),
                created_uid_maps=(("condition_folders", (("0", str(value)),)),),
                affected_families=("conditions",),
            ),
            dependency_resources=dependencies,
            owning_surface="condition-sidebar",
        )

    def queue_condition_folder_rename(
        self,
        database_id: str,
        bid_uid: str,
        folder_uid: str,
        name: str,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        resource = ResourceRef("condition_folder", str(folder_uid), bid_value)
        payload = ProjectWritePayload.from_values(
            "rename_condition_folder",
            {"folder_uid": str(folder_uid), "name": str(name)},
        )

        def rename(recorder):
            if not self._rename_condition_folder.execute(database_id, folder_uid, name):
                raise RuntimeError("The condition folder rename was incomplete.")
            recorder.record(resource, ChangeOperation.UPDATE, changed_fields=("name",))
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            (resource,),
            callback,
            rename,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=(resource,),
                affected_families=("conditions",),
            ),
            owning_surface="condition-sidebar",
        )

    def queue_condition_folders_delete(
        self,
        database_id: str,
        bid_uid: str,
        folder_uids: List[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        valid_uids = self._unique_nonempty_uids(folder_uids)
        if not valid_uids:
            raise ValueError("A queued folder deletion requires a folder")
        validation = self.validate_condition_folder_delete(
            database_id, bid_uid, valid_uids
        )
        if validation.blocked_uids:
            raise ValueError("A requested condition folder is still in use")
        bid_value = int(bid_uid)
        resources = tuple(
            ResourceRef("condition_folder", uid, bid_value) for uid in valid_uids
        )
        collection = ResourceRef("conditions_collection", bid_uid, bid_value)
        payload = ProjectWritePayload.from_values(
            "delete_condition_folders", {"folder_uids": valid_uids}
        )

        def delete(recorder):
            if not self._delete_condition_folders.execute(database_id, valid_uids):
                raise RuntimeError("The condition folder deletion was incomplete.")
            for resource in resources:
                recorder.record(resource, ChangeOperation.DELETE)
            recorder.record(collection, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            resources,
            callback,
            delete,
            lambda _value: AuthoritativeMutationResult(
                deleted_resources=resources,
                affected_families=("conditions",),
            ),
            dependency_resources=(collection,),
            owning_surface="condition-sidebar",
        )

    def queue_layer_insert(
        self,
        database_id: str,
        bid_uid: str,
        name: str,
        after_sequence: int,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        collection = ResourceRef("layers_collection", bid_uid, bid_value)
        payload = ProjectWritePayload.from_values(
            "insert_layer",
            {"name": str(name), "after_sequence": int(after_sequence)},
        )

        def insert(recorder):
            new_uid = self._insert_layer.execute(
                database_id, bid_uid, name, after_sequence
            )
            if new_uid is None:
                raise RuntimeError("The layer insertion was incomplete.")
            recorder.record(
                ResourceRef("layer", str(new_uid), bid_value),
                ChangeOperation.CREATE,
            )
            recorder.record(collection, ChangeOperation.UPDATE)
            return str(new_uid)

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            (collection,),
            callback,
            insert,
            lambda value: AuthoritativeMutationResult(
                created_resource_ids=(str(value),),
                created_uid_maps=(("layers", (("0", str(value)),)),),
                affected_families=("layers",),
            ),
        )

    def queue_layer_delete(
        self,
        database_id: str,
        bid_uid: str,
        layer_uid: str,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        return self.queue_layers_delete(
            database_id,
            bid_uid,
            [layer_uid],
            callback,
        )

    def queue_layers_delete(
        self,
        database_id: str,
        bid_uid: str,
        layer_uids: List[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        valid_uids = self._unique_nonempty_uids(layer_uids)
        if not valid_uids:
            raise ValueError("A queued layer deletion requires at least one layer")
        bid_value = int(bid_uid)
        resources = tuple(ResourceRef("layer", uid, bid_value) for uid in valid_uids)
        collection = ResourceRef("layers_collection", bid_uid, bid_value)
        payload = ProjectWritePayload.from_values(
            "delete_layers", {"layer_uids": valid_uids}
        )

        def delete(recorder):
            for layer_uid in valid_uids:
                if not self._delete_layer.execute(database_id, layer_uid):
                    raise RuntimeError("The layer deletion was incomplete.")
            for resource in resources:
                recorder.record(resource, ChangeOperation.DELETE)
            recorder.record(collection, ChangeOperation.UPDATE)
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            resources,
            callback,
            delete,
            lambda _value: AuthoritativeMutationResult(
                deleted_resources=resources,
                affected_families=("layers",),
            ),
            dependency_resources=(collection,),
        )

    def queue_layer_reorder(
        self,
        database_id: str,
        bid_uid: str,
        layer_uid_a: str,
        layer_uid_b: str,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        collection = ResourceRef("layers_collection", bid_uid, bid_value)
        resources = tuple(
            ResourceRef("layer", str(uid), bid_value)
            for uid in (layer_uid_a, layer_uid_b)
        )
        payload = ProjectWritePayload.from_values(
            "swap_layers",
            {"layer_uid_a": str(layer_uid_a), "layer_uid_b": str(layer_uid_b)},
        )

        def reorder(recorder):
            if not self._swap_layer_sequence.execute(
                database_id, layer_uid_a, layer_uid_b
            ):
                raise RuntimeError("The layer reorder was incomplete.")
            for resource in resources:
                recorder.record(resource, ChangeOperation.REORDER)
            recorder.record(collection, ChangeOperation.REORDER)
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            resources,
            callback,
            reorder,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=resources,
                affected_families=("layers",),
            ),
            dependency_resources=(collection,),
        )

    def queue_layer_rename(
        self,
        database_id: str,
        bid_uid: str,
        layer_uid: str,
        name: str,
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        bid_value = int(bid_uid)
        resource = ResourceRef("layer", str(layer_uid), bid_value)
        payload = ProjectWritePayload.from_values(
            "rename_layer", {"layer_uid": str(layer_uid), "name": str(name)}
        )

        def rename(recorder):
            if not self._update_layer_name.execute(database_id, layer_uid, name):
                raise RuntimeError("The layer rename was incomplete.")
            recorder.record(
                resource,
                ChangeOperation.UPDATE,
                changed_fields=("name",),
            )
            return True

        return self._queue_project_write(
            database_id,
            bid_uid,
            payload,
            (resource,),
            callback,
            rename,
            lambda _value: AuthoritativeMutationResult(
                updated_resources=(resource,),
                affected_families=("layers",),
            ),
        )

    def queue_page_setting_if_sql(
        self,
        database_id: str,
        page_uid: str,
        setting_kind: str,
        values: list,
        *,
        owning_surface: str = "main-plan",
    ) -> Optional[bool]:
        if not self.uses_sql_collaboration_mutations(database_id):
            return None
        if setting_kind == "bid_selected_page":
            return True
        bid_uid = self._active_bid_uid_for(database_id)
        if bid_uid is None:
            return False

        def complete(result: QueuedMutationResult) -> None:
            if setting_kind == "view_state" and result.outcome_status not in {
                MutationOutcomeStatus.COMMITTED,
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                self.logger.debug(
                    "Best-effort SQL page view persistence ended for %s with %s: %s",
                    page_uid,
                    result.outcome_status.value,
                    result.message,
                )
                return
            if result.outcome_status not in {
                MutationOutcomeStatus.COMMITTED,
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                self.logger.warning(
                    "Queued page setting %s failed for %s: %s",
                    setting_kind,
                    page_uid,
                    result.message,
                )

        sequence = self.queue_page_settings(
            database_id,
            str(bid_uid),
            setting_kind,
            [[str(page_uid), *values]],
            complete,
            owning_surface=owning_surface,
        )
        return sequence >= 0

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
        valid_page_uids = self._unique_nonempty_uids(page_uids)
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
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            and mutation.value
            else (False, False)
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
        valid_page_uids = self._unique_nonempty_uids(page_uids)
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
        new_uid = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else None
        )
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
        if (
            mutation.outcome_status != MutationOutcomeStatus.COMMITTED
            or mutation.value is None
        ):
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
        valid_page_uids = self._unique_nonempty_uids(page_uids)
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

    def save_job_statuses(self, db_path: str, changes: dict) -> Optional[dict]:
        changes_to_write = changes or {}
        if not any(
            changes_to_write.get(key) for key in ("new", "updated", "deleted_uids")
        ):
            return {}
        collection = ResourceRef("job_statuses_collection", "database")

        def save(recorder):
            uid_map = self._save_job_statuses.execute(db_path, changes_to_write)
            if uid_map is not None:
                recorder.record(collection, ChangeOperation.UPDATE)
            return uid_map

        mutation = self._execute_database_mutation(db_path, (collection,), save)
        if mutation.outcome_status != MutationOutcomeStatus.COMMITTED:
            return None
        uid_map = mutation.value
        if uid_map is None or not self.reload_and_notify(db_path):
            return None
        return dict(uid_map)

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
        result = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else None
        )
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

    def save_pay_classes(self, db_path: str, changes: dict) -> Optional[dict]:
        changes_to_write = changes or {}
        if not any(
            changes_to_write.get(key) for key in ("new", "updated", "deleted_uids")
        ):
            return {}
        collection = ResourceRef("pay_classes_collection", "database")

        def save(recorder):
            uid_map = self._save_pay_classes.execute(db_path, changes_to_write)
            if uid_map is not None:
                recorder.record(collection, ChangeOperation.UPDATE)
            return uid_map

        mutation = self._execute_database_mutation(db_path, (collection,), save)
        if mutation.outcome_status != MutationOutcomeStatus.COMMITTED:
            return None
        uid_map = mutation.value
        if uid_map is None or not self.reload_and_notify(db_path):
            return None
        return dict(uid_map)

    def save_condition_types(self, db_path: str, changes: dict) -> Optional[dict]:
        result = self.save_condition_types_result(db_path, changes)
        return result.value if result.success else None

    def validate_condition_types_delete(
        self, db_path: str, condition_type_uids: List[str]
    ) -> DeleteValidationResult:
        requested = [str(uid) for uid in (condition_type_uids or [])]
        if not requested:
            return DeleteValidationResult()
        used_uids = self._condition_type_uids_in_use(db_path)
        if used_uids is None:
            return DeleteValidationResult(
                requested_uids=requested,
                blocked_uids=requested,
                failure_reason="condition_type_usage_unavailable",
            )
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
        result = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else None
        )
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

    def _condition_type_uids_in_use(self, db_path: str) -> Optional[set[str]]:
        if self._condition_type_uids_in_use_provider is None:
            self.logger.warning(
                "Cannot validate condition type usage without a provider"
            )
            return None
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
            return None

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
        result = (
            mutation.value
            if mutation.outcome_status == MutationOutcomeStatus.COMMITTED
            else None
        )
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
