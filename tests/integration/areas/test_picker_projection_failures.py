import unittest
from unittest.mock import Mock, patch, MagicMock
from types import SimpleNamespace
import logging
from ost_visualizer.application.services.project_read_service import ProjectReadService
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
import tests.integration.surfaces.test_presentation as surface_fixture


class AreaProjectionFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        surface_fixture.SceneControlPresentationTests.setUpClass()

    def test_failed_area_read_cannot_replace_authoritative_family_with_empty_list(self):
        reader = MdbReader.__new__(MdbReader)
        reader.logger = logging.getLogger(__name__)
        reader._connection = Mock(side_effect=OSError("Database read failed"))
        read_service = ProjectReadService.__new__(ProjectReadService)
        read_service._reader = reader
        read_service.logger = reader.logger
        writes = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda *_args: False,
            save_bid_areas_result=lambda *_args: None,
            reload_and_notify=Mock(return_value=False),
        )
        case = surface_fixture.SceneControlPresentationTests()
        self.addCleanup(case.doCleanups)
        bundle, _combo = case._main_components(read_service, writes)
        case.main_data.replace_bid_areas_after_local_save = Mock(return_value=True)
        bar = bundle.central_widget.findChild(PageSettingsBar)
        with self.assertLogs(level="WARNING"):
            result = bar._refresh_areas_fn("bid.mdb", "1", ())
        case.main_data.replace_bid_areas_after_local_save.assert_not_called()
        self.assertIsNone(result)
        writes.reload_and_notify.assert_not_called()
