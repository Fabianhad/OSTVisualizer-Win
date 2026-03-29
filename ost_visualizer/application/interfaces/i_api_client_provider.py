from typing import Protocol
from ...domain.repositories.i_license_api_client import ILicenseApiClient


class IApiClientProvider(Protocol):
    def get_license_api_client(self) -> ILicenseApiClient: ...
