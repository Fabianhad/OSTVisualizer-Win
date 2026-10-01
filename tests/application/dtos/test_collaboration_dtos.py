import json
import hashlib
import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    DatabaseMutationRequest,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    MutationOutcomeStatus,
    PageSettingsPayload,
    PlanItemsPastePayload,
    PlanPropertyPayload,
    ProjectImportPayload,
    ProjectWritePayload,
    QueuedMutationRequest,
    QueuedMutationResult,
    ResourceRef,
    canonical_mutation_request_hash,
    session_identities_equal,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.events.app_events import AppEvents

OPERATION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER_OPERATION_ID = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"


def _request(
    *,
    operation_id: str | None = None,
    resource_id: str = "10",
) -> QueuedMutationRequest:
    return QueuedMutationRequest(
        database_id="database",
        operation_id=operation_id or OPERATION_ID,
        mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
        owning_surface="main-plan",
        resources=(ResourceRef("takeoff", resource_id, 1),),
        dependency_resources=(ResourceRef("page", "20", 1),),
        bid_uid=1,
        page_uid="20",
        payload={"positions": [(resource_id, [1.0, 2.0])]},
    )


class QueuedMutationRequestTests(unittest.TestCase):
    def test_request_normalizes_identity_resources_and_hash(self):
        operation_id = OPERATION_ID.upper()
        resource = ResourceRef("takeoff", "10", 1)
        dependency = ResourceRef("page", "20", 1)
        request = QueuedMutationRequest(
            database_id="database",
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
            owning_surface="main-plan",
            resources=(resource, resource),
            dependency_resources=(dependency, dependency),
            payload={"b": [2, 1], "a": True},
        )
        self.assertEqual(request.operation_id, OPERATION_ID)
        self.assertEqual(request.resources, (resource,))
        self.assertEqual(request.dependency_resources, (dependency,))
        self.assertEqual(
            request.request_hash,
            "8f782eaaaafe8667389e029940b4bd2b8da59755d0c1c3a061ffef26a9cfcc3d",
        )
        self.assertNotEqual(
            replace(request, payload={"a": True, "b": [1, 2]}).request_hash,
            request.request_hash,
        )

    def test_request_rejects_non_uuid(self):
        with self.assertRaises(ValueError):
            _request(operation_id="not-a-uuid")

    def test_canonical_hash_encodes_typed_values_and_rejects_nonfinite_or_unsupported_data(
        self,
    ):
        payload = {
            "values": {2, 1},
            "bytes": b"\x00\xff",
            "resources": (ResourceRef("condition", "42", 8),),
        }
        expected_wire = (
            b'{"bytes":{"bytes":"00ff"},"resources":'
            b'[{"bid_uid":8,"resource_id":"42","resource_type":"condition"}],'
            b'"values":[1,2]}'
        )
        self.assertEqual(
            canonical_mutation_request_hash(payload),
            hashlib.sha256(expected_wire).hexdigest(),
        )
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_mutation_request_hash({"nested": [value]})
        with self.assertRaisesRegex(TypeError, "Unsupported collaboration"):
            canonical_mutation_request_hash({"value": object()})

    def test_request_lease_must_own_database_surface_and_exact_bid_resource(self):
        request = _request()
        handle = EditLeaseHandle(
            database_id=request.database_id,
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit",
            owning_surface=request.owning_surface,
            resources=request.resources,
        )
        owned = replace(request, edit_lease_handle=handle)
        self.assertIs(owned.edit_lease_handle, handle)
        for foreign in (
            replace(handle, database_id="other-db"),
            replace(handle, owning_surface="detached"),
            replace(handle, resources=(ResourceRef("takeoff", "10", 2),)),
            replace(handle, resources=(ResourceRef("takeoff", "other", 1),)),
        ):
            with self.subTest(foreign=foreign), self.assertRaisesRegex(
                ValueError, "own its affected resources"
            ):
                replace(request, edit_lease_handle=foreign)


class CollaborationDtosCollaborationTests(unittest.TestCase):
    def test_edit_lease_result_rejects_incomplete_ownership_state(self):
        resource = ResourceRef("condition", "42", 8)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="test",
            resources=(resource,),
        )
        with self.assertRaisesRegex(ValueError, "handle"):
            EditLeaseResult(True)
        with self.assertRaisesRegex(ValueError, "handle"):
            EditLeaseResult(False, handle=handle)
        self.assertIs(EditLeaseResult(True, handle=handle).handle, handle)
        denied = EditLeaseResult(False, message="Locked")
        self.assertFalse(denied.granted)
        self.assertEqual(denied.message, "Locked")

    def test_resource_reference_order_handles_optional_bid_context(self):
        context_free = ResourceRef("condition", "42")
        bid_scoped = ResourceRef("condition", "42", 8)
        self.assertEqual(
            sorted((bid_scoped, context_free)),
            [context_free, bid_scoped],
        )
        self.assertLess(context_free, bid_scoped)

    def test_session_identity_comparison_normalizes_uuid_text(self):
        self.assertTrue(
            session_identities_equal(
                "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            )
        )
        self.assertFalse(session_identities_equal("session-a", "session-b"))
        self.assertFalse(session_identities_equal("session-a", "SESSION-A"))
        self.assertFalse(session_identities_equal(None, None))
        self.assertFalse(session_identities_equal("session-a", "session-a"))
        self.assertFalse(session_identities_equal(OPERATION_ID, OTHER_OPERATION_ID))

    def test_queued_mutation_result_requires_current_keyword_shape(self):
        with self.assertRaises(TypeError):
            QueuedMutationResult("database", 1, "operation", True)
        result = QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=OPERATION_ID,
            outcome_status=MutationOutcomeStatus.COMMITTED,
        )
        self.assertEqual(result.operation_id, OPERATION_ID)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertTrue(result.commit_attempted)

    def test_lease_loss_event_requires_the_typed_loss_payload(self):
        with self.assertRaises(TypeError):
            AppEvents.EDIT_LEASE_LOST()
        loss = EditLeaseLoss(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="test",
            resources=(ResourceRef("condition", "42", 8),),
            reason="trust-lost",
        )
        self.assertIs(AppEvents.EDIT_LEASE_LOST(loss).loss, loss)


