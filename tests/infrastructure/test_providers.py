from ost_visualizer.infrastructure import providers
from unittest.mock import Mock, patch
import unittest
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.providers import RepositoryProvider


class ProvidersPersistenceTests(unittest.TestCase):
    def test_pdf_page_size_renderer_closes_when_page_read_fails(self):
        class FakeRenderer:
            last_instance = None

            def __init__(self):
                self.closed = False
                FakeRenderer.last_instance = self

            def open(self, _path):
                return True

            def page_count(self):
                return 1

            def page_size(self, _page_index):
                raise RuntimeError("page failed")

            def close(self):
                self.closed = True

        original_renderer = providers._ost_pdf.PDFRenderer
        providers._ost_pdf.PDFRenderer = FakeRenderer
        try:
            service_provider = providers.InfrastructureServiceProvider(
                logger=logging.getLogger("test"),
                callback_bridge_factory=lambda: None,
                database_session_registry=object(),
            )
            with self.assertLogs("test", level="ERROR"):
                self.assertEqual(service_provider.get_pdf_page_sizes("bad.pdf"), [])
            self.assertTrue(FakeRenderer.last_instance.closed)
        finally:
            providers._ost_pdf.PDFRenderer = original_renderer

    def test_infrastructure_provider_reuses_one_owned_default_connection_manager(self):
        class FalseyManager:
            def __bool__(self):
                return False

        explicit_manager = FalseyManager()
        service_provider = providers.InfrastructureServiceProvider(
            logger=logging.getLogger("test"),
            callback_bridge_factory=lambda: None,
            database_session_registry=object(),
            descriptor_registry=object(),
            credential_store=object(),
        )
        with (
            patch.object(providers, "DatabaseProjectReader") as reader_type,
            patch.object(providers, "DatabaseProjectWriter") as writer_type,
        ):
            default_reader = service_provider.get_mdb_reader()
            self.assertIs(service_provider.get_mdb_reader(), default_reader)
            default_writer = service_provider.get_mdb_writer()
            self.assertIs(service_provider.get_mdb_writer(), default_writer)
            default_manager = reader_type.call_args_list[0].args[0]
            self.assertIs(writer_type.call_args_list[0].args[0], default_manager)
            service_provider.get_mdb_reader(explicit_manager)
            service_provider.get_mdb_writer(explicit_manager)
            self.assertIs(reader_type.call_args_list[1].args[0], explicit_manager)
            self.assertIs(writer_type.call_args_list[1].args[0], explicit_manager)
            self.assertEqual(reader_type.call_count, 2)
            self.assertEqual(writer_type.call_count, 2)


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
