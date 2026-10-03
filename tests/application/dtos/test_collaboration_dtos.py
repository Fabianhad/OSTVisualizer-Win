import dataclasses
import enum
import json
import hashlib
import unittest
from dataclasses import replace
import ost_visualizer.application.dtos.collaboration_dtos as collaboration_dtos
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    CollaborationMutationType,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseChangePollResult,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DurableOperationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    HydratedDatabaseChangeBatch,
    MutationExecutionResult,
    MutationOutcomeStatus,
    MutationRejectionReason,
    PageSettingsPayload,
    PendingMutationState,
    PendingSqlOperationRecord,
    PlanGeometryPayload,
    PlanItemsDeletePayload,
    PlanItemsPastePayload,
    PlanPropertyPayload,
    ProjectImportPayload,
    ProjectWritePayload,
    QueuedMutationRequest,
    QueuedMutationResult,
    ReconciliationFailureKind,
    ReconciliationResult,
    ResourceRef,
    SynchronizationConflict,
    ordered_lock_resources,
    resource_lock_sort_key,
    canonical_mutation_request_hash,
    is_queued_takeoff_preview_uid,
    queued_takeoff_preview_uid,
    rejection_reason_message,
    session_identities_equal,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
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


class ResourceRefContractTests(unittest.TestCase):
    def test_type_and_id_length_boundaries_and_unknown_types(self):
        ResourceRef("condition", "x" * 128)
        for resource_type, resource_id in (
            ("", "1"),
            ("condition", ""),
            ("condition", "x" * 129),
            ("c" * 65, "1"),
        ):
            with self.subTest(
                resource_type=resource_type[:8], id_length=len(resource_id)
            ):
                with self.assertRaises(ValueError):
                    ResourceRef(resource_type, resource_id)
        with self.assertRaisesRegex(ValueError, "1 to 64 characters"):
            ResourceRef("c" * 65, "1")
        with self.assertRaisesRegex(ValueError, "1 to 128 characters"):
            ResourceRef("condition", "x" * 129)

    def test_ordering_identity_and_equality_distinguish_bid_context(self):
        bare = ResourceRef("condition", "42")
        eight = ResourceRef("condition", "42", 8)
        nine = ResourceRef("condition", "42", 9)
        zero = ResourceRef("condition", "42", 0)
        later_id = ResourceRef("condition", "43")
        later_type = ResourceRef("layer", "1")
        self.assertEqual(
            sorted((later_type, nine, later_id, eight, zero, bare)),
            [bare, zero, eight, nine, later_id, later_type],
        )
        self.assertLess(bare, zero)
        self.assertLessEqual(eight, eight)
        self.assertGreater(nine, eight)
        self.assertGreaterEqual(nine, nine)
        self.assertNotEqual(bare, zero)
        self.assertNotEqual(eight, nine)
        self.assertEqual(eight, ResourceRef("condition", "42", 8))
        self.assertEqual(len({bare, zero, eight, nine, eight}), 4)
        self.assertEqual(
            {r.lease_identity for r in (bare, zero, eight, nine)}, {("condition", "42")}
        )
        self.assertEqual(later_type.lease_identity, ("layer", "1"))
        with self.assertRaises(TypeError):
            bare < ("condition", "42")
        self.assertNotEqual(bare, ("condition", "42", None))


class ApplicationLockOrderContractTests(unittest.TestCase):
    """The one order every SQL application-lock transaction must follow (D1)."""

    def test_bid_resources_come_first_then_type_id_and_bid_identity(self):
        bid_three = ResourceRef("bid", "3", 3)
        bid_eight = ResourceRef("bid", "8", 8)
        bid_bare = ResourceRef("bid", "8")
        annotation = ResourceRef("annotation", "line/7", 8)
        area = ResourceRef("area", "3", 8)
        takeoff_eight = ResourceRef("takeoff", "10", 8)
        takeoff_nine = ResourceRef("takeoff", "10", 9)
        takeoff_bare = ResourceRef("takeoff", "10")
        later_id = ResourceRef("takeoff", "11", 3)
        expected = (
            bid_three,
            bid_bare,
            bid_eight,
            annotation,
            area,
            takeoff_bare,
            takeoff_eight,
            takeoff_nine,
            later_id,
        )
        for shuffled in (expected, tuple(reversed(expected))):
            with self.subTest(first=shuffled[0]):
                self.assertEqual(ordered_lock_resources(shuffled), expected)
        # plain ResourceRef ordering puts annotation/area before the Bid: the
        # shared order is intentionally different (the bug behind D1).
        self.assertNotEqual(tuple(sorted(expected)), expected)
        self.assertLess(annotation, bid_eight)

    def test_the_order_is_total_stable_and_deduplicated(self):
        a = ResourceRef("takeoff", "10", 8)
        b = ResourceRef("takeoff", "10", 8)
        c = ResourceRef("takeoff", "10", 0)
        self.assertEqual(resource_lock_sort_key(a), resource_lock_sort_key(b))
        self.assertNotEqual(resource_lock_sort_key(a), resource_lock_sort_key(c))
        self.assertEqual(ordered_lock_resources((a, b, c, a)), (c, a))
        self.assertEqual(ordered_lock_resources(()), ())
        self.assertEqual(
            ordered_lock_resources(iter((c, a))), ordered_lock_resources((a, c))
        )
        self.assertEqual(
            resource_lock_sort_key(ResourceRef("bid", "8", 8)),
            (0, "bid", "8", True, 8),
        )
        self.assertEqual(
            resource_lock_sort_key(ResourceRef("takeoff", "10")),
            (1, "takeoff", "10", False, 0),
        )


