import unittest
from dataclasses import replace
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ConcurrencyToken,
    HydratedDatabaseChangeBatch,
    ReconciliationFailureKind,
    ReconciliationResult,
    ResourceRef,
    queued_takeoff_preview_uid,
)
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.conflict_resolution_service import (
    ConflictResolutionService,
)
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
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from tests.application.services.reconciliation_support import (
    _EventBus,
    _ProjectData,
    _TokenReader,
    _batch,
    _change,
    _cover_sheet,
    _token_service,
)


class RemoteChangeReconciliationServiceCollaborationTests(unittest.TestCase):
    @staticmethod
    def _make_service(database_id="database"):
        data = _ProjectData(database_id)
        events = _EventBus()
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            data, events, tokens, drafts, ConflictResolutionService()
        )
        return service, data, events, tokens

    def test_navigation_owner_requires_exact_bid_and_database_lifetime(self):
        service, data, _events, _tokens = self._make_service()
        owner = service.capture_navigation_owner("database")
        self.assertIs(owner, data.bid)
        self.assertTrue(service.navigation_owner_is_current("database", owner))
        self.assertIsNone(service.capture_navigation_owner("other-database"))
        self.assertFalse(service.navigation_owner_is_current("other-database", owner))
        data.bid = replace(data.bid)
        self.assertFalse(service.navigation_owner_is_current("database", owner))
        replacement_owner = service.capture_navigation_owner("database")
        self.assertIs(replacement_owner, data.bid)
        data.bid_ref = BidRef("database", "9")
        data.bid = replace(data.bid, uid="9")
        self.assertFalse(
            service.navigation_owner_is_current("database", replacement_owner)
        )
        other_bid = service.capture_navigation_owner("database")
        self.assertIs(other_bid, data.bid)
        data.bid_ref = None
        self.assertFalse(
            service.navigation_owner_is_current("database", replacement_owner)
        )
        self.assertIsNone(service.capture_navigation_owner("database"))
        self.assertTrue(service.navigation_owner_is_current("database", None))

    def test_foreign_bid_or_database_updates_tokens_without_active_family_projection(
        self,
    ):
        for database_id, bid_uid in (("database", 9), ("other-database", 8)):
            with self.subTest(database=database_id, bid=bid_uid):
                service, data, events, tokens = self._make_service()
                owner = data.bid
                original = Condition(uid="42", name="Active")
                data.conditions = {"42": original}
                resource = ResourceRef("condition", "42", bid_uid)
                change = _change(database_id, resource, 7)
                hydrated = HydratedDatabaseChangeBatch(
                    _batch(database_id, "epoch", 1, 7, (change,)),
                    conditions_by_bid={
                        bid_uid: {"42": Condition(uid="42", name="Foreign")}
                    },
                    condition_folders_by_bid={bid_uid: {}},
                )
                self.assertTrue(service.apply(hydrated).applied)
                self.assertIs(data.conditions["42"], original)
                self.assertIs(data.bid, owner)
                self.assertEqual(data.merges, [])
                self.assertEqual(events.published, [])
                self.assertEqual(
                    tokens.expected_versions(database_id, (resource,))[0].expected,
                    change.resulting_version,
                )
                other_scope = ResourceRef("condition", "42", 8 if bid_uid == 9 else 9)
                self.assertEqual(
                    tokens.expected_versions(database_id, (other_scope,)), ()
                )
                if database_id != "database":
                    self.assertEqual(
                        tokens.expected_versions("database", (resource,)), ()
                    )

    def test_master_data_requires_complete_snapshots_but_accepts_empty_collections(
        self,
    ):
        cases = (
            ("default_layers_collection", "default_layers", None),
            ("job_statuses_collection", "job_statuses", "used_job_status_uids"),
            ("employees_collection", "employees", "used_employee_uids"),
            ("pay_classes_collection", "pay_classes", None),
        )
        for resource_type, snapshot_field, usage_field in cases:
            for missing in (
                (snapshot_field, usage_field) if usage_field else (snapshot_field,)
            ):
                with self.subTest(resource=resource_type, missing=missing):
                    service, data, events, tokens = self._make_service()
                    data.database_settings["database"] = {
                        "defaults": {"next_bid_no": 4}
                    }
                    resource = ResourceRef(resource_type, "database")
                    batch = _batch(
                        "database", "epoch", 1, 2, (_change("database", resource, 2),)
                    )
                    values = {snapshot_field: ()}
                    if usage_field:
                        values[usage_field] = frozenset()
                    incomplete = dict(values)
                    incomplete.pop(missing)
                    result = service.apply(
                        HydratedDatabaseChangeBatch(batch, **incomplete)
                    )
                    self.assertEqual(
                        result,
                        ReconciliationResult(
                            applied=False,
                            failure_kind=ReconciliationFailureKind.MALFORMED_PAYLOAD,
                        ),
                    )
                    self.assertEqual(
                        data.database_settings,
                        {"database": {"defaults": {"next_bid_no": 4}}},
                    )
                    self.assertEqual(events.published, [])
                    self.assertEqual(
                        tokens.expected_versions("database", (resource,)), ()
                    )
                    self.assertTrue(
                        service.apply(
                            HydratedDatabaseChangeBatch(batch, **values)
                        ).applied
                    )
                    self.assertEqual(
                        data.database_settings["database"],
                        {"defaults": {"next_bid_no": 4}, **values},
                    )
                    self.assertEqual(
                        events.published,
                        [
                            (
                                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                                {
                                    "database_id": "database",
                                    "families": [snapshot_field],
                                },
                            )
                        ],
                    )
                    self.assertEqual(
                        tokens.expected_versions("database", (resource,))[0].expected,
                        batch.changes[0].resulting_version,
                    )

    def test_empty_authoritative_condition_and_area_families_clear_old_state(self):
        service, data, events, _tokens = self._make_service()
        data.conditions = {"42": Condition(uid="42")}
        data.folders = {"5": BidConditionFolder(uid="5", name="Old")}
        data.areas = (BidArea("6", "8", "0", "Old", 1),)
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change("database", ResourceRef("conditions_collection", "8", 8), 1),
                _change("database", ResourceRef("areas_collection", "8", 8), 2),
            ),
        )
        self.assertTrue(
            service.apply(
                HydratedDatabaseChangeBatch(
                    batch,
                    conditions_by_bid={8: {}},
                    condition_folders_by_bid={8: {}},
                    areas_by_bid={8: ()},
                )
            ).applied
        )
        self.assertEqual((data.conditions, data.folders, data.areas), ({}, {}, ()))
        self.assertEqual(
            [event for event, _payload in events.published],
            [AppEvents.CONDITIONS_CHANGED, AppEvents.REMOTE_AREAS_CHANGED],
        )
        self.assertEqual(events.published[1][1]["area_uids"], [])

    def test_inactive_database_snapshots_do_not_replace_active_workspace(self):
        service, data, events, tokens = self._make_service("active-database")
        owner = data.bid
        condition = Condition(uid="42", name="Active")
        data.conditions = {"42": condition}
        resource = ResourceRef("cover_sheet", "8", 8)
        change = _change("other-database", resource, 2)
        cover = _cover_sheet()
        hydrated = HydratedDatabaseChangeBatch(
            _batch("other-database", "epoch", 1, 2, (change,)),
            cover_sheet_by_bid={8: cover},
            page_delete_content_uids_by_bid={8: frozenset({"20"})},
            settings_defaults={"next_bid_no": 12},
        )
        self.assertTrue(service.apply(hydrated).applied)
        self.assertEqual(data.cover_sheets, {("other-database", "8"): cover})
        self.assertEqual(
            data.page_delete_content, {("other-database", "8"): frozenset({"20"})}
        )
        self.assertEqual(
            data.database_settings,
            {"other-database": {"defaults": {"next_bid_no": 12}}},
        )
        self.assertIs(data.bid, owner)
        self.assertIs(data.conditions["42"], condition)
        self.assertEqual(data.merges, [])
        self.assertEqual(events.published, [])
        self.assertEqual(
            tokens.expected_versions("other-database", (resource,))[0].expected,
            change.resulting_version,
        )

    def test_malformed_takeoff_contracts_leave_live_state_and_tokens_untouched(self):
        valid = Takeoff(uid="30", page_uid="20", condition_uid="10")
        cases = {
            "not_takeoff": [object()],
            "duplicate_uid": [valid, replace(valid)],
            "empty_uid": [replace(valid, uid="")],
            "missing_page": [replace(valid, page_uid="999")],
            "cross_page_parent": [
                valid,
                Takeoff(uid="31", page_uid="21", condition_uid="10", parent_uid="30"),
            ],
        }
        for label, takeoffs in cases.items():
            with self.subTest(case=label):
                service, data, events, tokens = self._make_service()
                data.conditions = {"10": Condition(uid="10")}
                data.takeoffs = [valid]
                retained = data.takeoffs
                resource = ResourceRef("takeoffs_collection", "8", 8)
                result = service.apply(
                    HydratedDatabaseChangeBatch(
                        _batch(
                            "database",
                            "epoch",
                            1,
                            2,
                            (_change("database", resource, 2),),
                        ),
                        bid_data_by_bid={
                            8: BidLoadResult(
                                bid_takeoffs=takeoffs,
                                pages={
                                    "20": Page(uid="20", name="First"),
                                    "21": Page(uid="21", name="Second"),
                                },
                            )
                        },
                    )
                )
                self.assertEqual(
                    result,
                    ReconciliationResult(
                        applied=False,
                        failure_kind=ReconciliationFailureKind.MALFORMED_PAYLOAD,
                    ),
                )
                self.assertIs(data.takeoffs, retained)
                self.assertEqual(data.merges, [])
                self.assertEqual(events.published, [])
                self.assertEqual(tokens.expected_versions("database", (resource,)), ())

    def test_rejected_single_family_merge_does_not_publish_or_advance_tokens(self):
        for family, method, payload in (
            (
                "condition",
                "replace_condition_family",
                {"conditions_by_bid": {8: {}}, "condition_folders_by_bid": {8: {}}},
            ),
            ("area", "replace_bid_areas", {"areas_by_bid": {8: ()}}),
            (
                "layer",
                "replace_remote_bid_families",
                {"bid_data_by_bid": {8: BidLoadResult()}},
            ),
        ):
            with self.subTest(family=family):
                service, data, events, tokens = self._make_service()
                resource = ResourceRef(family, "42", 8)
                with patch.object(data, method, return_value=False) as merge:
                    result = service.apply(
                        HydratedDatabaseChangeBatch(
                            _batch(
                                "database",
                                "epoch",
                                1,
                                2,
                                (_change("database", resource, 2),),
                            ),
                            **payload
                        )
                    )
                self.assertEqual(result, ReconciliationResult(applied=False))
                merge.assert_called_once()
                self.assertEqual(data.merges, [])
                self.assertEqual(events.published, [])
                self.assertEqual(tokens.expected_versions("database", (resource,)), ())

    def test_local_condition_delete_invalidates_history_unlike_local_update(self):
        for operation in (ChangeOperation.UPDATE, ChangeOperation.DELETE):
            with self.subTest(operation=operation):
                service, data, events, _tokens = self._make_service()
                data.conditions = {"42": Condition(uid="42", name="Old")}
                replacement = (
                    {"42": Condition(uid="42", name="New")}
                    if operation == ChangeOperation.UPDATE
                    else {}
                )
                self.assertTrue(
                    service.apply(
                        HydratedDatabaseChangeBatch(
                            _batch(
                                "database",
                                "epoch",
                                1,
                                2,
                                (
                                    _change(
                                        "database",
                                        ResourceRef("condition", "42", 8),
                                        2,
                                        changed_fields=("name",),
                                        operation=operation,
                                    ),
                                ),
                            ),
                            conditions_by_bid={8: replacement},
                            condition_folders_by_bid={8: {}},
                        ),
                        local_completion=True,
                    ).applied
                )
                self.assertEqual(data.conditions, replacement)
                self.assertEqual(len(events.published), 1)
                event, payload = events.published[0]
                self.assertIs(event, AppEvents.CONDITIONS_CHANGED)
                self.assertEqual(
                    payload["invalidates_undo"], operation == ChangeOperation.DELETE
                )
                self.assertEqual(payload["condition_uids"], ["42"])
                self.assertEqual(payload["change_operations"], [operation.value])

    def test_unclassified_condition_collection_projects_every_authoritative_condition(
        self,
    ):
        service, data, events, _tokens = self._make_service()
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id="database",
            runtime_generation=3,
            is_runtime_current=lambda *_args: True,
            on_complete=completed.append,
        )
        conditions = {uid: Condition(uid=uid) for uid in ("42", "10")}
        self.assertTrue(
            service.apply(
                HydratedDatabaseChangeBatch(
                    _batch(
                        "database",
                        "epoch",
                        1,
                        2,
                        (
                            _change(
                                "database",
                                ResourceRef("conditions_collection", "8", 8),
                                2,
                            ),
                        ),
                    ),
                    conditions_by_bid={8: conditions},
                    condition_folders_by_bid={8: {}},
                ),
                barrier,
            ).applied
        )
        self.assertEqual(data.conditions, conditions)
        self.assertEqual(
            [event for event, _payload in events.published],
            [AppEvents.CONDITIONS_CHANGED, AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED],
        )
        projection = events.published[1][1]
        self.assertEqual(projection["condition_uids"], ("10", "42"))
        self.assertEqual(projection["condition_changed_fields"], ())
        self.assertIs(projection["barrier"], barrier)
        self.assertEqual(
            completed, []
        )  # Rendering consumers, not reconciliation, own completion.

    def test_annotation_identity_is_typed_and_unknown_scope_stays_conservative(self):
        for resource_type, uid, expected in (
            ("annotation", "text/42", {"annotations": ("20", "21")}),
            ("annotation", "line/42", {"annotations": ("22",)}),
            ("annotation", "text/999", {}),
            ("annotation", "malformed", {}),
            ("annotations_collection", "8", {}),
        ):
            with self.subTest(resource_type=resource_type, uid=uid):
                service, data, events, _tokens = self._make_service()
                data.annotations = [
                    BidAnnotation(uid="42", annotation_type="text", page_uid="20"),
                    BidAnnotation(uid="42", annotation_type="line", page_uid="22"),
                ]
                updated = [
                    replace(data.annotations[0], page_uid="21"),
                    data.annotations[1],
                ]
                self.assertTrue(
                    service.apply(
                        HydratedDatabaseChangeBatch(
                            _batch(
                                "database",
                                "epoch",
                                1,
                                2,
                                (
                                    _change(
                                        "database",
                                        ResourceRef(resource_type, uid, 8),
                                        2,
                                    ),
                                ),
                            ),
                            bid_data_by_bid={8: BidLoadResult(bid_annotations=updated)},
                        )
                    ).applied
                )
                self.assertEqual(data.annotations, updated)
                self.assertEqual(len(events.published), 1)
                self.assertIs(
                    events.published[0][0], AppEvents.REMOTE_BID_CONTENT_CHANGED
                )
                self.assertEqual(
                    events.published[0][1]["affected_page_uids_by_family"], expected
                )

    def test_takeoff_collection_or_unknown_identity_refreshes_old_and_new_pages(self):
        for resource_type, uid in (("takeoffs_collection", "8"), ("takeoff", "999")):
            with self.subTest(resource_type=resource_type):
                service, data, events, _tokens = self._make_service()
                data.conditions = {"10": Condition(uid="10")}
                data.takeoffs = [Takeoff(uid="30", page_uid="20", condition_uid="10")]
                updated = Takeoff(uid="31", page_uid="21", condition_uid="10")
                self.assertTrue(
                    service.apply(
                        HydratedDatabaseChangeBatch(
                            _batch(
                                "database",
                                "epoch",
                                1,
                                2,
                                (
                                    _change(
                                        "database",
                                        ResourceRef(resource_type, uid, 8),
                                        2,
                                    ),
                                ),
                            ),
                            bid_data_by_bid={
                                8: BidLoadResult(
                                    bid_takeoffs=[updated],
                                    pages={"21": Page(uid="21", name="New")},
                                )
                            },
                        )
                    ).applied
                )
                self.assertEqual(data.takeoffs, [updated])
                self.assertEqual(len(events.published), 1)
                self.assertEqual(
                    events.published[0][1]["affected_page_uids_by_family"],
                    {"takeoffs": ("20", "21")},
                )

    def test_layer_rename_impact_matches_local_and_remote_projection(self):
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
                        self.assertIs(data.layers[0], updated)
                        self.assertEqual(
                            [event for event, _payload in events.published],
                            [AppEvents.REMOTE_BID_CONTENT_CHANGED]
                            + (
                                [AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED]
                                if deferred
                                else []
                            ),
                        )
                        for event, payload in events.published:
                            self.assertEqual(payload["database_id"], "database")
                            self.assertEqual(payload["bid_uid"], "8")
                            if event is AppEvents.REMOTE_BID_CONTENT_CHANGED:
                                self.assertEqual(payload["local_completion"], local)
                                self.assertEqual(payload["families"], ["layers"])
                                self.assertEqual(
                                    payload["resource_uids_by_family"],
                                    {"layers": ["20"]},
                                )
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
                    data = _ProjectData("database")
                    data.pages = {"20": Page(uid="20", name="Old")}
                    service = RemoteChangeReconciliationService(
                        data,
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
                    updated_pages = (
                        {}
                        if operation == ChangeOperation.DELETE
                        else {"20": Page(uid="20", name="Sheet")}
                    )
                    hydrated = HydratedDatabaseChangeBatch(
                        _batch("database", "epoch", 1, 2, (change,)),
                        bid_data_by_bid={8: BidLoadResult(pages=updated_pages)},
                        cover_sheet_by_bid={8: _cover_sheet()},
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
                    self.assertEqual(data.pages, updated_pages)
                    self.assertEqual(
                        [event for event, _payload in events.published],
                        [AppEvents.REMOTE_BID_CONTENT_CHANGED],
                    )
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
                    deferred_result = service.apply(
                        hydrated,
                        local_completion=local_completion,
                        projection_barrier=barrier,
                    )
                    self.assertTrue(deferred_result.applied)
                    self.assertEqual(data.pages, updated_pages)
                    self.assertEqual(
                        [event for event, _payload in events.published],
                        [
                            AppEvents.REMOTE_BID_CONTENT_CHANGED,
                            AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
                        ],
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
        self.assertEqual(project_data.conditions, hydrated.conditions_by_bid[8])
        self.assertIs(
            project_data.conditions["42"], hydrated.conditions_by_bid[8]["42"]
        )
        self.assertEqual(project_data.areas, hydrated.areas_by_bid[8])
        self.assertEqual(
            project_data.merges,
            [
                ("conditions", BidRef(database_id, "8")),
                ("areas", BidRef(database_id, "8")),
            ],
        )
        names = [event for event, _payload in events.published]
        self.assertEqual(
            names, [AppEvents.CONDITIONS_CHANGED, AppEvents.REMOTE_AREAS_CHANGED]
        )
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
        self.assertIs(projected[0]["barrier"], barrier)
        self.assertEqual(projected[0]["database_id"], database_id)
        self.assertEqual(projected[0]["bid_uid"], "8")
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
                        self.assertEqual(data.takeoffs, [takeoff])
                        self.assertEqual(data.areas, hydrated.areas_by_bid[8])
                        self.assertEqual(
                            [event for event, _payload in events.published],
                            ([AppEvents.CONDITIONS_CHANGED] if has_condition else [])
                            + [
                                AppEvents.REMOTE_AREAS_CHANGED,
                                AppEvents.REMOTE_BID_CONTENT_CHANGED,
                            ]
                            + (
                                [AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED]
                                if deferred
                                else []
                            ),
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
        self.assertEqual(project_data.areas, hydrated.areas_by_bid[8])
        self.assertEqual(
            [event for event, _payload in events.published],
            [AppEvents.REMOTE_AREAS_CHANGED],
        )
        area_event = next(
            payload
            for event, payload in events.published
            if event is AppEvents.REMOTE_AREAS_CHANGED
        )
        self.assertTrue(area_event["local_completion"])
        self.assertTrue(area_event["summary_refresh_required"])
        self.assertFalse(area_event["takeoff_family_pending"])
        self.assertEqual(
            (area_event["database_id"], area_event["bid_uid"], area_event["area_uids"]),
            (database_id, "8", ["6"]),
        )

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
        self.assertEqual(project_data.conditions, hydrated.conditions_by_bid[8])
        self.assertEqual(
            [event for event, _payload in events.published],
            [AppEvents.CONDITIONS_CHANGED],
        )
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
            condition_folders_by_bid={
                8: {"5": BidConditionFolder(uid="5", name="Renamed")}
            },
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
        self.assertEqual(project_data.folders, hydrated.condition_folders_by_bid[8])
        self.assertEqual(
            [event for event, _payload in events.published],
            [AppEvents.CONDITIONS_CHANGED],
        )
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
        self.assertEqual(project_data.takeoffs, [takeoff])
        self.assertIs(project_data.takeoffs[0], takeoff)
        self.assertEqual(
            projection_events[0]["resource_uids_by_family"], {"takeoffs": ("30",)}
        )
        self.assertIs(projection_events[0]["barrier"], barrier)

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
        self.assertEqual(project_data.takeoffs, [])
        self.assertEqual(
            [event for event, _payload in events.published],
            [AppEvents.REMOTE_BID_CONTENT_CHANGED],
        )

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
        self.assertEqual(project_data.annotations, [moved_annotation])
        self.assertIs(project_data.annotations[0], moved_annotation)
        self.assertEqual(
            [event for event, _payload in events.published],
            [
                AppEvents.REMOTE_BID_CONTENT_CHANGED,
                AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
            ],
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
        project_data.takeoffs = [
            Takeoff(uid=preview_uid, condition_uid="10", page_uid="20")
        ]
        project_data.transient_takeoffs = {preview_uid: project_data.takeoffs[0]}
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
        self.assertEqual(project_data.transient_takeoffs, {})
        self.assertEqual(project_data.takeoffs, [takeoff])
        self.assertIs(project_data.takeoffs[0], takeoff)
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

    def test_empty_checkpoint_does_not_publish_or_schedule_plan_projection(self):
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
        self.assertEqual(events.published, [])

    def test_hierarchy_only_change_does_not_schedule_plan_projection(self):
        database_id = "database"
        events = _EventBus()
        tokens, drafts = _token_service()
        project_data = _ProjectData(database_id)
        service = RemoteChangeReconciliationService(
            project_data,
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
        self.assertEqual(published, [AppEvents.REMOTE_HIERARCHY_CHANGED])
        self.assertEqual(project_data.hierarchy, {database_id: (hierarchy_file, {})})
        self.assertIs(project_data.hierarchy[database_id][0], hierarchy_file)
        self.assertEqual(
            project_data.database_settings[database_id]["defaults"], {"next_bid_no": 1}
        )

    def test_mixed_hierarchy_condition_event_assigns_sidebar_refresh_to_condition(self):
        database_id = "database"
        events = _EventBus()
        tokens, drafts = _token_service()
        project_data = _ProjectData(database_id)
        service = RemoteChangeReconciliationService(
            project_data,
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
        self.assertIs(project_data.hierarchy[database_id][0], hydrated.hierarchy_file)
        self.assertEqual(project_data.conditions, hydrated.conditions_by_bid[8])
        self.assertEqual(
            [event for event, _payload in events.published],
            [AppEvents.REMOTE_HIERARCHY_CHANGED, AppEvents.CONDITIONS_CHANGED],
        )
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
        project_data = _ProjectData(database_id)
        service = RemoteChangeReconciliationService(
            project_data,
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
        self.assertEqual(published, [AppEvents.CONDITIONS_CHANGED])
        self.assertIs(project_data.hierarchy[database_id][0], hierarchy_file)
        self.assertEqual(project_data.hierarchy[database_id][1], hydrated.cdn_types)
        self.assertFalse(condition_event["invalidates_undo"])

    def test_inactive_database_hierarchy_registration_includes_condition_types(self):
        database_id = "sql-database"
        project_data = _ProjectData("access-database")
        original_bid = project_data.bid
        events = _EventBus()
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            events,
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
        self.assertEqual(
            project_data.hierarchy, {database_id: (hierarchy_file, cdn_types)}
        )
        self.assertIs(project_data.bid, original_bid)
        self.assertEqual(project_data.bid_ref, BidRef("access-database", "8"))
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.REMOTE_HIERARCHY_CHANGED,
                    {"database_id": database_id, "defer_plan_projection": False},
                )
            ],
        )

    def test_remote_events_publish_only_after_all_model_merges(self):
        database_id = "database"
        events = _EventBus()
        project_data = _ProjectData(database_id)
        observations = []

        def switch_active_bid(**_payload):
            observations.append(
                (
                    dict(project_data.conditions),
                    project_data.areas,
                    tokens.expected_versions(
                        database_id,
                        (
                            ResourceRef("condition", "42", 8),
                            ResourceRef("area", "6", 8),
                        ),
                    ),
                )
            )
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
        self.assertEqual(len(observations), 1)
        conditions, areas, versions = observations[0]
        self.assertEqual(conditions, hydrated.conditions_by_bid[8])
        self.assertEqual(areas, hydrated.areas_by_bid[8])
        self.assertEqual(
            [version.expected for version in versions],
            [change.resulting_version for change in batch.changes],
        )
        self.assertEqual(
            [payload["bid_uid"] for _event, payload in events.published], ["8", "8"]
        )
        self.assertEqual(project_data.bid_ref, BidRef(database_id, "9"))

    def test_incomplete_remote_batch_does_not_advance_tokens_or_partial_merge(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        tokens, drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")
        project_data = _ProjectData(database_id)
        project_data.conditions = {"old": Condition(uid="old", name="Old")}
        original_conditions = project_data.conditions
        events = _EventBus()
        service = RemoteChangeReconciliationService(
            project_data,
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
        result = service.apply(HydratedDatabaseChangeBatch(batch))
        self.assertEqual(
            result,
            ReconciliationResult(
                applied=False, failure_kind=ReconciliationFailureKind.MALFORMED_PAYLOAD
            ),
        )
        self.assertIs(project_data.conditions, original_conditions)
        self.assertEqual(project_data.merges, [])
        self.assertEqual(events.published, [])
        self.assertEqual(set(project_data.conditions), {"old"})
        self.assertEqual(
            tokens.expected_versions(database_id, (resource,))[0].expected,
            initial,
        )

    def test_incomplete_cover_sheet_batch_does_not_cache_partial_snapshots(self):
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
                cover_sheet_by_bid={8: _cover_sheet()},
            )
        )
        self.assertFalse(result.applied)
        self.assertEqual(
            result.failure_kind,
            ReconciliationFailureKind.MALFORMED_PAYLOAD,
        )
        self.assertEqual(project_data.cover_sheets, {})
        self.assertEqual(project_data.page_delete_content, {})
        self.assertEqual(events.published, [])
        self.assertEqual(
            tokens.expected_versions(database_id, (batch.changes[0].resource,)), ()
        )

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
        accepted = service.apply(
            HydratedDatabaseChangeBatch(_batch(database_id, "epoch", 2, 3))
        )
        rejected_again = service.apply(malformed)
        self.assertEqual(accepted, ReconciliationResult(applied=True))
        self.assertEqual(result, rejected_again)
        self.assertIsNot(result, rejected_again)

    def test_remote_takeoff_cycle_is_rejected_before_projection(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        events = _EventBus()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
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
        self.assertEqual(project_data.merges, [])
        self.assertEqual(events.published, [])
        self.assertEqual(
            tokens.expected_versions(
                database_id, tuple(change.resource for change in hydrated.batch.changes)
            ),
            (),
        )

    def test_remote_takeoff_with_missing_condition_is_rejected(self):
        database_id = "database"
        project_data = _ProjectData(database_id)
        project_data.conditions = {"10": Condition(uid="10")}
        tokens, drafts = _token_service()
        events = _EventBus()
        service = RemoteChangeReconciliationService(
            project_data, events, tokens, drafts, ConflictResolutionService()
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
        self.assertEqual(project_data.merges, [])
        self.assertEqual(events.published, [])
        self.assertEqual(
            tokens.expected_versions(
                database_id, tuple(change.resource for change in hydrated.batch.changes)
            ),
            (),
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
        self.assertEqual(project_data.merges, [])
        self.assertEqual(
            tokens.expected_versions(database_id, (batch.changes[0].resource,))[
                0
            ].expected,
            batch.changes[0].resulting_version,
        )

    def test_default_layer_change_uses_authoritative_reconciliation(self):
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
            project_data.database_settings[database_id]["default_layers"],
            hydrated.default_layers,
        )
        self.assertEqual(
            tokens.expected_versions(database_id, (resource,))[0].expected,
            batch.changes[0].resulting_version,
        )
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    {"database_id": database_id, "families": ["default_layers"]},
                )
            ],
        )

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
        self.assertEqual(settings["job_statuses"], hydrated.job_statuses)
        self.assertEqual(settings["employees"], hydrated.employees)
        self.assertEqual(settings["pay_classes"], hydrated.pay_classes)
        self.assertEqual(
            settings["used_job_status_uids"], hydrated.used_job_status_uids
        )
        self.assertEqual(settings["used_employee_uids"], hydrated.used_employee_uids)
        self.assertEqual(
            [
                version.expected
                for version in tokens.expected_versions(database_id, resources)
            ],
            [change.resulting_version for change in batch.changes],
        )
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
        original_bid = project_data.bid
        events = _EventBus()
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            events,
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
        self.assertEqual(
            service.apply(HydratedDatabaseChangeBatch(batch)),
            ReconciliationResult(
                applied=False, failure_kind=ReconciliationFailureKind.MALFORMED_PAYLOAD
            ),
        )
        self.assertIs(project_data.bid, original_bid)
        self.assertEqual(project_data.cover_sheets, {})
        self.assertEqual(project_data.database_settings, {})
        self.assertEqual(events.published, [])
        self.assertEqual(
            tokens.expected_versions("database", (batch.changes[0].resource,)), ()
        )

    def test_remote_local_edit_conflict_is_resource_scoped(self):
        database_id = "database"
        resource = ResourceRef("condition", "42", 8)
        initial = ConcurrencyToken(b"\x00" * 7 + b"\x01")
        tokens, drafts = _token_service(_TokenReader({resource: initial}))
        tokens.load_bid(database_id, "8")
        draft = drafts.begin(
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
        self.assertEqual(len(events.published), 1)
        event, payload = events.published[-1]
        self.assertIs(event, AppEvents.SYNCHRONIZATION_CONFLICT)
        self.assertFalse(payload["blocks_database"])
        self.assertEqual(payload["bid_uid"], "8")
        self.assertEqual(payload["database_id"], database_id)
        self.assertEqual(payload["resource_type"], "condition")
        self.assertEqual(payload["resource_id"], "42")
        self.assertEqual(payload["draft_id"], draft.draft_id)
        self.assertEqual(
            payload["allowed_actions"], ["reload", "discard_draft", "cancel_read_only"]
        )
        self.assertEqual(
            tokens.expected_versions(database_id, (resource,))[0].expected, initial
        )
