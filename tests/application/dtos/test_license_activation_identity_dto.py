import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.license_activation_identity_dto import (
    LICENSE_ACTIVATION_IDENTITY_VERSION,
    LicenseActivationIdentityDto,
    WindowsJoinType,
)


class LicenseActivationIdentityTests(unittest.TestCase):
    def _identity(self, **changes):
        values = dict(
            version="v1",
            windows_account=r"EXAMPLE\Estimator",
            computer_name="ESTIMATOR-PC",
            join_type=WindowsJoinType.DOMAIN,
            join_name="EXAMPLE",
        )
        values.update(changes)
        return LicenseActivationIdentityDto(**values)

    def test_payload_is_one_versioned_activation_identity(self):
        identity = LicenseActivationIdentityDto(
            version=LICENSE_ACTIVATION_IDENTITY_VERSION,
            windows_account=r"EXAMPLE\Estimator",
            computer_name="ESTIMATOR-PC",
            join_type=WindowsJoinType.DOMAIN,
            join_name="EXAMPLE",
        )
        self.assertEqual(
            identity.to_payload(),
            {
                "version": "v1",
                "windows_account": r"EXAMPLE\Estimator",
                "computer_name": "ESTIMATOR-PC",
                "join_type": "domain",
                "join_name": "EXAMPLE",
            },
        )

    def test_all_join_types_produce_detached_string_only_payloads(self):
        for join_type, join_name, wire_value in (
            (WindowsJoinType.DOMAIN, "EXAMPLE", "domain"),
            (WindowsJoinType.WORKGROUP, "WORKGROUP", "workgroup"),
            (WindowsJoinType.UNJOINED, "", "unjoined"),
        ):
            with self.subTest(join_type=join_type):
                identity = self._identity(join_type=join_type, join_name=join_name)
                payload = identity.to_payload()
                self.assertEqual(payload["join_type"], wire_value)
                self.assertEqual(payload["join_name"], join_name)
                self.assertTrue(
                    all(isinstance(value, str) for value in payload.values())
                )
                payload["computer_name"] = "Changed caller copy"
                self.assertEqual(identity.to_payload()["computer_name"], "ESTIMATOR-PC")

    def test_required_values_validate_type_whitespace_controls_and_size_boundaries(
        self,
    ):
        valid = self._identity()
        for field, maximum in (
            ("windows_account", 512),
            ("computer_name", 255),
            ("join_name", 255),
        ):
            with self.subTest(field=field, boundary="valid"):
                self.assertEqual(
                    replace(valid, **{field: "x" * maximum}).to_payload()[field],
                    "x" * maximum,
                )
            for invalid in (
                None,
                False,
                "",
                " leading",
                "trailing ",
                "control\x00name",
                "x" * (maximum + 1),
            ):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        replace(valid, **{field: invalid})
        for changes in ({"version": "v2"}, {"join_type": "domain"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes)

    def test_unjoined_identity_rejects_falsey_nonstring_join_names(self):
        for invalid in (None, False, 0, [], {}, "named-workgroup"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self._identity(join_type=WindowsJoinType.UNJOINED, join_name=invalid)
