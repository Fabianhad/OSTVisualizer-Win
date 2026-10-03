"""Direct tests for the annotation history capture/resolve helpers and binding.
The data collaborator is an explicit fake that mirrors the three ProjectDataService
reads these helpers use (signature drift is checked below); annotations, pages,
page scales and BidRef are the real domain entities.
"""

import inspect
import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.presentation.services.annotation_history import (
    AnnotationHistoryBinding,
    AnnotationHistoryDependencyError,
    HOTLINK_VIEW_UNAVAILABLE_MESSAGE,
    capture_annotation_page_scales,
    capture_annotation_targets,
    capture_hotlink_view_dependencies,
    resolve_annotation_updates,
    resolve_hotlink_view_targets,
    retained_hotlink_view_targets,
)
from ost_visualizer.presentation.services.undo_redo_service import (
    AnnotationHistoryTarget,
)

BID = BidRef("bid.mdb", "7")


class _Data:
    def __init__(self, annotations=(), pages=None, bid=BID):
        self.annotations = list(annotations)
        self.pages = dict(pages or {})
        self.bid = bid
        self.scans = 0

    def get_all_annotations(self):
        self.scans += 1
        return list(self.annotations)

    def get_page(self, page_uid):
        return self.pages.get(page_uid)

    def get_current_bid_ref(self):
        return self.bid


class _Undo:
    def __init__(self):
        self.suspended = []
        self.rebound = []

    def suspend_deleted_annotations(self, bid_ref, deleted):
        self.suspended.append((bid_ref, deleted))
        return ("suspended", len(deleted))

    def rebind_restored_annotations(self, bid_ref, restored, targets):
        self.rebound.append((bid_ref, dict(restored), targets))


def _ann(uid, kind="rect", page="p1", position=None, **properties):
    return BidAnnotation(
        uid=uid,
        annotation_type=kind,
        page_uid=page,
        position=list(position if position is not None else [10, 10, 20, 20]),
        properties=dict(properties),
    )


def _target(uid, kind="rect", page="p1", bid=BID, available=True):
    return AnnotationHistoryTarget(bid, page, kind, uid, available)


def _pages():
    # Fresh Page objects per use: tests mutate page scale factors.
    return {
        "p1": Page("p1", "One"),
        "p2": Page("p2", "Two", scale_factor1=1.0, scale_factor2=2.0),
    }


class AnnotationHistoryFakeContractTests(unittest.TestCase):
    def test_fake_data_reads_match_project_data_service_signatures(self):
        for name in ("get_all_annotations", "get_page", "get_current_bid_ref"):
            with self.subTest(name):
                real = [
                    (p.name, p.default)
                    for p in list(
                        inspect.signature(
                            getattr(ProjectDataService, name)
                        ).parameters.values()
                    )[1:]
                ]
                fake = [
                    (p.name, p.default)
                    for p in list(
                        inspect.signature(getattr(_Data, name)).parameters.values()
                    )[1:]
                ]
                self.assertEqual(fake, real)


