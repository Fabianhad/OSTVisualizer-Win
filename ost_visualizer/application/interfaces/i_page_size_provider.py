from typing import Protocol


class IPageSizeProvider(Protocol):
    def get_page_size(
        self, file_path: str, page_index: int = 0
    ) -> tuple[float, float]: ...
