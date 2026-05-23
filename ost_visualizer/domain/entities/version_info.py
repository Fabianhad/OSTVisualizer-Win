from dataclasses import dataclass
from typing import Optional

ChangelogSections = dict[str, list[str]]


@dataclass
class VersionInfo:
    current_version: str
    your_version: str
    is_newer: bool
    download_url: str = ""
    release_date: str = ""
    release_url: str = ""
    changelog: Optional[ChangelogSections] = None
    release_notes_url: Optional[str] = None
