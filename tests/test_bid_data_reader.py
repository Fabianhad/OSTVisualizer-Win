import logging
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ost_visualizer.domain.entities.identity_refs import BidRef
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
        return None

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
            self.rows = [("page-1",), ("page-2",)]
        elif self.query_count == 2:
            self.rows = [("page-1",)]
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


class BidDataReaderTests(unittest.TestCase):
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
            delete_pages=Mock(side_effect=AssertionError("delete must not run"))
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
            get_estimator_uids_in_use=lambda _file_path: set(),
            get_pages_with_takeoffs=lambda _file_path, _bid_uid: set(),
            get_pages_with_delete_content=lambda _file_path, _bid_uid: None,
        )
        handler = CoverSheetHandler(
            window=object(),
            icon_provider=object(),
            project_data_service=object(),
            project_read_service=read_service,
            project_write_service=object(),
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
