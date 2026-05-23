import logging
from ...domain.aggregates.ost_aggregate import OstAggregate
from ..interfaces.i_api_client_provider import IApiClientProvider
from ..service_container import ServiceContainer
from ..services.active_bid_write_guard import ActiveBidWriteGuard
from ..services.annotation_write_service import AnnotationWriteService
from ..services.project_write_service import ProjectWriteService
from ..use_cases.license.activate_license_use_case import ActivateLicenseUseCase
from ..use_cases.license.deactivate_license_use_case import DeactivateLicenseUseCase
from ..use_cases.license.validate_license_use_case import ValidateLicenseUseCase
from ..use_cases.project.cleanup_deleted_files_use_case import (
    CleanupDeletedFilesUseCase,
)
from ..use_cases.project.create_bid_use_case import CreateBidUseCase
from ..use_cases.project.create_project_use_case import CreateProjectUseCase
from ..use_cases.project.delete_annotations_use_case import DeleteAnnotationsUseCase
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
from ..use_cases.project.insert_annotations_use_case import InsertAnnotationsUseCase
from ..use_cases.project.insert_condition_folder_use_case import (
    InsertConditionFolderUseCase,
)
from ..use_cases.project.insert_condition_use_case import InsertConditionUseCase
from ..use_cases.project.insert_layer_use_case import InsertLayerUseCase
from ..use_cases.project.insert_takeoffs_use_case import InsertTakeoffsUseCase
from ..use_cases.project.load_bid_use_case import LoadBidUseCase
from ..use_cases.project.load_file_use_case import LoadFileUseCase
from ..use_cases.project.load_files_from_config_use_case import (
    LoadFilesFromConfigUseCase,
)
from ..use_cases.project.move_bids_use_case import MoveBidsUseCase
from ..use_cases.project.reload_database_use_case import ReloadDatabaseUseCase
from ..use_cases.project.rename_condition_folder_use_case import (
    RenameConditionFolderUseCase,
)
from ..use_cases.project.rename_project_use_case import RenameProjectUseCase
from ..use_cases.project.renumber_conditions_use_case import RenumberConditionsUseCase
from ..use_cases.project.save_annotation_positions_use_case import (
    SaveAnnotationPositionsUseCase,
)
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
from ..use_cases.project.save_takeoffs_area_use_case import SaveTakeoffsAreaUseCase
from ..use_cases.project.save_takeoffs_condition_use_case import (
    SaveTakeoffsConditionUseCase,
)
from ..use_cases.project.set_takeoff_curve_use_case import SetTakeoffCurveUseCase
from ..use_cases.project.set_takeoffs_negative_use_case import (
    SetTakeoffsNegativeUseCase,
)
from ..use_cases.project.swap_layer_sequence_use_case import SwapLayerSequenceUseCase
from ..use_cases.project.unload_file_use_case import UnloadFileUseCase
from ..use_cases.project.update_all_layers_show_use_case import (
    UpdateAllLayersShowUseCase,
)
from ..use_cases.project.update_bid_job_status_use_case import UpdateBidJobStatusUseCase
from ..use_cases.project.update_condition_use_case import UpdateConditionUseCase
from ..use_cases.project.update_layer_name_use_case import UpdateLayerNameUseCase
from ..use_cases.project.update_layer_show_use_case import UpdateLayerShowUseCase