class ConcurrencyTokenContractTests(unittest.TestCase):
    def test_tokens_are_exactly_eight_bytes_and_render_as_hex(self):
        token = ConcurrencyToken(b"\x00\x00\x00\x00\x00\x00\xab\xcd")
        self.assertEqual(str(token), "000000000000abcd")
        for size in (0, 7, 9):
            with self.subTest(size=size):
                with self.assertRaisesRegex(ValueError, "8 bytes"):
                    ConcurrencyToken(bytes(size))
        self.assertEqual(token, ConcurrencyToken(bytes.fromhex("000000000000abcd")))

    def test_database_values_are_accepted_only_as_binary_buffers(self):
        raw = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        for value in (raw, bytearray(raw), memoryview(raw)):
            with self.subTest(kind=type(value).__name__):
                token = ConcurrencyToken.from_database(value)
                self.assertEqual(token, ConcurrencyToken(raw))
                self.assertIs(type(token.value), bytes)
        for value in (None, "0102030405060708", 1, [1, 2, 3, 4, 5, 6, 7, 8]):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaisesRegex(ValueError, "invalid rowversion"):
                    ConcurrencyToken.from_database(value)
        with self.assertRaisesRegex(ValueError, "8 bytes"):
            ConcurrencyToken.from_database(b"\x01")


class SessionIdentityContractTests(unittest.TestCase):
    def test_uuid_forms_normalize_and_missing_values_never_match(self):
        canonical = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        for variant in (
            canonical.upper(),
            canonical.replace("-", ""),
            "{" + canonical + "}",
            "urn:uuid:" + canonical,
        ):
            with self.subTest(variant=variant):
                self.assertTrue(session_identities_equal(canonical, variant))
                self.assertTrue(session_identities_equal(variant, canonical))
        for left, right in (
            (canonical, ""),
            ("", canonical),
            (None, canonical),
            (canonical, None),
            ("", ""),
            (canonical, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee0"),
        ):
            with self.subTest(left=left, right=right):
                self.assertIs(session_identities_equal(left, right), False)


class ReconciliationResultContractTests(unittest.TestCase):
    def test_success_cannot_carry_a_failure_kind(self):
        applied = ReconciliationResult(applied=True)
        self.assertIsNone(applied.failure_kind)
        failed = ReconciliationResult(
            applied=False, failure_kind=ReconciliationFailureKind.MALFORMED_PAYLOAD
        )
        self.assertFalse(failed.applied)
        self.assertEqual(ReconciliationResult(applied=False).failure_kind, None)
        with self.assertRaisesRegex(ValueError, "cannot carry a failure kind"):
            ReconciliationResult(
                applied=True, failure_kind=ReconciliationFailureKind.MALFORMED_PAYLOAD
            )
        with self.assertRaises(TypeError):
            ReconciliationResult(True)


class PayloadValidationContractTests(unittest.TestCase):
    def test_delete_payload_normalizes_and_requires_an_item(self):
        payload = PlanItemsDeletePayload(
            takeoff_uids=(5, "5", "", None, "6"),
            annotations=(
                ("7", "rect"),
                (7, "rect"),
                ("", "rect"),
                ("8", ""),
                ("8", "oval"),
            ),
        )
        self.assertEqual(payload.takeoff_uids, ("5", "6"))
        self.assertEqual(payload.annotations, (("7", "rect"), ("8", "oval")))
        self.assertEqual(PlanItemsDeletePayload(takeoff_uids=("1",)).annotations, ())
        self.assertEqual(
            PlanItemsDeletePayload(annotations=(("1", "rect"),)).takeoff_uids, ()
        )
        for empty in (
            {},
            {"takeoff_uids": ("", None)},
            {"annotations": (("", "rect"), ("1", ""))},
        ):
            with self.subTest(empty=empty):
                with self.assertRaisesRegex(ValueError, "at least one item"):
                    PlanItemsDeletePayload(**empty)

    def test_geometry_payload_requires_an_update_and_nonempty_identities(self):
        self.assertEqual(
            PlanGeometryPayload(
                takeoff_positions=(("1", (0.0, 1.0)),)
            ).takeoff_rotations,
            (),
        )
        PlanGeometryPayload(takeoff_rotations=(("1", 90.0),))
        PlanGeometryPayload(annotation_positions=(("1", "rect", (0.0, 1.0)),))
        with self.assertRaisesRegex(ValueError, "at least one update"):
            PlanGeometryPayload()
        for options in (
            {"takeoff_positions": (("", (0.0, 1.0)),)},
            {"takeoff_rotations": (("", 1.0),)},
            {"takeoff_positions": (("1", (0.0,)),), "takeoff_rotations": (("", 1.0),)},
        ):
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, "identities cannot be empty"):
                    PlanGeometryPayload(**options)

    def test_json_update_payloads_validate_kind_and_non_empty_list(self):
        for payload_type, kinds, message in (
            (
                PlanPropertyPayload,
                (
                    "takeoff_text",
                    "takeoff_area",
                    "takeoff_condition",
                    "takeoff_negative",
                    "takeoff_curve",
                    "annotation_text",
                    "annotation_style",
                ),
                "Unsupported plan property mutation",
            ),
            (
                PageSettingsPayload,
                (
                    "scale",
                    "show_mode",
                    "overlay_image",
                    "overlay_rect",
                    "invert",
                    "bitonal",
                    "image_adjustments",
                    "area",
                    "name",
                    "layer_show",
                ),
                "Unsupported page setting mutation",
            ),
        ):
            for kind in kinds:
                with self.subTest(payload=payload_type.__name__, kind=kind):
                    built = payload_type.from_updates(kind, [["1", 2]])
                    self.assertEqual(built.decoded_updates(), [["1", 2]])
            with self.assertRaisesRegex(ValueError, message):
                payload_type.from_updates("unknown_kind", [["1", 2]])
            field = "updates_json"
            kind_field = next(
                name
                for name in ("property_kind", "setting_kind")
                if name in payload_type.__dataclass_fields__
            )
            for bad, text in (
                ("not json", "valid JSON"),
                (None, "valid JSON"),
                ("{}", "non-empty list"),
                ("[]", "non-empty list"),
                ('"text"', "non-empty list"),
            ):
                with self.subTest(payload=payload_type.__name__, updates=bad):
                    with self.assertRaisesRegex(ValueError, text):
                        payload_type(**{kind_field: kinds[0], field: bad})

    def test_project_write_payload_requires_a_known_kind_and_json_object(self):
        self.assertEqual(
            ProjectWritePayload.from_values("create_bid", {}).values_json, "{}"
        )
        for kind in (
            "create_condition",
            "save_pay_classes",
            "move_bids",
            "delete_layers",
        ):
            ProjectWritePayload.from_values(kind, {"a": 1})
        for bad, text in (
            ("not json", "valid JSON"),
            (None, "valid JSON"),
            ("[]", "JSON object"),
            ('"x"', "JSON object"),
        ):
            with self.subTest(values=bad):
                with self.assertRaisesRegex(ValueError, text):
                    ProjectWritePayload(write_kind="create_bid", values_json=bad)
        self.assertEqual(
            ProjectWritePayload.from_values(
                "create_bid", {"b": 1, "a": "é"}
            ).values_json,
            '{"a":"\\u00e9","b":1}',
        )

    def test_import_payload_boundaries(self):
        ProjectImportPayload(
            source_path="a.osp", source_kind="osp", source_size=0, source_modified_ns=0
        )
        base = dict(
            source_path="a.ost", source_kind="ost", source_size=1, source_modified_ns=1
        )
        for override, text in (
            ({"source_path": ""}, "source path"),
            ({"source_kind": "OST"}, "OST or OSP"),
            ({"source_size": -1}, "cannot be negative"),
            ({"source_modified_ns": -1}, "cannot be negative"),
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, text):
                    ProjectImportPayload(**{**base, **override})
        self.assertEqual(ProjectImportPayload(**base).target_project_uid, "")


