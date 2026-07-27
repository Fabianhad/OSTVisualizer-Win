import unittest
from types import SimpleNamespace
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    LoadBidUseCase,
)
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.identity_refs import BidRef


class LoadBidUseCaseTests(unittest.TestCase):
    def test_loads_concurrency_tokens_before_bid_state(self):
        calls = []

        class FileManager:
            def load_bid(self, bid_uid, file_path):
                calls.append(("state", file_path, bid_uid))
                return BidLoadResult()

        class ConcurrencyTokens:
            def load_bid(self, file_path, bid_uid):
                calls.append(("tokens", file_path, bid_uid))

        model = SimpleNamespace(
            find_bid_info=lambda _bid_ref: None,
            set_pages=lambda _pages: None,
            set_annotations=lambda _annotations: None,
            deselect_pages=lambda: None,
        )
        use_case = LoadBidUseCase(model, FileManager(), ConcurrencyTokens())
        self.assertTrue(use_case.execute(BidRef("database-id", "42")))
        self.assertEqual(
            calls,
            [
                ("tokens", "database-id", "42"),
                ("state", "database-id", "42"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
