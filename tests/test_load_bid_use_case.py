import unittest
from types import SimpleNamespace
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    LoadBidUseCase,
    PreparedBidLoad,
)
from ost_visualizer.application.dtos.user_workspace_state_dtos import (
    UserBidWorkspaceState,
    UserPageViewState,
)
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page


class LoadBidUseCaseTests(unittest.TestCase):
    @staticmethod
    def _apply_with_workspace_state(workspace_state):
        loaded_pages = {}
        model = SimpleNamespace(
            find_bid_info=lambda _bid_ref: None,
            set_pages=lambda pages: loaded_pages.update(pages),
            set_annotations=lambda _annotations: None,
            deselect_pages=lambda: None,
        )
        bid_data = BidLoadResult(
            pages={
                "p1": Page(
                    uid="p1",
                    name="Page 1",
                    zoom_fac=1.25,
                    current_x=1.0,
                    current_y=2.0,
                ),
                "p2": Page(uid="p2", name="Page 2"),
            },
            selected_page_uid="p1",
        )
        use_case = LoadBidUseCase(
            model,
            SimpleNamespace(
                replace_cover_sheet_data=lambda *_args: None,
                replace_page_delete_content_uids=lambda *_args: None,
            ),
            SimpleNamespace(apply_bid_load=lambda _database_id: None),
            SimpleNamespace(load_bid=lambda *_args: None),
            SimpleNamespace(uses_sql_workspace=lambda *_args: False),
        )
        use_case.apply_prepared(
            BidRef("sql-database", "42"),
            PreparedBidLoad(bid_data, workspace_state),
        )
        return model, loaded_pages

    def test_loads_concurrency_tokens_before_bid_state(self):
        calls = []

        class FileManager:
            def prepare_bid_load(self, bid_uid, file_path):
                calls.append(("state", file_path, bid_uid))
                return BidLoadResult()

            def apply_bid_load(self, file_path):
                calls.append(("apply", file_path))

        class ConcurrencyTokens:
            def load_bid(self, file_path, bid_uid):
                calls.append(("tokens", file_path, bid_uid))

        model = SimpleNamespace(
            find_bid_info=lambda _bid_ref: None,
            set_pages=lambda _pages: None,
            set_annotations=lambda _annotations: None,
            deselect_pages=lambda: None,
        )
        project_data = SimpleNamespace(
            replace_cover_sheet_data=lambda *_args: None,
            replace_page_delete_content_uids=lambda *_args: None,
        )
        use_case = LoadBidUseCase(
            model,
            project_data,
            FileManager(),
            ConcurrencyTokens(),
            SimpleNamespace(uses_sql_workspace=lambda *_args: False),
        )
        self.assertTrue(use_case.execute(BidRef("database-id", "42")))
        self.assertEqual(
            calls,
            [
                ("tokens", "database-id", "42"),
                ("state", "database-id", "42"),
                ("apply", "database-id"),
            ],
        )

    def test_sql_execute_rejects_synchronous_navigation_read(self):
        use_case = LoadBidUseCase(
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(uses_sql_workspace=lambda _database_id: True),
        )
        with self.assertRaisesRegex(RuntimeError, "background navigation service"):
            use_case.execute(BidRef("sql-database", "42"))

    def test_projects_sql_cover_sheet_snapshots_with_prepared_bid_state(self):
        calls = []
        cover_sheet = object()

        class FileManager:
            def prepare_bid_load(self, bid_uid, file_path):
                return BidLoadResult(
                    cover_sheet_data=cover_sheet,
                    page_delete_content_uids=frozenset({"page-1"}),
                )

            def apply_bid_load(self, file_path):
                calls.append(("apply", file_path))

        class ProjectData:
            def replace_cover_sheet_data(self, database_id, bid_uid, value):
                calls.append(("cover", database_id, bid_uid, value))

            def replace_page_delete_content_uids(self, database_id, bid_uid, page_uids):
                calls.append(("delete-content", database_id, bid_uid, page_uids))

        model = SimpleNamespace(
            find_bid_info=lambda _bid_ref: None,
            set_pages=lambda _pages: None,
            set_annotations=lambda _annotations: None,
            deselect_pages=lambda: None,
        )
        use_case = LoadBidUseCase(
            model,
            ProjectData(),
            FileManager(),
            SimpleNamespace(load_bid=lambda *_args: None),
            SimpleNamespace(uses_sql_workspace=lambda *_args: False),
        )
        self.assertTrue(use_case.execute(BidRef("sql-database", "42")))
        self.assertEqual(
            calls,
            [
                ("apply", "sql-database"),
                ("cover", "sql-database", "42", cover_sheet),
                (
                    "delete-content",
                    "sql-database",
                    "42",
                    frozenset({"page-1"}),
                ),
            ],
        )

    def test_user_selected_page_and_precise_view_override_shared_sql_state(self):
        workspace_state = UserBidWorkspaceState(
            active_page_uid="p2",
            page_views={
                "p2": UserPageViewState(
                    zoom_fac=3.125,
                    current_x=10.1250000001,
                    current_y=20.8750000001,
                )
            },
        )
        model, pages = self._apply_with_workspace_state(workspace_state)
        self.assertEqual(model.last_selected_page_uid, "p2")
        self.assertEqual(pages["p2"].zoom_fac, 3.125)
        self.assertEqual(pages["p2"].current_x, 10.1250000001)
        self.assertEqual(pages["p2"].current_y, 20.8750000001)

    def test_missing_user_selected_page_does_not_restore_shared_page(self):
        model, pages = self._apply_with_workspace_state(
            UserBidWorkspaceState(active_page_uid="deleted-page")
        )
        self.assertIsNone(model.last_selected_page_uid)
        self.assertEqual(pages["p1"].zoom_fac, 0.0)
        self.assertEqual(pages["p1"].current_x, 0.0)
        self.assertEqual(pages["p1"].current_y, 0.0)

    def test_sql_without_workspace_row_does_not_use_shared_page_view_columns(self):
        model, pages = self._apply_with_workspace_state(UserBidWorkspaceState())
        self.assertIsNone(model.last_selected_page_uid)
        self.assertEqual(
            (pages["p1"].zoom_fac, pages["p1"].current_x, pages["p1"].current_y),
            (0.0, 0.0, 0.0),
        )

    def test_users_restore_independent_active_pages(self):
        first, _pages = self._apply_with_workspace_state(
            UserBidWorkspaceState(active_page_uid="p1")
        )
        second, _pages = self._apply_with_workspace_state(
            UserBidWorkspaceState(active_page_uid="p2")
        )
        self.assertEqual(first.last_selected_page_uid, "p1")
        self.assertEqual(second.last_selected_page_uid, "p2")

    def test_mdb_without_client_state_preserves_database_page_and_view(self):
        model, pages = self._apply_with_workspace_state(None)
        self.assertEqual(model.last_selected_page_uid, "p1")
        self.assertEqual(pages["p1"].zoom_fac, 1.25)
        self.assertEqual(pages["p1"].current_x, 1.0)
        self.assertEqual(pages["p1"].current_y, 2.0)


if __name__ == "__main__":
    unittest.main()
