import unittest
from ost_visualizer.application.dtos.collaboration_dtos import ResourceRef
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)


class DatabaseSessionRegistryCollaborationTests(unittest.TestCase):
    def test_session_registry_tracks_owned_lock_tokens_and_clears_them(self):
        registry = DatabaseSessionRegistry()
        resource = ResourceRef("condition", "42", 8)
        registry.register("database", "session")
        self.assertEqual(registry.get("database"), "session")
        self.assertEqual(registry.require("database"), "session")
        registry.register_lock("database", resource, "lock-token")
        self.assertEqual(registry.lock_tokens("database", (resource,)), ("lock-token",))
        registry.remove("database", "session")
        self.assertEqual(registry.lock_tokens("database", (resource,)), ())
        self.assertEqual(registry.get("database"), "")
        with self.assertRaisesRegex(RuntimeError, "no active collaboration session"):
            registry.require("database")

    def test_session_registry_uses_sql_lock_identity_without_bid_context(self):
        registry = DatabaseSessionRegistry()
        registered = ResourceRef("condition", "42")
        requested = ResourceRef("condition", "42", 8)
        registry.register("database", "session")
        registry.register_lock("database", registered, "lock-token")
        self.assertEqual(
            registry.lock_tokens("database", (requested,)),
            ("lock-token",),
        )
        registry.remove_lock("database", requested)
        self.assertEqual(registry.lock_tokens("database", (registered,)), ())

    def test_stale_removal_cannot_clear_reopened_session_or_another_database(self):
        registry = DatabaseSessionRegistry()
        resource = ResourceRef("condition", "42", 8)
        registry.register("first", "old-session")
        registry.register_lock("first", resource, "old-token")
        registry.register("second", "other-session")
        registry.register_lock("second", resource, "other-token")
        registry.remove("first", "old-session")
        registry.register("first", "new-session")
        registry.register_lock("first", resource, "new-token")
        registry.remove("first", "old-session")
        self.assertEqual(registry.require("first"), "new-session")
        self.assertEqual(registry.lock_tokens("first", (resource,)), ("new-token",))
        self.assertEqual(registry.require("second"), "other-session")
        self.assertEqual(registry.lock_tokens("second", (resource,)), ("other-token",))
        registry.remove("first")
        registry.remove("first")
        self.assertEqual(registry.get("first"), "")
        self.assertEqual(registry.lock_tokens("first", (resource,)), ())
        self.assertEqual(registry.lock_tokens("second", (resource,)), ("other-token",))

    def test_lock_tokens_deduplicate_in_request_order_and_keep_resource_types_distinct(
        self,
    ):
        registry = DatabaseSessionRegistry()
        first = ResourceRef("condition", "42", 8)
        second = ResourceRef("layer", "42", 8)
        missing = ResourceRef("condition", "43", 8)
        registry.register("database", "session")
        registry.register_lock("database", first, "condition-token")
        registry.register_lock("database", second, "layer-token")
        registry.register("database", "session")
        self.assertEqual(
            registry.lock_tokens("database", (second, first, missing, first)),
            ("layer-token", "condition-token"),
        )
        registry.remove_lock("database", missing)
        registry.remove_lock("database", second)
        self.assertEqual(
            registry.lock_tokens("database", (first, second)), ("condition-token",)
        )

    def test_invalid_registration_does_not_replace_existing_session(self):
        registry = DatabaseSessionRegistry()
        registry.register("database", "session")
        for database, session in (("", "new"), ("database", "")):
            with self.subTest(database=database, session=session):
                with self.assertRaisesRegex(ValueError, "IDs are required"):
                    registry.register(database, session)
        self.assertEqual(registry.require("database"), "session")
        self.assertEqual(registry.get("missing"), "")
