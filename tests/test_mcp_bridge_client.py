import unittest
from unittest.mock import patch
from ost_visualizer.mcp_server.bridge_client import McpBridgeClient


class FakeBridgeClient(McpBridgeClient):
    def __init__(self, response):
        super().__init__(timeout_ms=10)
        self.response = response

    def _request_windows_pipe(self, _payload):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class McpBridgeClientTests(unittest.TestCase):
    def test_returns_none_when_desktop_bridge_is_unavailable(self):
        self.assertIsNone(
            McpBridgeClient(
                timeout_ms=10,
                server_name="OSTVisualizerMissingMcpBridgeForTest",
            ).get_context()
        )

    def test_malformed_bridge_payload_is_reported_without_crashing(self):
        client = FakeBridgeClient(b"{not-json")
        with patch("sys.platform", "win32"):
            self.assertIsNone(client.get_context())
        self.assertEqual(client.last_status, "malformed_bridge_payload")

    def test_valid_bridge_payload_reports_live_context(self):
        client = FakeBridgeClient(
            b'{"success": true, "data": {"source": "live_app", "bid_uid": "b1"}}'
        )
        with patch("sys.platform", "win32"):
            self.assertEqual(
                client.get_context(),
                {"source": "live_app", "bid_uid": "b1"},
            )
        self.assertEqual(client.last_status, "live_context")


if __name__ == "__main__":
    unittest.main()
