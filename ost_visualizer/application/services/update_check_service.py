import logging
from typing import Optional, Tuple
from ..dtos.application_info import APPLICATION_VERSION
from ...domain.entities.version_info import ChangelogSections, VersionInfo


class UpdateCheckService:
    CURRENT_VERSION = APPLICATION_VERSION

    def __init__(
        self,
        api_client,
        logger: logging.Logger,
    ):
        self.api_client = api_client
        self.logger = logger

    def check_for_updates(self) -> Tuple[bool, Optional[VersionInfo]]:
        try:
            success, response = self.api_client.check_version()
            if not success or not response:
                self.logger.warning(
                    "Failed to check for updates: no response from server"
                )
                return False, None
            server_version = self._get_string(response, "latest_version")
            if not server_version:
                self.logger.warning("Server response missing version information")
                return False, None
            is_newer = self._is_version_newer(server_version, self.CURRENT_VERSION)
            version_info = VersionInfo(
                current_version=server_version,
                your_version=self.CURRENT_VERSION,
                is_newer=is_newer,
                download_url=self._get_string(response, "download_url"),
                release_date=self._get_string(response, "release_date"),
                release_url=self._get_string(response, "release_url"),
                changelog=self._normalize_changelog(response.get("changelog")),
                release_notes_url=self._get_optional_string(
                    response, "release_notes_url"
                ),
            )
            return is_newer, version_info
        except Exception as exc:
            self.logger.exception("Error checking for updates: %s", exc)
            return False, None

    def _is_version_newer(self, server_version: str, current_version: str) -> bool:
        try:
            server_parts = [int(x) for x in server_version.split(".")]
            current_parts = [int(x) for x in current_version.split(".")]
            max_length = max(len(server_parts), len(current_parts))
            while len(server_parts) < max_length:
                server_parts.append(0)
            while len(current_parts) < max_length:
                current_parts.append(0)
            for server_part, current_part in zip(server_parts, current_parts):
                if server_part > current_part:
                    return True
                if server_part < current_part:
                    return False
            return False
        except (ValueError, AttributeError) as exc:
            self.logger.warning(
                "Failed to parse version strings: %s vs %s (%s)",
                server_version,
                current_version,
                exc,
            )
            return False

    def _normalize_changelog(self, value) -> Optional[ChangelogSections]:
        if not isinstance(value, dict):
            return None
        changelog: ChangelogSections = {}
        for section, items in value.items():
            if not isinstance(section, str) or not isinstance(items, list):
                continue
            normalized_items = [
                item.strip() for item in items if isinstance(item, str) and item.strip()
            ]
            if normalized_items:
                changelog[section.lower()] = normalized_items
        return changelog or None

    def _get_string(self, response: dict, key: str) -> str:
        value = response.get(key, "")
        return value.strip() if isinstance(value, str) else ""

    def _get_optional_string(self, response: dict, key: str) -> Optional[str]:
        value = self._get_string(response, key)
        return value or None
