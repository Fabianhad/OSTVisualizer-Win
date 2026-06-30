from typing import Any, Dict, List, Optional, Protocol
from ...domain.entities.condition import Condition
from ...domain.entities.takeoff import Takeoff


class IExportStrategy(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def extension(self) -> str: ...
    def get_dialog_title(self, page_count: int) -> str: ...
    def prepare_filename(self, bid_name: str, page_names: List[str]) -> str: ...
    def prepare_title(self, bid_name: str, page_names: List[str]) -> Optional[str]: ...
    def get_export_options(
        self,
        config_model: Any,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    ) -> Dict[str, Any]: ...
    def execute_export(
        self,
        bid_conditions: Dict[str, Condition],
        takeoffs: List[Takeoff],
        output_path: str,
        **export_options,
    ) -> bool: ...
