import logging
from typing import Callable, Optional, Protocol
from ...domain.entities.identity_refs import BidRef
from ...domain.services.project_data_service import ProjectDataService


class ILoadFileUseCase(Protocol):
    last_error: Optional[str]

    def execute(self, file_path: str) -> bool: ...
class ProjectOperationsService:
    def __init__(
        self,
        data_service: ProjectDataService,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.data_service = data_service
        self.logger = logger or logging.getLogger(__name__)
        self._load_file_use_case: Optional[ILoadFileUseCase] = None
        self._unload_file_handler: Optional[Callable[[Optional[str]], bool]] = None
        self._load_bid_handler: Optional[Callable[[BidRef], bool]] = None
        self._reload_database_handler: Optional[Callable[[Optional[str]], bool]] = None
        self.last_error: str = ""

    def configure_use_cases(
        self,
        load_file_use_case: ILoadFileUseCase,
        unload_file_handler: Callable[[Optional[str]], bool],
        load_bid_handler: Callable[[BidRef], bool],
        reload_database_handler: Callable[[Optional[str]], bool],
    ) -> None:
        self._load_file_use_case = load_file_use_case
        self._unload_file_handler = unload_file_handler
        self._load_bid_handler = load_bid_handler
        self._reload_database_handler = reload_database_handler

    def load_file(self, file_path: str) -> bool:
        self.last_error = ""
        use_case = self._require_handler(
            self._load_file_use_case, "LoadFileUseCase is not configured"
        )
        success = use_case.execute(file_path)
        self.last_error = use_case.last_error or ""
        return success

    def unload_file(self, file_path: Optional[str] = None) -> bool:
        handler = self._require_handler(
            self._unload_file_handler, "UnloadFileUseCase is not configured"
        )
        return handler(file_path)

    def load_bid(self, bid_ref: BidRef) -> bool:
        handler = self._require_handler(
            self._load_bid_handler, "LoadBidUseCase is not configured"
        )
        return handler(bid_ref)

    def reload_database(self, file_path: Optional[str] = None) -> bool:
        handler = self._require_handler(
            self._reload_database_handler,
            "ReloadDatabaseUseCase is not configured",
        )
        return handler(file_path)

    @staticmethod
    def _require_handler(handler: Optional[Callable], message: str) -> Callable:
        if handler is None:
            raise RuntimeError(message)
        return handler
