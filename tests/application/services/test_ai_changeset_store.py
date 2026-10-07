import time
import unittest
from unittest.mock import patch
from ost_visualizer.application.dtos.ai_changeset_write_dtos import AppliedChangeset
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.domain.entities.ai_changeset import (
    ASSUMPTION_ACCEPTED,
    ASSUMPTION_OPEN,
    ASSUMPTION_OVERRIDDEN,
    IMPACT_HIGH,
    IMPACT_NORMAL,
    KIND_ELEMENTS,
    STATUS_APPLIED,
    STATUS_APPLYING,
    STATUS_DISCARDED,
    STATUS_EXPIRED,
    STATUS_PENDING_APPROVAL,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    STATUS_STALE,
    STATUS_UNDONE,
    SUBJECT_OTHER,
    SUBJECT_THICKNESS,
    AiChangeset,
    ChangesetAssumption,
    ChangesetError,
    ProposedCondition,
    ProposedTakeoff,
)

SQUARE = (0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Tokens:
    def __init__(self):
        self.values = {}
        self.calls = []

    def __call__(self, database_id, bid_uid, resources):
        self.calls.append((database_id, bid_uid, tuple(resources)))
        return {resource: self.values.get(resource, "v0") for resource in resources}


def _changeset(bid_uid="7", page_uid="page-1", assumptions=(), thickness=8.0):
    return AiChangeset(
        uid="",
        database_id="C:/jobs/a.mdb",
        bid_uid=bid_uid,
        bid_key="a" * 32,
        kind=KIND_ELEMENTS,
        created_at=0.0,
        conditions=(ProposedCondition("c1", "Slab", thickness, 1200.0),),
        takeoffs=(ProposedTakeoff("t1", page_uid, "c1", SQUARE),),
        assumptions=assumptions,
    )


def _assumption(uid, subject=SUBJECT_THICKNESS, impact=IMPACT_HIGH):
    return ChangesetAssumption(uid, subject, "c1", "8", "not shown", "S-101", impact)


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.tokens = Tokens()
        self.counter = iter(range(1, 1000))
        self.store = AiChangesetStore(
            clock=self.clock,
            token_reader=self.tokens,
            uid_factory=lambda: f"cs-{next(self.counter)}",
        )
        self.proposals = AiChangesetProposals(self.store)

    def add(self, changeset=None):
        return self.proposals.add(changeset or _changeset())


class ProposalTests(StoreTestCase):
    def test_add_assigns_an_id_the_clock_and_the_touched_base_tokens(self):
        self.tokens.values["page:page-1"] = "v7"
        added = self.add()
        self.assertEqual(added.uid, "cs-1")
        self.assertEqual(added.created_at, 1000.0)
        self.assertEqual(added.status, STATUS_PROPOSED)
        self.assertEqual(added.base_tokens, (("page:page-1", "v7"),))
        self.assertEqual(self.tokens.calls, [("C:/jobs/a.mdb", "7", ("page:page-1",))])

    def test_caps_are_checked_before_storing(self):
        too_many = AiChangeset(
            uid="",
            database_id="C:/jobs/a.mdb",
            bid_uid="7",
            bid_key="a" * 32,
            kind=KIND_ELEMENTS,
            created_at=0.0,
            takeoffs=tuple(
                ProposedTakeoff(f"t{index}", "page-1", "existing:1", SQUARE)
                for index in range(201)
            ),
        )
        with self.assertRaises(ChangesetError) as raised:
            self.add(too_many)
        self.assertEqual(raised.exception.code, "changeset_too_large")
        self.assertEqual(self.store.open_for_bid("C:/jobs/a.mdb", "7"), ())

    def test_at_most_five_open_changesets_per_bid(self):
        for _ in range(5):
            self.add()
        with self.assertRaises(ChangesetError) as raised:
            self.add()
        self.assertEqual(raised.exception.code, "changeset_too_large")
        self.add(_changeset(bid_uid="8"))
        self.proposals.discard("cs-1")
        self.assertEqual(self.add().uid, "cs-7")

    def test_changesets_expire_thirty_minutes_after_proposal(self):
        added = self.add()
        self.clock.now = 1000.0 + 1799.0
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_PROPOSED)
        self.clock.now = 1000.0 + 1800.0
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_EXPIRED)
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.request_apply(added.uid)
        self.assertEqual(raised.exception.code, "stale_changeset")
        self.assertEqual(self.store.open_for_bid("C:/jobs/a.mdb", "7"), ())

    def test_unknown_ids_are_not_found(self):
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.get("missing")
        self.assertEqual(raised.exception.code, "not_found")

    def test_discard_closes_an_open_changeset_only(self):
        added = self.add()
        self.assertEqual(self.proposals.discard(added.uid).status, STATUS_DISCARDED)
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.discard(added.uid)
        self.assertEqual(raised.exception.code, "invalid_state")


