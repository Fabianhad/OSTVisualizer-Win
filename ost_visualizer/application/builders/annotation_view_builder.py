import logging
from typing import Optional
from ..interfaces.i_annotation_view_manager import IAnnotationViewManager
from ..services.annotation_view_event_handler import AnnotationViewEventHandler
from ..use_cases.annotation_view.open_annotation_view_use_case import (
    OpenAnnotationViewUseCase,
)


class AnnotationViewBuilder:
    def __init__(
        self,
        container,
        event_bus,
        view_manager_factory,
        repository_factory,
        logger: Optional[logging.Logger] = None,
    ):
        self.container = container
        self.event_bus = event_bus
        self.view_manager_factory = view_manager_factory
        self.repository_factory = repository_factory
        self.logger = logger or logging.getLogger(__name__)

    def build(self) -> None:
        self._build_repositories()
        self._build_managers()
        self._build_use_cases()
        self._build_event_handler()

    def _build_repositories(self) -> None:
        self.container.register_instance(
            "annotation_view_repository", self.repository_factory()
        )
        self.container.register_instance(
            "view_window_repository", self.repository_factory()
        )

    def _build_managers(self) -> None:
        self.container.register_singleton(
            "annotation_view_manager", self._create_manager
        )
        self.container.register_singleton(
            "view_window_manager", self._create_view_manager
        )

    def _create_manager(self) -> IAnnotationViewManager:
        repository = self.container.get("annotation_view_repository")
        return self._create_shared_manager(
            repository=repository,
            view_kind="annotation",
            write_service=self.container.get("project_write_service"),
            annotation_write_service=self.container.get("annotation_write_service"),
        )

    def _create_view_manager(self):
        repository = self.container.get("view_window_repository")
        return self._create_shared_manager(
            repository=repository,
            view_kind="view",
        )

    def _create_shared_manager(
        self,
        *,
        repository,
        view_kind: str,
        write_service=None,
        annotation_write_service=None,
    ):
        project_data_service = self.container.get("project_data_service")
        config_model = self.container.get("config_model")
        icon_provider = self.container.get("icon_provider")
        try:
            parent_window = self.container.get("main_window")
        except Exception:
            parent_window = None
        return self.view_manager_factory(
            event_bus=self.event_bus,
            icon_provider=icon_provider,
            repository=repository,
            project_data_service=project_data_service,
            config_model=config_model,
            parent_window=parent_window,
            logger=self.logger.getChild("ViewManager"),
            view_kind=view_kind,
            write_service=write_service,
            annotation_write_service=annotation_write_service,
        )

    def _build_use_cases(self) -> None:
        def create_open_view_use_case():
            manager = self.container.get("annotation_view_manager")
            project_data_service = self.container.get("project_data_service")
            return OpenAnnotationViewUseCase(
                view_manager=manager,
                project_data=project_data_service,
                logger=self.logger.getChild("OpenAnnotationViewUseCase"),
            )

        self.container.register_singleton(
            "open_annotation_view_use_case", create_open_view_use_case
        )

    def _build_event_handler(self) -> None:
        handler = AnnotationViewEventHandler(
            event_bus=self.event_bus,
            use_case_factory=lambda: self.container.get(
                "open_annotation_view_use_case"
            ),
            logger=self.logger.getChild("AnnotationViewEventHandler"),
        )
        handler.start()
        self.container.register_instance("annotation_view_event_handler", handler)