class PastePayloadContractTests(unittest.TestCase):
    def _takeoff(self, parent=None):
        return InsertTakeoffSpec("30", "20", "1", [0, 0, 1, 1], parent_uid=parent)

    def _annotation(self, kind="rect"):
        return InsertAnnotationSpec("20", kind, [0, 0, 1, 1], "red", 1.0)

    def _paste(self, **options):
        return PlanItemsPastePayload(
            source_bid_uid="7", destination_bid_uid="8", **options
        )

    def test_sources_and_specifications_must_align_and_be_present(self):
        self._paste(takeoff_source_uids=("1",), takeoff_specs=(self._takeoff(),))
        self._paste(
            annotation_source_uids=("rect/1",), annotation_specs=(self._annotation(),)
        )
        for options, text in (
            ({}, "at least one item"),
            ({"takeoff_source_uids": ("1",)}, "takeoff sources and specifications"),
            (
                {"takeoff_specs": (self._takeoff(),)},
                "takeoff sources and specifications",
            ),
            (
                {"annotation_source_uids": ("rect/1",)},
                "annotation sources and specifications",
            ),
            (
                {"annotation_specs": (self._annotation(),)},
                "annotation sources and specifications",
            ),
            (
                {
                    "takeoff_source_uids": ("1", "1"),
                    "takeoff_specs": (self._takeoff(), self._takeoff()),
                },
                "takeoff source identities must be unique",
            ),
            (
                {
                    "annotation_source_uids": ("rect/1", "rect/1"),
                    "annotation_specs": (self._annotation(), self._annotation()),
                },
                "annotation source identities must be unique",
            ),
        ):
            with self.subTest(options=sorted(options)):
                with self.assertRaisesRegex(ValueError, text):
                    self._paste(**options)

    def test_annotation_sources_must_be_type_qualified_and_match_their_spec(self):
        with self.assertRaisesRegex(ValueError, "type-qualified identities"):
            self._paste(
                annotation_source_uids=("oval/1",),
                annotation_specs=(self._annotation(),),
            )
        with self.assertRaisesRegex(ValueError, "Invalid annotation collaboration"):
            self._paste(
                annotation_source_uids=("1",), annotation_specs=(self._annotation(),)
            )

    def test_existing_parent_binding_needs_a_real_parent_uid(self):
        for parent in (None, "", "0", "None"):
            with self.subTest(parent=parent):
                with self.assertRaisesRegex(ValueError, "requires a parent UID"):
                    self._paste(
                        takeoff_source_uids=("1",),
                        takeoff_specs=(self._takeoff(parent),),
                        takeoff_external_parent_sources=("1",),
                    )
        bound = self._paste(
            takeoff_source_uids=("1", "2"),
            takeoff_specs=(self._takeoff("9"), self._takeoff()),
            takeoff_external_parent_sources=("1",),
        )
        self.assertEqual(bound.takeoff_external_parent_sources, ("1",))
        self._paste(
            takeoff_source_uids=("1", "2"),
            takeoff_specs=(self._takeoff(), self._takeoff("9")),
            takeoff_external_parent_sources=("2",),
        )


