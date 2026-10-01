import unittest
from unittest.mock import Mock
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.utils.annotation_delete import (
    order_annotations_for_delete,
    plan_named_view_hotlink_delete,
    skipped_named_view_selection_keys,
)


def named_view(uid):
    return BidAnnotation(uid=uid, annotation_type="namedview")


def hotlink(uid, target):
    return BidAnnotation(
        uid=uid, annotation_type="hotlink", properties={"BidPageViewUID": target}
    )


class OrderAnnotationsForDeleteTests(unittest.TestCase):
    def test_stable_order_deletes_hotlinks_before_named_views_without_mutating_input(
        self,
    ):
        view = named_view("v")
        rect = BidAnnotation(uid="r", annotation_type="rect")
        first, second = hotlink("h1", "v"), hotlink("h2", "v")
        original = [view, rect, first, second]
        self.assertEqual(
            order_annotations_for_delete(original), [first, second, rect, view]
        )
        self.assertEqual(original, [view, rect, first, second])


class PlanNamedViewHotlinkDeleteTests(unittest.TestCase):
    def test_no_named_view_never_queries_links_or_confirms(self):
        annotation = BidAnnotation(uid="r", annotation_type="rect")
        resolver, confirm = Mock(), Mock()
        result = plan_named_view_hotlink_delete([annotation], resolver, confirm)
        self.assertEqual(result.annotations_to_delete, [annotation])
        self.assertEqual(result.skipped_named_view_uids, set())
        resolver.assert_not_called()
        confirm.assert_not_called()

    def test_declining_one_view_keeps_other_deletions_and_explicit_hotlinks(self):
        rejected, accepted = named_view("reject"), named_view("accept")
        explicit, linked = hotlink("explicit", "reject"), hotlink("linked", "accept")
        resolver = Mock(return_value=[explicit, linked])
        result = plan_named_view_hotlink_delete(
            [rejected, accepted, explicit],
            resolver,
            lambda annotation: annotation is accepted,
        )
        self.assertEqual(result.skipped_named_view_uids, {"reject"})
        self.assertEqual(result.annotations_to_delete, [explicit, linked, accepted])
        resolver.assert_called_once_with({"reject", "accept"})

    def test_link_deduplication_uses_typed_identity_not_raw_uid(self):
        view = named_view("same")
        link = hotlink("same", "same")
        result = plan_named_view_hotlink_delete(
            [view, link], lambda _uids: [link], lambda _view: True
        )
        self.assertEqual(result.annotations_to_delete, [link, view])

    def test_linked_hotlink_sharing_raw_uid_with_selected_view_is_still_added(self):
        view = named_view("same")
        link = hotlink("same", "same")
        result = plan_named_view_hotlink_delete(
            [view], lambda _uids: [link], lambda _view: True
        )
        self.assertEqual(result.annotations_to_delete, [link, view])
        self.assertEqual(result.skipped_named_view_uids, set())

    def test_confirmation_is_asked_once_per_linked_view_with_that_view(self):
        linked_view, unlinked_view = named_view("linked"), named_view("free")
        link = hotlink("h", "linked")
        confirm = Mock(return_value=True)
        plan_named_view_hotlink_delete(
            [linked_view, unlinked_view], lambda _uids: [link], confirm
        )
        confirm.assert_called_once_with(linked_view)

    def test_hotlink_without_target_does_not_count_as_link(self):
        view = named_view("v")
        blank_target = hotlink("h", "")
        confirm = Mock()
        result = plan_named_view_hotlink_delete(
            [view], lambda _uids: [blank_target], confirm
        )
        self.assertEqual(result.annotations_to_delete, [view])
        confirm.assert_not_called()

    def test_unlinked_view_does_not_require_confirmation(self):
        view = named_view("v")
        confirm = Mock()
        result = plan_named_view_hotlink_delete([view], lambda _uids: [], confirm)
        self.assertEqual(result.annotations_to_delete, [view])
        confirm.assert_not_called()


class SkippedNamedViewSelectionKeysTests(unittest.TestCase):
    def test_same_raw_uid_in_another_annotation_family_is_not_selected(self):
        keys = {
            ("same", "namedview"): "named-key",
            ("same", "hotlink"): "hot-key",
            ("other", "namedview"): "other-key",
        }
        self.assertEqual(
            skipped_named_view_selection_keys(keys, {"same"}), {"named-key"}
        )
