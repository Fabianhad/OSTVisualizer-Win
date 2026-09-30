import logging
import sqlite3
import unittest
from collections import namedtuple
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


class _SelectiveSchema:
    def __init__(self, columns_by_table):
        self._columns_by_table = {
            table: frozenset(columns) for table, columns in columns_by_table.items()
        }
        self.optional_table_calls = []
        self.column_exists_calls = []
        self.require_column_calls = []

    def optional_table_missing(self, table):
        self.optional_table_calls.append(table)
        return table not in self._columns_by_table

    def column_exists(self, table, column):
        self.column_exists_calls.append((table, column))
        return column in self._columns_by_table.get(table, ())

    def require_column(self, table, column):
        self.require_column_calls.append((table, column))
        if column not in self._columns_by_table.get(table, ()):
            raise AssertionError(f"Missing required column {table}.{column}")

    def get_columns(self, table):
        return self._columns_by_table.get(table, ())


class _LimitedReadCursor:
    def __init__(self, owner):
        self._owner = owner
        self._cursor = owner.connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self._cursor.close()
        return False

    @property
    def description(self):
        return self._cursor.description

    def execute(self, query, *params):
        if len(params) > self._owner.parameter_limit:
            raise AssertionError(
                f"Query used {len(params)} parameters; "
                f"limit is {self._owner.parameter_limit}"
            )
        self._owner.queries.append((query, len(params)))
        self._cursor.execute(query, params)
        return self

    def fetchall(self):
        rows = self._cursor.fetchall()
        if self._cursor.description is None:
            return rows
        columns = [column[0] for column in self._cursor.description]
        row_type = namedtuple("LimitedReadRow", columns, rename=True)
        return [row_type(*row) for row in rows]


class _LimitedReadConnection:
    def __init__(self, connection, schema, parameter_limit=255):
        self.connection = connection
        self.schema = schema
        self.parameter_limit = parameter_limit
        self.queries = []

    def cursor(self):
        return _LimitedReadCursor(self)


class _StrictReadPolicyReader(BidDataReaderMixin):
    @staticmethod
    def _schema(connection):
        return connection.schema

    @staticmethod
    def _record_caught_read_error(_exc, _file_path=None):
        return True


class _TolerantReadPolicyReader(_StrictReadPolicyReader):
    @staticmethod
    def _record_caught_read_error(_exc, _file_path=None):
        return False


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
        def _parse_page_area_selections_for_bid(_connection, _bid_uid, _pages, _schema):
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