class MutationRequestContractTests(unittest.TestCase):
    def _kwargs(self, **overrides):
        values = dict(
            database_id="database",
            operation_id=OPERATION_ID,
            mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
            owning_surface="main-plan",
            resources=(ResourceRef("takeoff", "10", 1),),
        )
        values.update(overrides)
        return values

    def test_required_fields_are_validated(self):
        for override, text in (
            ({"database_id": ""}, "database ID"),
            ({"owning_surface": ""}, "owning surface"),
            ({"resources": ()}, "at least one resource"),
            ({"operation_id": ""}, "UUIDs"),
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, text):
                    QueuedMutationRequest(**self._kwargs(**override))
        request = QueuedMutationRequest(**self._kwargs())
        self.assertEqual(request.payload_format_version, 1)
        self.assertTrue(request.lifecycle_critical)
        self.assertEqual(request.page_uid, "")
        self.assertIsNone(request.bid_uid)
        self.assertIsNone(request.edit_lease_handle)

    def test_resources_are_sorted_deduplicated_and_not_part_of_the_hash(self):
        low = ResourceRef("takeoff", "1", 1)
        high = ResourceRef("takeoff", "2", 1)
        page = ResourceRef("page", "9", 1)
        first = QueuedMutationRequest(
            **self._kwargs(
                resources=(high, low, high), dependency_resources=(high, page, page)
            )
        )
        second = QueuedMutationRequest(**self._kwargs(resources=(low,)))
        self.assertEqual(first.resources, (low, high))
        self.assertEqual(first.dependency_resources, (page, high))
        self.assertEqual(first.request_hash, second.request_hash)
        changed = QueuedMutationRequest(
            **self._kwargs(mutation_type=CollaborationMutationType.PAGE_SETTINGS)
        )
        self.assertNotEqual(changed.request_hash, first.request_hash)
        versioned = canonical_mutation_request_hash(
            {
                "mutation_type": "plan_geometry",
                "payload_format_version": 1,
                "payload": None,
            }
        )
        self.assertEqual(first.request_hash, versioned)

    def test_lease_handle_must_cover_every_affected_resource(self):
        low = ResourceRef("takeoff", "1", 1)
        high = ResourceRef("takeoff", "2", 1)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit",
            owning_surface="main-plan",
            resources=(low, high),
        )
        QueuedMutationRequest(
            **self._kwargs(resources=(high, low), edit_lease_handle=handle)
        )
        QueuedMutationRequest(
            **self._kwargs(resources=(low,), edit_lease_handle=handle)
        )
        with self.assertRaisesRegex(ValueError, "own its affected resources"):
            QueuedMutationRequest(
                **self._kwargs(
                    resources=(low, ResourceRef("takeoff", "3", 1)),
                    edit_lease_handle=handle,
                )
            )

    def test_pending_sql_record_mirrors_the_request_and_validates_its_own_fields(self):
        low = ResourceRef("takeoff", "1", 1)
        high = ResourceRef("takeoff", "2", 1)
        request = QueuedMutationRequest(
            **self._kwargs(
                operation_id=OPERATION_ID.upper(),
                resources=(high, low),
                dependency_resources=(ResourceRef("page", "9", 1),),
                bid_uid=1,
                page_uid="9",
            )
        )
        record = PendingSqlOperationRecord.from_request(
            request, PendingMutationState.EXECUTING
        )
        self.assertEqual(
            (
                record.database_id,
                record.operation_id,
                record.mutation_type,
                record.request_hash,
                record.owning_surface,
                record.resources,
                record.dependency_resources,
                record.bid_uid,
                record.page_uid,
                record.state,
            ),
            (
                "database",
                OPERATION_ID,
                CollaborationMutationType.PLAN_GEOMETRY,
                request.request_hash,
                "main-plan",
                (low, high),
                (ResourceRef("page", "9", 1),),
                1,
                "9",
                PendingMutationState.EXECUTING,
            ),
        )
        self.assertEqual(
            PendingSqlOperationRecord.from_request(request).state,
            PendingMutationState.QUEUED,
        )
        valid = dict(
            database_id="database",
            operation_id=OPERATION_ID,
            mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
            request_hash="a" * 64,
            owning_surface="main-plan",
            resources=(low,),
        )
        for override, text in (
            ({"operation_id": "x"}, "UUIDs"),
            ({"database_id": ""}, "incomplete"),
            ({"owning_surface": ""}, "incomplete"),
            ({"resources": ()}, "incomplete"),
            ({"request_hash": "a" * 63}, "lowercase SHA-256"),
            ({"request_hash": "a" * 65}, "lowercase SHA-256"),
            ({"request_hash": "A" * 64}, "lowercase SHA-256"),
            ({"request_hash": "g" * 64}, "lowercase SHA-256"),
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, text):
                    PendingSqlOperationRecord(**{**valid, **override})
        PendingSqlOperationRecord(**valid)


