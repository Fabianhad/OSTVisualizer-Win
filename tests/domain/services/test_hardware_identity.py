import unittest
import uuid
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
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
            (
                HWID_VERSION,
                HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
                "00000000-0000-0000-0000-000000000000",
            ),
            (HWID_VERSION, HardwareIdentitySource.SMBIOS_SYSTEM_UUID, "not-a-uuid"),
            (HWID_VERSION, HardwareIdentitySource.SMBIOS_SYSTEM_UUID, None),
        ):
            with self.subTest(identity_args=identity_args):
                with self.assertRaises(ValueError):
                    MachineIdentity(*identity_args)


class MachineIdentityContractTests(unittest.TestCase):
    def identity(self, source=HardwareIdentitySource.SMBIOS_SYSTEM_UUID):
        return MachineIdentity.create(source, SYSTEM_UUID)

    def test_constants_and_source_values_are_the_wire_format(self):
        from ost_visualizer.domain.services import hardware_identity as hw

        self.assertEqual(HWID_VERSION, "v1")
        self.assertEqual(hw.HWID_DIGEST_LENGTH, 64)
        self.assertEqual(hw.HWID_EXTERNAL_LENGTH, 67)
        self.assertEqual(len(build_hwid(self.identity())), hw.HWID_EXTERNAL_LENGTH)
        self.assertEqual(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID.value, "smbios_system_uuid"
        )
        self.assertEqual(
            HardwareIdentitySource.INSTALLATION_UUID.value, "installation_uuid"
        )
        self.assertEqual(
            HardwareIdentitySource("installation_uuid"),
            HardwareIdentitySource.INSTALLATION_UUID,
        )

    def test_hwid_depends_on_source_and_identifier_and_is_pinned_per_source(self):
        smbios = build_hwid(self.identity())
        installed = build_hwid(self.identity(HardwareIdentitySource.INSTALLATION_UUID))
        other = build_hwid(
            MachineIdentity.create(
                HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
                uuid.UUID("00112233-4455-6677-8899-AABBCCDDEE00"),
            )
        )
        self.assertEqual(len({smbios, installed, other}), 3)
        self.assertEqual(
            installed,
            "v1:"
            + __import__("hashlib")
            .sha256(
                b"OST_VISUALIZER_HWID|v1|installation_uuid|"
                b"00112233-4455-6677-8899-AABBCCDDEEFF"
            )
            .hexdigest()
            .upper(),
        )
        self.assertEqual(build_hwid(self.identity()), smbios)

    def test_canonical_hwid_requires_version_prefix_and_exactly_64_uppercase_hex(self):
        digest = "A" * 64
        self.assertTrue(is_canonical_hwid("v1:" + digest))
        for value in (
            "v1:" + "A" * 63,
            "v1:" + "A" * 65,
            "v2:" + digest,
            "V1:" + digest,
            "v1:" + "a" * 64,
            "v1:" + "G" * 64,
            "v1" + digest,
            " v1:" + digest,
            "v1:" + digest + "\n",
            "",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_canonical_hwid(value))

    def test_is_canonical_hwid_is_a_total_boolean_predicate_for_non_strings(self):
        # A corrupt license cache can carry any JSON type in "hwid"; the predicate
        # must answer False instead of leaking the re module's TypeError.
        canonical = "v1:" + "A" * 64
        for value in (
            None,
            123,
            1.5,
            True,
            b"v1:" + b"A" * 64,
            bytearray(b"v1:" + b"A" * 64),
            ["v1:" + "A" * 64],
            {"hwid": canonical},
            object(),
        ):
            with self.subTest(value=repr(value)[:40]):
                self.assertIs(is_canonical_hwid(value), False)
        self.assertIs(is_canonical_hwid(canonical), True)
        self.assertIs(is_canonical_hwid(""), False)
        self.assertIs(is_canonical_hwid("not-an-hwid"), False)

    def test_create_uppercases_the_identifier_and_rejects_generic_uuids(self):
        identity = self.identity()
        self.assertEqual(identity.identifier, "00112233-4455-6677-8899-AABBCCDDEEFF")
        self.assertEqual(identity.version, HWID_VERSION)
        for generic in (
            "00000000-0000-0000-0000-000000000000",
            "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
            "00010203-0405-0607-0809-0A0B0C0D0E0F",
            "03000200-0400-0500-0006-000700080009",
            "DEADBEEF-DEAD-BEEF-DEAD-BEEFDEADBEEF",
        ):
            with self.subTest(generic=generic):
                with self.assertRaises(ValueError):
                    MachineIdentity.create(
                        HardwareIdentitySource.SMBIOS_SYSTEM_UUID, uuid.UUID(generic)
                    )
        from ost_visualizer.domain.services.hardware_identity import (
            is_usable_identity_uuid,
        )

        self.assertTrue(is_usable_identity_uuid(SYSTEM_UUID))
        self.assertFalse(is_usable_identity_uuid(uuid.UUID(int=0)))

    def test_constructor_failures_name_the_rejected_part(self):
        source = HardwareIdentitySource.SMBIOS_SYSTEM_UUID
        text = str(SYSTEM_UUID).upper()
        cases = (
            (("v2", source, text), "Invalid machine identity version"),
            (
                (HWID_VERSION, "smbios_system_uuid", text),
                "Invalid machine identity source",
            ),
            ((HWID_VERSION, source, None), "Invalid machine identity UUID"),
            ((HWID_VERSION, source, 5), "Invalid machine identity UUID"),
            ((HWID_VERSION, source, "not-a-uuid"), "Invalid machine identity UUID"),
            ((HWID_VERSION, source, text.lower()), "Invalid machine identity UUID"),
            (
                (HWID_VERSION, source, "{" + text + "}"),
                "Invalid machine identity UUID",
            ),
            (
                (HWID_VERSION, source, "00000000-0000-0000-0000-000000000000"),
                "Invalid machine identity UUID",
            ),
        )
        for args, message in cases:
            with self.subTest(args=args):
                with self.assertRaises(ValueError) as raised:
                    MachineIdentity(*args)
                self.assertEqual(str(raised.exception), message)

    def test_unparseable_uuid_text_chains_the_original_parse_error(self):
        with self.assertRaises(ValueError) as raised:
            MachineIdentity(
                HWID_VERSION, HardwareIdentitySource.SMBIOS_SYSTEM_UUID, "x"
            )
        self.assertIsInstance(raised.exception.__cause__, ValueError)

    def test_identity_is_frozen_and_round_trips_through_its_dict(self):
        from dataclasses import FrozenInstanceError

        identity = self.identity(HardwareIdentitySource.INSTALLATION_UUID)
        payload = identity.to_dict()
        self.assertEqual(
            payload,
            {
                "version": "v1",
                "source": "installation_uuid",
                "identifier": "00112233-4455-6677-8899-AABBCCDDEEFF",
            },
        )
        self.assertEqual(MachineIdentity.from_dict(payload), identity)
        with self.assertRaises(FrozenInstanceError):
            identity.identifier = "x"

    def test_from_dict_rejects_non_objects_and_each_bad_field_with_its_message(self):
        good = self.identity().to_dict()
        for value in (None, [], "x", 5, ("a",)):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as raised:
                    MachineIdentity.from_dict(value)
                self.assertEqual(
                    str(raised.exception),
                    "Invalid machine identity: expected JSON object",
                )
        for source in ("firmware", None, 3, ""):
            with self.subTest(source=source):
                with self.assertRaises(ValueError) as raised:
                    MachineIdentity.from_dict({**good, "source": source})
                self.assertEqual(
                    str(raised.exception), "Invalid machine identity source"
                )
        missing_source = dict(good)
        del missing_source["source"]
        with self.assertRaisesRegex(ValueError, "^Invalid machine identity source$"):
            MachineIdentity.from_dict(missing_source)
        for key, message in (
            ("version", "Invalid machine identity version"),
            ("identifier", "Invalid machine identity UUID"),
        ):
            for payload in (
                {**good, key: "bad"},
                {k: v for k, v in good.items() if k != key},
            ):
                with self.subTest(key=key, payload=payload):
                    with self.assertRaises(ValueError) as raised:
                        MachineIdentity.from_dict(payload)
                    self.assertEqual(str(raised.exception), message)
