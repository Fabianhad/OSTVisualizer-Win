import unittest

from ost_visualizer.application.interfaces.i_mdb_connection_manager import (
    IMdbConnectionManager,
)
from ost_visualizer.application.interfaces.i_mdb_reader import IMdbReader
from ost_visualizer.application.interfaces.i_mdb_writer import IMdbWriter
from ost_visualizer.application.interfaces.project_read_port import ProjectReadPort
from ost_visualizer.application.interfaces.project_storage_connection_port import (
    ProjectStorageConnectionPort,
)
from ost_visualizer.application.interfaces.project_write_port import ProjectWritePort


class ProjectPersistencePortTests(unittest.TestCase):
    def test_neutral_project_ports_alias_existing_mdb_ports(self):
        self.assertIs(ProjectReadPort, IMdbReader)
        self.assertIs(ProjectWritePort, IMdbWriter)
        self.assertIs(ProjectStorageConnectionPort, IMdbConnectionManager)


if __name__ == "__main__":
    unittest.main()