class OutcomeContractTests(unittest.TestCase):
    def _conflict(self):
        return SynchronizationConflict(
            "database", ResourceRef("condition", "1", 8), "changed"
        )

    def test_conflict_and_failure_reason_only_ride_their_own_outcomes(self):
        conflict = self._conflict()
        builders = (
            (
                "execution",
                lambda status, **extra: MutationExecutionResult(
                    outcome_status=status, **extra
                ),
            ),
            (
                "queued",
                lambda status, **extra: QueuedMutationResult(
                    database_id="database",
                    runtime_generation=1,
                    operation_id=OPERATION_ID,
                    outcome_status=status,
                    **extra,
                ),
            ),
            (
                "database",
                lambda status, **extra: DatabaseMutationResult(
                    OPERATION_ID, status, **extra
                ),
            ),
        )
        for name, build in builders:
            for status in MutationOutcomeStatus:
                with self.subTest(builder=name, status=status):
                    if status is MutationOutcomeStatus.CONFLICT:
                        self.assertIs(
                            build(status, conflict=conflict).conflict, conflict
                        )
                    else:
                        with self.assertRaisesRegex(ValueError, "Only a conflict"):
                            build(status, conflict=conflict)
                    result = build(status)
                    self.assertIs(
                        result.commit_attempted,
                        status is MutationOutcomeStatus.COMMITTED,
                    )
        for status in MutationOutcomeStatus:
            with self.subTest(failure_reason=status):
                if status is MutationOutcomeStatus.FAILED_BEFORE_COMMIT:
                    DatabaseMutationResult(OPERATION_ID, status, failure_reason="boom")
                else:
                    with self.assertRaisesRegex(ValueError, "failed-before-commit"):
                        DatabaseMutationResult(
                            OPERATION_ID, status, failure_reason="boom"
                        )

    def test_explicit_commit_attempt_flag_is_preserved(self):
        for status in MutationOutcomeStatus:
            with self.subTest(status=status):
                self.assertTrue(
                    MutationExecutionResult(
                        outcome_status=status, commit_attempted=True
                    ).commit_attempted
                )
                self.assertTrue(
                    DatabaseMutationResult(
                        OPERATION_ID, status, commit_attempted=True
                    ).commit_attempted
                )

    def test_database_result_value_exists_only_for_a_committed_outcome(self):
        # Decision D4: the commands rely on "a value only when COMMITTED", so the
        # DTO enforces it instead of trusting every executor and fake.
        for status in MutationOutcomeStatus:
            for value in (False, True, 0, "", [], ["501"], {"a": 1}):
                with self.subTest(status=status, value=value):
                    if status is MutationOutcomeStatus.COMMITTED:
                        self.assertEqual(
                            DatabaseMutationResult(
                                OPERATION_ID, status, value=value
                            ).value,
                            value,
                        )
                    else:
                        with self.assertRaisesRegex(
                            ValueError, "Only a committed outcome may carry a value"
                        ):
                            DatabaseMutationResult(OPERATION_ID, status, value=value)
            with self.subTest(status=status, value=None):
                self.assertIsNone(DatabaseMutationResult(OPERATION_ID, status).value)

    def test_result_operation_ids_are_normalized_or_rejected(self):
        upper = OPERATION_ID.upper()
        queued = QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=upper,
            outcome_status=MutationOutcomeStatus.REJECTED,
        )
        database = DatabaseMutationResult(upper, MutationOutcomeStatus.REJECTED)
        durable = DurableOperationResult(
            database_id="database", operation_id=upper, found=False
        )
        self.assertEqual(
            (queued.operation_id, database.operation_id, durable.operation_id),
            (OPERATION_ID,) * 3,
        )
        with self.assertRaisesRegex(ValueError, "UUIDs"):
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="nope",
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        with self.assertRaisesRegex(ValueError, "UUIDs"):
            DatabaseMutationResult("nope", MutationOutcomeStatus.REJECTED)
        with self.assertRaisesRegex(ValueError, "UUIDs"):
            DurableOperationResult(database_id="d", operation_id="nope", found=False)

    def test_durable_result_validates_found_records_only(self):
        missing = DurableOperationResult(
            database_id="database", operation_id=OPERATION_ID, found=False
        )
        self.assertEqual(
            (missing.mutation_type, missing.request_hash, missing.result_payload),
            ("", "", ""),
        )
        found = dict(
            database_id="database",
            operation_id=OPERATION_ID,
            found=True,
            mutation_type="project_write",
            request_hash="b" * 64,
            result_format_version=1,
            result_payload="{}",
        )
        self.assertTrue(DurableOperationResult(**found).found)
        for override, text in (
            ({"mutation_type": "old"}, "noncanonical mutation type"),
            ({"mutation_type": ""}, "noncanonical mutation type"),
            ({"request_hash": "b" * 63}, "invalid request hash"),
            ({"request_hash": "B" * 64}, "invalid request hash"),
            ({"result_format_version": 2}, "incomplete"),
            ({"result_format_version": 0}, "incomplete"),
            ({"result_payload": ""}, "incomplete"),
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, text):
                    DurableOperationResult(**{**found, **override})

    def test_database_request_hash_and_identity_are_strict(self):
        valid = dict(
            database_id="database",
            session_id="session",
            operation_id=OPERATION_ID.upper(),
            mutation_type="plan_geometry",
            request_hash="c" * 64,
        )
        request = DatabaseMutationRequest(**valid)
        self.assertEqual(request.operation_id, OPERATION_ID)
        self.assertEqual(request.mutation_type, "plan_geometry")
        self.assertEqual(request.expected_versions, ())
        self.assertEqual(request.required_lock_tokens, ())
        self.assertIs(request.block_bid_child_locks, False)
        self.assertIs(request.block_bid_active_editors, False)
        for override, text in (
            ({"operation_id": "nope"}, "UUIDs"),
            ({"request_hash": "c" * 63}, "lowercase SHA-256"),
            ({"request_hash": "C" * 64}, "lowercase SHA-256"),
            ({"request_hash": "z" * 64}, "lowercase SHA-256"),
            ({"mutation_type": "PLAN_GEOMETRY"}, "canonical"),
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, text):
                    DatabaseMutationRequest(**{**valid, **override})


