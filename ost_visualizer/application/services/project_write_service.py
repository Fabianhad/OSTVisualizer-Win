from typing import List, Optional, Tuple
from ..dtos.create_condition_spec_dto import CreateConditionSpec
from ..dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ..dtos.update_condition_dto import UpdateConditionDto, UpdateConditionResultDto
from ..interfaces.i_mdb_connection_manager import IMdbConnectionManager
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
from ..use_cases.project.update_all_layers_show_use_case import (
    UpdateAllLayersShowUseCase,
)
from ..use_cases.project.update_bid_job_status_use_case import UpdateBidJobStatusUseCase
from ..use_cases.project.update_condition_use_case import UpdateConditionUseCase
from ..use_cases.project.update_layer_name_use_case import UpdateLayerNameUseCase
from ..use_cases.project.update_layer_show_use_case import UpdateLayerShowUseCase
from .active_bid_write_guard import ActiveBidWriteGuard
from .base_write_service import BaseWriteService


class ProjectWriteService(BaseWriteService):
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
        connection_manager: Optional[IMdbConnectionManager] = None,
        reload_database=None,
        event_bus=None,
        logger=None,
        bid_write_guard: Optional[ActiveBidWriteGuard] = None,
    ) -> None:
        if bid_write_guard is None:
            raise ValueError("ProjectWriteService requires bid_write_guard")
        super().__init__(reload_database, event_bus, logger)
        self._bid_write_guard = bid_write_guard
        self._connection_manager = connection_manager
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

    def delete_bids(self, db_path: str, bid_uids: List[str]) -> bool:
        if not bid_uids:
            return True
        success = self._delete_bids.execute(db_path, bid_uids)
        if success:
            self.reload_and_notify(db_path)
        return success

    def delete_projects(self, db_path: str, project_uids: List[str]) -> bool:
        if not project_uids:
            return True
        if self._bid_write_guard.blocks_active_locked_bid_project_delete(
            "delete_projects", db_path, project_uids
        ):
            return False
        success = self._delete_projects.execute(db_path, project_uids)
        if success:
            self.reload_and_notify(db_path)
        return success

    def create_project(self, db_path: str, name: str) -> Optional[str]:
        new_uid = self._create_project.execute(db_path, name)
        if new_uid is not None:
            self.reload_and_notify(db_path)
        return new_uid

    def rename_project(self, db_path: str, project_uid: str, new_name: str) -> bool:
        success = self._rename_project.execute(db_path, project_uid, new_name)
        if success:
            self.reload_and_notify(db_path)
        return success

    def move_bids(
        self,
        db_path: str,
        bid_uids: List[str],
        target_project_uid: Optional[str],
        orig_project_uid: Optional[str] = None,
        reload_database: bool = True,
    ) -> bool:
        if not bid_uids:
            return True
        if any(
            self._bid_write_guard.blocks_active_locked_bid_write(
                "move_bids", db_path, uid
            )
            for uid in bid_uids
        ):
            return False
        success = self._move_bids.execute(
            db_path, bid_uids, target_project_uid, orig_project_uid
        )
        if success and reload_database:
            self.reload_and_notify(db_path)
        return success

    def duplicate_bid(
        self, db_path: str, bid_uid: str, reload: bool = True
    ) -> Optional[str]:
        new_uid = self._duplicate_bid.execute(db_path, bid_uid)
        if new_uid is not None and reload:
            self.reload_and_notify(db_path)
        return new_uid

    def create_bid(
        self, db_path: str, project_uid: Optional[str], updates: dict
    ) -> Optional[str]:
        new_uid = self._create_bid.execute(db_path, project_uid, updates)
        if new_uid is not None:
            self.reload_and_notify(db_path)
        return new_uid

    def delete_conditions(
        self, db_path: str, bid_uid: str, condition_uids: List[str]
    ) -> bool:
        if not condition_uids:
            return True
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "delete_conditions", db_path, bid_uid
        ):
            return False
        success = self._delete_conditions.execute(db_path, bid_uid, condition_uids)
        if success:
            self.reload_and_notify(db_path)
        return success

    def create_condition(
        self, db_path: str, bid_uid: str, spec: CreateConditionSpec
    ) -> Optional[str]:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "create_condition", db_path, bid_uid
        ):
            return None
        new_uid = self._insert_condition.execute(db_path, bid_uid, spec)
        if new_uid is not None:
            self.reload_and_notify(db_path)
        return new_uid

    def create_condition_folder(
        self,
        db_path: str,
        bid_uid: str,
        name: str,
        parent_uid: Optional[str] = None,
    ) -> Optional[str]:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "create_condition_folder", db_path, bid_uid
        ):
            return None
        new_uid = self._insert_condition_folder.execute(
            db_path, bid_uid, name, parent_uid
        )
        if new_uid is not None:
            self.reload_and_notify(db_path)
        return new_uid

    def rename_condition_folder(self, db_path: str, folder_uid: str, name: str) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "rename_condition_folder", db_path
        ):
            return False
        success = self._rename_condition_folder.execute(db_path, folder_uid, name)
        if success:
            self.reload_and_notify(db_path)
        return success

    def delete_condition_folders(self, db_path: str, folder_uids: List[str]) -> bool:
        if not folder_uids:
            return True
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "delete_condition_folders", db_path
        ):
            return False
        success = self._delete_condition_folders.execute(db_path, folder_uids)
        if success:
            self.reload_and_notify(db_path)
        return success

    def duplicate_conditions(
        self, db_path: str, bid_uid: str, condition_uids: list
    ) -> list:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "duplicate_conditions", db_path, bid_uid
        ):
            return []
        new_uids = self._duplicate_conditions.execute(db_path, bid_uid, condition_uids)
        if new_uids:
            self.reload_and_notify(db_path)
        return new_uids

    def duplicate_conditions_to_bid(
        self,
        db_path: str,
        source_bid_uid: str,
        destination_bid_uid: str,
        condition_uids: list,
        reload_database: bool = True,
    ) -> dict:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "duplicate_conditions_to_bid", db_path, destination_bid_uid
        ):
            return {}
        uid_map = self._duplicate_conditions.execute_to_bid(
            db_path, source_bid_uid, destination_bid_uid, condition_uids
        )
        if uid_map and reload_database:
            self.reload_and_notify(db_path)
        return uid_map

    def update_condition(
        self,
        db_path: str,
        bid_uid: str,
        condition_uid: str,
        updates: UpdateConditionDto,
        all_conditions=None,
    ) -> UpdateConditionResultDto:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "update_condition", db_path, bid_uid
        ):
            return UpdateConditionResultDto(
                success=False, error="The active bid is locked"
            )
        result = self._update_condition.execute(
            db_path, bid_uid, condition_uid, updates, all_conditions
        )
        if result.success:
            self.reload_and_notify(db_path)
        return result

    def renumber_conditions(
        self, db_path: str, bid_uid: str, ordered_condition_uids: List[str]
    ) -> bool:
        if not ordered_condition_uids:
            return True
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "renumber_conditions", db_path, bid_uid
        ):
            return False
        success = self._renumber_conditions.execute(
            db_path, bid_uid, ordered_condition_uids
        )
        if success:
            self.reload_and_notify(db_path)
        return success

    def set_takeoff_curve(
        self, db_path: str, takeoff_uid: str, position: List[float], curve: int
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "set_takeoff_curve", db_path
        ):
            return False
        success = self._set_takeoff_curve.execute(db_path, takeoff_uid, position, curve)
        if success:
            self.reload_and_notify(db_path)
        return success

    def save_takeoff_positions(
        self,
        db_path: str,
        positions: List[Tuple[str, List[float]]],
        reload_database: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_takeoff_positions", db_path
        ):
            return False
        success = self._save_takeoff_positions.execute(db_path, positions)
        if success and reload_database:
            self.reload_and_notify(db_path)
        return success

    def save_takeoff_rotations(
        self,
        db_path: str,
        rotations: List[Tuple[str, float]],
        reload_database: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_takeoff_rotations", db_path
        ):
            return False
        success = self._save_takeoff_rotations.execute(db_path, rotations)
        if success and reload_database:
            self.reload_and_notify(db_path)
        return success

    def save_takeoffs_area(
        self, db_path: str, takeoff_uids: List[str], area_uid: str
    ) -> bool:
        return self._save_takeoffs_assignment(
            "save_takeoffs_area",
            self._save_takeoffs_area,
            db_path,
            takeoff_uids,
            area_uid,
        )

    def save_takeoffs_condition(
        self, db_path: str, takeoff_uids: List[str], condition_uid: str
    ) -> bool:
        return self._save_takeoffs_assignment(
            "save_takeoffs_condition",
            self._save_takeoffs_condition,
            db_path,
            takeoff_uids,
            condition_uid,
        )

    def _save_takeoffs_assignment(
        self,
        operation: str,
        use_case,
        db_path: str,
        takeoff_uids: List[str],
        target_uid: str,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(operation, db_path):
            return False
        success = use_case.execute(db_path, takeoff_uids, target_uid)
        if success:
            self.reload_and_notify(db_path)
        return success

    def set_takeoffs_negative(
        self, db_path: str, takeoff_uids: List[str], is_negative: bool
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "set_takeoffs_negative", db_path
        ):
            return False
        success = self._set_takeoffs_negative.execute(
            db_path, takeoff_uids, is_negative
        )
        if success:
            self.reload_and_notify(db_path)
        return success

    def insert_takeoffs(
        self,
        db_path: str,
        bid_uid: str,
        takeoff_specs: List[InsertTakeoffSpec],
        reload_database: bool = True,
    ) -> List[str]:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "insert_takeoffs", db_path, bid_uid
        ):
            return []
        new_uids = self._insert_takeoffs.execute(db_path, bid_uid, takeoff_specs)
        if new_uids and reload_database:
            self.reload_and_notify(db_path)
        return new_uids

    def delete_takeoffs(
        self, db_path: str, takeoff_uids: List[str], reload_database: bool = True
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "delete_takeoffs", db_path
        ):
            return False
        success = self._delete_takeoffs.execute(db_path, takeoff_uids)
        if success and reload_database:
            self.reload_and_notify(db_path)
        return success

    def save_page_scale(
        self, db_path: str, page_uid: str, sf1: float, sf2: float
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_scale", db_path
        ):
            return False
        success = self._save_page_scale.execute(db_path, page_uid, sf1, sf2)
        if success:
            self.reload_and_notify(db_path)
        return success

    def save_page_name(self, db_path: str, page_uid: str, name: str) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_name", db_path
        ):
            return False
        success = self._save_page_name.execute(db_path, page_uid, name)
        if success:
            self.reload_and_notify(db_path)
        return success

    def save_page_scales(
        self, db_path: str, page_uids: List[str], sf1: float, sf2: float
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_scales", db_path
        ):
            return False
        valid_page_uids = self._unique_page_uids(page_uids)
        if not valid_page_uids:
            return False
        any_success = False
        all_success = True
        for page_uid in valid_page_uids:
            success = self._save_page_scale.execute(db_path, page_uid, sf1, sf2)
            any_success = any_success or success
            all_success = all_success and success
        if any_success:
            self.reload_and_notify(db_path)
        return all_success

    def save_page_show_mode(self, db_path: str, page_uid: str, show_mode: int) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_show_mode", db_path
        ):
            return False
        success = self._save_page_show_mode.execute(db_path, page_uid, show_mode)
        if success:
            self.reload_and_notify(db_path)
        return success

    def save_page_overlay_image(
        self, db_path: str, page_uid: str, overlay_image_path: str
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_overlay_image", db_path
        ):
            return False
        success = self._save_page_overlay_image.execute(
            db_path, page_uid, overlay_image_path
        )
        if success:
            self.reload_and_notify(db_path)
        return success

    def save_page_invert(self, db_path: str, page_uid: str, invert: bool) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_invert", db_path
        ):
            return False
        return self._save_page_invert.execute(db_path, page_uid, invert)

    def save_page_bitonal(self, db_path: str, page_uid: str, bitonal: bool) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_bitonal", db_path
        ):
            return False
        return self._save_page_bitonal.execute(db_path, page_uid, bitonal)

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
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_image_adjustments", db_path
        ):
            return False
        valid_page_uids = self._unique_page_uids(page_uids)
        if not valid_page_uids:
            return False
        success = self._save_page_image_adjustments.execute(
            db_path, valid_page_uids, rotation, flip_x, flip_y, invert, bitonal
        )
        if success:
            self.reload_and_notify(db_path)
        return success

    @staticmethod
    def _unique_page_uids(page_uids: List[str]) -> List[str]:
        valid_page_uids = []
        seen_page_uids = set()
        for uid in page_uids:
            if uid and uid not in seen_page_uids:
                valid_page_uids.append(uid)
                seen_page_uids.add(uid)
        return valid_page_uids

    def save_page_area(self, db_path: str, page_uid: str, area_uid: str) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_area", db_path
        ):
            return False
        success = self._save_page_area.execute(db_path, page_uid, area_uid)
        if success:
            self.reload_and_notify(db_path)
        return success

    def update_layer_show(self, db_path: str, layer_uid: str, show: bool) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "update_layer_show", db_path
        ):
            return False
        success = self._update_layer_show.execute(db_path, layer_uid, show)
        if success:
            self.reload_and_notify(db_path)
        return success

    def insert_layer(
        self, db_path: str, bid_uid: str, name: str, after_sequence: int
    ) -> Optional[str]:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "insert_layer", db_path, bid_uid
        ):
            return None
        new_uid = self._insert_layer.execute(db_path, bid_uid, name, after_sequence)
        if new_uid is not None:
            self.reload_and_notify(db_path)
        return new_uid

    def delete_layer(self, db_path: str, layer_uid: str) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "delete_layer", db_path
        ):
            return False
        success = self._delete_layer.execute(db_path, layer_uid)
        if success:
            self.reload_and_notify(db_path)
        return success

    def update_all_layers_show(self, db_path: str, bid_uid: str, show: bool) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "update_all_layers_show", db_path, bid_uid
        ):
            return False
        success = self._update_all_layers_show.execute(db_path, bid_uid, show)
        if success:
            self.reload_and_notify(db_path)
        return success

    def swap_layer_sequence(
        self, db_path: str, layer_uid_a: str, layer_uid_b: str
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "swap_layer_sequence", db_path
        ):
            return False
        success = self._swap_layer_sequence.execute(db_path, layer_uid_a, layer_uid_b)
        if success:
            self.reload_and_notify(db_path)
        return success

    def update_layer_name(self, db_path: str, layer_uid: str, name: str) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "update_layer_name", db_path
        ):
            return False
        success = self._update_layer_name.execute(db_path, layer_uid, name)
        if success:
            self.reload_and_notify(db_path)
        return success

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
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_page_view_state", db_path
        ):
            return False
        return self._save_page_view_state.execute(
            db_path, page_uid, zoom_fac, current_x, current_y
        )

    def save_bid_selected_page(self, db_path: str, bid_uid: str, page_uid: str) -> bool:
        if self._is_write_blocked():
            return False
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_bid_selected_page", db_path, bid_uid
        ):
            return False
        return self._save_bid_selected_page.execute(db_path, bid_uid, page_uid)

    def save_cover_sheet(self, db_path: str, bid_uid: str, updates: dict) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_cover_sheet", db_path, bid_uid
        ):
            return False
        success = self._save_cover_sheet.execute(db_path, bid_uid, updates)
        if success:
            self.reload_and_notify(db_path)
        return success

    def delete_pages(self, db_path: str, page_uids: List[str]) -> bool:
        valid_page_uids = self._unique_page_uids(page_uids)
        if not valid_page_uids:
            return False
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "delete_pages", db_path
        ):
            return False
        success = self._delete_pages.execute(db_path, valid_page_uids)
        if success:
            self.reload_and_notify(db_path)
        return success

    def update_bid_job_status(
        self, db_path: str, bid_uid: str, job_status_uid: Optional[str]
    ) -> bool:
        success = self._update_bid_job_status.execute(db_path, bid_uid, job_status_uid)
        if success:
            self.reload_and_notify(db_path)
        return success

    def save_job_statuses(self, db_path: str, changes: dict) -> bool:
        success = self._save_job_statuses.execute(db_path, changes)
        if success:
            self.reload_and_notify(db_path)
        return success

    def save_employees(self, db_path: str, changes: dict) -> bool:
        success = self._save_employees.execute(db_path, changes)
        if success:
            self.reload_and_notify(db_path)
        return success

    def save_pay_classes(self, db_path: str, changes: dict) -> bool:
        success = self._save_pay_classes.execute(db_path, changes)
        if success:
            self.reload_and_notify(db_path)
        return success

    def save_condition_types(self, db_path: str, changes: dict) -> dict:
        result = self._save_condition_types.execute(db_path, changes)
        self.reload_and_notify(db_path)
        return result

    def save_bid_areas(self, db_path: str, bid_uid: str, changes) -> dict:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_bid_areas", db_path, bid_uid
        ):
            return {}
        result = self._save_bid_areas.execute(db_path, bid_uid, changes)
        if result:
            self.reload_and_notify(db_path)
        return result
