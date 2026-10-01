import unittest
from unittest.mock import Mock
from ost_visualizer.infrastructure.database.master_data_identity import (
    AmbiguousMasterDataIdentityError,
    DuplicateMasterDataUidError,
    MissingMasterDataIdentityError,
    add_master_data_candidate,
    build_master_data_candidate_index,
    master_data_identity_key,
    require_optional_existing_unique_master_data_uid,
    require_unambiguous_incoming_identities,
    require_unique_master_data_uids,
    resolve_master_data_candidate,
)


class RequireMasterDataIdentityTests(unittest.TestCase):
    def test_integer_and_string_forms_are_the_same_authoritative_uid(self):
        with self.assertRaises(DuplicateMasterDataUidError):
            require_unique_master_data_uids([3, "3"], "CdnTypes")
        require_unique_master_data_uids([3, "4"], "CdnTypes")

    def test_optional_empty_value_skips_query_but_boolean_and_float_are_rejected(self):
        cursor = Mock(spec=["execute", "fetchall"])
        for value in (None, "", "  "):
            self.assertIsNone(
                require_optional_existing_unique_master_data_uid(
                    cursor, "CdnTypes", value
                )
            )
        for value in (False, True, 1.0, [7], b"7"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                require_optional_existing_unique_master_data_uid(
                    cursor, "CdnTypes", value
                )
        with self.assertRaises(ValueError):
            require_optional_existing_unique_master_data_uid(
                cursor, "CdnTypes", "not-a-uid"
            )
        self.assertEqual(cursor.mock_calls, [])

    def test_optional_identifier_requires_one_existing_row(self):
        cursor = Mock(spec=["execute", "fetchall"])
        cursor.fetchall.return_value = [(7,)]
        self.assertEqual(
            require_optional_existing_unique_master_data_uid(cursor, "CdnTypes", " 7 "),
            7,
        )
        cursor.execute.assert_called_once_with(
            "SELECT [UID] FROM [CdnTypes] WHERE [UID]=?", 7
        )
        self.assertEqual(
            require_optional_existing_unique_master_data_uid(cursor, "CdnTypes", 7),
            7,
        )
        cursor.fetchall.return_value = []
        with self.assertRaisesRegex(
            MissingMasterDataIdentityError, r"CdnTypes has no row for UID 7"
        ):
            require_optional_existing_unique_master_data_uid(cursor, "CdnTypes", 7)
        cursor.fetchall.return_value = [(7,), (7,)]
        with self.assertRaisesRegex(
            DuplicateMasterDataUidError, r"CdnTypes contains duplicate UID 7"
        ):
            require_optional_existing_unique_master_data_uid(cursor, "CdnTypes", 7)


class MasterDataCandidateTests(unittest.TestCase):
    def test_only_condition_type_name_identity_ignores_case_and_padding(self):
        self.assertEqual(
            master_data_identity_key("CdnTypes", "Name", " Walls "), "walls"
        )
        self.assertEqual(
            master_data_identity_key("Employees", "Name", " Walls "), " Walls "
        )
        self.assertEqual(
            master_data_identity_key("CdnTypes", "Other", " Walls "), " Walls "
        )
        self.assertEqual(master_data_identity_key("CdnTypes", "Name", None), "")
        self.assertEqual(master_data_identity_key("Employees", "Name", None), "")

    def test_weak_duplicate_names_are_retained_and_rejected_at_resolution(self):
        index = build_master_data_candidate_index(
            [(1, "Walls"), (2, " walls ")], "CdnTypes", "Name"
        )
        self.assertEqual(index, {"walls": ["1", "2"]})
        with self.assertRaisesRegex(
            AmbiguousMasterDataIdentityError,
            r"condition type: matching UIDs 1, 2",
        ):
            resolve_master_data_candidate(index, "walls", "condition type")
        self.assertIsNone(
            resolve_master_data_candidate(index, "missing", "condition type")
        )

    def test_candidate_index_rejects_duplicate_authoritative_uids(self):
        with self.assertRaises(DuplicateMasterDataUidError):
            build_master_data_candidate_index(
                [(1, "Walls"), ("1", "Floors")], "CdnTypes", "Name"
            )
        index = build_master_data_candidate_index(
            [(1, "Walls"), (None, "Floors")], "CdnTypes", "Name"
        )
        self.assertEqual(index, {"walls": ["1"], "floors": [""]})

    def test_repeated_candidate_does_not_create_false_ambiguity(self):
        index = {}
        add_master_data_candidate(index, "wall", "1")
        add_master_data_candidate(index, "wall", "1")
        self.assertEqual(index, {"wall": ["1"]})
        self.assertEqual(
            resolve_master_data_candidate(index, "wall", "condition type"), "1"
        )
        add_master_data_candidate(index, "wall", "2")
        with self.assertRaises(AmbiguousMasterDataIdentityError):
            resolve_master_data_candidate(index, "wall", "condition type")

    def test_incoming_uidless_rows_have_distinct_source_identities(self):
        rows = [{"Name": "Wall"}, {"Name": "Wall"}]
        with self.assertRaises(AmbiguousMasterDataIdentityError):
            require_unambiguous_incoming_identities(
                rows, lambda row: row["Name"], "type"
            )
        require_unambiguous_incoming_identities(
            [{"Name": ""}, {"Name": ""}],
            lambda row: row["Name"],
            "type",
            ignore_empty=True,
        )
        with self.assertRaises(AmbiguousMasterDataIdentityError):
            require_unambiguous_incoming_identities(
                [{"Name": ""}, {"Name": ""}], lambda row: row["Name"], "type"
            )

    def test_incoming_rows_with_authoritative_uids_are_distinguished_by_uid(self):
        def key(row):
            return row["Name"]

        with self.assertRaises(AmbiguousMasterDataIdentityError):
            require_unambiguous_incoming_identities(
                [{"UID": 1, "Name": "Wall"}, {"UID": 2, "Name": "Wall"}], key, "type"
            )
        require_unambiguous_incoming_identities(
            [{"UID": 1, "Name": "Wall"}, {"UID": 2, "Name": "Floor"}], key, "type"
        )
        require_unambiguous_incoming_identities(
            [{"UID": 1, "Name": "Wall"}, {"UID": 1, "Name": "Wall"}], key, "type"
        )
