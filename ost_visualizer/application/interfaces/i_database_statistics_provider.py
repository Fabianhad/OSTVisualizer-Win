from typing import Dict, Protocol


class IDatabaseStatisticsProvider(Protocol):
    def get_database_statistics(self, file_path: str) -> Dict[str, int]: ...
