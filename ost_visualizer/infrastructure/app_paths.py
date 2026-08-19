from pathlib import Path
from pywintypes import com_error
from win32com.shell import shell, shellcon

APP_DATA_DIR_NAME = ".ost_visualizer"
_OST_WORKING_DIR = Path("C:/OCS Documents/OST")
_FALLBACK_WORKING_DIR = Path.home() / "Documents" / "OST"


def get_app_data_dir() -> Path:
    return Path.home() / APP_DATA_DIR_NAME


def get_machine_app_data_dir() -> Path:
    try:
        common_app_data = shell.SHGetKnownFolderPath(
            shellcon.FOLDERID_ProgramData,
            0,
            None,
        )
    except (OSError, com_error) as exc:
        raise OSError("Windows machine data directory is unavailable") from exc
    if not common_app_data:
        raise OSError("Windows machine data directory is unavailable")
    return Path(common_app_data) / "OST Visualizer"


def get_default_working_dir() -> Path:
    if _OST_WORKING_DIR.exists():
        return _OST_WORKING_DIR
    if _OST_WORKING_DIR.drive and Path(_OST_WORKING_DIR.drive + "/").exists():
        return _OST_WORKING_DIR
    return _FALLBACK_WORKING_DIR
