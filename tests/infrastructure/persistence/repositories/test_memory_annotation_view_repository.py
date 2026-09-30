"""Active annotation view identity and detached database ownership."""

import unittest
from dataclasses import replace
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.persistence.repositories.memory_annotation_view_repository import (
    MemoryAnnotationViewRepository,
)


class MemoryAnnotationViewRepositoryTests(unittest.TestCase):
    def test_create_preserves_database_bid_and_target_and_replaces_active_view(self):
        repository = MemoryAnnotationViewRepository()
        self.assertIsNone(repository.get_active_view())
        owner = BidRef(file_path="first.mdb", bid_uid="bid")
        first = repository.create_view(owner, "page", "named")
        self.assertEqual(first.bid_ref, owner)
        self.assertEqual(
            (first.target_page_uid, first.target_named_view_uid), ("page", "named")
        )
        second = repository.create_view(
            BidRef(file_path="second.mdb", bid_uid="bid"), "page"
        )
        self.assertNotEqual(first.uid, second.uid)
        self.assertIs(repository.get_active_view(), second)
        self.assertIsNone(second.target_named_view_uid)

    def test_update_accepts_active_identity_but_ignores_replaced_view(self):
        repository = MemoryAnnotationViewRepository()
        owner = BidRef(file_path="first.mdb", bid_uid="bid")
        first = repository.create_view(owner, "page")
        second = repository.create_view(owner, "other")
        repository.update_view(replace(first, target_page_uid="stale"))
        self.assertIs(repository.get_active_view(), second)
        updated = replace(second, target_page_uid="current")
        repository.update_view(updated)
        self.assertIs(repository.get_active_view(), updated)
