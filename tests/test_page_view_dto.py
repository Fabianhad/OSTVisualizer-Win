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


if __name__ == "__main__":
    unittest.main()