class FreshnessTests(StoreTestCase):
    def test_apply_request_waits_for_approval(self):
        added = self.add()
        requested = self.proposals.request_apply(added.uid)
        self.assertEqual(requested.status, STATUS_PENDING_APPROVAL)
        self.assertEqual(
            self.proposals.request_apply(added.uid).status, STATUS_PENDING_APPROVAL
        )

    def test_only_touched_objects_make_a_changeset_stale(self):
        added = self.add()
        self.tokens.values["page:page-2"] = "changed"
        self.tokens.values["condition:99"] = "changed"
        self.assertEqual(
            self.proposals.request_apply(added.uid).status, STATUS_PENDING_APPROVAL
        )
        self.tokens.values["page:page-1"] = "changed"
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid)
        self.assertEqual(raised.exception.code, "stale_changeset")
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_STALE)

    def test_an_apply_request_on_a_touched_change_is_stale(self):
        added = self.add()
        self.tokens.values["page:page-1"] = "changed"
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.request_apply(added.uid)
        self.assertEqual(raised.exception.code, "stale_changeset")
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_STALE)


class ApprovalTests(StoreTestCase):
    def test_high_impact_open_assumptions_block_approval(self):
        added = self.add(
            _changeset(
                assumptions=(
                    _assumption("a1"),
                    _assumption("a2", SUBJECT_OTHER, IMPACT_NORMAL),
                ),
                thickness=None,
            )
        )
        self.proposals.request_apply(added.uid)
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid)
        self.assertEqual(raised.exception.code, "assumption_unresolved")
        self.store.override_assumption(added.uid, "a1", "10")
        approved = self.store.approve(added.uid)
        self.assertEqual(approved.status, STATUS_APPLYING)
        self.assertEqual(approved.resolved_conditions()[0].thickness_in, 10.0)
        statuses = {item.uid: item.status for item in approved.assumptions}
        self.assertEqual(statuses, {"a1": ASSUMPTION_OVERRIDDEN, "a2": ASSUMPTION_OPEN})

    def test_approval_requires_an_apply_request_first(self):
        added = self.add()
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid)
        self.assertEqual(raised.exception.code, "approval_required")

    def test_accept_and_reject(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        self.store.accept_assumption(added.uid, "a1")
        self.assertEqual(
            self.proposals.get(added.uid).assumptions[0].status, ASSUMPTION_ACCEPTED
        )
        self.proposals.request_apply(added.uid)
        self.assertEqual(self.store.reject(added.uid).status, STATUS_REJECTED)
        with self.assertRaises(ChangesetError):
            self.store.approve(added.uid)

    def test_applied_and_undone_are_recorded_per_bid(self):
        first = self.add()
        second = self.add()
        record = AppliedChangeset(
            folder_uid="F1",
            created_folder=True,
            condition_uids=("C1",),
            takeoff_uids=("T1",),
        )
        for changeset in (first, second):
            self.proposals.request_apply(changeset.uid)
            self.store.approve(changeset.uid)
            self.store.mark_applied(changeset.uid, record)
        self.assertEqual(self.proposals.get(second.uid).status, STATUS_APPLIED)
        self.assertEqual(self.store.last_applied("C:/jobs/a.mdb", "7").uid, second.uid)
        self.assertEqual(self.store.applied_record(second.uid), record)
        self.store.mark_undone(second.uid)
        self.assertEqual(self.proposals.get(second.uid).status, STATUS_UNDONE)
        self.assertEqual(self.store.last_applied("C:/jobs/a.mdb", "7").uid, first.uid)


class ProposalFacadeTests(StoreTestCase):
    def test_the_facade_offers_no_way_to_approve_or_accept(self):
        public = {name for name in dir(self.proposals) if not name.startswith("_")}
        self.assertEqual(
            public,
            {
                "add",
                "get",
                "discard",
                "request_apply",
                "add_assumption",
                "revise_assumption",
                "last_applied",
                "applied_record",
            },
        )

    def test_assumption_updates_never_change_status(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        added_more = self.proposals.add_assumption(
            added.uid, SUBJECT_OTHER, "c1", "flat", "ramp not shown", "S-102"
        )
        self.assertEqual(
            [(item.uid, item.status) for item in added_more.assumptions],
            [("a1", ASSUMPTION_OPEN), ("a2", ASSUMPTION_OPEN)],
        )
        revised = self.proposals.revise_assumption(
            added.uid, "a1", "9", "per S-101 note"
        )
        first = revised.assumptions[0]
        self.assertEqual(
            (first.value, first.reason, first.status),
            ("9", "per S-101 note", ASSUMPTION_OPEN),
        )
        self.store.accept_assumption(added.uid, "a1")
        reopened = self.proposals.revise_assumption(added.uid, "a1", "10", "changed")
        self.assertEqual(reopened.assumptions[0].status, ASSUMPTION_OPEN)


class RetentionTests(unittest.TestCase):
    def test_closed_changesets_do_not_accumulate(self):
        store = AiChangesetStore(clock=lambda: 100.0)
        proposals = AiChangesetProposals(store)
        first = proposals.add(_changeset())
        proposals.discard(first.uid)
        kept = proposals.add(_changeset())
        proposals.request_apply(kept.uid)
        store.approve(kept.uid)
        store.mark_applied(kept.uid, AppliedChangeset(takeoff_uids=("T1",)))
        last = None
        for _index in range(1000):
            last = proposals.add(_changeset())
            proposals.discard(last.uid)
        with self.assertRaises(ChangesetError) as raised:
            proposals.get(first.uid)
        self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual(proposals.get(last.uid).status, "discarded")
        self.assertEqual(proposals.get(kept.uid).status, "applied")
        self.assertEqual(proposals.last_applied("C:/jobs/a.mdb", "7").uid, kept.uid)


class MonotonicExpiryTests(unittest.TestCase):
    def test_expiry_follows_the_monotonic_clock_not_the_wall_clock(self):
        with patch.object(time, "monotonic", return_value=1000.0), patch.object(
            time, "time", return_value=5_000_000.0
        ):
            store = AiChangesetStore()
            proposals = AiChangesetProposals(store)
            added = proposals.add(_changeset())
        with patch.object(
            time, "monotonic", return_value=1000.0 + 1799.0
        ), patch.object(time, "time", return_value=5_000_000.0 + 7200.0):
            self.assertEqual(proposals.get(added.uid).status, "proposed")
        with patch.object(
            time, "monotonic", return_value=1000.0 + 1799.0
        ), patch.object(time, "time", return_value=5_000_000.0 - 7200.0):
            self.assertEqual(proposals.get(added.uid).status, "proposed")
        with patch.object(
            time, "monotonic", return_value=1000.0 + 1800.0
        ), patch.object(time, "time", return_value=5_000_000.0):
            self.assertEqual(proposals.get(added.uid).status, "expired")


if __name__ == "__main__":
    unittest.main()
