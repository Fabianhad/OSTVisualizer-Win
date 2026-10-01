from ost_visualizer.infrastructure import providers
from unittest.mock import Mock, patch
import unittest
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.providers import RepositoryProvider


class RecordingPdfRenderer:
    instances = []
    open_result = True
    pages = [(612.0, 792.0, "A1"), (1224.0, 864.0, "A2")]
    reported_page_count = None
    failing_page = None

    def __init__(self):
        self.closed = 0
        self.opened_path = None
        RecordingPdfRenderer.instances.append(self)

    def open(self, path):
        self.opened_path = path
        return RecordingPdfRenderer.open_result

    def page_count(self):
        if RecordingPdfRenderer.reported_page_count is not None:
            return RecordingPdfRenderer.reported_page_count
        return len(RecordingPdfRenderer.pages)

    def page_size(self, page_index):
        if page_index == RecordingPdfRenderer.failing_page:
            raise RuntimeError("page failed")
        return RecordingPdfRenderer.pages[page_index][:2]

    def page_label(self, page_index):
        return RecordingPdfRenderer.pages[page_index][2]

    def close(self):
        self.closed += 1


class ProvidersPersistenceTests(unittest.TestCase):
    def _service_provider(self):
        RecordingPdfRenderer.instances = []
        RecordingPdfRenderer.open_result = True
        RecordingPdfRenderer.pages = [(612.0, 792.0, "A1"), (1224.0, 864.0, "A2")]
        RecordingPdfRenderer.reported_page_count = None
        RecordingPdfRenderer.failing_page = None
        patcher = patch.object(providers._ost_pdf, "PDFRenderer", RecordingPdfRenderer)
        patcher.start()
        self.addCleanup(patcher.stop)
        return providers.InfrastructureServiceProvider(
            logger=logging.getLogger("test"),
            callback_bridge_factory=lambda: None,
            database_session_registry=object(),
        )

    def test_pdf_page_size_renderer_closes_when_page_read_fails(self):
        service_provider = self._service_provider()
        RecordingPdfRenderer.failing_page = 0
        with self.assertLogs("test", level="ERROR") as captured:
            self.assertEqual(service_provider.get_pdf_page_sizes("bad.pdf"), [])
        self.assertIn("bad.pdf", captured.output[0])
        self.assertIn("page failed", captured.output[0])
        (renderer,) = RecordingPdfRenderer.instances
        self.assertEqual(renderer.closed, 1)

    def test_pdf_page_size_renderer_closes_after_reading_inches_and_labels(self):
        service_provider = self._service_provider()
        sizes = service_provider.get_pdf_page_sizes("plans.pdf")
        self.assertEqual(sizes, [(8.5, 11.0, "A1"), (17.0, 12.0, "A2")])
        (renderer,) = RecordingPdfRenderer.instances
        self.assertEqual(renderer.opened_path, "plans.pdf")
        self.assertEqual(renderer.closed, 1)

    def test_pdf_page_size_renderer_reads_one_page_when_count_is_zero(self):
        service_provider = self._service_provider()
        RecordingPdfRenderer.pages = [(72.0, 144.0, "Only")]
        RecordingPdfRenderer.reported_page_count = 0
        self.assertEqual(
            service_provider.get_pdf_page_sizes("empty-count.pdf"),
            [(1.0, 2.0, "Only")],
        )
        (renderer,) = RecordingPdfRenderer.instances
        self.assertEqual(renderer.closed, 1)

    def test_pdf_page_size_renderer_not_closed_when_open_fails(self):
        service_provider = self._service_provider()
        RecordingPdfRenderer.open_result = False
        self.assertEqual(service_provider.get_pdf_page_sizes("locked.pdf"), [])
        (renderer,) = RecordingPdfRenderer.instances
        self.assertEqual(renderer.closed, 0)

    def test_infrastructure_provider_reuses_one_owned_default_connection_manager(self):
        class FalseyManager:
            def __bool__(self):
                return False

        explicit_manager = FalseyManager()
        descriptor_registry = object()
        credential_store = object()
        session_registry = object()
        service_provider = providers.InfrastructureServiceProvider(
            logger=logging.getLogger("test"),
            callback_bridge_factory=lambda: None,
            database_session_registry=session_registry,
            descriptor_registry=descriptor_registry,
            credential_store=credential_store,
        )
        with (
            patch.object(
                providers,
                "DatabaseProjectReader",
                autospec=True,
                side_effect=lambda *_args, **_kwargs: object(),
            ) as reader_type,
            patch.object(
                providers,
                "DatabaseProjectWriter",
                autospec=True,
                side_effect=lambda *_args, **_kwargs: object(),
            ) as writer_type,
        ):
            default_reader = service_provider.get_mdb_reader()
            self.assertIs(service_provider.get_mdb_reader(), default_reader)
            default_writer = service_provider.get_mdb_writer()
            self.assertIs(service_provider.get_mdb_writer(), default_writer)
            default_manager = reader_type.call_args_list[0].args[0]
            self.assertIsInstance(default_manager, providers.MdbConnectionManager)
            self.assertIs(writer_type.call_args_list[0].args[0], default_manager)
            explicit_reader = service_provider.get_mdb_reader(explicit_manager)
            explicit_writer = service_provider.get_mdb_writer(explicit_manager)
            self.assertIs(
                service_provider.get_mdb_reader(explicit_manager), explicit_reader
            )
            self.assertIs(
                service_provider.get_mdb_writer(explicit_manager), explicit_writer
            )
            self.assertIsNot(explicit_reader, default_reader)
            self.assertIsNot(explicit_writer, default_writer)
            self.assertIs(reader_type.call_args_list[1].args[0], explicit_manager)
            self.assertIs(writer_type.call_args_list[1].args[0], explicit_manager)
            self.assertEqual(reader_type.call_count, 2)
            self.assertEqual(writer_type.call_count, 2)
            for call in reader_type.call_args_list:
                self.assertEqual(call.args[1:], (descriptor_registry, credential_store))
                self.assertEqual(
                    call.kwargs["logger"].name, "test.DatabaseProjectReader"
                )
            for call in writer_type.call_args_list:
                self.assertEqual(
                    call.args[1:],
                    (descriptor_registry, credential_store, session_registry),
                )
                self.assertEqual(
                    call.kwargs["logger"].name, "test.DatabaseProjectWriter"
                )

    def test_default_connection_manager_is_owned_per_provider(self):
        def make_provider():
            return providers.InfrastructureServiceProvider(
                logger=logging.getLogger("test"),
                callback_bridge_factory=lambda: None,
                database_session_registry=object(),
                descriptor_registry=object(),
                credential_store=object(),
            )

        first, second = make_provider(), make_provider()
        with patch.object(
            providers,
            "DatabaseProjectReader",
            autospec=True,
            side_effect=lambda *_args, **_kwargs: object(),
        ) as reader_type:
            first.get_mdb_reader()
            second.get_mdb_reader()
        first_manager = reader_type.call_args_list[0].args[0]
        second_manager = reader_type.call_args_list[1].args[0]
        self.assertIsNot(first_manager, second_manager)


