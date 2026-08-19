import win32api
import win32con
import win32net
import win32netcon
from pywintypes import error as WindowsApiError
from ...application.dtos.license_activation_identity_dto import (
    LICENSE_ACTIVATION_IDENTITY_VERSION,
    LicenseActivationIdentityDto,
    LicenseActivationIdentityError,
    WindowsJoinType,
)

_JOIN_TYPES = {
    win32netcon.NetSetupUnjoined: WindowsJoinType.UNJOINED,
    win32netcon.NetSetupWorkgroupName: WindowsJoinType.WORKGROUP,
    win32netcon.NetSetupDomainName: WindowsJoinType.DOMAIN,
}


class WindowsLicenseActivationIdentityProvider:
    def __init__(self, windows_api=win32api, windows_network_api=win32net) -> None:
        self._windows_api = windows_api
        self._windows_network_api = windows_network_api

    def get_identity(self) -> LicenseActivationIdentityDto:
        try:
            windows_account = self._windows_api.GetUserNameEx(
                win32con.NameSamCompatible
            )
            computer_name = self._windows_api.GetComputerNameEx(
                win32con.ComputerNameNetBIOS
            )
            join_name, join_status = self._windows_network_api.NetGetJoinInformation(
                None
            )
        except WindowsApiError as exc:
            raise LicenseActivationIdentityError(
                "Unable to query the current Windows account and computer identity"
            ) from exc
        join_type = _JOIN_TYPES.get(join_status)
        if join_type is None:
            raise LicenseActivationIdentityError(
                f"Windows returned unsupported computer join status {join_status}"
            )
        normalized_join_name = (
            "" if join_type == WindowsJoinType.UNJOINED else join_name
        )
        try:
            return LicenseActivationIdentityDto(
                version=LICENSE_ACTIVATION_IDENTITY_VERSION,
                windows_account=windows_account,
                computer_name=computer_name,
                join_type=join_type,
                join_name=normalized_join_name,
            )
        except ValueError as exc:
            raise LicenseActivationIdentityError(
                "Windows returned an invalid account or computer identity"
            ) from exc