class ChangePollResultContractTests(unittest.TestCase):
    def _batch(self, **overrides):
        values = dict(
            database_id="database",
            feed_epoch="epoch",
            minimum_valid_version=1,
            high_water_version=5,
            delivered_through_version=4,
        )
        values.update(overrides)
        return DatabaseChangeBatch(**values)

    def test_observed_and_hydrated_batches_must_agree_on_every_cursor_field(self):
        observed = self._batch()
        result = DatabaseChangePollResult(
            observed, HydratedDatabaseChangeBatch(self._batch())
        )
        self.assertIs(result.observed_batch, observed)
        for override in (
            {"database_id": "other"},
            {"feed_epoch": "other"},
            {"minimum_valid_version": 2},
            {"high_water_version": 6},
            {"delivered_through_version": 3},
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, "must match"):
                    DatabaseChangePollResult(
                        observed, HydratedDatabaseChangeBatch(self._batch(**override))
                    )
        with_changes = HydratedDatabaseChangeBatch(
            self._batch(changes=(_poll_change(),))
        )
        DatabaseChangePollResult(observed, with_changes)


def _poll_change():
    return DatabaseChange(
        sequence=1,
        commit_version=2,
        transaction_id="t",
        source_session_id=None,
        resource=ResourceRef("condition", "1", 8),
        operation=ChangeOperation.UPDATE,
    )


class PreviewUidContractTests(unittest.TestCase):
    def test_preview_uids_are_namespaced_and_recognized_only_with_the_prefix(self):
        uid = queued_takeoff_preview_uid(OPERATION_ID, 3)
        self.assertEqual(uid, f"pending:takeoff-placement:{OPERATION_ID}:3")
        self.assertNotEqual(uid, queued_takeoff_preview_uid(OPERATION_ID, 4))
        self.assertNotEqual(uid, queued_takeoff_preview_uid(OTHER_OPERATION_ID, 3))
        self.assertTrue(is_queued_takeoff_preview_uid(uid))
        for other in (
            "",
            "1234",
            "pending:takeoff-placement",
            "xpending:takeoff-placement:",
        ):
            with self.subTest(uid=other):
                self.assertFalse(is_queued_takeoff_preview_uid(other))
        self.assertTrue(is_queued_takeoff_preview_uid("pending:takeoff-placement:"))


class CanonicalHashContractTests(unittest.TestCase):
    def _wire(self, payload):
        return hashlib.sha256(payload).hexdigest()

    def test_scalars_enums_dataclasses_and_nesting_have_one_wire_form(self):
        payload = {
            "b": [True, None, 1.5, "é"],
            "a": MutationOutcomeStatus.CONFLICT,
            "c": ConcurrencyToken(b"\x00\x00\x00\x00\x00\x00\x00\x09"),
            "d": ({"y": 1, "x": 2},),
        }
        wire = (
            b'{"a":"conflict","b":[true,null,1.5,"\\u00e9"],'
            b'"c":{"value":{"bytes":"0000000000000009"}},"d":[{"x":2,"y":1}]}'
        )
        self.assertEqual(canonical_mutation_request_hash(payload), self._wire(wire))

    def test_equivalent_containers_hash_alike_and_types_stay_distinct(self):
        self.assertEqual(
            canonical_mutation_request_hash({"a": (1, 2)}),
            canonical_mutation_request_hash({"a": [1, 2]}),
        )
        self.assertEqual(
            canonical_mutation_request_hash({"a": frozenset({3, 1, 2})}),
            canonical_mutation_request_hash({"a": {1, 2, 3}}),
        )
        self.assertNotEqual(
            canonical_mutation_request_hash({"a": [1, 2]}),
            canonical_mutation_request_hash({"a": [2, 1]}),
        )
        self.assertNotEqual(
            canonical_mutation_request_hash({"a": 1}),
            canonical_mutation_request_hash({"a": "1"}),
        )
        self.assertNotEqual(
            canonical_mutation_request_hash({"a": True}),
            canonical_mutation_request_hash({"a": 1.0}),
        )
        self.assertNotEqual(
            canonical_mutation_request_hash(b"\x01"),
            canonical_mutation_request_hash("01"),
        )
        self.assertEqual(
            canonical_mutation_request_hash({1: "x", 10: "y", 2: "z"}),
            canonical_mutation_request_hash({"1": "x", "10": "y", "2": "z"}),
        )


_KEYWORD_ONLY_DTOS = {
    "ReconciliationResult",
    "AuthoritativeMutationResult",
    "PlanItemsDeletePayload",
    "PlanItemsPastePayload",
    "PlanGeometryPayload",
    "PlanPropertyPayload",
    "PageSettingsPayload",
    "ProjectWritePayload",
    "ProjectImportPayload",
    "QueuedMutationRequest",
    "PendingMutation",
    "PendingSqlOperationRecord",
    "MutationExecutionResult",
    "QueuedMutationResult",
    "DurableOperationResult",
}


class _PlainEnum(enum.Enum):
    FIRST = "first-value"