class ProvidersSqlCleanupTests(unittest.TestCase):
    def test_repository_uses_the_composed_database_reader(self):
        manager = object()
        reader = object()
        calls = []
        provider = RepositoryProvider(
            logging.getLogger("test"),
            project_reader_factory=lambda connection_manager: (
                calls.append(connection_manager) or reader
            ),
        )
        repository = provider.get_project_repository(manager)
        self.assertIs(repository.parser.parser, reader)
        self.assertEqual(calls, [manager])

    def test_repository_passes_no_manager_and_descriptor_registry_to_composition(self):
        reader = object()
        calls = []
        descriptor_registry = object()
        provider = RepositoryProvider(
            logging.getLogger("test"),
            descriptor_registry=descriptor_registry,
            project_reader_factory=lambda connection_manager: (
                calls.append(connection_manager) or reader
            ),
        )
        repository = provider.get_project_repository()
        self.assertIs(repository.parser.parser, reader)
        self.assertEqual(calls, [None])
        self.assertIs(repository._descriptor_registry, descriptor_registry)

    def test_repository_without_reader_factory_builds_mdb_reader_for_manager(self):
        manager = object()
        with patch.object(providers, "MdbReader", autospec=True) as reader_type:
            provider = RepositoryProvider(logging.getLogger("test"))
            repository = provider.get_project_repository(manager)
        reader_type.assert_called_once()
        self.assertIs(reader_type.call_args.kwargs["conn_manager"], manager)
        self.assertEqual(
            reader_type.call_args.kwargs["logger"].name,
            "test.FileManager.MdbFileParser",
        )
        self.assertIs(repository.parser.parser, reader_type.return_value)
