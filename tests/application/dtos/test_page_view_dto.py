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


if __name__ == "__main__":
    unittest.main()