class UseCaseBuilder:
    def __init__(
        self,
        container: ServiceContainer,
        logger: logging.Logger,
        api_client_provider: IApiClientProvider,
    ) -> None:
        self.container = container
        self.logger = logger
        self.api_client_provider = api_client_provider

    def build(
        self,
        ost_model: OstAggregate,
        project_data_service,
        file_state_model,
        mdb_writer,
        event_bus,
        license_model,
        connection_manager=None,
    ) -> None:
        reload_database_uc = self._register_project_use_cases(
            ost_model, project_data_service, file_state_model
        )
        self._register_write_use_cases(
            mdb_writer,
            reload_database_uc,
            event_bus,
            project_data_service,
            connection_manager,
        )
        self._register_license_use_cases(license_model)

    def _register_project_use_cases(
        self, ost_model: OstAggregate, project_data_service, file_state_model
    ) -> ReloadDatabaseUseCase:
        project_logger = self.logger.getChild("ProjectUseCases")
        load_file = LoadFileUseCase(
            ost_model,
            project_data_service,
            ost_model.file_manager,
            project_logger.getChild("LoadFile"),
        )
        unload_file = UnloadFileUseCase(
            ost_model,
            project_data_service,
            ost_model.file_manager,
            project_logger.getChild("UnloadFile"),
        )
        load_bid = LoadBidUseCase(
            ost_model,
            ost_model.file_manager,
            project_logger.getChild("LoadBid"),
        )
        reload_database = ReloadDatabaseUseCase(
            ost_model,
            ost_model.file_manager,
            load_bid,
            project_logger.getChild("ReloadDatabase"),
        )
        cleanup_deleted_files = CleanupDeletedFilesUseCase(
            file_state_model.repository,
            project_logger.getChild("CleanupDeletedFiles"),
        )
        load_files_from_config = LoadFilesFromConfigUseCase(
            load_file,
            file_state_model.repository,
            project_logger.getChild("LoadFilesFromConfig"),
        )
        self.container.register_instance("load_file_use_case", load_file)
        self.container.register_instance("unload_file_use_case", unload_file)
        self.container.register_instance("load_bid_use_case", load_bid)
        self.container.register_instance("reload_database_use_case", reload_database)
        self.container.register_instance(
            "cleanup_deleted_files_use_case", cleanup_deleted_files
        )
        self.container.register_instance(
            "load_files_from_config_use_case", load_files_from_config
        )
        return reload_database

    def _register_write_use_cases(
        self,
        mdb_writer,
        reload_database_uc,
        event_bus,
        project_data_service,
        connection_manager=None,
    ) -> None:
        write_logger = self.logger.getChild("Write")
        ann_logger = self.logger.getChild("Annotation")
        bid_write_guard = ActiveBidWriteGuard(
            project_data_service, write_logger.getChild("ActiveBidWriteGuard")
        )
        delete_bids_uc = DeleteBidsUseCase(
            mdb_writer, write_logger.getChild("DeleteBids")
        )
        delete_projects_uc = DeleteProjectsUseCase(
            mdb_writer, write_logger.getChild("DeleteProjects")
        )
        create_project_uc = CreateProjectUseCase(
            mdb_writer, write_logger.getChild("CreateProject")
        )
        rename_project_uc = RenameProjectUseCase(
            mdb_writer, write_logger.getChild("RenameProject")
        )
        move_bids_uc = MoveBidsUseCase(mdb_writer, write_logger.getChild("MoveBids"))
        duplicate_bid_uc = DuplicateBidUseCase(
            mdb_writer, write_logger.getChild("DuplicateBid")
        )
        delete_conditions_uc = DeleteConditionsUseCase(
            mdb_writer, write_logger.getChild("DeleteConditions")
        )
        duplicate_conditions_uc = DuplicateConditionsUseCase(
            mdb_writer, write_logger.getChild("DuplicateConditions")
        )
        update_condition_uc = UpdateConditionUseCase(
            mdb_writer, write_logger.getChild("UpdateCondition")
        )
        renumber_conditions_uc = RenumberConditionsUseCase(
            mdb_writer, write_logger.getChild("RenumberConditions")
        )
        save_takeoff_positions_uc = SaveTakeoffPositionsUseCase(
            mdb_writer, write_logger.getChild("SaveTakeoffPositions")
        )
        save_takeoff_rotations_uc = SaveTakeoffRotationsUseCase(
            mdb_writer, write_logger.getChild("SaveTakeoffRotations")
        )
        save_takeoffs_area_uc = SaveTakeoffsAreaUseCase(
            mdb_writer, write_logger.getChild("SaveTakeoffsArea")
        )
        save_takeoffs_condition_uc = SaveTakeoffsConditionUseCase(
            mdb_writer, write_logger.getChild("SaveTakeoffsCondition")
        )
        set_takeoffs_negative_uc = SetTakeoffsNegativeUseCase(
            mdb_writer, write_logger.getChild("SetTakeoffsNegative")
        )
        insert_takeoffs_uc = InsertTakeoffsUseCase(
            mdb_writer, write_logger.getChild("InsertTakeoffs")
        )
        delete_takeoffs_uc = DeleteTakeoffsUseCase(
            mdb_writer, write_logger.getChild("DeleteTakeoffs")
        )
        delete_pages_uc = DeletePagesUseCase(
            mdb_writer, write_logger.getChild("DeletePages")
        )
        save_annotation_positions_uc = SaveAnnotationPositionsUseCase(
            mdb_writer, ann_logger.getChild("SavePositions")
        )
        insert_annotations_uc = InsertAnnotationsUseCase(
            mdb_writer, ann_logger.getChild("Insert")
        )
        delete_annotations_uc = DeleteAnnotationsUseCase(
            mdb_writer, ann_logger.getChild("Delete")
        )
        create_bid_uc = CreateBidUseCase(mdb_writer, write_logger.getChild("CreateBid"))
        insert_condition_uc = InsertConditionUseCase(
            mdb_writer, write_logger.getChild("InsertCondition")
        )
        insert_condition_folder_uc = InsertConditionFolderUseCase(
            mdb_writer, write_logger.getChild("InsertConditionFolder")
        )
        rename_condition_folder_uc = RenameConditionFolderUseCase(
            mdb_writer, write_logger.getChild("RenameConditionFolder")
        )
        delete_condition_folders_uc = DeleteConditionFoldersUseCase(
            mdb_writer, write_logger.getChild("DeleteConditionFolders")
        )
        set_takeoff_curve_uc = SetTakeoffCurveUseCase(
            mdb_writer, write_logger.getChild("SetTakeoffCurve")
        )
        save_cover_sheet_uc = SaveCoverSheetUseCase(
            mdb_writer, write_logger.getChild("SaveCoverSheet")
        )
        update_bid_job_status_uc = UpdateBidJobStatusUseCase(
            mdb_writer, write_logger.getChild("UpdateBidJobStatus")
        )
        save_job_statuses_uc = SaveJobStatusesUseCase(
            mdb_writer, write_logger.getChild("SaveJobStatuses")
        )
        save_bid_areas_uc = SaveBidAreasUseCase(
            mdb_writer, write_logger.getChild("SaveBidAreas")
        )
        save_page_name_uc = SavePageNameUseCase(
            mdb_writer, write_logger.getChild("SavePageName")
        )
        save_page_scale_uc = SavePageScaleUseCase(
            mdb_writer, write_logger.getChild("SavePageScale")
        )
        save_page_show_mode_uc = SavePageShowModeUseCase(
            mdb_writer, write_logger.getChild("SavePageShowMode")
        )
        save_page_overlay_image_uc = SavePageOverlayImageUseCase(
            mdb_writer, write_logger.getChild("SavePageOverlayImage")
        )
        save_page_invert_uc = SavePageInvertUseCase(
            mdb_writer, write_logger.getChild("SavePageInvert")
        )
        save_page_bitonal_uc = SavePageBitonalUseCase(
            mdb_writer, write_logger.getChild("SavePageBitonal")
        )
        save_page_image_adjustments_uc = SavePageImageAdjustmentsUseCase(
            mdb_writer, write_logger.getChild("SavePageImageAdjustments")
        )
        save_page_area_uc = SavePageAreaUseCase(
            mdb_writer, write_logger.getChild("SavePageArea")
        )
        save_employees_uc = SaveEmployeesUseCase(
            mdb_writer, write_logger.getChild("SaveEmployees")
        )
        save_pay_classes_uc = SavePayClassesUseCase(
            mdb_writer, write_logger.getChild("SavePayClasses")
        )
        save_condition_types_uc = SaveConditionTypesUseCase(
            mdb_writer, write_logger.getChild("SaveConditionTypes")
        )
        update_layer_show_uc = UpdateLayerShowUseCase(
            mdb_writer, write_logger.getChild("UpdateLayerShow")
        )
        update_all_layers_show_uc = UpdateAllLayersShowUseCase(
            mdb_writer, write_logger.getChild("UpdateAllLayersShow")
        )
        update_layer_name_uc = UpdateLayerNameUseCase(
            mdb_writer, write_logger.getChild("UpdateLayerName")
        )
        insert_layer_uc = InsertLayerUseCase(
            mdb_writer, write_logger.getChild("InsertLayer")
        )
        delete_layer_uc = DeleteLayerUseCase(
            mdb_writer, write_logger.getChild("DeleteLayer")
        )
        swap_layer_sequence_uc = SwapLayerSequenceUseCase(
            mdb_writer, write_logger.getChild("SwapLayerSequence")
        )
        save_bid_selected_page_uc = SaveBidSelectedPageUseCase(
            mdb_writer, write_logger.getChild("SaveBidSelectedPage")
        )
        save_page_view_state_uc = SavePageViewStateUseCase(
            mdb_writer, write_logger.getChild("SavePageViewState")
        )
        self.container.register_instance("delete_bids_use_case", delete_bids_uc)
        self.container.register_instance("delete_projects_use_case", delete_projects_uc)
        self.container.register_instance("create_project_use_case", create_project_uc)
        self.container.register_instance("rename_project_use_case", rename_project_uc)
        self.container.register_instance("move_bids_use_case", move_bids_uc)
        self.container.register_instance("duplicate_bid_use_case", duplicate_bid_uc)
        self.container.register_instance(
            "delete_conditions_use_case", delete_conditions_uc
        )
        self.container.register_instance(
            "duplicate_conditions_use_case", duplicate_conditions_uc
        )
        self.container.register_instance(
            "update_condition_use_case", update_condition_uc
        )
        self.container.register_instance(
            "renumber_conditions_use_case", renumber_conditions_uc
        )
        self.container.register_instance(
            "save_takeoff_positions_use_case", save_takeoff_positions_uc
        )
        self.container.register_instance(
            "save_takeoff_rotations_use_case", save_takeoff_rotations_uc
        )
        self.container.register_instance(
            "save_takeoffs_area_use_case", save_takeoffs_area_uc
        )
        self.container.register_instance(
            "save_takeoffs_condition_use_case", save_takeoffs_condition_uc
        )
        self.container.register_instance(
            "set_takeoffs_negative_use_case", set_takeoffs_negative_uc
        )
        self.container.register_instance("insert_takeoffs_use_case", insert_takeoffs_uc)
        self.container.register_instance("delete_takeoffs_use_case", delete_takeoffs_uc)
        self.container.register_instance("delete_pages_use_case", delete_pages_uc)
        self.container.register_instance(
            "save_annotation_positions_use_case", save_annotation_positions_uc
        )
        self.container.register_instance(
            "insert_annotations_use_case", insert_annotations_uc
        )
        self.container.register_instance(
            "project_write_service",
            ProjectWriteService(
                delete_bids=delete_bids_uc,
                delete_projects=delete_projects_uc,
                create_project=create_project_uc,
                rename_project=rename_project_uc,
                move_bids=move_bids_uc,
                duplicate_bid=duplicate_bid_uc,
                create_bid=create_bid_uc,
                delete_conditions=delete_conditions_uc,
                duplicate_conditions=duplicate_conditions_uc,
                update_condition=update_condition_uc,
                renumber_conditions=renumber_conditions_uc,
                insert_condition=insert_condition_uc,
                insert_condition_folder=insert_condition_folder_uc,
                rename_condition_folder=rename_condition_folder_uc,
                delete_condition_folders=delete_condition_folders_uc,
                save_takeoff_positions=save_takeoff_positions_uc,
                save_takeoff_rotations=save_takeoff_rotations_uc,
                save_takeoffs_area=save_takeoffs_area_uc,
                save_takeoffs_condition=save_takeoffs_condition_uc,
                set_takeoffs_negative=set_takeoffs_negative_uc,
                set_takeoff_curve=set_takeoff_curve_uc,
                insert_takeoffs=insert_takeoffs_uc,
                delete_takeoffs=delete_takeoffs_uc,
                delete_pages=delete_pages_uc,
                save_cover_sheet=save_cover_sheet_uc,
                update_bid_job_status=update_bid_job_status_uc,
                save_job_statuses=save_job_statuses_uc,
                save_bid_areas=save_bid_areas_uc,
                save_page_name=save_page_name_uc,
                save_page_scale=save_page_scale_uc,
                save_page_show_mode=save_page_show_mode_uc,
                save_page_overlay_image=save_page_overlay_image_uc,
                save_page_invert=save_page_invert_uc,
                save_page_bitonal=save_page_bitonal_uc,
                save_page_image_adjustments=save_page_image_adjustments_uc,
                save_page_area=save_page_area_uc,
                save_employees=save_employees_uc,
                save_pay_classes=save_pay_classes_uc,
                save_condition_types=save_condition_types_uc,
                update_layer_show=update_layer_show_uc,
                update_all_layers_show=update_all_layers_show_uc,
                update_layer_name=update_layer_name_uc,
                insert_layer=insert_layer_uc,
                delete_layer=delete_layer_uc,
                swap_layer_sequence=swap_layer_sequence_uc,
                save_bid_selected_page=save_bid_selected_page_uc,
                save_page_view_state=save_page_view_state_uc,
                connection_manager=connection_manager,
                reload_database=reload_database_uc.execute,
                event_bus=event_bus,
                bid_write_guard=bid_write_guard,
            ),
        )
        self.container.register_instance(
            "annotation_write_service",
            AnnotationWriteService(
                save_annotation_positions=save_annotation_positions_uc,
                insert_annotations=insert_annotations_uc,
                delete_annotations=delete_annotations_uc,
                reload_database=reload_database_uc.execute,
                event_bus=event_bus,
                bid_write_guard=bid_write_guard,
            ),
        )

    def _register_license_use_cases(self, license_model) -> None:
        license_logger = self.logger.getChild("License")
        api_client = self.api_client_provider.get_license_api_client()
        validate_license = ValidateLicenseUseCase(
            license_model,
            api_client,
            license_logger.getChild("ValidateUseCase"),
        )
        activate_license = ActivateLicenseUseCase(
            license_model,
            api_client,
            license_logger.getChild("ActivateUseCase"),
        )
        deactivate_license = DeactivateLicenseUseCase(
            license_model,
            api_client,
            license_logger.getChild("DeactivateUseCase"),
        )
        self.container.register_instance("license_api_client", api_client)
        self.container.register_instance("validate_license_use_case", validate_license)
        self.container.register_instance("activate_license_use_case", activate_license)
        self.container.register_instance(
            "deactivate_license_use_case", deactivate_license
        )
