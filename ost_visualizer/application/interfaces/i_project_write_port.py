from typing import Protocol


class IProjectWritePort(Protocol):
    def update_layer_show(self, db_path: str, layer_uid: str, show: bool) -> bool: ...
    def update_default_layer_show(
        self, db_path: str, layer_uid: str, show: bool
    ) -> bool: ...
