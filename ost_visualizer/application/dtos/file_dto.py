from dataclasses import dataclass


@dataclass
class FileLoadResultDto:
    success: bool
    file_path: str = ""
    error_message: str = ""
