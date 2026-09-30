import sqlite3
import tempfile
import unittest
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationRequest,
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.services.annotation_write_service import (
    AnnotationWriteService,
)
from ost_visualizer.application.use_cases.project.delete_annotations_use_case import (
    DeleteAnnotationsUseCase,
)
from ost_visualizer.application.use_cases.project.insert_annotations_use_case import (
    InsertAnnotationsUseCase,
)
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    LoadBidUseCase,
    PreparedBidLoad,
)
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    MissingBidOwnedUidError,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.services.annotation_write_coordinator import (
    AnnotationWriteCoordinator,
)
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from tests.presentation.windows.detached_annotation_support import FakeDetachedPlanView
from tests.presentation.windows.detached_access_support import _full_plan_surface_access
from tests.helpers.mdb.operations import (
    _SqliteAnnotationOps,
    _SqliteConnectionWrapper,
    _SqliteDuplicateOps,
    _SqliteSchema,
)
from tests.presentation.handlers.test_plan_view_action_handler import (
    FakePlanView,
    FakeUndoService,
    FakeWriteService,
)


class _AnnotationOps(BidDataReaderMixin, _SqliteAnnotationOps):
    @staticmethod
    def _record_caught_mutation_error(_exc):
        return True


class _TransactionConnection(_SqliteConnectionWrapper):
    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()


class _Connections:
    def __init__(self, connection):
        self.connection_ref = connection
        self.committed_reads = []

    @contextmanager
    def connection(self, _path, *, autocommit):
        assert not autocommit
        yield _TransactionConnection(self.connection_ref)

    def use_committed_writer_for_reads(self, path):
        self.committed_reads.append(path)


class _RoutedAnnotationWriter(DatabaseProjectWriter):
    def _schema(self, _connection):
        return _SqliteSchema(self._conn_manager.connection_ref)

    _execute_insert_values = _SqliteDuplicateOps._execute_insert_values
