import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
from contextlib import nullcontext

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyPageInfo,
    HierarchyFolderInfo,
)
from ost_visualizer.domain.entities.condition import Condition
import tests.integration.pages.test_set_scale_apply as scale_fixture
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
import pyodbc
import tests.integration.surfaces.test_presentation as surface_fixture


class RefreshScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scale_fixture.SetScaleRepeatedApplyTests.setUpClass()

    def setUp(self):
        self.fixture = scale_fixture.SetScaleRepeatedApplyTests()
        self.fixture.setUp()
        self.service = self.fixture.service
        self.service._save_page_name = SimpleNamespace(execute=lambda *_args: True)
        self.info = HierarchyPageInfo("42", "Page 42")
        self.fixture.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        "test.mdb",
                        orphan_bids=[
                            HierarchyBidInfo("7", pages_without_folder=[self.info])
                        ],
                    )
                ]
            )
        )

    def test_shared_condition_family_reader_does_not_read_takeoffs_or_pages(self):
        for reader_type in (MdbReader, SqlProjectReader):
            with self.subTest(reader=reader_type):
                reader = reader_type.__new__(reader_type)
                connection = MagicMock()
                reader._connection = lambda _path: nullcontext(connection)
                reader._schema = Mock(return_value=object())
                reader._parse_bid_layers_for_bid = Mock(return_value={})
                reader._parse_cdn_types = Mock(return_value={})
                reader._parse_bid_conditions_for_bid = Mock(
                    return_value={"12": Condition("12", "Updated", 0)}
                )
                reader._parse_bid_condition_folders_for_bid = Mock(return_value={})
                reader._parse_bid_takeoffs_for_bid = Mock(
                    side_effect=AssertionError("Takeoff graph read")
                )
                reader._parse_bid_pages_for_bid = Mock(
                    side_effect=AssertionError("Page graph read")
                )
                with patch(
                    "ost_visualizer.infrastructure.mdb.components.bid_data_reader.require_existing_unique_bid_owned_uid_matches"
                ) as validate:
                    conditions, folders = reader.get_condition_family("test.mdb", "7")
                self.assertEqual(list(conditions), ["12"])
                self.assertEqual(folders, {})
                validate.assert_called_once_with(
                    connection.cursor.return_value.__enter__.return_value,
                    "Bids",
                    ("7",),
                )
                reader._parse_bid_takeoffs_for_bid.assert_not_called()
                reader._parse_bid_pages_for_bid.assert_not_called()


class AreaProjectionFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        surface_fixture.SceneControlPresentationTests.setUpClass()

    def test_condition_folder_query_failure_cannot_publish_incomplete_family(self):
        for reader_type in (MdbReader, SqlProjectReader):
            reader = reader_type.__new__(reader_type)
            connection = MagicMock()
            connection.cursor.return_value.__enter__.return_value.execute.side_effect = pyodbc.Error(
                "Read failed"
            )
            reader._connection = lambda _path: nullcontext(connection)
            schema = Mock()
            schema.optional_table_missing.return_value = False
            reader._schema = lambda _conn: schema
            reader._parse_bid_layers_for_bid = Mock(return_value={})
            reader._parse_cdn_types = Mock(return_value={})
            reader._parse_bid_conditions_for_bid = Mock(return_value={})
            for read in (reader.get_condition_family, reader.get_area_family):
                with self.subTest(reader=reader_type, read=read.__name__):
                    with patch(
                        "ost_visualizer.infrastructure.mdb.components.bid_data_reader.require_existing_unique_bid_owned_uid_matches"
                    ):
                        with self.assertRaises(pyodbc.Error):
                            read("bid.mdb", "1")