class CaptureAndResolveTests(unittest.TestCase):
    def test_page_scales_are_normalized_floats_keyed_by_text_uid(self):
        pages = {
            "1": Page("1", "a", scale_factor1=3, scale_factor2=6),
            "2": Page("2", "b", scale_factor1=0, scale_factor2=None),
        }
        scales = capture_annotation_page_scales(_Data(pages=pages), [1, "2"])
        self.assertEqual(scales, {"1": (3.0, 6.0), "2": (1.0, 1.0)})
        self.assertTrue(all(isinstance(v, float) for s in scales.values() for v in s))

    def test_missing_page_scale_is_refused_not_defaulted(self):
        with self.assertRaisesRegex(ValueError, "Annotation Page no longer exists"):
            capture_annotation_page_scales(_Data(pages=_pages()), ["p1", "gone"])

    def test_targets_key_by_uid_and_kind_with_each_annotations_own_page(self):
        data = _Data([_ann("1", "rect", "p2"), _ann("1", "text", "p1")])
        targets = capture_annotation_targets(
            data, BID, [(1, "rect", {"x": 1}, "extra"), ("1", "text")]
        )
        self.assertEqual(
            targets,
            {
                ("1", "rect"): _target("1", "rect", "p2"),
                ("1", "text"): _target("1", "text", "p1"),
            },
        )

    def test_unknown_annotation_is_not_authoritative(self):
        data = _Data([_ann("a1", "rect")])
        with self.assertRaisesRegex(ValueError, "no longer authoritative"):
            capture_annotation_targets(data, BID, [("a1", "text")])

    def test_resolve_without_targets_returns_the_updates_untouched(self):
        updates = [("a1", "rect", [1])]
        self.assertIs(resolve_annotation_updates(_Data(), updates, {}), updates)

    def test_resolve_follows_the_retargeted_uid_and_keeps_extra_values(self):
        data = _Data([_ann("restored", "rect", "p1")])
        target = _target("restored")
        targets = {("old", "rect"): target}
        self.assertEqual(
            resolve_annotation_updates(
                data, [("old", "rect", [1, 2], {"k": 1})], targets
            ),
            [("restored", "rect", [1, 2], {"k": 1})],
        )

    def test_resolve_refuses_each_way_the_annotation_stopped_owning_its_page(self):
        good = _Data([_ann("a1", "rect", "p1")])
        updates = [("a1", "rect", [1])]
        targets = {("a1", "rect"): _target("a1")}
        self.assertEqual(
            resolve_annotation_updates(good, updates, targets), [("a1", "rect", [1])]
        )
        cases = {
            "unavailable": (good, _target("a1", available=False)),
            "missing": (_Data([]), _target("a1")),
            "moved page": (_Data([_ann("a1", "rect", "p2")]), _target("a1")),
            "other bid": (
                _Data([_ann("a1", "rect", "p1")], bid=BidRef("other.mdb", "7")),
                _target("a1"),
            ),
            "other bid uid": (
                _Data([_ann("a1", "rect", "p1")], bid=BidRef("bid.mdb", "8")),
                _target("a1"),
            ),
            "no current bid": (
                _Data([_ann("a1", "rect", "p1")], bid=None),
                _target("a1"),
            ),
            "same uid other kind": (_Data([_ann("a1", "text", "p1")]), _target("a1")),
        }
        for label, (data, target) in cases.items():
            with self.subTest(label):
                with self.assertRaisesRegex(ValueError, "no longer owns its Page"):
                    resolve_annotation_updates(data, updates, {("a1", "rect"): target})

    def test_resolve_validates_every_target_before_returning(self):
        data = _Data([_ann("a1", "rect", "p1")])
        targets = {
            ("a1", "rect"): _target("a1"),
            ("a2", "rect"): _target("a2"),
        }
        with self.assertRaises(ValueError):
            resolve_annotation_updates(data, [("a1", "rect", [1])], targets)


