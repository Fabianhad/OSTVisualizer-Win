from ...application.interfaces.i_annotation_view_manager import IAnnotationViewManager
from ..windows.annotation_view_window import AnnotationViewWindow
from .detached_page_view_manager import DetachedPageViewManager


class QtAnnotationViewManager(DetachedPageViewManager, IAnnotationViewManager):
    def __init__(
        self,
        event_bus,
        icon_provider,
        repository,
        project_data,
        config_model,
        coord_factory,
        color_service,
        infrastructure_provider,
        ui_access_manager,
        write_service=None,
        annotation_write_service=None,
        saved_window_state_provider=None,
        parent_window=None,
        logger=None,
    ):
        super().__init__(
            event_bus=event_bus,
            icon_provider=icon_provider,
            repository=repository,
            project_data=project_data,
            config_model=config_model,
            coord_factory=coord_factory,
            color_service=color_service,
            infrastructure_provider=infrastructure_provider,
            ui_access_manager=ui_access_manager,
            window_factory=AnnotationViewWindow,
            write_service=write_service,
            annotation_write_service=annotation_write_service,
            saved_window_state_provider=saved_window_state_provider,
            parent_window=parent_window,
            logger=logger,
        )
