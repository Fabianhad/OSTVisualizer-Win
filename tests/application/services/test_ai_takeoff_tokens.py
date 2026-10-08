import hashlib
import json
import unittest
from dataclasses import replace
from ost_visualizer.application.services.ai_takeoff_tokens import ProjectDataTokenReader
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff


class FakeProjectData:
    def __init__(self):
        self.bid_ref = BidRef("C:/jobs/a.mdb", "7")
        self.pages = {
            "p1": Page(
                uid="p1",
                name="P1",
                image_path="C:/plans/a.pdf",
                scale_factor1=0.25,
                scale_factor2=12.0,
            ),
            "p2": Page(
                uid="p2",
                name="P2",
                image_path="C:/plans/b.pdf",
                scale_factor1=0.25,
                scale_factor2=12.0,
            ),
        }
        self.conditions = {"c1": Condition(uid="c1", name="Slab", thickness=8.0)}
        self.takeoffs = [
            Takeoff("t1", "c1", "p1", position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0]),
            Takeoff("t2", "c1", "p2", position=[1.0, 1.0, 2.0, 2.0]),
        ]

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_page(self, uid):
        return self.pages.get(uid)

    def get_bid_conditions(self):
        return dict(self.conditions)

    def get_page_takeoffs(self, page_uid):
        return [takeoff for takeoff in self.takeoffs if takeoff.page_uid == page_uid]

    def get_all_takeoffs(self):
        return list(self.takeoffs)


class ProjectDataTokenReaderTests(unittest.TestCase):
    RESOURCES = ("condition:c1", "page:p1", "page_takeoffs:p1")

    def setUp(self):
        self.project = FakeProjectData()
        self.reader = ProjectDataTokenReader(self.project)

    def read(self):
        return self.reader("C:/jobs/a.mdb", "7", self.RESOURCES)

    def test_tokens_are_stable_while_nothing_changes(self):
        first = self.read()
        self.assertEqual(set(first), set(self.RESOURCES))
        self.assertTrue(all(len(token) == 16 for token in first.values()))
        self.assertEqual(self.read(), first)

    def test_page_tokens_digest_the_scale_fields_as_canonical_key_sorted_json(self):
        page = self.project.pages["p1"]
        canonical = json.dumps(
            {
                "height_pts": page.height_pts,
                "image_path": page.image_path,
                "overlay_image_path": page.overlay_image_path,
                "page_index": page.page_index,
                "scale_factor1": page.scale_factor1,
                "scale_factor2": page.scale_factor2,
                "width_pts": page.width_pts,
            },
            separators=(",", ":"),
        )
        self.assertEqual(
            self.read()["page:p1"],
            hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
        )

    def test_each_touched_object_change_changes_only_its_token(self):
        cases = {
            "page:p1": lambda: self.project.pages.__setitem__(
                "p1", replace(self.project.pages["p1"], scale_factor1=0.125)
            ),
            "page_takeoffs:p1": lambda: self.project.takeoffs.__setitem__(
                0,
                replace(
                    self.project.takeoffs[0], position=[0.0, 0.0, 11.0, 0.0, 10.0, 10.0]
                ),
            ),
            "condition:c1": lambda: self.project.conditions.__setitem__(
                "c1", replace(self.project.conditions["c1"], thickness=10.0)
            ),
        }
        for resource, change in cases.items():
            with self.subTest(resource=resource):
                self.setUp()
                before = self.read()
                change()
                after = self.read()
                self.assertEqual(
                    {name for name in self.RESOURCES if before[name] != after[name]},
                    {resource},
                )

    def test_condition_membership_tokens_follow_which_takeoffs_use_a_condition(self):
        resources = ("condition_takeoffs:c1", "condition_takeoffs:c2")
        before = self.reader("C:/jobs/a.mdb", "7", resources)
        self.project.takeoffs[0] = replace(
            self.project.takeoffs[0], position=[5.0, 5.0, 6.0, 5.0, 6.0, 6.0]
        )
        self.assertEqual(self.reader("C:/jobs/a.mdb", "7", resources), before)
        self.project.takeoffs.append(
            Takeoff("t3", "c1", "p1", position=[0.0, 0.0, 1.0, 1.0])
        )
        after = self.reader("C:/jobs/a.mdb", "7", resources)
        self.assertNotEqual(
            after["condition_takeoffs:c1"], before["condition_takeoffs:c1"]
        )
        self.assertEqual(
            after["condition_takeoffs:c2"], before["condition_takeoffs:c2"]
        )
        self.project.takeoffs[2] = replace(self.project.takeoffs[2], condition_uid="c2")
        moved = self.reader("C:/jobs/a.mdb", "7", resources)
        self.assertEqual(
            moved["condition_takeoffs:c1"], before["condition_takeoffs:c1"]
        )
        self.assertNotEqual(
            moved["condition_takeoffs:c2"], before["condition_takeoffs:c2"]
        )

    def test_unrelated_objects_do_not_change_tokens(self):
        before = self.read()
        self.project.pages["p2"] = replace(self.project.pages["p2"], scale_factor1=1.0)
        self.project.takeoffs[1] = replace(
            self.project.takeoffs[1], position=[9.0, 9.0]
        )
        self.project.conditions["c2"] = Condition(uid="c2", name="Other")
        self.assertEqual(self.read(), before)

    def test_another_open_bid_or_missing_objects_never_match(self):
        before = self.read()
        self.project.bid_ref = BidRef("C:/jobs/a.mdb", "8")
        self.assertEqual(set(self.read().values()), {"closed"})
        self.project.bid_ref = BidRef("C:/jobs/a.mdb", "7")
        del self.project.pages["p1"]
        del self.project.conditions["c1"]
        tokens = self.read()
        self.assertEqual(
            (tokens["page:p1"], tokens["condition:c1"]), ("missing", "missing")
        )
        self.assertNotEqual(tokens, before)
        self.assertEqual(
            self.reader("C:/jobs/a.mdb", "7", ("bogus:1",)), {"bogus:1": "unknown"}
        )

    def test_takeoff_tokens_follow_one_takeoff(self):
        before = self.reader("C:/jobs/a.mdb", "7", ("takeoff:t1", "takeoff:t2"))
        self.project.takeoffs[1] = replace(
            self.project.takeoffs[1], position=[3.0, 3.0]
        )
        after = self.reader(
            "C:/jobs/a.mdb", "7", ("takeoff:t1", "takeoff:t2", "takeoff:t9")
        )
        self.assertEqual(after["takeoff:t1"], before["takeoff:t1"])
        self.assertNotEqual(after["takeoff:t2"], before["takeoff:t2"])
        self.assertEqual(after["takeoff:t9"], "missing")


if __name__ == "__main__":
    unittest.main()
