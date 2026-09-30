import unittest
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.hotlink import build_hotlink_from_annotation


class BuildHotlinkFromAnnotationTests(unittest.TestCase):
    def test_non_hotlink_is_not_projected_as_a_link(self):
        self.assertIsNone(
            build_hotlink_from_annotation(
                BidAnnotation(uid="same", annotation_type="rect")
            )
        )

    def test_missing_coordinate_defaults_without_losing_owner_or_target(self):
        annotation = BidAnnotation(
            uid="link",
            annotation_type="hotlink",
            page_uid="page",
            layer_uid="layer",
            position=[8.5],
            width=3.0,
            color="#112233",
            properties={"BidPageViewUID": "view"},
        )
        result = build_hotlink_from_annotation(annotation)
        self.assertEqual((result.position_x, result.position_y), (8.5, 0.0))
        self.assertEqual(
            (
                result.uid,
                result.bid_page_uid,
                result.bid_layer_uid,
                result.target_view_uid,
            ),
            ("link", "page", "layer", "view"),
        )
        self.assertEqual((result.color, result.width), ("#112233", 3.0))
        self.assertEqual(annotation.position, [8.5])
