import unittest
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.application.dtos.collaboration_dtos import MutationOutcomeStatus
from ost_visualizer.domain.services.takeoff_domain_service import (
    expand_takeoff_uids_with_descendants,
)
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    MissingBidOwnedUidError,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from tests import test_plan_property_history_identity as history
from tests import test_plan_property_ownership as ownership


class ConditionReassignmentBackoutTests(unittest.TestCase):
    def test_area_with_attachment_reassigns_backouts_without_retyping_attachment(self):
        fixture = history.PlanPropertyHistoryIdentityTests()
        for queued in (False, True):
            with self.subTest(queued=queued):
                handler, data, write, undo = fixture.make_handler()
                data.conditions["attachment"] = Condition(
                    uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
                )
                data.takeoffs["attachment"] = replace(
                    data.takeoffs["child"],
                    uid="attachment",
                    condition_uid="attachment",
                    position=[2, 2],
                )
                write.sql_collaboration_mutations = queued
                handler.on_reassign_condition(["parent"], "42")
                if queued:
                    self.assertTrue(write.queued_properties)
                    fixture.complete_property(data, write)
                self.assertEqual(data.takeoffs["parent"].condition_uid, "42")
                self.assertEqual(data.takeoffs["child"].condition_uid, "42")
                self.assertEqual(
                    data.takeoffs["attachment"].condition_uid, "attachment"
                )
                undo.undo()
                if queued:
                    fixture.complete_property(data, write)
                self.assertEqual(data.takeoffs["parent"].condition_uid, "c1")
                self.assertEqual(data.takeoffs["child"].condition_uid, "c1")
                self.assertEqual(
                    data.takeoffs["attachment"].condition_uid, "attachment"
                )

    def persistence_fixture(self):
        fixture = ownership.PlanPropertyOwnershipTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.conn.executescript(
            "CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY, BidUID INTEGER);"
            "INSERT INTO BidConditions VALUES (30,7),(31,7),(32,7);"
            "INSERT INTO BidTakeoffs VALUES (14,7,20,31,2,10,'3;3;4;3;4;4');"
        )
        fixture.service._save_takeoffs_condition = SimpleNamespace(
            execute=fixture.ops.save_takeoffs_condition
        )
        return fixture

    def test_persisted_batch_and_inverse_preserve_every_non_condition_field(self):
        for queued in (False, True):
            with self.subTest(queued=queued):
                fixture = self.persistence_fixture()
                targets = expand_takeoff_uids_with_descendants(
                    fixture.takeoffs(), ("10", "11", "12")
                )
                before = fixture.snapshot()
                forward = [(uid, "32") for uid in sorted(targets)]
                inverse = [(str(row[0]), str(row[3])) for row in before]
                requests = []
                fixture.service._sql_collaboration_provider = lambda: SimpleNamespace(
                    queue_request=lambda *args: requests.append(args) or 1
                )
                for updates in (forward, inverse, forward, inverse):
                    if queued:
                        fixture.service.queue_plan_properties(
                            "database.mdb",
                            "7",
                            "takeoff_condition",
                            updates,
                            lambda _result: None,
                        )
                        result = requests[-1][1]()
                    else:
                        result = fixture.service.execute_plan_properties_local(
                            "database.mdb",
                            "7",
                            "takeoff_condition",
                            updates,
                            publish_database_refreshed_after_write=False,
                        )
                    self.assertEqual(
                        result.outcome_status, MutationOutcomeStatus.COMMITTED
                    )
                    after = fixture.snapshot()
                    self.assertEqual(
                        [row[:3] + row[4:] for row in after],
                        [row[:3] + row[4:] for row in before],
                    )
                    self.assertEqual(
                        {str(row[0]): str(row[3]) for row in after}, dict(updates)
                    )

    def test_captured_reassignment_rejects_deleted_reparented_or_changed_child(self):
        for mutation in (
            "DELETE FROM BidTakeoffs WHERE UID=14",
            "UPDATE BidTakeoffs SET ParentUID=12 WHERE UID=14",
            "UPDATE BidTakeoffs SET BidConditionUID=30 WHERE UID=14",
        ):
            with self.subTest(mutation=mutation):
                fixture = self.persistence_fixture()
                targets = expand_takeoff_uids_with_descendants(
                    fixture.takeoffs(), ("10", "11")
                )
                payload = fixture.service._plan_property_payload(
                    "database.mdb",
                    "7",
                    "takeoff_condition",
                    [(uid, "32") for uid in sorted(targets)],
                )
                queued = []
                fixture.service._sql_collaboration_provider = lambda: SimpleNamespace(
                    queue_request=lambda *args: queued.append(args) or 1
                )
                fixture.service.queue_plan_properties(
                    "database.mdb",
                    "7",
                    "takeoff_condition",
                    [(uid, "32") for uid in sorted(targets)],
                    lambda _result: None,
                )
                fixture.conn.execute(mutation)
                fixture.conn.commit()
                before = fixture.snapshot()
                with self.assertRaises(MissingBidOwnedUidError):
                    fixture.apply(payload)
                self.assertEqual(fixture.snapshot(), before)
                with self.assertRaises(MissingBidOwnedUidError):
                    queued[0][1]()
                self.assertEqual(fixture.snapshot(), before)
                # Exercise SQL's real preflight against the same persisted row
                # snapshots. Its transport returns rows; SQL conflicts retain
                # the backend's optimistic-conflict classification.
                rows = [
                    (row[0], row[2], row[3], row[4], row[5])
                    for row in before
                    if str(row[0]) in targets
                ]

                class Cursor:
                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return False

                    def execute(self, *_args):
                        pass

                    def fetchone(self):
                        return (0,)

                    def fetchall(self):
                        return rows

                @contextmanager
                def connection(_database):
                    yield SimpleNamespace(cursor=Cursor)

                writer = SqlProjectWriter.__new__(SqlProjectWriter)
                writer._write_schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)
                writer._connection = connection
                with self.assertRaises(SqlInfrastructureError) as caught:
                    writer.verify_plan_items_exist(
                        "database",
                        "7",
                        tuple(sorted(targets)),
                        (),
                        takeoff_ownership=payload.takeoff_ownership,
                    )
                self.assertEqual(caught.exception.details.code, SqlErrorCode.CONFLICT)

    def test_parent_reassignment_and_history_include_all_backouts_on_both_paths(self):
        fixture = history.PlanPropertyHistoryIdentityTests()
        for queued in (False, True):
            for selected in (
                ("parent",),
                ("parent", "plain"),
                ("parent", "child", "parent"),
            ):
                with self.subTest(queued=queued, selected=selected):
                    handler, data, write, undo = fixture.make_handler()
                    data.conditions["other"] = replace(
                        data.conditions["c1"], uid="other"
                    )
                    data.takeoffs["second"] = replace(
                        data.takeoffs["child"],
                        uid="second",
                        condition_uid="other",
                        position=[3, 3, 4, 3, 4, 4],
                    )
                    data.takeoffs["nested"] = replace(
                        data.takeoffs["child"],
                        uid="nested",
                        parent_uid="second",
                    )
                    data.takeoffs["plain"] = replace(
                        data.takeoffs["parent"], uid="plain"
                    )
                    before = {uid: replace(item) for uid, item in data.takeoffs.items()}
                    targets = {"parent", "child", "second", "nested"} | set(selected)
                    write.sql_collaboration_mutations = queued
                    handler.on_reassign_condition(list(selected), "42")
                    if queued:
                        updates = write.queued_properties[-1][3]
                        self.assertEqual({uid for uid, _ in updates}, targets)
                        self.assertEqual(len(updates), len(targets))
                        fixture.complete_property(data, write)

                    def verify(restored):
                        for uid, item in data.takeoffs.items():
                            expected = (
                                before[uid].condition_uid
                                if restored or uid not in targets
                                else "42"
                            )
                            self.assertEqual(item.condition_uid, expected, uid)
                            self.assertEqual(
                                replace(item, condition_uid=before[uid].condition_uid),
                                before[uid],
                            )

                    verify(False)
                    for _cycle in range(2):
                        undo.undo()
                        if queued:
                            fixture.complete_property(data, write)
                        verify(True)
                        undo.redo()
                        if queued:
                            fixture.complete_property(data, write)
                        verify(False)

    def test_selected_backout_does_not_pull_in_parent_or_siblings(self):
        fixture = history.PlanPropertyHistoryIdentityTests()
        handler, data, _write, undo = fixture.make_handler()
        data.takeoffs["sibling"] = replace(data.takeoffs["child"], uid="sibling")
        handler.on_reassign_condition(["child"], "42")
        self.assertEqual(data.takeoffs["child"].condition_uid, "42")
        self.assertEqual(data.takeoffs["parent"].condition_uid, "c1")
        self.assertEqual(data.takeoffs["sibling"].condition_uid, "c1")
        undo.undo()
        self.assertEqual(data.takeoffs["child"].condition_uid, "c1")
