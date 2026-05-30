import unittest
from ost_visualizer.infrastructure.persistence.repositories.file_project_repository import (
    MdbFileParser,
)


class FakeMdbReaderWithLayerFailure:
    def get_bid_data(self, file_path, bid_uid):
        return ({}, [], {}, {}, {}, {}, [], {}, None, {})

    def get_bid_layers_for_sidebar(self, file_path, bid_uid):
        raise ValueError("bad layer sequence")


class MdbFileParserTests(unittest.TestCase):
    def test_bid_load_keeps_core_data_when_optional_layers_fail(self):
        parser = MdbFileParser(parser=FakeMdbReaderWithLayerFailure())
        with self.assertLogs(parser.logger, level="WARNING") as logs:
            result = parser.load_bid_data("demo.mdb", "bid-1")
        self.assertIn("Failed to load bid layers", logs.output[0])
        self.assertEqual(result.bid_layers, [])
        self.assertEqual(result.bid_conditions, {})
        self.assertEqual(result.bid_takeoffs, [])


if __name__ == "__main__":
    unittest.main()