class DtoShapeContractTests(unittest.TestCase):
    def _dtos(self):
        return {
            name: value
            for name, value in vars(collaboration_dtos).items()
            if isinstance(value, type)
            and dataclasses.is_dataclass(value)
            and value.__module__ == collaboration_dtos.__name__
        }

    def test_every_collaboration_dto_is_frozen_and_keyword_only_where_declared(self):
        dtos = self._dtos()
        self.assertGreaterEqual(len(dtos), 36)
        self.assertTrue(_KEYWORD_ONLY_DTOS.issubset(dtos))
        for name, cls in dtos.items():
            with self.subTest(dto=name):
                self.assertTrue(cls.__dataclass_params__.frozen)
                fields = dataclasses.fields(cls)
                self.assertEqual(
                    all(field.kw_only for field in fields),
                    name in _KEYWORD_ONLY_DTOS,
                )
                self.assertEqual(
                    any(field.kw_only for field in fields),
                    name in _KEYWORD_ONLY_DTOS,
                )

    def test_lease_and_staleness_windows_match_the_server_contract(self):
        self.assertEqual(collaboration_dtos.COLLABORATION_STALE_SECONDS, 45)
        self.assertEqual(collaboration_dtos.COLLABORATION_LOCK_SECONDS, 45)
        policy = collaboration_dtos.CollaborationPollingPolicy()
        self.assertLess(
            3 * policy.heartbeat_seconds, collaboration_dtos.COLLABORATION_STALE_SECONDS
        )

    def test_polling_policy_and_metrics_defaults(self):
        policy = collaboration_dtos.CollaborationPollingPolicy()
        self.assertEqual(
            (
                policy.selected_database_seconds,
                policy.active_edit_seconds,
                policy.inactive_database_seconds,
                policy.heartbeat_seconds,
                policy.jitter_ratio,
                policy.maximum_batch_size,
                policy.reconnect_backoff_seconds,
            ),
            (1.0, 0.5, 5.0, 10.0, 0.1, 500, (1.0, 2.0, 5.0, 10.0, 30.0)),
        )
        self.assertEqual(
            list(policy.reconnect_backoff_seconds),
            sorted(set(policy.reconnect_backoff_seconds)),
        )
        metrics = collaboration_dtos.CollaborationMetrics("database")
        self.assertEqual(
            dataclasses.astuple(metrics),
            ("database", 0, 0.0, 0, 0, 0, 0.0, 0, 0),
        )
        status = collaboration_dtos.CollaborationStatus(
            "database", collaboration_dtos.SynchronizationState.HEALTHY
        )
        self.assertEqual(
            (status.message, status.locked_resources, status.conflicted_resources),
            ("", frozenset(), frozenset()),
        )

    def test_record_defaults(self):
        session = collaboration_dtos.DatabaseSession("database", "session")
        self.assertEqual(session.last_acknowledged_version, 0)
        pending = collaboration_dtos.PendingMutation(request=_request())
        self.assertEqual(
            (pending.state, pending.runtime_generation, pending.message),
            (PendingMutationState.QUEUED, 0, ""),
        )
        durable = DurableOperationResult(
            database_id="database", operation_id=OPERATION_ID, found=False
        )
        self.assertEqual(durable.result_format_version, 0)
        self.assertEqual(
            collaboration_dtos.DatabaseMutationRequest(
                database_id="database",
                session_id="session",
                operation_id=OPERATION_ID,
                mutation_type="plan_geometry",
                request_hash="d" * 64,
            ).result_format_version,
            1,
        )


class IdentityAndHashEdgeTests(unittest.TestCase):
    def test_unknown_resource_types_and_length_boundary_messages(self):
        with self.assertRaisesRegex(ValueError, "Unknown collaboration resource type"):
            ResourceRef("folder", "1")
        with self.assertRaisesRegex(ValueError, "Unknown collaboration resource type"):
            ResourceRef("c" * 64, "1")
        with self.assertRaisesRegex(ValueError, "1 to 64 characters"):
            ResourceRef("c" * 65, "1")
        with self.assertRaisesRegex(ValueError, "1 to 64 characters"):
            ResourceRef("", "1")
        ResourceRef("condition", "x" * 128)

    def test_ordering_distinguishes_adjacent_bid_numbers(self):
        zero = ResourceRef("condition", "42", 0)
        one = ResourceRef("condition", "42", 1)
        eight = ResourceRef("condition", "42", 8)
        self.assertLess(zero, one)
        self.assertLess(one, eight)
        self.assertFalse(one < zero)
        self.assertFalse(zero < ResourceRef("condition", "42", 0))
        self.assertFalse(
            ResourceRef("condition", "42") < ResourceRef("condition", "42")
        )
        self.assertEqual(sorted((eight, one, zero)), [zero, one, eight])

    def test_non_uuid_session_identities_are_strictly_false(self):
        for left, right in (
            ("session-a", "session-b"),
            ("session-a", "session-a"),
            ("0", "0"),
            (0, 0),
        ):
            with self.subTest(left=left, right=right):
                self.assertIs(session_identities_equal(left, right), False)

    def test_plain_enums_encode_by_value_and_set_order_follows_the_escaped_text(self):
        self.assertEqual(
            canonical_mutation_request_hash({"kind": _PlainEnum.FIRST}),
            hashlib.sha256(b'{"kind":"first-value"}').hexdigest(),
        )
        self.assertEqual(
            canonical_mutation_request_hash({"values": {"z", "é"}}),
            hashlib.sha256(b'{"values":["\\u00e9","z"]}').hexdigest(),
        )

    def test_update_payloads_serialize_ascii_with_sorted_keys(self):
        for payload_type, kind in (
            (PlanPropertyPayload, "takeoff_text"),
            (PageSettingsPayload, "name"),
        ):
            with self.subTest(payload=payload_type.__name__):
                built = payload_type.from_updates(kind, [["1", {"b": "é", "a": 1}]])
                self.assertEqual(built.updates_json, '[["1",{"a":1,"b":"\\u00e9"}]]')

    def test_hash_validation_rejects_a_single_bad_character(self):
        one_bad = "a" * 63 + "g"
        low = ResourceRef("takeoff", "1", 1)
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            DatabaseMutationRequest(
                database_id="database",
                session_id="session",
                operation_id=OPERATION_ID,
                mutation_type="plan_geometry",
                request_hash=one_bad,
            )
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            PendingSqlOperationRecord(
                database_id="database",
                operation_id=OPERATION_ID,
                mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
                request_hash=one_bad,
                owning_surface="main-plan",
                resources=(low,),
            )
        with self.assertRaisesRegex(ValueError, "invalid request hash"):
            DurableOperationResult(
                database_id="database",
                operation_id=OPERATION_ID,
                found=True,
                mutation_type="project_write",
                request_hash=one_bad,
                result_format_version=1,
                result_payload="{}",
            )

    def test_pending_record_normalizes_its_own_identity_and_resources(self):
        low = ResourceRef("takeoff", "1", 1)
        high = ResourceRef("takeoff", "2", 1)
        page = ResourceRef("page", "9", 1)
        record = PendingSqlOperationRecord(
            database_id="database",
            operation_id=OPERATION_ID.upper(),
            mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
            request_hash="a" * 64,
            owning_surface="main-plan",
            resources=(high, low, high),
            dependency_resources=(high, page, page),
        )
        self.assertEqual(record.operation_id, OPERATION_ID)
        self.assertEqual(record.resources, (low, high))
        self.assertEqual(record.dependency_resources, (page, high))


