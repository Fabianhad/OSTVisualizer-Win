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


class LicenseActivationIdentityValidationTests(unittest.TestCase):
    def _identity(self, **changes):
        return LicenseActivationIdentityTests._identity(self, **changes)

    def failure(self, **changes):
        with self.assertRaises(ValueError) as raised:
            self._identity(**changes)
        return str(raised.exception)

    def test_constants_and_immutability(self):
        from dataclasses import FrozenInstanceError
        from ost_visualizer.application.dtos import (
            license_activation_identity_dto as module,
        )

        self.assertEqual(module.LICENSE_ACTIVATION_IDENTITY_VERSION, "v1")
        self.assertEqual(
            module.LICENSE_ACTIVATION_IDENTITY_PAYLOAD_FIELD, "activation_identity"
        )
        self.assertEqual(
            [member.value for member in WindowsJoinType],
            ["unjoined", "workgroup", "domain"],
        )
        with self.assertRaises(FrozenInstanceError):
            self._identity().computer_name = "x"

    def test_each_invalid_part_reports_its_own_message(self):
        self.assertEqual(
            self.failure(version="v2"), "Invalid license activation identity version"
        )
        self.assertEqual(
            self.failure(version=None), "Invalid license activation identity version"
        )
        self.assertEqual(self.failure(windows_account=""), "Invalid Windows account")
        self.assertEqual(self.failure(computer_name=""), "Invalid computer name")
        self.assertEqual(self.failure(join_type="domain"), "Invalid Windows join type")
        self.assertEqual(self.failure(join_name=""), "Invalid Windows join name")
        self.assertEqual(
            self.failure(join_type=WindowsJoinType.UNJOINED, join_name="X"),
            "An unjoined computer cannot have a join name",
        )
        self.assertEqual(
            self.failure(join_type=WindowsJoinType.UNJOINED, join_name=None),
            "An unjoined computer cannot have a join name",
        )

    def test_values_must_be_clean_text_within_their_length_limits(self):
        limits = (
            ("windows_account", 512, "Windows account"),
            ("computer_name", 255, "computer name"),
            ("join_name", 255, "Windows join name"),
        )
        for field, maximum, label in limits:
            with self.subTest(field=field):
                self._identity(**{field: "a" * maximum})
                self.assertEqual(
                    self.failure(**{field: "a" * (maximum + 1)}), f"Invalid {label}"
                )
                for bad in (
                    " lead",
                    "trail ",
                    "a\x00b",
                    "a\x1fb",
                    "a\tb",
                    "a\nb",
                    None,
                    5,
                    b"x",
                ):
                    self.assertEqual(
                        self.failure(**{field: bad}), f"Invalid {label}", repr(bad)
                    )
                self._identity(**{field: "a b"})
                self._identity(**{field: "a\x7fb"})


class LicenseActivationIdentityStrictnessTests(unittest.TestCase):
    def _identity(self, **changes):
        return LicenseActivationIdentityTests._identity(self, **changes)

    def test_unjoined_join_name_must_be_a_real_empty_string_not_a_lookalike(self):
        class BlankLookalike:
            __hash__ = None

            def __eq__(self, other):
                return other == ""

            def __ne__(self, other):
                return not self.__eq__(other)

        lookalike = BlankLookalike()
        self.assertTrue(lookalike == "")
        self.assertFalse(lookalike != "")
        with self.assertRaisesRegex(
            ValueError, "^An unjoined computer cannot have a join name$"
        ):
            self._identity(join_type=WindowsJoinType.UNJOINED, join_name=lookalike)
        self.assertEqual(
            self._identity(join_type=WindowsJoinType.UNJOINED, join_name="").join_name,
            "",
        )

    def test_payload_values_are_plain_strings_not_str_subclass_members(self):
        payload = self._identity().to_payload()
        self.assertEqual(
            list(payload),
            ["version", "windows_account", "computer_name", "join_type", "join_name"],
        )
        for key, value in payload.items():
            with self.subTest(key=key):
                self.assertIs(type(value), str)

    def test_the_error_type_is_a_runtime_error_that_carries_its_message(self):
        from ost_visualizer.application.dtos.license_activation_identity_dto import (
            LicenseActivationIdentityError,
        )

        self.assertTrue(issubclass(LicenseActivationIdentityError, RuntimeError))
        self.assertEqual(
            str(LicenseActivationIdentityError("no identity available")),
            "no identity available",
        )
        with self.assertRaises(RuntimeError):
            raise LicenseActivationIdentityError("x")
