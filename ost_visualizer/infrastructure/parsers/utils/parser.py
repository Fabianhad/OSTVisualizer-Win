from typing import Any


def decode_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return str(value)


def parse_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        str_val = str(value).replace(",", ".")
        return float(str_val)
    except (ValueError, TypeError):
        return default


def remove_empty_folders(folders_dict):
    result = {}
    for folder_uid, folder_data in folders_dict.items():
        folder_data.subfolders = remove_empty_folders(folder_data.subfolders)
        if folder_data.pages or folder_data.subfolders:
            result[folder_uid] = folder_data
    return result
