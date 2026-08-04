import logging
from typing import Callable, Optional, Protocol
from ...domain.entities.identity_refs import BidRef
from ...domain.services.project_data_service import ProjectDataService
from ..use_cases.project.load_bid_use_case import PreparedBidLoad
from .navigation_load_service import NavigationLoadService, NavigationLoadState


class ILoadFileUseCase(Protocol):
    last_error: Optional[str]

    def execute(self, file_path: str) -> bool: ...
class ILoadBidUseCase(Protocol):
    def execute(self, bid_ref: BidRef) -> bool: ...
    def prepare(self, bid_ref: BidRef) -> PreparedBidLoad: ...
    def apply_prepared(self, bid_ref: BidRef, result: PreparedBidLoad) -> bool: ...
class ProjectOperationsService:
    def __init__(
        self,
        data_service: ProjectDataService,
        navigation_loader: NavigationLoadService,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.data_service = data_service
        self._navigation_loader = navigation_loader
        self.logger = logger or logging.getLogger(__name__)
        self._load_file_use_case: Optional[ILoadFileUseCase] = None
        self._unload_file_handler: Optional[Callable[[Optional[str]], bool]] = None
        self._load_bid_use_case: Optional[ILoadBidUseCase] = None
        self._reload_database_handler: Optional[Callable[[Optional[str]], bool]] = None
        self.last_error: str = ""

    def configure_use_cases(
        self,
        load_file_use_case: ILoadFileUseCase,
        unload_file_handler: Callable[[Optional[str]], bool],
        load_bid_use_case: ILoadBidUseCase,
        reload_database_handler: Callable[[Optional[str]], bool],
    ) -> None:
        self._load_file_use_case = load_file_use_case
        self._unload_file_handler = unload_file_handler
        self._load_bid_use_case = load_bid_use_case
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

    def request_load_bid(
        self,
        bid_ref: BidRef,
        completion: Callable[[bool, str], None],
    ) -> bool:
        use_case = self._require_handler(
            self._load_bid_use_case, "LoadBidUseCase is not configured"
        )
        if not self._navigation_loader.uses_background_reads(bid_ref.file_path):
            try:
                completion(bool(use_case.execute(bid_ref)), "")
            except Exception as exc:
                completion(False, str(exc) or exc.__class__.__name__)
            return False

        def prepared(result) -> None:
            if result.state != NavigationLoadState.READY or result.value is None:
                completion(False, result.message or "The SQL bid could not be loaded.")
                return
            try:
                success = bool(use_case.apply_prepared(bid_ref, result.value))
            except Exception as exc:
                self.logger.exception("Failed to project the SQL bid navigation result")
                completion(False, str(exc) or exc.__class__.__name__)
                return
            completion(success, "" if success else "The SQL bid could not be loaded.")

        self._navigation_loader.submit(
            bid_ref.file_path,
            bid_ref.bid_uid,
            lambda: use_case.prepare(bid_ref),
            prepared,
        )
        return True

    def cancel_navigation_load(self, database_id: str = "") -> None:
        self._navigation_loader.cancel(database_id)

    def navigation_load_in_progress(self) -> bool:
        return self._navigation_loader.state().state == NavigationLoadState.LOADING

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
