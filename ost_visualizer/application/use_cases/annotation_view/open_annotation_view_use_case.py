import logging
from typing import Optional
from ....domain.entities.named_view import build_named_view_from_annotation
from ....domain.services.project_data_service import ProjectDataService
from ...events.app_events import AppEvents
from ...interfaces.i_annotation_view_manager import IAnnotationViewManager


class OpenAnnotationViewUseCase:
    def __init__(
        self,
        view_manager: IAnnotationViewManager,
        project_data: ProjectDataService,
        config_model=None,
        view_window_manager: Optional[IAnnotationViewManager] = None,
        main_view_manager: Optional[IAnnotationViewManager] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.view_manager = view_manager
        self.project_data = project_data
        self.config_model = config_model
        self.view_window_manager = view_window_manager
        self.main_view_manager = main_view_manager

    def execute_from_hotlink(self, event: AppEvents.HOTLINK_CLICKED) -> str:
        bid_ref = self.project_data.get_current_bid_ref()
        if not bid_ref:
            return ""
        target_page_uid = self._resolve_target_page(event.target_view_uid)
        if not target_page_uid:
            return ""
        manager = self._hotlink_view_manager()
        if manager.is_view_open():
            manager.bring_to_front()
            manager.navigate_to_view(target_page_uid, event.target_view_uid)
            return "__current__"
        return manager.open_view(
            bid_ref=bid_ref,
            target_page_uid=target_page_uid,
            target_named_view_uid=event.target_view_uid,
        )

    def _hotlink_view_manager(self) -> IAnnotationViewManager:
        if (
            self.config_model is not None
            and self.config_model.hotlink_target == "main"
            and self.main_view_manager is not None
        ):
            return self.main_view_manager
        if (
            self.config_model is not None
            and self.config_model.hotlink_target == "view"
            and self.view_window_manager is not None
        ):
            return self.view_window_manager
        return self.view_manager

    def _resolve_target_page(self, target_view_uid: Optional[str]) -> Optional[str]:
        if not target_view_uid:
            return None
        all_annotations = self.project_data.get_all_annotations()
        for ann in all_annotations:
            nv = build_named_view_from_annotation(ann)
            if nv and nv.uid == target_view_uid:
                return nv.bid_page_uid
        return None
