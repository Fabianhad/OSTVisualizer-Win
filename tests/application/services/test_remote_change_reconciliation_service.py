import unittest
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ChangeOperation,
    CollaborationMutationType,
    CollaborationPollingPolicy,
    CollaborationShutdownState,
    CollaborationStatus,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseChangePollResult,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DatabaseSession,
    DurableOperationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    HydratedDatabaseChangeBatch,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PendingMutationState,
    PendingSqlOperationRecord,
    PresenceMode,
    QueuedMutationRequest,
    QueuedMutationResult,
    ReconciliationFailureKind,
    ReconciliationResult,
    ResourceLock,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
    SynchronizationState,
    queued_takeoff_preview_uid,
    session_identities_equal,
)
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    COLLABORATION_RESOURCE_CATALOG,
    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
    SUPPORTED_REMOTE_RESOURCE_TYPES,
    CollaborationResourceFamily,
    coalesced_resource_type,
)
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.conflict_resolution_service import (
    ConflictResolutionService,
)
from ost_visualizer.application.services.database_concurrency_token_service import (
    DatabaseConcurrencyTokenService,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from ost_visualizer.application.services.remote_change_reconciliation_service import (
    RemoteChangeReconciliationService,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from tests.helpers.sql.collaboration import (
    _EventBus,
    _ProjectData,
    _TokenReader,
    _batch,
    _change,
    _token_service,
)


class RemoteChangeReconciliationServiceCollaborationTests(unittest.TestCase):
    def test_layer_rename_impact_matches_local_and_remote_projection(self):
        from dataclasses import replace
        from ost_visualizer.domain.entities.layer import BidLayer

        for name, fields, changes, expected in (
            ("Walls", ("name",), {"name": "Partitions"}, True),
            ("Image", ("name",), {"name": "Partitions"}, False),
            ("Walls", ("name",), {"name": "Annotation"}, False),
            ("Walls", ("show",), {"show": False}, False),
            ("Walls", ("name", "unknown"), {"name": "Partitions"}, False),
            ("Walls", ("name",), {"name": "Partitions", "show": False}, False),
        ):
            for local in (False, True):
                for deferred in (False, True):
                    with self.subTest(
                        name=name, fields=fields, local=local, deferred=deferred
                    ):
                        data = _ProjectData("database")
                        data.layers = [BidLayer("20", "8", name, True, 1)]
                        updated = replace(data.layers[0], **changes)
                        events = _EventBus()
                        tokens, drafts = _token_service()
                        service = RemoteChangeReconciliationService(
                            data, events, tokens, drafts, ConflictResolutionService()
                        )
                        change = _change(
                            "database",
                            ResourceRef("layer", "20", 8),
                            changed_fields=fields,
                        )
                        barrier = (
                            RemoteProjectionBarrier(
                                database_id="database",
                                runtime_generation=1,
                                is_runtime_current=lambda *_args: True,
                                on_complete=lambda _ok: None,
                            )
                            if deferred
                            else None
                        )
                        result = service.apply(
                            HydratedDatabaseChangeBatch(
                                _batch("database", "epoch", 1, 2, (change,)),
                                bid_data_by_bid={
                                    8: BidLoadResult(bid_layers=[updated])
                                },
                            ),
                            local_completion=local,
                            projection_barrier=barrier,
                        )
                        self.assertTrue(result.applied)
                        self.assertEqual(data.layers, [updated])
                        for event, payload in events.published:
                            if event is AppEvents.REMOTE_BID_CONTENT_CHANGED:
                                self.assertEqual(
                                    payload["mesh_scene_unchanged"], expected
                                )
                                self.assertEqual(
                                    payload["image_sources_unchanged"], expected
                                )
                            elif event is AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED:
                                self.assertEqual(
                                    payload["mesh_scene_unchanged"], expected
                                )

    def test_page_refresh_preserves_sources_only_for_known_metadata_updates(self):
        for fields, operation, expected in (
            (("scale",), ChangeOperation.UPDATE, True),
            (("name",), ChangeOperation.UPDATE, True),
            (("name", "scale"), ChangeOperation.UPDATE, True),
            (("name", "overlay_image"), ChangeOperation.UPDATE, False),
            (("name",), ChangeOperation.DELETE, False),
            ((), ChangeOperation.UPDATE, False),
            (("scale", "overlay_image"), ChangeOperation.UPDATE, False),
            (("overlay_image",), ChangeOperation.UPDATE, False),
            (("image_path",), ChangeOperation.UPDATE, False),
            (("show_mode",), ChangeOperation.UPDATE, True),
            (("show_mode", "invert", "bitonal"), ChangeOperation.UPDATE, True),
            (("show_mode", "scale"), ChangeOperation.UPDATE, True),
            (("show_mode", "unknown"), ChangeOperation.UPDATE, False),
            (("invert",), ChangeOperation.UPDATE, True),
            (("bitonal",), ChangeOperation.UPDATE, True),
            (("image_adjustments",), ChangeOperation.UPDATE, False),
            (("invert", "overlay_image"), ChangeOperation.UPDATE, False),
            (("overlay_rect",), ChangeOperation.UPDATE, True),
            (("overlay_rect", "overlay_image"), ChangeOperation.UPDATE, False),
            (("scale",), ChangeOperation.DELETE, False),
        ):
            for local_completion in (False, True):
                with self.subTest(
                    fields=fields, operation=operation, local=local_completion
                ):
                    events = _EventBus()
                    tokens, drafts = _token_service()
                    service = RemoteChangeReconciliationService(
                        _ProjectData("database"),
                        events,
                        tokens,
                        drafts,
                        ConflictResolutionService(),
                    )
                    change = _change(
                        "database",
                        ResourceRef("page", "20", 8),
                        changed_fields=fields,
                        operation=operation,
                    )
                    hydrated = HydratedDatabaseChangeBatch(
                        _batch("database", "epoch", 1, 2, (change,)),
                        bid_data_by_bid={
                            8: BidLoadResult(pages={"20": Page(uid="20", name="Sheet")})
                        },
                        cover_sheet_by_bid={8: object()},
                        page_delete_content_uids_by_bid={8: frozenset()},
                    )
                    self.assertTrue(
                        service.apply(
                            hydrated, local_completion=local_completion
                        ).applied
                    )
                    content = [
                        payload
                        for event, payload in events.published
                        if event is AppEvents.REMOTE_BID_CONTENT_CHANGED
                    ]
                    self.assertEqual(len(content), 1)
                    self.assertEqual(content[0]["image_sources_unchanged"], expected)
                    self.assertEqual(
                        content[0]["mesh_scene_unchanged"],
                        fields == ("name",) and operation == ChangeOperation.UPDATE,
                    )
                    texture_only = (
                        bool(fields)
                        and set(fields).issubset({"show_mode", "invert", "bitonal"})
                        and operation == ChangeOperation.UPDATE
                    )
                    self.assertEqual(content[0]["page_texture_only"], texture_only)
                    events.published.clear()
                    barrier = RemoteProjectionBarrier(
                        database_id="database",
                        runtime_generation=1,
                        is_runtime_current=lambda *_args: True,
                        on_complete=lambda _success: None,
                    )
                    service.apply(
                        hydrated,
                        local_completion=local_completion,
                        projection_barrier=barrier,
                    )
                    projections = [
                        payload
                        for event, payload in events.published
                        if event is AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
                    ]
                    self.assertEqual(len(projections), 1)
                    self.assertEqual(projections[0]["page_texture_only"], texture_only)
                    self.assertEqual(
                        projections[0]["mesh_scene_unchanged"],
                        fields == ("name",) and operation == ChangeOperation.UPDATE,
                    )

    def test_condition_and_area_remote_batch_merges_once(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        condition_resource = ResourceRef("condition", "42", 8)
        area_resource = ResourceRef("area", "6", 8)
        batch = _batch(
            database_id,
            "epoch",
            1,
            2,
            (
                _change(
                    database_id,
                    condition_resource,
                    1,
                    changed_fields=("name", "z_value"),
                ),
                _change(database_id, area_resource, 2),
            ),
        )
        hydrated = HydratedDatabaseChangeBatch(
            batch,
            conditions_by_bid={8: {"42": Condition(uid="42", name="Remote")}},
            condition_folders_by_bid={8: {}},
            areas_by_bid={
                8: (
                    BidArea(
                        uid="6",
                        bid_uid="8",
                        parent_uid="0",
                        name="Remote Area",
                        sequence=1,
                    ),
                )
            },
        )
        self.assertTrue(service.apply(hydrated).applied)
        self.assertEqual(set(project_data.conditions), {"42"})
        self.assertEqual([area.uid for area in project_data.areas], ["6"])
        names = [event for event, _payload in events.published]
        self.assertEqual(names.count(AppEvents.CONDITIONS_CHANGED), 1)
        self.assertEqual(names.count(AppEvents.REMOTE_AREAS_CHANGED), 1)
        condition_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.CONDITIONS_CHANGED
        )
        self.assertEqual(condition_event["changed_fields"], ["name", "z_value"])
        self.assertEqual(condition_event["change_operations"], ["update"])
        self.assertTrue(condition_event["invalidates_undo"])
        self.assertFalse(condition_event["local_completion"])

    def test_remote_transaction_publishes_one_deferred_plan_projection(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("condition", "42", 8),
                        1,
                        changed_fields=("name",),
                    ),
                    _change(database_id, ResourceRef("area", "6", 8), 2),
                ),
            ),
            conditions_by_bid={8: {"42": Condition(uid="42", name="Remote")}},
            condition_folders_by_bid={8: {}},
            areas_by_bid={
                8: (
                    BidArea(
                        uid="6",
                        bid_uid="8",
                        parent_uid="0",
                        name="Remote Area",
                        sequence=1,
                    ),
                )
            },
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        projected = [
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
        ]
        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["runtime_generation"], 5)
        self.assertEqual(projected[0]["condition_uids"], ("42",))
        self.assertEqual(projected[0]["condition_changed_fields"], ("name",))
        self.assertTrue(projected[0]["areas_changed"])
        granular = [
            payload
            for event, payload in events.published
            if event
            in {
                AppEvents.CONDITIONS_CHANGED,
                AppEvents.REMOTE_AREAS_CHANGED,
            }
        ]
        self.assertEqual(
            [payload["defer_plan_projection"] for payload in granular],
            [True, True],
        )

    def test_mixed_batch_marks_single_aggregate_owners(self):
        for has_condition in (False, True):
            for deferred in (False, True):
                for local in (False, True):
                    with self.subTest(
                        condition=has_condition, deferred=deferred, local=local
                    ):
                        database_id = "database"
                        events = _EventBus()
                        data = _ProjectData(database_id)
                        data.conditions = {"42": Condition(uid="42")}
                        tokens, drafts = _token_service()
                        service = RemoteChangeReconciliationService(
                            data, events, tokens, drafts, ConflictResolutionService()
                        )
                        takeoff = Takeoff(uid="30", condition_uid="42", page_uid="20")
                        changes = [
                            _change(database_id, ResourceRef("area", "6", 8), 1),
                            _change(database_id, ResourceRef("takeoff", "30", 8), 2),
                            _change(database_id, ResourceRef("layer", "7", 8), 3),
                        ]
                        if has_condition:
                            changes.append(
                                _change(
                                    database_id, ResourceRef("condition", "42", 8), 4
                                )
                            )
                        hydrated = HydratedDatabaseChangeBatch(
                            _batch(database_id, "epoch", 1, 4, tuple(changes)),
                            conditions_by_bid=(
                                {8: data.conditions} if has_condition else {}
                            ),
                            condition_folders_by_bid={8: {}} if has_condition else {},
                            areas_by_bid={
                                8: (
                                    BidArea(
                                        uid="6",
                                        bid_uid="8",
                                        parent_uid="0",
                                        name="New",
                                        sequence=1,
                                    ),
                                )
                            },
                            bid_data_by_bid={
                                8: BidLoadResult(
                                    bid_takeoffs=[takeoff],
                                    pages={
                                        "20": Page(
                                            uid="20", name="Sheet", takeoffs=[takeoff]
                                        )
                                    },
                                )
                            },
                        )
                        barrier = (
                            RemoteProjectionBarrier(
                                database_id=database_id,
                                runtime_generation=5,
                                is_runtime_current=lambda *args: True,
                                on_complete=lambda success: None,
                            )
                            if deferred
                            else None
                        )
                        self.assertTrue(
                            service.apply(
                                hydrated, barrier, local_completion=local
                            ).applied
                        )
                        area = next(
                            payload
                            for event, payload in events.published
                            if event == AppEvents.REMOTE_AREAS_CHANGED
                        )
                        content = next(
                            payload
                            for event, payload in events.published
                            if event == AppEvents.REMOTE_BID_CONTENT_CHANGED
                        )
                        self.assertTrue(area["takeoff_family_pending"])
                        self.assertFalse(area["summary_refresh_required"])
                        self.assertTrue(content["area_family_projected"])
                        self.assertEqual(
                            content["condition_family_projected"], has_condition
                        )
                        self.assertEqual(
                            content["affected_page_uids_by_family"]["takeoffs"], ("20",)
                        )

    def test_local_area_completion_is_identified_on_granular_event(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("area", "6", 8), 2),),
            ),
            areas_by_bid={
                8: (
                    BidArea(
                        uid="6",
                        bid_uid="8",
                        parent_uid="0",
                        name="Local Area",
                        sequence=1,
                    ),
                )
            },
        )
        self.assertTrue(service.apply(hydrated, local_completion=True).applied)
        area_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.REMOTE_AREAS_CHANGED
        )
        self.assertTrue(area_event["local_completion"])

    def test_local_condition_completion_is_identified_on_granular_event(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("condition", "42", 8),
                        2,
                        changed_fields=("name",),
                    ),
                ),
            ),
            conditions_by_bid={8: {"42": Condition(uid="42", name="Local")}},
            condition_folders_by_bid={8: {}},
        )
        self.assertTrue(service.apply(hydrated, local_completion=True).applied)
        condition_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.CONDITIONS_CHANGED
        )
        self.assertTrue(condition_event["local_completion"])
        self.assertFalse(condition_event["invalidates_undo"])

    def test_condition_folder_only_change_is_not_projected_as_condition_geometry(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("condition_folder", "5", 8),
                        1,
                        changed_fields=("name",),
                    ),
                    _change(
                        database_id,
                        ResourceRef("conditions_collection", "8", 8),
                        2,
                    ),
                ),
            ),
            conditions_by_bid={8: {"42": Condition(uid="42", name="Walls")}},
            condition_folders_by_bid={8: {"5": object()}},
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        condition_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.CONDITIONS_CHANGED
        )
        self.assertEqual(condition_event["condition_uids"], [])
        self.assertEqual(condition_event["changed_fields"], ["condition_folder"])
        self.assertEqual(condition_event["change_operations"], [])
        self.assertFalse(
            any(
                event is AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
                for event, _payload in events.published
            )
        )

    def test_valid_remote_takeoff_reconciles_and_requests_one_active_plan_update(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        takeoff = Takeoff(uid="30", condition_uid="10", page_uid="20")
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("takeoff", "30", 8), 2),),
            ),
            conditions_by_bid={8: {"10": Condition(uid="10")}},
            condition_folders_by_bid={8: {}},
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[takeoff],
                    pages={"20": Page(uid="20", name="Sheet", takeoffs=[takeoff])},
                )
            },
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        content_events = [
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_BID_CONTENT_CHANGED
        ]
        projection_events = [
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
        ]
        self.assertEqual(len(content_events), 1)
        self.assertEqual(content_events[0]["families"], ["takeoffs"])
        self.assertEqual(len(projection_events), 1)

    def test_remote_takeoff_projection_carries_old_and_new_page_ownership(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        project_data.takeoffs = [
            Takeoff(
                uid="takeoff-1",
                condition_uid="10",
                page_uid="page-1",
            )
        ]
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        moved_takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="10",
            page_uid="page-2",
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("takeoff", "takeoff-1", 8),
                        2,
                    ),
                ),
            ),
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[moved_takeoff],
                    pages={
                        "page-2": Page(
                            uid="page-2", name="Second", takeoffs=[moved_takeoff]
                        )
                    },
                )
            },
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        content = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_BID_CONTENT_CHANGED
        )
        projection = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
        )
        self.assertEqual(
            content["affected_page_uids_by_family"],
            {"takeoffs": ("page-1", "page-2")},
        )
        self.assertEqual(
            projection["affected_page_uids_by_family"],
            {"takeoffs": ("page-1", "page-2")},
        )
        # The old Page must still be projected when its final Takeoff is deleted.
        events.published.clear()
        deletion = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                2,
                3,
                (
                    _change(
                        database_id,
                        ResourceRef("takeoff", "takeoff-1", 8),
                        3,
                        operation=ChangeOperation.DELETE,
                    ),
                ),
            ),
            bid_data_by_bid={8: BidLoadResult()},
        )
        self.assertTrue(service.apply(deletion).applied)
        content = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_BID_CONTENT_CHANGED
        )
        self.assertEqual(
            content["affected_page_uids_by_family"], {"takeoffs": ("page-2",)}
        )
        self.assertFalse(content["condition_family_projected"])

    def test_remote_annotation_projection_carries_old_and_new_page_ownership(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.annotations = [
            BidAnnotation(
                uid="annotation-1",
                annotation_type=ANNOTATION_TYPE_TEXT,
                page_uid="page-1",
            )
        ]
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        moved_annotation = BidAnnotation(
            uid="annotation-1",
            annotation_type=ANNOTATION_TYPE_TEXT,
            page_uid="page-2",
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("annotation", "text/annotation-1", 8),
                        2,
                    ),
                ),
            ),
            bid_data_by_bid={8: BidLoadResult(bid_annotations=[moved_annotation])},
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        content = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_BID_CONTENT_CHANGED
        )
        projection = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
        )
        self.assertEqual(
            content["affected_page_uids_by_family"],
            {"annotations": ("page-1", "page-2")},
        )
        self.assertEqual(
            projection["affected_page_uids_by_family"],
            {"annotations": ("page-1", "page-2")},
        )

    def test_local_takeoff_projection_replaces_transient_identity_as_one_change(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        operation_id = "54a05683-1032-431d-b57b-3552317fc74b"
        preview_uid = queued_takeoff_preview_uid(operation_id, 0)
        takeoff = Takeoff(uid="30", condition_uid="10", page_uid="20")
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("takeoff", "30", 8), 2),),
            ),
            conditions_by_bid={8: {"10": Condition(uid="10")}},
            condition_folders_by_bid={8: {}},
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[takeoff],
                    pages={"20": Page(uid="20", name="Sheet", takeoffs=[takeoff])},
                )
            },
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
            resource_uid_aliases_by_family={"takeoffs": (preview_uid,)},
        )
        self.assertTrue(service.apply(hydrated, barrier, local_completion=True).applied)
        self.assertEqual(project_data.removed_transient_takeoff_uids, [preview_uid])
        content = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_BID_CONTENT_CHANGED
        )
        self.assertTrue(content["condition_family_projected"])
        projection = next(
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED
        )
        self.assertEqual(
            content["resource_uids_by_family"]["takeoffs"],
            sorted((preview_uid, "30")),
        )
        self.assertEqual(
            projection["resource_uids_by_family"]["takeoffs"],
            tuple(sorted((preview_uid, "30"))),
        )

    def test_self_only_checkpoint_does_not_schedule_plan_projection(self):
        database_id = "database"
        events = _EventBus()
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            _ProjectData(database_id),
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(
            service.apply(
                HydratedDatabaseChangeBatch(_batch(database_id, "epoch", 1, 2, ())),
                barrier,
            ).applied
        )
        self.assertNotIn(
            AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
            [event for event, _payload in events.published],
        )

    def test_hierarchy_only_change_does_not_schedule_plan_projection(self):
        database_id = "database"
        events = _EventBus()
        tokens, drafts = _token_service()

        class _HierarchyProjectData(_ProjectData):
            def replace_database_hierarchy(self, _file_entry, _cdn_types):
                pass

        service = RemoteChangeReconciliationService(
            _HierarchyProjectData(database_id),
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        hierarchy_file = HierarchyFileEntry(
            file_path=database_id,
            display_name="SQL",
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("database", database_id), 2),),
            ),
            hierarchy_file=hierarchy_file,
            settings_defaults={"next_bid_no": 1},
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        published = [event for event, _payload in events.published]
        self.assertIn(AppEvents.REMOTE_HIERARCHY_CHANGED, published)
        self.assertNotIn(AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED, published)

    def test_mixed_hierarchy_condition_event_assigns_sidebar_refresh_to_condition(self):
        database_id = "database"
        events = _EventBus()
        tokens, drafts = _token_service()

        class _HierarchyProjectData(_ProjectData):
            def replace_database_hierarchy(self, _file_entry, _cdn_types):
                pass

        service = RemoteChangeReconciliationService(
            _HierarchyProjectData(database_id),
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(database_id, ResourceRef("database", database_id), 1),
                    _change(database_id, ResourceRef("condition", "42", 8), 2),
                ),
            ),
            hierarchy_file=HierarchyFileEntry(
                file_path=database_id,
                display_name="SQL",
            ),
            conditions_by_bid={8: {"42": Condition(uid="42", name="Remote")}},
            condition_folders_by_bid={8: {}},
            settings_defaults={"next_bid_no": 1},
        )
        self.assertTrue(service.apply(hydrated).applied)
        hierarchy_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.REMOTE_HIERARCHY_CHANGED
        )
        self.assertTrue(hierarchy_event["condition_family_projected"])
        self.assertEqual(
            sum(
                event is AppEvents.CONDITIONS_CHANGED
                for event, _payload in events.published
            ),
            1,
        )

    def test_condition_type_only_change_refreshes_conditions_without_view_rebuild(self):
        database_id = "database"
        events = _EventBus()
        tokens, drafts = _token_service()

        class _ConditionTypeProjectData(_ProjectData):
            def replace_database_hierarchy(self, _file_entry, _cdn_types):
                pass

        service = RemoteChangeReconciliationService(
            _ConditionTypeProjectData(database_id),
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        hierarchy_file = HierarchyFileEntry(
            file_path=database_id,
            display_name="SQL",
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("condition_type", "5"),
                        1,
                        changed_fields=("name",),
                    ),
                    _change(
                        database_id,
                        ResourceRef("condition_types_collection", "database"),
                        2,
                    ),
                ),
            ),
            hierarchy_file=hierarchy_file,
            cdn_types={"5": CdnType(uid="5", name="Concrete")},
            settings_defaults={"next_bid_no": 1},
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=5,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(service.apply(hydrated, barrier).applied)
        condition_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.CONDITIONS_CHANGED
        )
        self.assertEqual(condition_event["changed_fields"], ["condition_type_catalog"])
        published = [event for event, _payload in events.published]
        self.assertNotIn(AppEvents.REMOTE_HIERARCHY_CHANGED, published)
        self.assertNotIn(AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED, published)

    def test_initial_sql_hierarchy_registration_includes_cdn_types(self):
        database_id = "sql-database"
        registered = []

        class _InactiveProjectData(_ProjectData):
            def __init__(self):
                super().__init__("access-database")

            def replace_database_hierarchy(self, file_entry, cdn_types):
                registered.append((file_entry, cdn_types))

        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            _InactiveProjectData(),
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        hierarchy_file = HierarchyFileEntry(
            file_path=database_id,
            display_name="SQL",
        )
        cdn_types = {"1": CdnType(uid="1", name="Linear")}
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                1,
                (
                    _change(
                        database_id,
                        ResourceRef("database", database_id),
                    ),
                ),
            ),
            hierarchy_file=hierarchy_file,
            cdn_types=cdn_types,
            settings_defaults={"next_bid_no": 1},
        )
        self.assertTrue(service.apply(hydrated).applied)
        self.assertEqual(registered, [(hierarchy_file, cdn_types)])

    def test_remote_events_publish_only_after_all_model_merges(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)

        def switch_active_bid(**_payload):
            project_data.bid_ref = BidRef(database_id, "9")

        events.subscribe(AppEvents.CONDITIONS_CHANGED, switch_active_bid)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            2,
            (
                _change(database_id, ResourceRef("condition", "42", 8), 1),
                _change(database_id, ResourceRef("area", "6", 8), 2),
            ),
        )
        hydrated = HydratedDatabaseChangeBatch(
            batch,
            conditions_by_bid={8: {"42": Condition(uid="42", name="Remote")}},
            condition_folders_by_bid={8: {}},
            areas_by_bid={
                8: (
                    BidArea(
                        uid="6",
                        bid_uid="8",
                        parent_uid="0",
                        name="Remote Area",
                        sequence=1,
                    ),
                )
            },
        )
        self.assertTrue(service.apply(hydrated).applied)
        self.assertEqual([area.uid for area in project_data.areas], ["6"])

    def test_incomplete_remote_batch_does_not_advance_tokens_or_partial_merge(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        tokens, drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")
        project_data = _ProjectData(database_id)
        project_data.conditions = {"old": Condition(uid="old", name="Old")}
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            2,
            (_change(database_id, resource, 2),),
        )
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)).applied)
        self.assertEqual(set(project_data.conditions), {"old"})
        self.assertEqual(
            tokens.expected_versions(database_id, (resource,))[0].expected,
            initial,
        )

    def test_incomplete_cover_sheet_batch_does_not_cache_partial_snapshots(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            2,
            (
                _change(
                    database_id,
                    ResourceRef("cover_sheet", "8", 8),
                    2,
                ),
            ),
        )
        result = service.apply(
            HydratedDatabaseChangeBatch(
                batch,
                cover_sheet_by_bid={8: object()},
            )
        )
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind,
            ReconciliationFailureKind.MALFORMED_PAYLOAD,
        )
        self.assertEqual(project_data.cover_sheets, {})
        self.assertEqual(project_data.page_delete_content, {})

    def test_malformed_remote_takeoff_graph_is_rejected_before_projection(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        change = _change(database_id, ResourceRef("takeoffs_collection", "8", 8), 2)
        orphan = Takeoff(
            uid="4485",
            condition_uid="10",
            page_uid="20",
            parent_uid="4393",
        )
        hydrated = HydratedDatabaseChangeBatch(
            _batch(database_id, "epoch", 1, 2, (change,)),
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[orphan],
                    pages={"20": Page(uid="20", name="Sheet", takeoffs=[orphan])},
                )
            },
        )
        result = service.apply(hydrated)
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind, ReconciliationFailureKind.MALFORMED_PAYLOAD
        )
        self.assertEqual(events.published, [])

    def test_reconciliation_returns_typed_result_without_mutable_failure_state(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        malformed = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (_change(database_id, ResourceRef("condition", "42", 8), 2),),
            )
        )
        result = service.apply(malformed)
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind,
            ReconciliationFailureKind.MALFORMED_PAYLOAD,
        )
        self.assertFalse(hasattr(service, "last_failure_kind"))

    def test_remote_takeoff_cycle_is_rejected_before_projection(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, _EventBus(), tokens, drafts, ConflictResolutionService()
        )
        first = Takeoff(uid="30", condition_uid="10", page_uid="20", parent_uid="31")
        second = Takeoff(uid="31", condition_uid="10", page_uid="20", parent_uid="30")
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("takeoffs_collection", "8", 8),
                        2,
                    ),
                ),
            ),
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[first, second],
                    pages={
                        "20": Page(uid="20", name="Sheet", takeoffs=[first, second])
                    },
                )
            },
        )
        result = service.apply(hydrated)
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind, ReconciliationFailureKind.MALFORMED_PAYLOAD
        )

    def test_remote_takeoff_with_missing_condition_is_rejected(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, _EventBus(), tokens, drafts, ConflictResolutionService()
        )
        takeoff = Takeoff(uid="30", condition_uid="999", page_uid="20")
        hydrated = HydratedDatabaseChangeBatch(
            _batch(
                database_id,
                "epoch",
                1,
                2,
                (
                    _change(
                        database_id,
                        ResourceRef("takeoffs_collection", "8", 8),
                        2,
                    ),
                ),
            ),
            bid_data_by_bid={
                8: BidLoadResult(
                    bid_takeoffs=[takeoff],
                    pages={"20": Page(uid="20", name="Sheet", takeoffs=[takeoff])},
                )
            },
        )
        result = service.apply(hydrated)
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind, ReconciliationFailureKind.MALFORMED_PAYLOAD
        )

    def test_remote_bid_change_is_acknowledged_when_no_bid_is_active(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        project_data.bid_ref = None
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            1,
            (_change(database_id, ResourceRef("condition", "42", 8)),),
        )
        self.assertTrue(service.apply(HydratedDatabaseChangeBatch(batch)).applied)
        self.assertEqual(events.published, [])

    def test_default_layer_change_uses_authoritative_reconciliation(self):
        self.assertIn("default_layers_collection", SUPPORTED_REMOTE_RESOURCE_TYPES)
        database_id = "database"
        project_data = _ProjectData(database_id)
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        resource = ResourceRef("default_layers_collection", "database")
        batch = _batch(
            database_id,
            "epoch",
            1,
            2,
            (_change(database_id, resource, 2),),
        )
        hydrated = HydratedDatabaseChangeBatch(
            batch,
            default_layers=(
                BidLayer(
                    uid="5",
                    bid_uid="",
                    name="Default",
                    show=True,
                    sequence=1,
                    is_template=True,
                ),
            ),
        )
        self.assertTrue(service.apply(hydrated).applied)
        self.assertEqual(
            project_data.database_settings[database_id]["default_layers"][0].uid,
            "5",
        )
        self.assertEqual(len(tokens.expected_versions(database_id, (resource,))), 1)

    def test_master_data_change_replaces_all_authoritative_lists_and_publishes(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        events = _EventBus()
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        resources = (
            ResourceRef("job_statuses_collection", database_id),
            ResourceRef("employees_collection", database_id),
            ResourceRef("pay_classes_collection", database_id),
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            3,
            tuple(
                _change(database_id, resource, sequence)
                for sequence, resource in enumerate(resources, start=1)
            ),
        )
        hydrated = HydratedDatabaseChangeBatch(
            batch,
            job_statuses=(JobStatus("job-1", "Open"),),
            employees=(Employee("employee-1", first_name="Ava"),),
            pay_classes=(PayClass("pay-1", "Regular"),),
            used_job_status_uids=frozenset({"job-1"}),
            used_employee_uids=frozenset({"employee-1"}),
        )
        self.assertTrue(service.apply(hydrated).applied)
        settings = project_data.database_settings[database_id]
        self.assertEqual(settings["job_statuses"][0].uid, "job-1")
        self.assertEqual(settings["employees"][0].uid, "employee-1")
        self.assertEqual(settings["pay_classes"][0].uid, "pay-1")
        master_events = [
            payload
            for event, payload in events.published
            if event == AppEvents.REMOTE_MASTER_DATA_CHANGED
        ]
        self.assertEqual(
            master_events,
            [
                {
                    "database_id": database_id,
                    "families": ["job_statuses", "employees", "pay_classes"],
                }
            ],
        )

    def test_inactive_database_rejects_incomplete_cover_sheet_hydration(self):
        project_data = _ProjectData("other-database")
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change(
                    "database",
                    ResourceRef("cover_sheet", "8", 8),
                    2,
                ),
            ),
        )
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)).applied)

    def test_remote_local_edit_conflict_is_resource_scoped(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        tokens, drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")
        drafts.begin(
            draft_type="condition",
            database_id=database_id,
            bid_uid=8,
            page_uid=None,
            owning_surface="test",
            affected_resources=(resource,),
            base_tokens=tokens.tokens_for_resources(database_id, (resource,)),
        )
        events = _EventBus()
        service = RemoteChangeReconciliationService(
            _ProjectData(database_id),
            events,
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        batch = _batch(
            database_id,
            "epoch",
            1,
            2,
            (_change(database_id, resource, 2),),
        )
        self.assertFalse(service.apply(HydratedDatabaseChangeBatch(batch)).applied)
        event, payload = events.published[-1]
        self.assertIs(event, AppEvents.SYNCHRONIZATION_CONFLICT)
        self.assertFalse(payload["blocks_database"])
        self.assertEqual(payload["bid_uid"], "8")
