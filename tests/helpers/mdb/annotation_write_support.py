"""sqlite stand-ins for annotation writes that keep the production contracts.

``_DimensionWriteOps`` (tests.integration.annotations.dimension_support) reports
every table and column as present and skips the declared required columns, so
schema-presence branches of ``AnnotationOperationsMixin`` never run there.
``RealContractAnnotationOps`` instead combines the mixin with
``RealContractOps`` (the production MdbWriter column contract on sqlite, real
PRAGMA-based schema checks) and rolls the sqlite transaction back when the body
raises, like ``MdbWriter._connection`` does for a top-level transaction.
"""

import logging
import sqlite3

from ost_visualizer.infrastructure.mdb.components.annotation_operations import (
    AnnotationOperationsMixin,
)
from tests.helpers.mdb.real_write_contract import (
    ListParamConnection,
    RealContractOps,
)


class RollbackListParamConnection(ListParamConnection):
    def __exit__(self, exc_type, _exc, _tb):
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        return False


class RealContractAnnotationOps(AnnotationOperationsMixin, RealContractOps):
    """Annotation writes with real schema checks, required columns and rollback."""

    logger = logging.getLogger("test.annotation_write_support")

    def _connection(self, _db_path):
        return RollbackListParamConnection(self._connection_ref)


class ReraisingRealContractAnnotationOps(RealContractAnnotationOps):
    """Variant whose error policy asks the mixin to re-raise (nested transaction)."""

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return True


def annotation_database(*ddl):
    """In-memory sqlite database committed after creating the given tables."""
    conn = sqlite3.connect(":memory:")
    for statement in ddl:
        conn.execute(statement)
    conn.commit()
    return conn