class HotlinkDependencyTests(unittest.TestCase):
    def link(self, uid, target, kind="hotlink"):
        return _ann(uid, kind, "p1", [5, 5], BidPageViewUID=target)

    def test_capture_is_aligned_with_items_and_retains_each_external_view_once(self):
        data = _Data([_ann("5", "namedview", "p1"), _ann("6", "namedview", "p2")])
        items = [
            self.link("a", "5"),
            _ann("plain"),
            self.link("b", "6"),
            self.link("c", "5"),
        ]
        first, plain, third, fourth = capture_hotlink_view_dependencies(
            data, BID, items
        )
        self.assertIsNone(plain)
        self.assertIs(first, fourth)
        self.assertEqual(first, _target("5", "namedview", "p1"))
        self.assertEqual(third, _target("6", "namedview", "p2"))
        self.assertEqual(
            retained_hotlink_view_targets((first, plain, third, fourth)), (first, third)
        )

    def test_capture_ignores_views_of_its_own_batch_and_unreachable_views(self):
        data = _Data(
            [
                _ann("5", "namedview", "p1"),
                _ann("5", "rect", "p1"),
            ]
        )
        items = [self.link("a", "5"), self.link("b", "9"), self.link("c", "5")]
        self.assertEqual(
            capture_hotlink_view_dependencies(data, BID, items, {"5"}),
            (None, None, None),
        )
        self.assertEqual(
            capture_hotlink_view_dependencies(data, BID, items, {5}),
            (None, None, None),
        )
        self.assertEqual(
            capture_hotlink_view_dependencies(data, BID, items),
            (_target("5", "namedview", "p1"), None, _target("5", "namedview", "p1")),
        )

    def test_capture_treats_only_none_blank_and_zero_as_no_target(self):
        data = _Data([_ann("1", "namedview", "p1"), _ann("2", "namedview", "p2")])
        for no_target in (None, "", 0, "0"):
            with self.subTest(target=no_target):
                self.assertEqual(
                    capture_hotlink_view_dependencies(
                        data, BID, [self.link("a", no_target)]
                    ),
                    (None,),
                )
        # A real view whose uid is 1 (int or text) is a dependency like any other.
        for target in (1, "1"):
            with self.subTest(target=target):
                self.assertEqual(
                    capture_hotlink_view_dependencies(
                        data, BID, [self.link("a", target)]
                    ),
                    (_target("1", "namedview", "p1"),),
                )

    def test_capture_matches_only_namedview_type_with_the_same_uid(self):
        data = _Data([_ann("5", "rect", "p1")])
        self.assertEqual(
            capture_hotlink_view_dependencies(data, BID, [self.link("a", "5")]),
            (None,),
        )

    def test_capture_binds_the_bid_it_was_given(self):
        other = BidRef("other.mdb", "9")
        data = _Data([_ann("5", "namedview", "p1")])
        (dependency,) = capture_hotlink_view_dependencies(
            data, other, [self.link("a", "5")]
        )
        self.assertEqual(dependency.bid_ref, other)

    def test_resolve_ignores_surplus_dependencies_and_only_rewrites_dependents(self):
        data = _Data([_ann("10", "namedview", "p1")])
        item = self.link("a", "5")
        plain = _ann("b")
        dependency = _target("10", "namedview", "p1")
        resolved = resolve_hotlink_view_targets(
            data,
            [item, plain],
            (dependency, None, _target("77", "namedview", "p1")),
        )
        self.assertEqual(resolved[0].properties, {"BidPageViewUID": "10"})
        self.assertIs(resolved[1], plain)
        self.assertEqual(item.properties, {"BidPageViewUID": "5"})
        self.assertEqual(len(resolved), 2)

    def test_resolve_refuses_with_the_published_message(self):
        data = _Data([])
        with self.assertRaises(AnnotationHistoryDependencyError) as caught:
            resolve_hotlink_view_targets(
                data, [self.link("a", "5")], (_target("5", "namedview", "p1"),)
            )
        self.assertEqual(str(caught.exception), HOTLINK_VIEW_UNAVAILABLE_MESSAGE)
        self.assertIsInstance(caught.exception, ValueError)

    def test_resolve_refuses_a_view_whose_page_changed_under_the_same_uid(self):
        data = _Data([_ann("5", "namedview", "p2")])
        with self.assertRaises(AnnotationHistoryDependencyError):
            resolve_hotlink_view_targets(
                data, [self.link("a", "5")], (_target("5", "namedview", "p1"),)
            )

    def test_resolve_refuses_when_the_current_bid_is_not_the_captured_bid(self):
        dependency = _target("5", "namedview", "p1")
        for bid in (BidRef("other.mdb", "7"), BidRef("bid.mdb", "8"), None):
            with self.subTest(bid=bid):
                with self.assertRaises(AnnotationHistoryDependencyError):
                    resolve_hotlink_view_targets(
                        _Data([_ann("5", "namedview", "p1")], bid=bid),
                        [self.link("a", "5")],
                        (dependency,),
                    )

    def test_resolve_accepts_a_view_only_when_type_uid_and_page_all_match(self):
        dependency = _target("5", "namedview", "p1")
        item = self.link("a", "5")
        for annotation in (
            _ann("5", "rect", "p1"),
            _ann("6", "namedview", "p1"),
            _ann("5", "namedview", "p3"),
        ):
            with self.subTest(annotation=annotation):
                with self.assertRaises(AnnotationHistoryDependencyError):
                    resolve_hotlink_view_targets(
                        _Data([annotation]), [item], (dependency,)
                    )
        (resolved,) = resolve_hotlink_view_targets(
            _Data([_ann("5", "namedview", "p1")]), [item], (dependency,)
        )
        self.assertEqual(resolved.properties, {"BidPageViewUID": "5"})