class CollaborationPayloadContractTests(unittest.TestCase):
    def test_project_import_payload_is_typed_and_request_hash_is_stable(self):
        payload = ProjectImportPayload(
            source_path="C:/imports/project.ost",
            source_kind="ost",
            source_size=123,
            source_modified_ns=456,
            target_project_uid="9",
        )
        first = QueuedMutationRequest(
            database_id="database",
            operation_id=OPERATION_ID,
            mutation_type=CollaborationMutationType.PROJECT_IMPORT,
            owning_surface="project-import",
            resources=(ResourceRef("project_bids", "9"),),
            payload=payload,
        )
        second = replace(first, operation_id=OTHER_OPERATION_ID)
        self.assertEqual(first.request_hash, second.request_hash)
        self.assertNotEqual(first.operation_id, second.operation_id)
        changed = replace(first, payload=replace(payload, source_size=124))
        self.assertNotEqual(first.request_hash, changed.request_hash)
        with self.assertRaisesRegex(ValueError, "OST or OSP"):
            replace(payload, source_kind="zip")

    def test_property_and_page_payloads_canonicalize_updates(self):
        updates = [["10", {"FontSize": 12, "FontName": "Arial"}]]
        first = PlanPropertyPayload.from_updates("takeoff_text", updates)
        second = PlanPropertyPayload.from_updates(
            "takeoff_text",
            [["10", {"FontName": "Arial", "FontSize": 12}]],
        )
        page = PageSettingsPayload.from_updates("scale", [["20", 1.0, 96.0]])
        self.assertEqual(first, second)
        expected = [["10", {"FontName": "Arial", "FontSize": 12}]]
        self.assertEqual(first.decoded_updates(), expected)
        self.assertEqual(page.decoded_updates(), [["20", 1.0, 96.0]])
        updates[0][1]["FontSize"] = 999
        returned = first.decoded_updates()
        returned[0][1]["FontName"] = "Changed"
        self.assertEqual(first.decoded_updates(), expected)

    def test_project_write_payload_is_typed_and_canonical(self):
        first = ProjectWritePayload.from_values(
            "rename_layer", {"name": "Coordination", "layer_uid": "10"}
        )
        second = ProjectWritePayload.from_values(
            "rename_layer", {"layer_uid": "10", "name": "Coordination"}
        )
        self.assertEqual(first, second)
        self.assertEqual(
            json.loads(first.values_json),
            {"layer_uid": "10", "name": "Coordination"},
        )
        with self.assertRaisesRegex(ValueError, "Unsupported queued project write"):
            ProjectWritePayload.from_values("unsupported_write", {})

    def test_sql_selected_page_is_not_a_collaboration_mutation_payload(self):
        with self.assertRaisesRegex(ValueError, "Unsupported page setting"):
            PageSettingsPayload.from_updates(
                "bid_selected_page",
                [["8", "22"]],
            )

    def test_database_request_requires_canonical_identity_and_hash(self):
        operation_id = OPERATION_ID
        request = DatabaseMutationRequest(
            database_id="database",
            session_id="session",
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(ResourceRef("takeoff", "10", 1),),
        )
        self.assertEqual(request.operation_id, operation_id)
        self.assertEqual(request.request_hash, "a" * 64)
        with self.assertRaises(TypeError):
            DatabaseMutationRequest(database_id="database", session_id="session")
        with self.assertRaisesRegex(ValueError, "result format version 1"):
            DatabaseMutationRequest(
                database_id="database",
                session_id="session",
                operation_id=OPERATION_ID,
                mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
                request_hash="a" * 64,
                result_format_version=2,
            )
        with self.assertRaisesRegex(ValueError, "types must be canonical"):
            DatabaseMutationRequest(
                database_id="database",
                session_id="session",
                operation_id=OPERATION_ID,
                mutation_type="old_project_write",
                request_hash="a" * 64,
            )

    def test_queued_request_rejects_noncanonical_payload_format(self):
        with self.assertRaisesRegex(ValueError, "payload format version 1"):
            QueuedMutationRequest(
                database_id="database",
                operation_id=OPERATION_ID,
                mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
                owning_surface="main-plan",
                resources=(ResourceRef("takeoff", "10", 1),),
                payload_format_version=2,
            )


class PlanPropertyOwnershipTests(unittest.TestCase):
    def test_external_parent_bindings_reject_incomplete_or_ambiguous_sources(self):
        valid = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("10",),
            takeoff_specs=(
                InsertTakeoffSpec("30", "20", "1", [0, 0, 1, 1], parent_uid="10"),
            ),
            takeoff_external_parent_sources=("10",),
        )
        self.assertEqual(valid.takeoff_external_parent_sources, ("10",))
        for sources, parent_uid in (
            (("missing",), "10"),
            (("10", "10"), "10"),
            (("10",), "0"),
        ):
            with self.subTest(sources=sources, parent_uid=parent_uid):
                with self.assertRaises(ValueError):
                    PlanItemsPastePayload(
                        source_bid_uid="7",
                        destination_bid_uid="7",
                        takeoff_source_uids=("10",),
                        takeoff_specs=(
                            InsertTakeoffSpec(
                                "30", "20", "1", [0, 0, 1, 1], parent_uid=parent_uid
                            ),
                        ),
                        takeoff_external_parent_sources=sources,
                    )
