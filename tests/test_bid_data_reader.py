import logging
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.handlers.cover_sheet_handler import CoverSheetHandler


class _Schema:
    @staticmethod
    def optional_table_missing(_table):
        return False

    @staticmethod
    def require_column(_table, _column):
        pass

    @staticmethod
    def column_exists(_table, _column):
        return True


class _FailingContentConnection:
    def __init__(self):
        self.query_count = 0
        self.rows = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def execute(self, query, *_params):
        self.query_count += 1
        if self.query_count == 1:
            self.rows = [(1,), (2,)]
        elif self.query_count == 2:
            self.rows = [(1,)]
        else:
            raise RuntimeError(f"content scan failed: {query}")
        return self

    def fetchall(self):
        return list(self.rows)


class _Reader(BidDataReaderMixin):
    def __init__(self):
        self.connection = _FailingContentConnection()
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def _connection(self, _file_path):
        yield self.connection

    @staticmethod
    def _schema(_connection):
        return _Schema()

    @staticmethod
    def _record_caught_read_error(_exc, _file_path=None):
        return False


def _owner_validation_reader(takeoffs):
    class OwnerValidationReader(BidDataReaderMixin):
        @contextmanager
        def _connection(self, _file_path):
            yield object()

        @staticmethod
        def _schema(_connection):
            return _Schema()

        @staticmethod
        def _parse_cdn_types(_connection):
            return {}

        @staticmethod
        def _parse_bid_layers_for_bid(_connection, _bid_uid):
            return {}

        @staticmethod
        def _parse_bid_pages_for_bid(_connection, _bid_uid, _layers, _schema):
            return {"3": SimpleNamespace(uid="3")}

        @staticmethod
        def _parse_bid_areas_for_bid(_connection, _bid_uid, _schema):
            return {}

        @staticmethod
        def _parse_page_area_selections_for_bid(_connection, _pages, _schema):
            return {}

        @staticmethod
        def _parse_bid_conditions_for_bid(
            _connection, _bid_uid, _layers, _cdn_types, _schema
        ):
            return {"5": SimpleNamespace(uid="5")}

        @staticmethod
        def _parse_bid_takeoffs_for_bid(_connection, _bid_uid, _schema):
            return list(takeoffs), {}

        @staticmethod
        def _parse_bid_annotations_for_bid(_connection, _bid_uid, _layers, _schema):
            return []

        @staticmethod
        def _parse_bid_condition_folders_for_bid(_connection, _bid_uid, _schema):
            return {}

        @staticmethod
        def _parse_bid_selected_page(_connection, _bid_uid):
            return None

        @staticmethod
        def _hydrates_bid_navigation_snapshots():
            return False

    return OwnerValidationReader()


