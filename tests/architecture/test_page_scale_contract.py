import unittest
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)


class SqlPageScaleImplementationContractTests(unittest.TestCase):
    def test_sql_uses_the_same_scale_position_contract(self):
        from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter

        self.assertIs(
            SqlProjectWriter._rescale_page_positions,
            PageOperationsMixin._rescale_page_positions,
        )
