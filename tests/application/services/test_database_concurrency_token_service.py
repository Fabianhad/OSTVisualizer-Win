import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import (
    ConcurrencyToken,
    ExpectedResourceVersion,
    ResourceLock,
    ResourceRef,
)
from ost_visualizer.application.dtos.local_draft_dtos import (
    LocalDraftConflict,
    LocalDraftState,
)
from ost_visualizer.application.services.database_concurrency_token_service import (
    DatabaseConcurrencyTokenService,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from tests.helpers.sql.collaboration import _change


class _VersionReader:
    """Database-scoped version snapshots; failures occur before returning a snapshot."""

    def __init__(self, databases):
        self.databases = {
            database: dict(versions) for database, versions in databases.items()
        }
        self.calls = []
        self.failure = None

    def _read(self, database_id, bid_uid):
        self.calls.append((database_id, bid_uid))
        if self.failure is not None:
            raise self.failure
        return {
            resource: token
            for resource, token in self.databases[database_id].items()
            if resource.bid_uid == bid_uid
        }

    def read_database_versions(self, database_id):
        return self._read(database_id, None)

    def read_bid_versions(self, database_id, bid_uid):
        return self._read(database_id, int(bid_uid))


class DatabaseConcurrencyTokenServiceCollaborationTests(unittest.TestCase):
    def setUp(self):
        self.resource = ResourceRef("condition", "42", 8)
        self.initial = ConcurrencyToken((1).to_bytes(8, "big"))
        self.current = ConcurrencyToken((2).to_bytes(8, "big"))
        self.reader = _VersionReader({"database": {self.resource: self.initial}})
        self.drafts = LocalDraftRegistry()
        self.tokens = DatabaseConcurrencyTokenService(self.reader, self.drafts)

    def begin_draft(self, database="database"):
        draft = self.drafts.begin(
            draft_type="condition",
            database_id=database,
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(self.resource,),
            base_tokens=self.tokens.tokens_for_resources(database, (self.resource,)),
        )
        self.drafts.activate(
            draft.draft_id,
            (ResourceLock(database, self.resource, "owned-token"),),
            runtime_generation=1,
        )
        return self.drafts.get(draft.draft_id)

    def test_remote_change_during_local_edit_returns_conflict(self):
        self.tokens.load_bid("database", "8")
        draft = self.begin_draft()
        changes = (_change("database", self.resource, 2),)
        self.tokens.apply_remote_changes("database", changes)
        conflicts = self.drafts.conflicts_for_changes("database", changes)
        self.assertEqual(
            conflicts,
            (LocalDraftConflict(draft.draft_id, self.resource, "condition", "test"),),
        )
        self.assertEqual(
            self.drafts.get(draft.draft_id).state, LocalDraftState.CONFLICTED
        )
        self.assertEqual(
            self.tokens.tokens_for_resources("database", (self.resource,)),
            ((self.resource, self.current),),
        )
        self.assertEqual(
            self.tokens.expected_versions("database", (self.resource,)),
            (ExpectedResourceVersion(self.resource, self.initial),),
        )

    def test_authoritative_reload_uses_current_token_after_drafts_are_cancelled(self):
        self.tokens.load_bid("database", "8")
        draft = self.begin_draft()
        self.reader.databases["database"][self.resource] = self.current
        self.tokens.load_bid("database", "8")
        self.assertEqual(
            self.tokens.tokens_for_resources("database", (self.resource,)),
            ((self.resource, self.current),),
        )
        self.assertEqual(
            self.tokens.expected_versions("database", (self.resource,)),
            (ExpectedResourceVersion(self.resource, self.initial),),
        )
        self.drafts.finish(draft.draft_id)
        self.assertIsNone(self.drafts.get(draft.draft_id))
        self.assertEqual(
            self.tokens.expected_versions("database", (self.resource,)),
            (ExpectedResourceVersion(self.resource, self.current),),
        )

    def test_new_session_reloads_bid_tokens_before_the_next_edit(self):
        self.tokens.load_bid("database", "8")
        self.reader.databases["database"][self.resource] = self.current
        self.tokens.load_database("database")
        self.assertEqual(
            self.tokens.tokens_for_resources("database", (self.resource,)), ()
        )
        self.tokens.ensure_resources_loaded("database", (self.resource,))
        self.assertEqual(
            self.reader.calls,
            [
                ("database", 8),
                ("database", None),
                ("database", 8),
            ],
        )
        self.assertEqual(
            self.tokens.expected_versions("database", (self.resource,)),
            (ExpectedResourceVersion(self.resource, self.current),),
        )

    def test_successful_local_save_advances_active_draft_base_token(self):
        self.reader.databases["other"] = {self.resource: self.initial}
        for database in ("database", "other"):
            self.tokens.load_bid(database, "8")
        draft = self.begin_draft()
        other_draft = self.begin_draft("other")
        versions = {self.resource: self.current}
        self.tokens.apply_result("database", versions)
        self.assertEqual(versions, {self.resource: self.current})
        self.assertEqual(
            self.drafts.get(draft.draft_id).base_tokens,
            ((self.resource, self.current),),
        )
        self.assertIs(self.drafts.get(other_draft.draft_id), other_draft)
        self.assertEqual(
            self.tokens.tokens_for_resources("database", (self.resource,)),
            ((self.resource, self.current),),
        )
        self.assertEqual(
            self.tokens.expected_versions("database", (self.resource,)),
            (ExpectedResourceVersion(self.resource, self.current),),
        )
        self.assertEqual(
            self.tokens.expected_versions("other", (self.resource,)),
            (ExpectedResourceVersion(self.resource, self.initial),),
        )

    def test_bid_reload_replaces_exact_snapshot_without_touching_sibling_scopes(self):
        sibling = ResourceRef("condition", "99", 9)
        global_resource = ResourceRef("database", "database")
        self.reader.databases["database"].update(
            {
                sibling: self.initial,
                global_resource: self.initial,
            }
        )
        self.reader.databases["other"] = {self.resource: self.initial}
        self.tokens.load_database("database")
        self.tokens.load_bid("database", "8")
        self.tokens.load_bid("database", "9")
        self.tokens.load_bid("other", "8")
        replacement = ResourceRef("condition", "43", 8)
        del self.reader.databases["database"][self.resource]
        self.reader.databases["database"][replacement] = self.current
        loaded = self.tokens.load_bid("database", "8")
        self.assertEqual(loaded, ((replacement, self.current),))
        self.assertEqual(
            self.tokens.tokens_for_resources(
                "database", (self.resource, replacement, sibling, global_resource)
            ),
            (
                (replacement, self.current),
                (sibling, self.initial),
                (global_resource, self.initial),
            ),
        )
        self.assertEqual(
            self.tokens.tokens_for_resources("other", (self.resource,)),
            ((self.resource, self.initial),),
        )
        self.assertEqual(
            self.tokens.expected_versions("database", (self.resource,)), ()
        )

    def test_failed_reads_preserve_tokens_and_loaded_marker_until_successful_retry(
        self,
    ):
        before = self.tokens.load_bid("database", "8")
        self.reader.databases["database"][self.resource] = self.current
        for scope in ("bid", "database"):
            with self.subTest(scope=scope):
                self.reader.failure = OSError("version read failed")
                with self.assertRaisesRegex(OSError, "version read failed"):
                    if scope == "bid":
                        self.tokens.load_bid("database", "8")
                    else:
                        self.tokens.load_database("database")
                self.assertTrue(
                    self.tokens.bid_versions_are_current("database", "8", before)
                )
                calls = list(self.reader.calls)
                self.tokens.ensure_resources_loaded("database", (self.resource,))
                self.assertEqual(self.reader.calls, calls)
                self.assertEqual(
                    self.tokens.tokens_for_resources("database", (self.resource,)),
                    before,
                )
        self.reader.failure = None
        self.assertEqual(
            self.tokens.load_bid("database", "8"), ((self.resource, self.current),)
        )
        self.assertFalse(self.tokens.bid_versions_are_current("database", "8", before))

    def test_ensure_and_clear_are_database_scoped_and_read_each_missing_bid_once(self):
        sibling = ResourceRef("condition", "99", 9)
        global_resource = ResourceRef("database", "database")
        self.reader.databases["database"][sibling] = self.initial
        self.reader.databases["other"] = {self.resource: self.current}
        requested = (sibling, self.resource, self.resource, global_resource)
        self.tokens.ensure_resources_loaded("database", ())
        self.tokens.ensure_resources_loaded("database", requested)
        self.tokens.ensure_resources_loaded("database", requested)
        self.tokens.ensure_resources_loaded("other", (self.resource,))
        self.assertEqual(
            self.reader.calls, [("database", 8), ("database", 9), ("other", 8)]
        )
        self.tokens.clear_database("database")
        self.tokens.clear_database("database")
        self.assertEqual(self.tokens.tokens_for_resources("database", requested), ())
        self.assertEqual(
            self.tokens.tokens_for_resources("other", (self.resource,)),
            ((self.resource, self.current),),
        )
        self.tokens.ensure_resources_loaded("other", (self.resource,))
        self.tokens.ensure_resources_loaded("database", requested)
        self.assertEqual(
            self.reader.calls,
            [
                ("database", 8),
                ("database", 9),
                ("other", 8),
                ("database", 8),
                ("database", 9),
            ],
        )

    def test_bid_snapshot_requires_loaded_owner_and_exact_resource_versions(self):
        self.assertFalse(self.tokens.bid_versions_are_current("database", "8", ()))
        snapshot = self.tokens.load_bid("database", "8")
        self.assertTrue(self.tokens.bid_versions_are_current("database", "8", snapshot))
        self.assertFalse(self.tokens.bid_versions_are_current("other", "8", snapshot))
        self.assertFalse(
            self.tokens.bid_versions_are_current("database", "9", snapshot)
        )
        self.assertFalse(self.tokens.bid_versions_are_current("database", "8", ()))
        change = _change("database", self.resource, 2)
        self.tokens.apply_remote_changes(
            "database", (replace(change, resulting_version=None),)
        )
        self.assertTrue(self.tokens.bid_versions_are_current("database", "8", snapshot))
        self.tokens.apply_remote_changes("database", (change,))
        self.assertFalse(
            self.tokens.bid_versions_are_current("database", "8", snapshot)
        )
        current = ((self.resource, self.current),)
        self.assertTrue(self.tokens.bid_versions_are_current("database", "8", current))
        self.reader.databases["database"].clear()
        self.assertEqual(self.tokens.load_bid("database", "8"), ())
        self.assertTrue(self.tokens.bid_versions_are_current("database", "8", ()))
