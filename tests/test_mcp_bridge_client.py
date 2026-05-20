import unittest
from ost_visualizer.mcp_server.bridge_client import McpBridgeClient


class McpBridgeClientTests(unittest.TestCase):
    def test_returns_none_when_desktop_bridge_is_unavailable(self):
        self.assertIsNone(
            McpBridgeClient(
                timeout_ms=10,
                server_name="OSTVisualizerMissingMcpBridgeForTest",
            ).get_context()
        )


if __name__ == "__main__":
    unittest.main()
