from pathlib import Path

APP_DATA_DIR_NAME = ".ost_visualizer"
_OST4_WORKING_DIR = Path("C:/OCS Documents/OST")
_FALLBACK_WORKING_DIR = Path.home() / "Documents" / "OST"


def get_app_data_dir() -> Path:
    return Path.home() / APP_DATA_DIR_NAME


def get_default_working_dir() -> Path:
    if _OST4_WORKING_DIR.exists():
        return _OST4_WORKING_DIR
    if _OST4_WORKING_DIR.drive and Path(_OST4_WORKING_DIR.drive + "/").exists():
        return _OST4_WORKING_DIR
    return _FALLBACK_WORKING_DIR
