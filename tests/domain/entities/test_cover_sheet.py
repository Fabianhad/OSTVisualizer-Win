import unittest
from ost_visualizer.domain.entities.cover_sheet import (
    JobStatus,
    resolve_bid_status_lock,
)


def _statuses(*rows):
    return [
        JobStatus(uid=uid, name=f"status {uid}", locked=locked) for uid, locked in rows
    ]


class ResolveBidStatusLockTests(unittest.TestCase):
    """The single rule behind the Bid lock reads: no status is unlocked, a
    resolvable status reads its own flag, an unresolvable one is None (the
    callers turn that into a fail-closed lock)."""

    def test_a_bid_without_a_status_is_unlocked_whatever_the_statuses_say(self):
        for status_uid in (None, ""):
            for rows in ([], [("1", True)], [("", True), ("0", True)]):
                with self.subTest(status_uid=status_uid, statuses=rows):
                    result = resolve_bid_status_lock(_statuses(*rows), status_uid)
                    self.assertIs(result, False)

    def test_an_unknown_status_uid_is_unresolved_not_unlocked(self):
        statuses = _statuses(("1", False), ("2", True))
        for status_uid in ("3", "0", 0, "01", "-1"):
            with self.subTest(status_uid=status_uid):
                self.assertIsNone(resolve_bid_status_lock(statuses, status_uid))
        self.assertIsNone(resolve_bid_status_lock([], "1"))
        self.assertIsNone(resolve_bid_status_lock([], 0))
        self.assertIsNone(resolve_bid_status_lock(iter(()), "0"))

    def test_a_matching_uid_reads_that_statuss_own_locked_flag(self):
        statuses = _statuses(("1", True), ("2", False), ("3", True))
        self.assertIs(resolve_bid_status_lock(statuses, "1"), True)
        self.assertIs(resolve_bid_status_lock(statuses, "2"), False)
        self.assertIs(resolve_bid_status_lock(statuses, "3"), True)

    def test_the_status_uid_zero_is_an_ordinary_uid_when_it_exists(self):
        for locked in (True, False):
            with self.subTest(locked=locked):
                statuses = _statuses(("1", not locked), ("0", locked))
                self.assertIs(resolve_bid_status_lock(statuses, "0"), locked)
                self.assertIs(resolve_bid_status_lock(statuses, 0), locked)

    def test_uids_match_by_text_whether_stored_as_int_or_str(self):
        for stored, requested in ((2, "2"), ("2", 2), (2, 2), ("2", "2")):
            for locked in (True, False):
                with self.subTest(stored=stored, requested=requested, locked=locked):
                    statuses = _statuses((1, not locked), (stored, locked))
                    self.assertIs(resolve_bid_status_lock(statuses, requested), locked)

    def test_the_first_matching_status_wins(self):
        self.assertIs(
            resolve_bid_status_lock(_statuses(("2", True), ("2", False)), "2"), True
        )
        self.assertIs(
            resolve_bid_status_lock(_statuses(("2", False), ("2", True)), "2"), False
        )
        self.assertIs(
            resolve_bid_status_lock(_statuses((2, False), ("2", True)), "2"), False
        )

    def test_uids_are_compared_verbatim_without_trimming_or_case_folding(self):
        for stored, requested in (
            ("2", " 2"),
            ("2", "2 "),
            (" 2", "2"),
            ("2 ", "2"),
            ("a", "A"),
            ("A", "a"),
        ):
            with self.subTest(stored=stored, requested=requested):
                statuses = _statuses((stored, True))
                self.assertIsNone(resolve_bid_status_lock(statuses, requested))
        self.assertIs(resolve_bid_status_lock(_statuses((" 2", True)), " 2"), True)

    def test_a_none_status_uid_is_not_matched_against_the_statuses(self):
        statuses = _statuses(("None", True))
        self.assertIs(resolve_bid_status_lock(statuses, None), False)
        self.assertIsNone(resolve_bid_status_lock(statuses, "none"))

    def test_the_statuses_may_be_a_one_shot_iterable(self):
        generator = (status for status in _statuses(("1", False), ("2", True)))
        self.assertIs(resolve_bid_status_lock(generator, "2"), True)
