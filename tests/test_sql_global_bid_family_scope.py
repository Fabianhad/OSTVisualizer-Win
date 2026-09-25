import unittest
from unittest.mock import MagicMock, Mock
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ConcurrencyToken,
    ResourceRef,
)
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    LoadBidUseCase,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyFileEntry,
    HierarchyFolderInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page_info import BidPageInfo
from ost_visualizer.infrastructure.sql.remote_change_reader import SqlRemoteChangeReader
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _RecordedMutation
from tests import test_remote_batch_navigation_handoff
from tests.test_sql_collaboration_phase4 import _batch, _change

FAMILIES = (
    "pages_collection",
    "areas_collection",
    "takeoffs_collection",
    "annotations_collection",
    "layers_collection",
    "cover_sheet",
)


class GlobalBidFamilyScopeTests(unittest.TestCase):
    def make_fixture(self, resource_type, global_scope, empty=False):
        context = (
            test_remote_batch_navigation_handoff.RemoteBatchNavigationHandoffTests()
        )
        context.setUp()
        self.addCleanup(context.doCleanups)
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
            (8,),
            (9,),
        ]
        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._reader = Mock()
        source = reader._reader
        source._parse_bid_conditions_for_bid.return_value = {}
        source._parse_bid_condition_folders_for_bid.return_value = {}
        source._parse_bid_areas_for_bid.return_value = {}
        source._parse_bid_takeoffs_for_bid.return_value = ([], {})
        source._parse_bid_annotations_for_bid.return_value = []
        source._parse_page_area_selections_for_bid.return_value = {}
        source._parse_bid_layers_for_sidebar.return_value = []
        source._parse_pages_with_delete_content.return_value = set()
        source._parse_cover_sheet_data.side_effect = lambda _c, bid: {
            "bid": bid,
            "name": "New",
        }
        pages = context.fixture.read().bid_pages
        pages["1"].folder_uid = "10"
        pages["1"].sequence = 70
        pages = dict(
            sorted(
                pages.items(),
                key=lambda item: (item[1].sequence, item[1].name, int(item[0])),
            )
        )
        source._parse_bid_pages_for_bid.side_effect = lambda _connection, bid, *_args: (
            {}
            if empty
            else (
                pages
                if bid == "8"
                else {"901": BidPageInfo("B Page", sequence=2, folder_uid="90")}
            )
        )
        bids = range(8, 459) if global_scope else (8, 9)
        # Bid-qualified collections are themselves valid coalescer inputs.
        records = [
            _RecordedMutation(
                ResourceRef(resource_type, str(bid), bid), ChangeOperation.BULK_REFRESH
            )
            for bid in bids
        ]
        coalesced = SqlProjectWriter._coalesce_records(records)
        self.assertEqual(
            [r.resource for r in coalesced],
            (
                [ResourceRef(resource_type, "database")]
                if global_scope
                else [ResourceRef(resource_type, str(bid), bid) for bid in bids]
            ),
        )
        batch = _batch(
            "database",
            "epoch",
            0,
            4,
            tuple(
                _change("database", r.resource, 4, operation=r.operation)
                for r in coalesced
            ),
        )
        hydrated = reader.hydrate_connection(batch, connection)
        return context, reader, connection, hydrated

    def check_projection(self, context, hydrated):
        runtime = context.runtime
        context.coordinator._on_remote_batch(
            (
                "database",
                runtime.generation,
                runtime.session_generation,
                hydrated,
                context.fixture.model.current_bid,
            )
        )
        self.assertEqual(runtime.acknowledged_version, 4)
        self.assertFalse(runtime.recovery_requested)
        self.assertTrue(runtime.healthy)

    def check_scope(self, resource_type, hydrated):
        self.assertEqual(
            set(
                hydrated.areas_by_bid
                if resource_type == "areas_collection"
                else (
                    hydrated.cover_sheet_by_bid
                    if resource_type == "cover_sheet"
                    else hydrated.bid_data_by_bid
                )
            ),
            {8, 9},
        )
        if resource_type == "takeoffs_collection":
            self.assertEqual(set(hydrated.conditions_by_bid), {8, 9})
            self.assertEqual(set(hydrated.condition_folders_by_bid), {8, 9})
        if resource_type in {"pages_collection", "cover_sheet"}:
            self.assertEqual(set(hydrated.page_delete_content_uids_by_bid), {8, 9})

    def test_scoped_families_preserve_bid_ownership(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                context, reader, connection, hydrated = self.make_fixture(family, False)
                self.check_scope(family, hydrated)
                self.check_projection(context, hydrated)
                connection.cursor.assert_not_called()

    def test_global_families_hydrate_before_acknowledgement(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                context, reader, connection, hydrated = self.make_fixture(family, True)
                self.check_scope(family, hydrated)
                self.check_projection(context, hydrated)
                connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
                    "SELECT [UID] FROM [Bids] ORDER BY [UID]"
                )
                if family == "cover_sheet":
                    self.assertEqual(
                        context.data.get_cover_sheet_snapshot("database", "8"),
                        {"bid": "8", "name": "New"},
                    )
                    self.assertEqual(
                        context.data.get_cover_sheet_snapshot("database", "9"),
                        {"bid": "9", "name": "New"},
                    )
                if family == "pages_collection":
                    pages = hydrated.bid_data_by_bid[8].pages
                    self.assertEqual(
                        [p.uid for p in context.data.get_all_pages()], list(pages)
                    )
                    self.assertEqual(
                        context.fixture.model.get_page("1").folder_uid, "10"
                    )
                    self.assertIs(context.fixture.model.get_page("1"), pages["1"])

    def test_global_empty_collections_are_present_and_clear_active_state(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                context, reader, connection, hydrated = self.make_fixture(
                    family, True, empty=True
                )
                self.check_scope(family, hydrated)
                self.check_projection(context, hydrated)
                if family == "pages_collection":
                    self.assertEqual(context.data.get_all_pages(), [])

    def test_global_pages_then_inactive_navigation_preserves_owner_order_and_tokens(
        self,
    ):
        context, reader, connection, hydrated = self.make_fixture(
            "pages_collection", True
        )
        bid = context.fixture.model.current_bid
        self.check_projection(context, hydrated)
        self.assertIs(context.fixture.model.current_bid, bid)
        self.assertEqual(
            [p.sequence for p in hydrated.bid_data_by_bid[8].pages.values()],
            sorted(p.sequence for p in hydrated.bid_data_by_bid[8].pages.values()),
        )
        context.data.replace_database_hierarchy(
            HierarchyFileEntry(
                file_path="database",
                orphan_bids=[
                    context.fixture.info,
                    HierarchyBidInfo(
                        uid="9",
                        name="B",
                        folders={"90": HierarchyFolderInfo("B Folder")},
                    ),
                ],
            ),
            {},
        )
        resource = ResourceRef("page", "901", 9)
        token = ConcurrencyToken((5).to_bytes(8, "big"))
        context.tokens._reader.resources[resource] = token
        files = Mock()
        # A fresh independent navigation read, rather than retaining inactive
        # hydration objects or inferring ownership from the current active Bid.
        fresh = reader.hydrate_connection(hydrated.batch, connection).bid_data_by_bid[9]
        files.prepare_bid_load.return_value = fresh
        workspace = Mock()
        workspace.uses_sql_workspace.return_value = False
        loader = LoadBidUseCase(
            context.fixture.model, context.data, files, context.tokens, workspace
        )
        ref = BidRef("database", "9")
        prepared = loader.prepare(ref)
        self.assertTrue(loader.apply_prepared(ref, prepared))
        page = context.fixture.model.get_page("901")
        self.assertIs(page, fresh.pages["901"])
        self.assertEqual(page.folder_uid, "90")
        self.assertEqual(page.sequence, 2)
        self.assertEqual([p.uid for p in context.data.get_all_pages()], ["901"])
        self.assertIsNone(context.fixture.model.get_page("1"))
        self.assertEqual(
            context.tokens.expected_versions("database", (resource,))[0].expected, token
        )


if __name__ == "__main__":
    unittest.main()
