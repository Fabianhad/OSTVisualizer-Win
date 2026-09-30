import os
import unittest
from tests.paths import REPO_ROOT

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class InspectSqlSchemaDatabaseDescriptorTests(unittest.TestCase):
    def test_schema_inspection_tool_uses_canonical_certificate_default(self):
        root = REPO_ROOT
        tool = (root / "tools/inspect_sql_schema.py").read_text(encoding="utf-8")
        self.assertNotIn("--trust-server-certificate", tool)
        self.assertNotIn("trust_server_certificate=", tool)
