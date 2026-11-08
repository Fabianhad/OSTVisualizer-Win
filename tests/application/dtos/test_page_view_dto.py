import unittest
from ost_visualizer.application.dtos.page_view_dto import PageViewDto


class PageViewDtoTests(unittest.TestCase):
    def test_page_area_selections_default_to_independent_empty_maps(self):
        first = PageViewDto(page=None)
        second = PageViewDto(page=None)
        self.assertIsNone(first.page_area_selections.get("page-1"))
        first.page_area_selections["page-1"] = "area-1"
        self.assertEqual(first.page_area_selections, {"page-1": "area-1"})
        self.assertEqual(second.page_area_selections, {})

    def test_hidden_layer_visibility_normalizes_identity_without_hiding_unassigned(
        self,
    ):
        first = PageViewDto(page=None)
        second = PageViewDto(page=None)
        first.hidden_layer_uids.add("7")
        self.assertFalse(first.is_layer_visible("7"))
        self.assertFalse(first.is_layer_visible(7))
        self.assertTrue(second.is_layer_visible("7"))
        self.assertEqual(second.hidden_layer_uids, set())
        for visible in (None, "", "other"):
            with self.subTest(visible=visible):
                self.assertTrue(first.is_layer_visible(visible))


class PageViewLayerVisibilityTests(unittest.TestCase):
    def test_a_layer_literally_named_none_is_not_confused_with_an_unassigned_layer(
        self,
    ):
        from ost_visualizer.application.dtos.page_view_dto import PageViewDto

        view = PageViewDto(page=None, hidden_layer_uids={"None", 5})
        self.assertIs(view.is_layer_visible(None), True)
        self.assertIs(view.is_layer_visible(""), True)
        self.assertIs(view.is_layer_visible("None"), False)
        self.assertIs(view.is_layer_visible(5), False)
        self.assertIs(view.is_layer_visible("5"), False)
        self.assertIs(view.is_layer_visible("other"), True)
        self.assertIs(PageViewDto(page=None).is_layer_visible("x"), True)


class PageViewDtoDefaultTests(unittest.TestCase):
    def test_page_is_required_and_every_other_field_has_its_documented_default(self):
        from dataclasses import fields

        with self.assertRaises(TypeError):
            PageViewDto()
        view = PageViewDto(page=None)
        self.assertEqual(
            [field.name for field in fields(PageViewDto)],
            [
                "page",
                "takeoffs",
                "conditions",
                "color_map",
                "bid_ref",
                "annotations",
                "ordered_pages",
                "named_view",
                "page_area_selections",
                "hidden_layer_uids",
                "annotation_layer_uid",
            ],
        )
        self.assertIsNone(view.page)
        self.assertIsNone(view.bid_ref)
        self.assertIsNone(view.named_view)
        self.assertIsNone(view.annotation_layer_uid)
        for name, empty_type in (
            ("takeoffs", list),
            ("conditions", dict),
            ("color_map", dict),
            ("annotations", list),
            ("ordered_pages", list),
            ("page_area_selections", dict),
            ("hidden_layer_uids", set),
        ):
            with self.subTest(field=name):
                value = getattr(view, name)
                self.assertIs(type(value), empty_type)
                self.assertEqual(len(value), 0)
                self.assertIsNot(value, getattr(PageViewDto(page=None), name))

    def test_constructor_values_are_kept_by_identity(self):
        takeoffs, annotations, pages = [], [], []
        conditions, color_map, selections = {}, {}, {}
        hidden = set()
        view = PageViewDto(
            page=None,
            takeoffs=takeoffs,
            conditions=conditions,
            color_map=color_map,
            bid_ref="ref",
            annotations=annotations,
            ordered_pages=pages,
            named_view="view",
            page_area_selections=selections,
            hidden_layer_uids=hidden,
            annotation_layer_uid="layer",
        )
        self.assertIs(view.takeoffs, takeoffs)
        self.assertIs(view.conditions, conditions)
        self.assertIs(view.color_map, color_map)
        self.assertEqual(view.bid_ref, "ref")
        self.assertIs(view.annotations, annotations)
        self.assertIs(view.ordered_pages, pages)
        self.assertEqual(view.named_view, "view")
        self.assertIs(view.page_area_selections, selections)
        self.assertIs(view.hidden_layer_uids, hidden)
        self.assertEqual(view.annotation_layer_uid, "layer")

    def test_a_blank_entry_in_the_hidden_set_never_hides_an_unassigned_layer(self):
        view = PageViewDto(page=None, hidden_layer_uids={"", "9"})
        self.assertIs(view.is_layer_visible(None), True)
        self.assertIs(view.is_layer_visible(""), True)
        self.assertIs(view.is_layer_visible(0), True)
        self.assertIs(view.is_layer_visible("9"), False)
        self.assertIs(view.is_layer_visible("10"), True)


if __name__ == "__main__":
    unittest.main()
