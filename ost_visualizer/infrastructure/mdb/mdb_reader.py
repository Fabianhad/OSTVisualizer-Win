import logging
from contextlib import contextmanager
from typing import Dict, Generator, List, Optional, Tuple
import pyodbc
from ...domain.entities.cdn_type import CdnType
from ...domain.entities.condition import Condition
from ...domain.entities.hierarchy_data import HierarchyFileEntry
from ...domain.entities.page_info import BidPageInfo
from ...domain.entities.takeoff import Takeoff
from ..parsers.utils.parser import decode_value
from .components.annotation_reader import AnnotationReaderMixin
from .components.bid_data_reader import BidDataReaderMixin
from .components.hierarchy_reader import HierarchyReaderMixin
from .components.settings_reader import SettingsReaderMixin
from .connection_manager import MdbConnectionManager
from .schema_compatibility import MdbSchemaInspector

ParsedHierarchy = HierarchyFileEntry
BidPages = Dict[str, BidPageInfo]
BidConditions = Dict[str, Condition]
BidTakeoffs = List[Takeoff]
BidPageAreaSelections = Dict[str, Optional[str]]
CdnTypes = Dict[str, CdnType]


class MdbReader(
    HierarchyReaderMixin,
    BidDataReaderMixin,
    AnnotationReaderMixin,
    SettingsReaderMixin,
):
    def __init__(
        self,
        conn_manager: Optional[MdbConnectionManager] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._conn_manager = conn_manager or MdbConnectionManager()

    @contextmanager
    def _connection(self, file_path: str) -> Generator[pyodbc.Connection, None, None]:
        with self._conn_manager.connection(file_path, autocommit=True) as conn:
            yield conn

    def close_connection(self, db_path: Optional[str] = None) -> None:
        if db_path:
            self._conn_manager.close_read(db_path)
        else:
            self._conn_manager.close()

    def parse_file(self, file_path: str) -> Tuple[ParsedHierarchy, CdnTypes]:
        with self._connection(file_path) as connection:
            hierarchy = self._parse_hierarchy(connection, file_path)
            cdn_types = self._parse_cdn_types(connection)
            return hierarchy, cdn_types

    def _parse_cdn_types(self, connection) -> CdnTypes:
        cdn_types: CdnTypes = {}
        schema = MdbSchemaInspector(connection, self.logger)
        if schema.optional_table_missing("CdnTypes"):
            return cdn_types
        schema.require_column("CdnTypes", "UID")
        schema.require_column("CdnTypes", "Name")
        with connection.cursor() as cursor:
            cursor.execute("SELECT [UID], [Name] FROM [CdnTypes]")
            for row in cursor.fetchall():
                uid = str(row.UID)
                name = decode_value(row.Name)
                cdn_types[uid] = CdnType(uid=uid, name=name)
            return cdn_types

    def get_cdn_types(self, file_path: str) -> CdnTypes:
        with self._connection(file_path) as connection:
            return self._parse_cdn_types(connection)
