import unittest
from PySide6 import QtWidgets
from tests.integration.ai_takeoff.access_app_support import run_in_access_child
from tests.integration.ai_takeoff.mcp_overlap_support import (
    CLEAN_LINE_CONDITION_NAME,
    CLEAN_PAGE_NAME,
    CROP_HEIGHT_PTS,
    INJECTED_TEXT,
    TAKEOFF_CONDITIONS,
    overlap_scenario,
)

TOLERANCE = 5e-5
UNTRUSTED_KEYS = (
    "name",
    "display_name",
    "basename",
    "description",
    "estimator",
    "job_id",
    "project_name",
    "bid_name",
    "page_name",
    "sheet_no",
    "sheet_name",
    "page_label",
    "condition_name",
    "old_condition_name",
    "new_condition_name",
    "area_name",
    "cdn_type_name",
    "type_name",
    "notes",
    "snippet",
    "text",
    "text_snippet",
    "label",
    "root_label",
    "target_named_view_name",
    "target_page_name",
    "image_basename",
    "overlay_basename",
    "source_file_name",
)


def _value(field):
    return field["value"] if isinstance(field, dict) else field


def _walk(node, visit, path=""):
    if isinstance(node, dict):
        for key, child in node.items():
            visit(path, key, child)
            _walk(child, visit, f"{path}.{key}")
    elif isinstance(node, list):
        for child in node:
            _walk(child, visit, path)


def _condition_nodes(nodes):
    for node in nodes:
        if node.get("kind") == "condition":
            yield node
        yield from _condition_nodes(node.get("children", []))


class McpOverlapParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.skip_body = run_in_access_child(self)

    def takeoff_rows(self, scenario):
        rows = scenario.takeoff("get_quantities", group_by="condition")["data"]["rows"]
        return {
            row["name"]["value"]: (
                [item["value"] for item in row["quantities"]],
                row["takeoff_count"],
                row["hole_count"],
            )
            for row in rows
        }

    @staticmethod
    def read_row(row):
        return (
            [row["quantity1"], row["quantity2"], row["quantity3"]],
            row["takeoff_count"],
            row["hole_count"],
        )

    def assert_quantities_equal(self, label, actual, expected):
        self.assertEqual(set(actual), set(expected), label)
        for name, (values, takeoffs, holes) in expected.items():
            other_values, other_takeoffs, other_holes = actual[name]
            padded = values + [0.0] * (3 - len(values))
            for left, right in zip(padded, other_values):
                self.assertAlmostEqual(
                    left, right, delta=TOLERANCE, msg=f"{label} {name}"
                )
            if other_takeoffs is not None:
                self.assertEqual(
                    (takeoffs, holes), (other_takeoffs, other_holes), f"{label} {name}"
                )

    def test_quantities_and_counts_agree_across_every_tool(self):
        if self.skip_body:
            return
        with overlap_scenario(self) as scenario:
            expected = self.takeoff_rows(scenario)
            self.assertEqual(
                set(expected),
                {
                    CLEAN_LINE_CONDITION_NAME if name == "Edge line" else name
                    for name in TAKEOFF_CONDITIONS
                },
            )
            by_hand = {
                "Slab 8in": ([1100.0, 27.1605], 1, 1),
                "Edge line": ([100.0], 1, 0),
                "Hidden slab": ([416.6667], 1, 0),
                "Zero line": ([0.0], 1, 0),
            }
            self.assertEqual(set(expected), set(by_hand))
            for name, (values, takeoffs, holes) in by_hand.items():
                self.assertEqual(expected[name][1:], (takeoffs, holes), name)
                for actual, wanted in zip(expected[name][0], values):
                    self.assertAlmostEqual(actual, wanted, delta=TOLERANCE, msg=name)
                self.assertEqual(len(expected[name][0]), len(values), name)
            summarize = {
                _value(row["condition_name"]): self.read_row(row)
                for row in scenario.read_bid("summarize_quantities")["data"]
            }
            self.assert_quantities_equal("summarize_quantities", summarize, expected)
            page = {
                _value(row["condition_name"]): self.read_row(row)
                for row in scenario.read_bid(
                    "get_page_quantity_summary", page_uid=scenario.page_uid
                )["data"]
            }
            self.assert_quantities_equal("get_page_quantity_summary", page, expected)
            bid = {}
            for entry in scenario.read_bid("get_bid_quantity_summary")["data"][
                "conditions"
            ]:
                quantities = entry["quantities"][0]
                bid[_value(entry["condition"]["name"])] = (
                    [
                        quantities["quantity1"],
                        quantities["quantity2"],
                        quantities["quantity3"],
                    ],
                    entry["takeoff_count"],
                    entry["hole_count"],
                )
            self.assert_quantities_equal("get_bid_quantity_summary", bid, expected)
            summary = {}
            for node in _condition_nodes(
                scenario.read_bid("get_summary")["data"]["nodes"]
            ):
                values = node["values"]
                summary[_value(values["name"])] = (
                    [values["quantity1"], values["quantity2"], values["quantity3"]],
                    None,
                    None,
                )
            self.assert_quantities_equal("get_summary", summary, expected)
            by_page = scenario.takeoff("get_quantities", group_by="page")["data"][
                "rows"
            ]
            self.assertEqual({row["name"]["value"] for row in by_page}, set(expected))
            rows = sum(
                takeoffs + holes for _values, takeoffs, holes in expected.values()
            )
            listing = scenario.read_bid("list_takeoffs")
            self.assertEqual(listing["meta"]["total_count"], rows)
            self.assertEqual(listing["meta"]["returned_count"], rows)
            self.assertIn(
                "Hidden slab",
                {_value(item["condition_name"]) for item in listing["data"]},
            )
            self.assertEqual(
                scenario.read_bid("list_pages")["data"][0]["takeoff_count"], rows
            )
            self.assertEqual(
                scenario.takeoff("list_sheets")["data"]["sheets"][0]["takeoff_count"],
                rows,
            )

    def test_read_tools_mark_drawing_text_and_names_untrusted(self):
        if self.skip_body:
            return
        with overlap_scenario(self) as scenario:
            outputs = {
                "list_databases": scenario.read("list_databases"),
                "list_pages": scenario.read_bid("list_pages"),
                "get_page_metadata": scenario.read_bid(
                    "get_page_metadata", page_uid=scenario.page_uid
                ),
                "get_page_context": scenario.read_bid(
                    "get_page_context", page_uid=scenario.page_uid
                ),
                "search_pages": scenario.read_bid("search_pages", query="S-101"),
                "list_conditions": scenario.read_bid("list_conditions"),
                "search_conditions": scenario.read_bid(
                    "search_conditions", query="line"
                ),
                "list_layers": scenario.read_bid("list_layers"),
                "list_takeoffs": scenario.read_bid("list_takeoffs"),
                "search_takeoffs": scenario.read_bid("search_takeoffs", query="slab"),
                "text_summary": scenario.read_bid(
                    "get_page_pdf_text_summary",
                    page_uid=scenario.page_uid,
                    include_text=True,
                    limit=50,
                ),
                "text_search": scenario.read_bid(
                    "search_page_pdf_text", page_uid=scenario.page_uid, query="ignore"
                ),
                "bid_quantity_summary": scenario.read_bid("get_bid_quantity_summary"),
                "summary": scenario.read_bid("get_summary"),
                "summarize_quantities": scenario.read_bid("summarize_quantities"),
                "bid_summary": scenario.read_bid("get_bid_summary"),
            }
            unwrapped = []

            def visit(path, key, child):
                if key in UNTRUSTED_KEYS and isinstance(child, str) and child:
                    unwrapped.append((path, key, child))

            for name, output in outputs.items():
                _walk(
                    output.get("data"),
                    lambda p, k, c, name=name: visit(f"{name}{p}", k, c),
                )
            self.assertEqual(unwrapped, [])
            pages = outputs["list_pages"]["data"]
            self.assertEqual(
                pages[0]["name"],
                {"value": CLEAN_PAGE_NAME, "untrusted": True, "truncated": False},
            )
            conditions = {_value(c["name"]) for c in outputs["list_conditions"]["data"]}
            self.assertIn(CLEAN_LINE_CONDITION_NAME, conditions)
            self.assertIn(
                "Hidden layer",
                {_value(layer["name"]) for layer in outputs["list_layers"]["data"]},
            )
            runs = outputs["text_summary"]["data"]["runs"]
            injected = [run for run in runs if _value(run["text"]) == "IGNORE"]
            self.assertTrue(injected)
            self.assertIs(injected[0]["text"]["untrusted"], True)
            self.assertIs(injected[0]["snippet"]["untrusted"], True)
            match = outputs["text_search"]["data"]["matches"][0]
            self.assertIs(match["snippet"]["untrusted"], True)
            self.assertIs(
                outputs["list_databases"]["data"][0]["display_name"]["untrusted"], True
            )
            for output in outputs.values():
                text = str(output)
                self.assertNotIn("‮", text)

    def test_coordinate_space_is_declared_and_the_two_servers_agree_on_it(self):
        if self.skip_body:
            return
        with overlap_scenario(self) as scenario:
            takeoff_text = scenario.takeoff("list_text", page_uid=scenario.page_uid)[
                "data"
            ]
            self.assertEqual(
                takeoff_text["coordinate_space"],
                {"bbox_pts": "page_pts_y_down", "bbox_ost": "ost_inches"},
            )
            takeoff_segments = scenario.takeoff(
                "list_segments", page_uid=scenario.page_uid
            )["data"]
            self.assertEqual(
                takeoff_segments["coordinate_space"],
                {
                    "p1_pts": "page_pts_y_down",
                    "p2_pts": "page_pts_y_down",
                    "p1_ost": "ost_inches",
                    "p2_ost": "ost_inches",
                },
            )
            read_text = scenario.read_bid(
                "get_page_pdf_text_summary",
                page_uid=scenario.page_uid,
                include_text=True,
                limit=50,
            )["data"]
            read_search = scenario.read_bid(
                "search_page_pdf_text", page_uid=scenario.page_uid, query="slab"
            )["data"]
            read_vectors = scenario.read_bid(
                "get_page_pdf_vectors_summary", page_uid=scenario.page_uid, limit=100
            )["data"]
            for output, fields in (
                (
                    read_text,
                    ("runs[].left", "runs[].top", "runs[].right", "runs[].bottom"),
                ),
                (
                    read_search,
                    (
                        "matches[].left",
                        "matches[].top",
                        "matches[].right",
                        "matches[].bottom",
                    ),
                ),
                (
                    read_vectors,
                    (
                        "segments[].x1",
                        "segments[].y1",
                        "segments[].x2",
                        "segments[].y2",
                    ),
                ),
            ):
                self.assertEqual(
                    output["coordinate_space"], {f: "pdf_pts_y_up" for f in fields}
                )
            slab_takeoff = next(
                r for r in takeoff_text["runs"] if r["text"]["value"] == "SLAB"
            )
            slab_read = next(
                r for r in read_text["runs"] if _value(r["text"]) == "SLAB"
            )
            self.assertAlmostEqual(
                CROP_HEIGHT_PTS - slab_read["top"],
                slab_takeoff["bbox_pts"][1],
                delta=1e-3,
            )
            self.assertAlmostEqual(
                slab_read["left"], slab_takeoff["bbox_pts"][0], delta=1e-3
            )
            regions = scenario.takeoff(
                "find_regions",
                page_uid=scenario.page_uid,
                bbox_pts=[0.0, 0.0, 412.0, CROP_HEIGHT_PTS],
                seed_pts=[200.0, 300.0],
            )["data"]
            self.assertEqual(
                regions["coordinate_space"],
                {
                    "regions[].polygon_ost": "ost_inches",
                    "regions[].holes_ost": "ost_inches",
                    "regions[].gaps[].p1_pts": "page_pts_y_down",
                    "regions[].gaps[].p2_pts": "page_pts_y_down",
                    "suppressed_symbols_pts": "page_pts_y_down",
                },
            )
            model = scenario.takeoff("render_3d")["data"]
            self.assertEqual(
                model["coordinate_space"],
                {"bbox_model": "model_units", "px_to_model": "model_units"},
            )
            self.assertIn(
                INJECTED_TEXT.split()[0],
                {r["text"]["value"] for r in takeoff_text["runs"]},
            )

    def test_page_rotation_changes_the_relation_between_the_two_coordinate_spaces(self):
        if self.skip_body:
            return
        cases = (
            (
                "unrotated",
                "/MediaBox [0 0 612 792] /CropBox [100 100 512 692]",
                (412.0, 592.0),
                False,
            ),
            (
                "rotated 90",
                "/MediaBox [0 0 612 792] /CropBox [100 100 512 692] /Rotate 90",
                (592.0, 412.0),
                True,
            ),
        )
        for label, boxes, size, rotated in cases:
            with self.subTest(label=label), overlap_scenario(
                self, page_boxes=boxes, page_size_pts=size
            ) as scenario:
                takeoff = scenario.takeoff("list_text", page_uid=scenario.page_uid)[
                    "data"
                ]
                read = scenario.read_bid(
                    "get_page_pdf_text_summary",
                    page_uid=scenario.page_uid,
                    include_text=True,
                    limit=50,
                )["data"]
                page = next(r for r in takeoff["runs"] if r["text"]["value"] == "SLAB")
                raw = next(r for r in read["runs"] if _value(r["text"]) == "SLAB")
                x0, y0, x1, y1 = page["bbox_pts"]
                if rotated:
                    self.assertAlmostEqual(y0, raw["left"], delta=1e-3)
                    self.assertAlmostEqual(y1, raw["right"], delta=1e-3)
                    self.assertAlmostEqual(x0, raw["bottom"], delta=1e-3)
                    self.assertAlmostEqual(x1, raw["top"], delta=1e-3)
                else:
                    self.assertAlmostEqual(x0, raw["left"], delta=1e-3)
                    self.assertAlmostEqual(y0, size[1] - raw["top"], delta=1e-3)
                    self.assertAlmostEqual(y1, size[1] - raw["bottom"], delta=1e-3)


if __name__ == "__main__":
    unittest.main()