class AnnotationHistoryBindingTests(unittest.TestCase):
    def binding(self, data=None, targets=None, **kwargs):
        data = data or _Data(
            [_ann("a1", "rect", "p1"), _ann("a2", "rect", "p2")], _pages()
        )
        targets = (
            targets
            if targets is not None
            else {
                ("a1", "rect"): _target("a1", "rect", "p1"),
                ("a2", "rect"): _target("a2", "rect", "p2"),
            }
        )
        undo = _Undo()
        return AnnotationHistoryBinding(data, undo, BID, targets, **kwargs), data, undo

    def test_scales_default_to_the_pages_current_scale_at_capture(self):
        binding, data, _undo = self.binding()
        # p2 was 1:2 when captured; when it later becomes 1:6, a stored geometry
        # replays three times larger there, while p1 (still 1:1) is unchanged.
        data.pages["p2"].scale_factor2 = 6.0
        self.assertEqual(
            binding.positions(
                [("a1", "rect", [10, 10, 20, 20]), ("a2", "rect", [10, 10, 20, 20])]
            ),
            [
                ("a1", "rect", [10, 10, 20, 20]),
                ("a2", "rect", [30.0, 30.0, 60.0, 60.0]),
            ],
        )

    def test_supplied_scales_are_copied_and_used_instead_of_capturing(self):
        scales = {"p1": (1.0, 1.0), "p2": (1.0, 1.0)}
        binding, _data, _undo = self.binding(captured_scales=scales)
        scales["p2"] = (1.0, 100.0)
        # p2's real current ratio is 2, the supplied captured ratio is 1.
        self.assertEqual(
            binding.positions([("a2", "rect", [10, 10, 20, 20])]),
            [("a2", "rect", [20.0, 20.0, 40.0, 40.0])],
        )

    def test_positions_keep_stored_rotation_untouched_when_rescaling(self):
        data = _Data([_ann("t", "text", "p2", [10, 10, 80, 24, 0.5])], _pages())
        targets = {("t", "text"): _target("t", "text", "p2")}
        binding, _data, _undo = self.binding(
            data, targets, captured_scales={"p2": (1.0, 1.0)}
        )
        self.assertEqual(
            binding.positions([("t", "text", [10, 10, 80, 24, 0.5])]),
            [("t", "text", [20.0, 20.0, 160.0, 48.0, 0.5])],
        )

    def test_updates_and_keys_resolve_through_the_current_uids(self):
        binding, data, _undo = self.binding()
        data.annotations = [_ann("r1", "rect", "p1"), _ann("a2", "rect", "p2")]
        binding.targets[("a1", "rect")].uid = "r1"
        self.assertEqual(
            binding.updates([("a1", "rect", [1]), ("a2", "rect", [2])]),
            [("r1", "rect", [1]), ("a2", "rect", [2])],
        )
        self.assertEqual(binding.keys(), [("r1", "rect"), ("a2", "rect")])

    def test_updates_refuse_when_an_annotation_left_its_page(self):
        binding, data, _undo = self.binding()
        data.annotations = [_ann("a1", "rect", "p2"), _ann("a2", "rect", "p2")]
        with self.assertRaisesRegex(ValueError, "no longer owns its Page"):
            binding.updates([("a1", "rect", [1])])

    def test_specs_rescale_each_spec_to_its_own_target_page(self):
        binding, data, _undo = self.binding(
            captured_scales={"p1": (1.0, 1.0), "p2": (1.0, 1.0)}
        )
        specs = [
            InsertAnnotationSpec("p1", "rect", [10, 10, 20, 20], "#fff", 1.0, {}),
            InsertAnnotationSpec("p2", "rect", [10, 10, 20, 20], "#fff", 1.0, {}),
        ]
        resolved = binding.specs(specs)
        self.assertEqual(
            [spec.position for spec in resolved],
            [[10, 10, 20, 20], [20.0, 20.0, 40.0, 40.0]],
        )
        self.assertEqual([spec.position for spec in specs], [[10, 10, 20, 20]] * 2)

    def test_specs_follow_a_restored_named_view_dependency(self):
        view = _target("5", "namedview", "p1")
        data = _Data(
            [_ann("a1", "hotlink", "p1", [5, 5], BidPageViewUID="5")], _pages()
        )
        binding, _data, _undo = self.binding(
            data,
            {("a1", "hotlink"): _target("a1", "hotlink", "p1")},
            view_dependencies=(view,),
        )
        spec = InsertAnnotationSpec(
            "p1", "hotlink", [5, 5], "#fff", 1.0, {"BidPageViewUID": "5"}
        )
        data.annotations.append(_ann("9", "namedview", "p1"))
        view.uid = "9"
        (resolved,) = binding.specs([spec])
        self.assertEqual(resolved.properties, {"BidPageViewUID": "9"})
        self.assertEqual(spec.properties, {"BidPageViewUID": "5"})
        view.available = False
        with self.assertRaises(AnnotationHistoryDependencyError):
            binding.specs([spec])

    def test_history_targets_list_own_targets_then_each_dependency_once(self):
        view = _target("5", "namedview", "p1")
        binding, _data, _undo = self.binding(view_dependencies=(view, None, view))
        self.assertEqual(binding.history_targets(), (*binding.targets.values(), view))
        self.assertEqual(binding.view_dependencies, (view, None, view))

    def test_saved_annotations_keep_current_uid_when_not_restoring(self):
        binding, data, _undo = self.binding(
            captured_scales={"p1": (1.0, 1.0), "p2": (1.0, 1.0)}
        )
        data.annotations = [_ann("r1", "rect", "p1"), _ann("a2", "rect", "p2")]
        binding.targets[("a1", "rect")].uid = "r1"
        saved = [
            _ann("stale-1", "rect", "p1", [10, 10, 20, 20]),
            _ann("stale-2", "rect", "p2", [10, 10, 20, 20]),
        ]
        result = binding.saved_annotations(saved)
        self.assertEqual(
            [(a.uid, a.position) for a in result],
            [("r1", [10, 10, 20, 20]), ("a2", [20.0, 20.0, 40.0, 40.0])],
        )
        self.assertEqual([a.uid for a in saved], ["stale-1", "stale-2"])

    def test_saved_annotations_validate_authority_unless_restoring(self):
        binding, data, _undo = self.binding()
        data.annotations = []
        saved = [_ann("a1", "rect", "p1"), _ann("a2", "rect", "p2")]
        with self.assertRaisesRegex(ValueError, "no longer owns its Page"):
            binding.saved_annotations(saved)
        restored = binding.saved_annotations(saved, restoring=True)
        self.assertEqual([a.uid for a in restored], ["a1", "a2"])

    def test_restoring_keeps_saved_uid_and_resolves_hotlink_targets(self):
        view = _target("5", "namedview", "p1")
        link = _ann("l1", "hotlink", "p1", [5, 5], BidPageViewUID="5")
        data = _Data([_ann("9", "namedview", "p1")], _pages())
        binding, _data, _undo = self.binding(
            data,
            {("l1", "hotlink"): _target("l1", "hotlink", "p1")},
            captured_scales={"p1": (1.0, 1.0)},
            view_dependencies=(view,),
        )
        view.uid = "9"
        (restored,) = binding.saved_annotations([link], restoring=True)
        self.assertEqual(restored.uid, "l1")
        self.assertEqual(restored.properties, {"BidPageViewUID": "9"})
        self.assertEqual(link.properties, {"BidPageViewUID": "5"})

    def test_suspend_and_rebind_use_the_targets_and_their_suspended_set(self):
        binding, _data, undo = self.binding()
        binding.suspend()
        self.assertEqual(undo.suspended, [(BID, tuple(binding.targets.values()))])
        binding.rebind(["r1", 2])
        self.assertEqual(
            undo.rebound,
            [
                (
                    BID,
                    {("p1", "rect", "a1"): "r1", ("p2", "rect", "a2"): "2"},
                    ("suspended", 2),
                )
            ],
        )

    def test_rebind_without_a_prior_suspend_rebinds_nothing_instead_of_failing(self):
        binding, _data, undo = self.binding()
        binding.rebind(["r1", "r2"])
        self.assertEqual(undo.rebound[0][2], ())

    def test_rebind_refuses_an_incomplete_identity_map(self):
        binding, _data, undo = self.binding()
        with self.assertRaisesRegex(ValueError, "incomplete identity map"):
            binding.rebind(["r1"])
        with self.assertRaisesRegex(ValueError, "incomplete identity map"):
            binding.rebind(["r1", "r2", "r3"])
        self.assertEqual(undo.rebound, [])


if __name__ == "__main__":
    unittest.main()