class BidDataReaderTests(unittest.TestCase):
    def test_bid_load_rejects_takeoff_with_missing_required_owner(self):
        class OwnerValidationReader(BidDataReaderMixin):
            @contextmanager
            def _connection(self, _file_path):
                yield object()

            @staticmethod
            def _schema(_connection):
                return _Schema()

            @staticmethod
            def _parse_cdn_types(_connection):
                return {}

            @staticmethod
            def _parse_bid_layers_for_bid(_connection, _bid_uid):
                return {}

            @staticmethod
            def _parse_bid_pages_for_bid(_connection, _bid_uid, _layers, _schema):
                return {"3": SimpleNamespace(uid="3")}

            @staticmethod
            def _parse_bid_areas_for_bid(_connection, _bid_uid, _schema):
                return {}

            @staticmethod
            def _parse_page_area_selections_for_bid(_connection, _pages, _schema):
                return {}

            @staticmethod
            def _parse_bid_conditions_for_bid(
                _connection, _bid_uid, _layers, _cdn_types, _schema
            ):
                return {"5": SimpleNamespace(uid="5")}

            @staticmethod
            def _parse_bid_takeoffs_for_bid(_connection, _bid_uid, _schema):
                return (
                    [
                        Takeoff(
                            uid="7",
                            condition_uid="99",
                            page_uid="3",
                            position=[0.0, 0.0, 1.0, 1.0],
                        )
                    ],
                    {},
                )

            @staticmethod
            def _parse_bid_annotations_for_bid(_connection, _bid_uid, _layers, _schema):
                return []

            @staticmethod
            def _parse_bid_condition_folders_for_bid(_connection, _bid_uid, _schema):
                return {}

            @staticmethod
            def _parse_bid_selected_page(_connection, _bid_uid):
                return None

            @staticmethod
            def _hydrates_bid_navigation_snapshots():
                return False

        with self.assertRaisesRegex(
            RuntimeError,
            "BidTakeoffs.UID=7 references missing BidConditions.UID=99",
        ):
            OwnerValidationReader().get_bid_data("malformed.mdb", "1")

    def test_bid_load_rejects_takeoff_with_missing_parent(self):
        takeoff = Takeoff(
            uid="7",
            condition_uid="5",
            page_uid="3",
            parent_uid="99",
            position=[0.0, 0.0, 1.0, 1.0],
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "BidTakeoffs.UID=7 references missing BidTakeoffs.UID=99",
        ):
            _owner_validation_reader([takeoff]).get_bid_data("malformed.mdb", "1")

    def test_bid_load_rejects_self_parented_takeoff(self):
        takeoff = Takeoff(
            uid="7",
            condition_uid="5",
            page_uid="3",
            parent_uid="7",
            position=[0.0, 0.0, 1.0, 1.0],
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "BidTakeoffs.UID=7 participates in a ParentUID cycle",
        ):
            _owner_validation_reader([takeoff]).get_bid_data("malformed.mdb", "1")

    def test_bid_load_rejects_multi_takeoff_parent_cycle(self):
        takeoffs = [
            Takeoff(
                uid="7",
                condition_uid="5",
                page_uid="3",
                parent_uid="8",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
            Takeoff(
                uid="8",
                condition_uid="5",
                page_uid="3",
                parent_uid="9",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
            Takeoff(
                uid="9",
                condition_uid="5",
                page_uid="3",
                parent_uid="7",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
        ]
        with self.assertRaisesRegex(RuntimeError, "participates in a ParentUID cycle"):
            _owner_validation_reader(takeoffs).get_bid_data("malformed.mdb", "1")

    def test_bid_load_accepts_valid_multi_level_takeoff_parent_chain(self):
        takeoffs = [
            Takeoff(
                uid="7",
                condition_uid="5",
                page_uid="3",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
            Takeoff(
                uid="8",
                condition_uid="5",
                page_uid="3",
                parent_uid="7",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
            Takeoff(
                uid="9",
                condition_uid="5",
                page_uid="3",
                parent_uid="8",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
        ]
        loaded = _owner_validation_reader(takeoffs).get_bid_data("valid.mdb", "1")
        self.assertEqual([takeoff.uid for takeoff in loaded[1]], ["7", "8", "9"])

    def test_delete_content_scan_discards_partial_results_after_failure(self):
        reader = _Reader()
        self.assertIsNone(reader.get_pages_with_delete_content("project.mdb", "bid-1"))
        self.assertGreaterEqual(reader.connection.query_count, 3)

    def test_current_page_delete_stops_when_content_verification_is_unavailable(self):
        critical = Mock()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.can_delete_current_page = lambda: True
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: BidRef("project.mdb", "bid-1"),
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda _uid: object(),
        )
        coordinator._project_read_service = SimpleNamespace(
            get_pages_with_delete_content=lambda _file_path, _bid_uid: None
        )
        coordinator._stage_selection_after_page_delete = Mock()
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False,
            delete_pages=Mock(side_effect=AssertionError("delete must not run")),
        )
        coordinator.main_window = object()
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "show_critical",
            critical,
        ):
            coordinator.delete_current_page()
        critical.assert_called_once()
        coordinator._stage_selection_after_page_delete.assert_not_called()
        coordinator._project_write_service.delete_pages.assert_not_called()

    def test_cover_sheet_stops_when_content_verification_is_unavailable(self):
        read_service = SimpleNamespace(
            get_cover_sheet_data=lambda _file_path, _bid_uid: object(),
            get_employee_uids_in_use=lambda _file_path: set(),
            get_pages_with_takeoffs=lambda _file_path, _bid_uid: set(),
            get_pages_with_delete_content=lambda _file_path, _bid_uid: None,
        )
        handler = CoverSheetHandler(
            window=object(),
            icon_provider=object(),
            project_data_service=object(),
            project_read_service=read_service,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _file_path: False
            ),
            infrastructure_provider=object(),
            event_bus=object(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("project.mdb", "bid-1")
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=object(),
            workspace_state_model=object(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
        ) as critical, patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.CoverSheetDialog",
            side_effect=AssertionError("dialog must not open"),
        ):
            handler.open_cover_sheet()
        critical.assert_called_once()


if __name__ == "__main__":
    unittest.main()
