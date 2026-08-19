from typing import Protocol
from ..dtos.license_activation_identity_dto import LicenseActivationIdentityDto


class ILicenseActivationIdentityProvider(Protocol):
    def get_identity(self) -> LicenseActivationIdentityDto: ...
