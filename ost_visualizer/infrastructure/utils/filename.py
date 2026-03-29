import re

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:"*?<>|]')


def sanitize_filename(name: str) -> str:
    return _INVALID_FILENAME_CHARS.sub("_", name)