class MutationRejectionReasonContractTests(unittest.TestCase):
    """Decision B2: a REJECTED outcome may carry the reason it was refused for
    (today only bid_locked); every other outcome may not, mirroring the D4 rule
    that a value exists only for COMMITTED."""

    def _builders(self):
        return (
            (
                "execution",
                lambda status, **extra: MutationExecutionResult(
                    outcome_status=status, **extra
                ),
            ),
            (
                "queued",
                lambda status, **extra: QueuedMutationResult(
                    database_id="database",
                    runtime_generation=1,
                    operation_id=OPERATION_ID,
                    outcome_status=status,
                    **extra,
                ),
            ),
            (
                "database",
                lambda status, **extra: DatabaseMutationResult(
                    OPERATION_ID, status, **extra
                ),
            ),
        )

    def test_the_reason_enum_and_message_are_the_pinned_contract(self):
        self.assertEqual(
            [(reason.name, reason.value) for reason in MutationRejectionReason],
            [("BID_LOCKED", "bid_locked")],
        )
        self.assertEqual(MutationRejectionReason.BID_LOCKED, "bid_locked")
        self.assertEqual(
            collaboration_dtos.BID_LOCKED_MESSAGE, "The active bid is locked"
        )
        self.assertEqual(
            rejection_reason_message(MutationRejectionReason.BID_LOCKED),
            "The active bid is locked",
        )

    def test_a_reason_rides_only_a_rejected_outcome_on_every_result_type(self):
        for name, build in self._builders():
            for status in MutationOutcomeStatus:
                with self.subTest(builder=name, status=status):
                    if status is MutationOutcomeStatus.REJECTED:
                        self.assertIs(
                            build(
                                status,
                                rejection_reason=MutationRejectionReason.BID_LOCKED,
                            ).rejection_reason,
                            MutationRejectionReason.BID_LOCKED,
                        )
                    else:
                        with self.assertRaisesRegex(
                            ValueError, "Only a rejected outcome"
                        ):
                            build(
                                status,
                                rejection_reason=MutationRejectionReason.BID_LOCKED,
                            )
                    self.assertIsNone(build(status).rejection_reason)

    def test_a_reason_must_be_a_member_of_the_enum(self):
        for name, build in self._builders():
            for bogus in ("bid_locked", "locked", 1, True, object()):
                with self.subTest(builder=name, reason=bogus):
                    with self.assertRaisesRegex(ValueError, "MutationRejectionReason"):
                        build(MutationOutcomeStatus.REJECTED, rejection_reason=bogus)

    def test_a_rejected_result_may_carry_a_message_and_no_value_conflict_or_commit(
        self,
    ):
        result = DatabaseMutationResult(
            OPERATION_ID,
            MutationOutcomeStatus.REJECTED,
            rejection_reason=MutationRejectionReason.BID_LOCKED,
        )
        self.assertEqual(
            (result.value, result.conflict, result.failure_reason),
            (None, None, None),
        )
        self.assertFalse(result.commit_attempted)
        self.assertEqual(result.consumed_lock_tokens, ())

    def test_unknown_reason_has_no_message(self):
        with self.assertRaisesRegex(ValueError, "Unsupported mutation rejection"):
            rejection_reason_message("another_reason")

    def test_the_bid_lock_exemption_defaults_off_and_is_not_part_of_the_request_hash(
        self,
    ):
        valid = dict(
            database_id="database",
            session_id="session",
            operation_id=OPERATION_ID,
            mutation_type="plan_items_delete",
            request_hash="c" * 64,
        )
        plain = DatabaseMutationRequest(**valid)
        exempt = DatabaseMutationRequest(**valid, bid_lock_exempt=True)
        self.assertIs(plain.bid_lock_exempt, False)
        self.assertIs(exempt.bid_lock_exempt, True)
        # the hash is supplied by the caller from the queued payload only: the flag
        # neither feeds nor changes it
        self.assertEqual(plain.request_hash, exempt.request_hash)
        queued = _request()
        self.assertNotIn("bid_lock_exempt", dataclasses.asdict(queued))
        self.assertNotIn("exempt", json.dumps(dataclasses.asdict(queued), default=str))
        self.assertEqual(
            queued.request_hash,
            canonical_mutation_request_hash(
                {
                    "mutation_type": queued.mutation_type.value,
                    "payload_format_version": queued.payload_format_version,
                    "payload": queued.payload,
                }
            ),
        )
        # no queued DTO or payload class can carry the exemption
        for cls in (
            QueuedMutationRequest,
            ProjectWritePayload,
            PlanItemsDeletePayload,
            PlanItemsPastePayload,
            PlanGeometryPayload,
            PlanPropertyPayload,
            PageSettingsPayload,
            ProjectImportPayload,
        ):
            with self.subTest(cls=cls.__name__):
                self.assertNotIn(
                    "bid_lock_exempt", {f.name for f in dataclasses.fields(cls)}
                )
