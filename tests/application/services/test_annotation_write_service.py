import unittest
from types import SimpleNamespace
from ost_visualizer.application.services.annotation_write_service import (
    AnnotationWriteService,
)
from ost_visualizer.domain.entities.identity_refs import BidRef


class UIAccessPlanEditingTests(unittest.TestCase):
    def test_annotation_resources_keep_bid_identity_for_equivalent_windows_path(self):
        service = AnnotationWriteService.__new__(AnnotationWriteService)
        service._project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef(
                file_path=r"C:\Jobs\Current.mdb",
                bid_uid="41",
            )
        )
        self.assertEqual(service._bid_uid("c:/jobs/CURRENT.mdb"), 41)
