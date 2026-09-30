import unittest
import uuid
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
    HardwareIdentitySource,
    MachineIdentity,
    build_hwid,
    is_canonical_hwid,
)

SYSTEM_UUID = uuid.UUID("00112233-4455-6677-8899-AABBCCDDEEFF")


class HwidV1Tests(unittest.TestCase):
    def test_hwid_formula_is_canonical_full_sha256(self):
        identity = MachineIdentity.create(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
            SYSTEM_UUID,
        )
        hwid = build_hwid(identity)
        self.assertEqual(
            hwid,
            "v1:B216EAC22D5562B0F8448312C46EE0C55E5F8AB6EF7BB1D8F799C020761525AD",
        )
        self.assertTrue(is_canonical_hwid(hwid))
        self.assertFalse(is_canonical_hwid(hwid.lower()))
        self.assertFalse(is_canonical_hwid("A" * 16))

    def test_machine_identity_rejects_noncanonical_contract_values(self):
        for identity_args in (
            (
                "unsupported",
                HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
                str(SYSTEM_UUID).upper(),
            ),
            (HWID_VERSION, "unknown_source", str(SYSTEM_UUID).upper()),
            (
                HWID_VERSION,
                HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
                str(SYSTEM_UUID).lower(),
            ),
        ):
            with self.subTest(identity_args=identity_args):
                with self.assertRaises(ValueError):
                    MachineIdentity(*identity_args)
