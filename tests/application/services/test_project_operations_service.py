import unittest
from ost_visualizer.application.services.project_operations_service import (
    ProjectOperationsService,
)


class ProjectOperationsNavigationContractTests(unittest.TestCase):
    def test_project_operations_has_no_synchronous_bid_navigation_entry_point(self):
        self.assertFalse(hasattr(ProjectOperationsService, "load_bid"))
