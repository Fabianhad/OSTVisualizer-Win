import inspect
import os
import unittest
from typing import TypeVar, get_args, get_origin, get_type_hints

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.interfaces.i_annotation_caption_resolver import (
    IAnnotationCaptionResolver,
)
from ost_visualizer.application.interfaces.i_color_service import IColorService
from ost_visualizer.application.interfaces.i_collaboration_store import (
    ICollaborationStore,
)
from ost_visualizer.application.interfaces.i_coordinate_transformer import (
    ICoordinateTransformer,
)
from ost_visualizer.application.interfaces.i_database_catalog import IDatabaseCatalog
from ost_visualizer.application.interfaces.i_database_mutation_executor import (
    IDatabaseMutationExecutor,
)
from ost_visualizer.application.interfaces.i_database_session_registry import (
    IDatabaseSessionRegistry,
)
from ost_visualizer.application.interfaces.i_entity_version_reader import (
    IEntityVersionReader,
)
from ost_visualizer.application.interfaces.i_html_renderer import IHtmlRenderer
from ost_visualizer.application.interfaces.i_infrastructure_service_provider import (
    IInfrastructureServiceProvider,
)
from ost_visualizer.application.interfaces.i_mdb_reader import IMdbReader
from ost_visualizer.application.interfaces.i_mdb_writer import IMdbWriter
from ost_visualizer.application.interfaces.i_page_load_strategy_service import (
    IPageLoadStrategyService,
)
from ost_visualizer.application.interfaces.i_page_rendering_service import (
    IPageRenderingService,
)
from ost_visualizer.application.interfaces.i_page_size_provider import IPageSizeProvider
from ost_visualizer.application.interfaces.i_pdf_exporter import IPDFExporter
from ost_visualizer.application.interfaces.i_osp_exporter import IOspExporter
from ost_visualizer.application.interfaces.i_ost_exporter import IOstExporter
from ost_visualizer.application.interfaces.i_repository_provider import (
    IRepositoryProvider,
)
from ost_visualizer.application.interfaces.i_remote_change_reader import (
    IRemoteChangeReader,
)
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    ISqlDatabaseCreator,
)
from ost_visualizer.application.interfaces.i_shutdown_aware import IShutdownAware
from ost_visualizer.application.interfaces.i_thread_callback_bridge import (
    IThreadCallbackBridge,
)
from ost_visualizer.application.interfaces.i_uom_service import IUOMService
from ost_visualizer.application.services.annotation_caption_resolver import (
    AnnotationCaptionResolver,
)
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.visualization_provider import _HtmlRendererAdapter
from ost_visualizer.infrastructure.database.entity_version_reader import (
    DatabaseEntityVersionReader,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.infrastructure.providers import (
    InfrastructureServiceProvider,
    RepositoryProvider,
)
from ost_visualizer.infrastructure.sql.catalog import SqlDatabaseCatalog
from ost_visualizer.infrastructure.sql.collaboration_store import SqlCollaborationStore
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator
from ost_visualizer.infrastructure.sql.remote_change_reader import SqlRemoteChangeReader
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from ost_visualizer.presentation.interfaces.i_workspace_shell import IWorkspaceShell
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.utils.qt_callback_bridge import QtCallbackBridge
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.exporters.osp_exporter import OspExporter
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.services.pdf_rendering_service import (
    PDFRenderingService,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)


def _call_shape(member):
    signature = inspect.signature(member)
    return tuple(
        (parameter.name, parameter.kind, parameter.default)
        for parameter in signature.parameters.values()
    )


def _public_methods(cls):
    return {
        name
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def _type_shape(annotation):
    if isinstance(annotation, TypeVar):
        return TypeVar
    if isinstance(annotation, list):
        return tuple(_type_shape(item) for item in annotation)
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    return origin, tuple(_type_shape(item) for item in get_args(annotation))


def _hint_shapes(member):
    return {
        name: _type_shape(annotation)
        for name, annotation in get_type_hints(member).items()
    }


class CaptionInterfaceContractTests(unittest.TestCase):
    def test_caption_resolver_call_shape_matches_implementation(self):
        self.assertEqual(
            _call_shape(IAnnotationCaptionResolver.resolve),
            _call_shape(AnnotationCaptionResolver.resolve),
        )

    def test_pdf_exporter_call_shape_and_progress_type_match(self):
        self.assertEqual(
            _call_shape(IPDFExporter.export),
            _call_shape(PDFExporter.export),
        )
        interface_progress = get_type_hints(IPDFExporter.export)["on_progress"]
        implementation_progress = get_type_hints(PDFExporter.export)["on_progress"]
        self.assertEqual(interface_progress, implementation_progress)

    def test_archive_exporter_progress_contracts_match_implementations(self):
        for interface, implementation in (
            (IOstExporter, OstExporter),
            (IOspExporter, OspExporter),
        ):
            self.assertEqual(
                _call_shape(interface.export),
                _call_shape(implementation.export),
            )
            self.assertEqual(
                get_type_hints(interface.export)["on_progress"],
                get_type_hints(implementation.export)["on_progress"],
            )

    def test_uom_service_call_shapes_match_implementation(self):
        for name in (
            "calculate_bounding_box_inches",
            "calculate_net_area_sf",
            "calculate_condition_quantities",
        ):
            self.assertEqual(
                _call_shape(getattr(IUOMService, name)),
                _call_shape(getattr(UOMDomainService, name)),
                name,
            )


class ProviderInterfaceContractTests(unittest.TestCase):
    def test_html_renderer_contract_matches_its_adapter(self):
        self.assertEqual(
            _call_shape(IHtmlRenderer.render),
            _call_shape(_HtmlRendererAdapter.render),
        )
        self.assertEqual(
            _hint_shapes(IHtmlRenderer.render),
            _hint_shapes(_HtmlRendererAdapter.render),
        )

    def test_infrastructure_provider_public_methods_match_interface(self):
        self.assertEqual(
            _public_methods(IInfrastructureServiceProvider),
            _public_methods(InfrastructureServiceProvider),
        )

    def test_mdb_reader_cleanup_is_part_of_provider_contract(self):
        self.assertIn("close_connection", _public_methods(IMdbReader))
        self.assertEqual(
            _call_shape(IMdbReader.close_connection),
            _call_shape(MdbReader.close_connection),
        )

    def test_mdb_writer_corrected_member_types_match_implementation(self):
        for name in ("delete_annotations", "save_pay_classes", "update_condition"):
            interface_hints = get_type_hints(getattr(IMdbWriter, name))
            implementation_hints = get_type_hints(getattr(MdbWriter, name))
            self.assertEqual(interface_hints, implementation_hints, name)

    def test_database_writer_router_accepts_every_protocol_call_shape(self):
        for name in _public_methods(IMdbWriter):
            with self.subTest(name=name):
                self.assertEqual(
                    _call_shape(getattr(IMdbWriter, name)),
                    _call_shape(getattr(DatabaseProjectWriter, name)),
                )

    def test_repository_provider_public_methods_match_interface(self):
        self.assertEqual(
            _public_methods(IRepositoryProvider),
            _public_methods(RepositoryProvider),
        )
        self.assertEqual(
            get_type_hints(IRepositoryProvider.get_license_signature_verifier)[
                "return"
            ],
            get_type_hints(RepositoryProvider.get_license_signature_verifier)["return"],
        )


class CollaborationInterfaceContractTests(unittest.TestCase):
    def test_collaboration_protocol_call_shapes_match_implementations(self):
        pairs = (
            (ICollaborationStore, SqlCollaborationStore),
            (IDatabaseMutationExecutor, DatabaseProjectWriter),
            (IDatabaseSessionRegistry, DatabaseSessionRegistry),
            (IEntityVersionReader, DatabaseEntityVersionReader),
            (IRemoteChangeReader, SqlRemoteChangeReader),
            (IDatabaseCatalog, SqlDatabaseCatalog),
            (ISqlDatabaseCreator, SqlDatabaseCreator),
            (IThreadCallbackBridge, QtCallbackBridge),
        )
        for interface, implementation in pairs:
            implementation_methods = _public_methods(implementation)
            for name in _public_methods(interface):
                self.assertIn(name, implementation_methods)
                self.assertEqual(
                    _call_shape(getattr(interface, name)),
                    _call_shape(getattr(implementation, name)),
                    f"{implementation.__name__}.{name}",
                )
                self.assertEqual(
                    _hint_shapes(getattr(interface, name)),
                    _hint_shapes(getattr(implementation, name)),
                    f"{implementation.__name__}.{name} annotations",
                )

    def test_phase4_implementation_contracts_are_fully_annotated(self):
        members = (
            DatabaseProjectWriter.execute,
            SqlProjectWriter.execute,
            QtCallbackBridge.dispatch,
        )
        for member in members:
            signature = inspect.signature(member)
            self.assertIsNot(signature.return_annotation, inspect.Signature.empty)
            for parameter in signature.parameters.values():
                if parameter.name == "self":
                    continue
                self.assertIsNot(
                    parameter.annotation,
                    inspect.Signature.empty,
                    f"{member.__qualname__}.{parameter.name}",
                )


class InterfaceShapeContractTests(unittest.TestCase):
    def test_coordinate_class_helpers_are_static_in_contract_and_implementation(self):
        for name in ("parse_position", "ost_to_pdf_coordinates"):
            self.assertIsInstance(
                inspect.getattr_static(ICoordinateTransformer, name), staticmethod
            )
            self.assertIsInstance(
                inspect.getattr_static(OSTCoordinateSystem, name), staticmethod
            )

    def test_color_helpers_are_instance_methods_in_contract_and_implementation(self):
        for name in ("int_to_hex", "hex_to_rgb_int", "hex_to_rgb", "parse_hex_color"):
            self.assertTrue(
                inspect.isfunction(inspect.getattr_static(IColorService, name))
            )
            self.assertTrue(
                inspect.isfunction(inspect.getattr_static(ColorService, name))
            )

    def test_workspace_window_defaults_match_implementation(self):
        for name in ("set_annotation_window_visible", "set_view_window_visible"):
            interface_default = (
                inspect.signature(getattr(IWorkspaceShell, name))
                .parameters["initial_is_maximized"]
                .default
            )
            implementation_default = (
                inspect.signature(getattr(MainWindow, name))
                .parameters["initial_is_maximized"]
                .default
            )
            self.assertEqual(interface_default, implementation_default, name)

    def test_shutdown_contract_has_no_fallback_implementation(self):
        self.assertNotIn(
            "NotImplementedError",
            inspect.getsource(IShutdownAware.shutdown),
        )


class PageInterfaceContractTests(unittest.TestCase):
    def test_page_size_return_contract_matches_cache(self):
        self.assertEqual(
            get_type_hints(IPageSizeProvider.get_page_size)["return"],
            get_type_hints(PageCache.get_page_size)["return"],
        )

    def test_pending_page_data_accepts_the_declared_strategy_protocol(self):
        self.assertEqual(
            get_type_hints(IPageLoadStrategyService.create_pending_page_data)[
                "strategy"
            ],
            get_type_hints(PageLoadStrategyService.create_pending_page_data)[
                "strategy"
            ],
        )

    def test_page_renderer_shutdown_and_callback_bridge_return_none(self):
        for interface_member, implementation_member in (
            (IPageRenderingService.shutdown, PDFRenderingService.shutdown),
            (IThreadCallbackBridge.request_callback, QtCallbackBridge.request_callback),
        ):
            self.assertEqual(
                get_type_hints(interface_member)["return"],
                get_type_hints(implementation_member)["return"],
            )


if __name__ == "__main__":
    unittest.main()
