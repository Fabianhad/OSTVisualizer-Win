"""Stateful application-boundary fakes; no SQL connection or worker simulation."""

from copy import deepcopy
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
)
from ost_visualizer.application.services.database_concurrency_token_service import (
    DatabaseConcurrencyTokenService,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.cover_sheet import CoverSheetData
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.events.event_bus import EventBus


class _EventBus(EventBus):
    def __init__(self):
        super().__init__()
        self.published = []

    def publish(self, event, **payload):
        event(**payload)
        self.published.append((event, payload))
        super().publish(event, **payload)


class _TokenReader:
    def __init__(self, resources=None):
        self.resources = dict(resources or {})
        self.calls = []

    def read_database_versions(self, database_id):
        self.calls.append((database_id, None))
        return {
            resource: token
            for resource, token in self.resources.items()
            if resource.bid_uid is None
        }

    def read_bid_versions(self, database_id, bid_uid):
        self.calls.append((database_id, str(bid_uid)))
        return {
            resource: token
            for resource, token in self.resources.items()
            if resource.bid_uid == int(bid_uid)
        }


def _token_service(reader=None):
    drafts = LocalDraftRegistry()
    return DatabaseConcurrencyTokenService(reader or _TokenReader(), drafts), drafts


class _ProjectData:
    def __init__(self, database_id):
        self.bid_ref = BidRef(database_id, "8")
        self.bid = Bid(uid="8", name="Current")
        self.conditions = {}
        self.folders = {}
        self.pages = {}
        self.areas = ()
        self.database_settings = {}
        self.cover_sheets = {}
        self.page_delete_content = {}
        self.removed_transient_takeoff_uids = []
        self.annotations = []
        self.takeoffs = []
        self.transient_takeoffs = {}
        self.layers = []
        self.hierarchy = {}
        self.merges = []

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_bid(self, bid_ref):
        return self.bid if bid_ref == self.bid_ref else None

    def get_bid_conditions(self):
        return self.conditions

    def replace_condition_family(self, bid_ref, conditions, folders):
        if bid_ref != self.bid_ref:
            return False
        self.conditions = dict(conditions)
        self.folders = dict(folders)
        self.merges.append(("conditions", bid_ref))
        return True

    def replace_bid_areas(self, bid_ref, areas):
        if bid_ref != self.bid_ref:
            return False
        self.areas = tuple(areas)
        self.merges.append(("areas", bid_ref))
        return True

    def replace_database_hierarchy(self, file_entry, cdn_types):
        self.hierarchy[file_entry.file_path] = (file_entry, dict(cdn_types or {}))
        self.merges.append(("hierarchy", file_entry.file_path))

    def replace_remote_bid_families(self, bid_ref, bid_data, families):
        if bid_ref != self.bid_ref:
            return False
        if not set(families) <= {"layers", "annotations", "takeoffs", "pages"}:
            raise AssertionError(f"Unexpected families: {families}")
        if "layers" in families:
            self.layers = list(bid_data.bid_layers)
        if "annotations" in families:
            self.annotations = list(bid_data.bid_annotations)
        if "takeoffs" in families:
            authoritative_uids = {takeoff.uid for takeoff in bid_data.bid_takeoffs}
            self.takeoffs = list(bid_data.bid_takeoffs) + [
                takeoff
                for uid, takeoff in self.transient_takeoffs.items()
                if uid not in authoritative_uids
            ]
        if "pages" in families:
            self.pages = dict(bid_data.pages)
        self.merges.append(("content", bid_ref, frozenset(families)))
        return True

    def get_bid_layer_snapshot(self):
        return list(self.layers)

    def get_all_takeoffs(self):
        return list(self.takeoffs)

    def get_all_annotations(self):
        return list(self.annotations)

    def remove_transient_takeoffs(self, takeoff_uids):
        self.removed_transient_takeoff_uids.extend(takeoff_uids)
        for uid in takeoff_uids:
            self.transient_takeoffs.pop(uid, None)
        self.takeoffs = [
            takeoff for takeoff in self.takeoffs if takeoff.uid not in takeoff_uids
        ]

    def replace_database_settings(
        self,
        database_id,
        *,
        default_layers=None,
        job_statuses=None,
        employees=None,
        pay_classes=None,
        used_job_status_uids=None,
        used_employee_uids=None,
    ):
        values = dict(
            default_layers=default_layers,
            job_statuses=job_statuses,
            employees=employees,
            pay_classes=pay_classes,
            used_job_status_uids=used_job_status_uids,
            used_employee_uids=used_employee_uids,
        )
        self.database_settings.setdefault(database_id, {}).update(
            {key: deepcopy(value) for key, value in values.items() if value is not None}
        )

    def replace_cover_sheet_data(self, database_id, bid_uid, cover_sheet):
        self.cover_sheets[(database_id, str(bid_uid))] = deepcopy(cover_sheet)

    def replace_page_delete_content_uids(self, database_id, bid_uid, page_uids):
        self.page_delete_content[(database_id, str(bid_uid))] = frozenset(page_uids)

    def replace_settings_defaults(self, database_id, defaults):
        self.database_settings.setdefault(database_id, {})["defaults"] = deepcopy(
            defaults
        )


def _cover_sheet(bid_uid="8"):
    return CoverSheetData(
        bid_uid=bid_uid,
        job_status_uid="",
        job_name="Fixture",
        estimator_uid="",
        notes="",
        bid_date="",
        bid_no="8",
        job_id="",
    )


def _change(
    database_id,
    resource,
    sequence=1,
    source="other-session",
    changed_fields=(),
    operation=ChangeOperation.UPDATE,
):
    return DatabaseChange(
        sequence=sequence,
        commit_version=sequence,
        transaction_id="transaction-1",
        source_session_id=source,
        resource=resource,
        operation=operation,
        resulting_version=ConcurrencyToken(sequence.to_bytes(8, "big")),
        changed_fields=tuple(changed_fields),
    )


def _batch(
    database_id,
    feed_epoch,
    minimum_version,
    high_water_version,
    changes=(),
    delivered_through=None,
):
    return DatabaseChangeBatch(
        database_id=database_id,
        feed_epoch=feed_epoch,
        minimum_valid_version=minimum_version,
        high_water_version=high_water_version,
        delivered_through_version=(
            high_water_version if delivered_through is None else delivered_through
        ),
        changes=changes,
    )
