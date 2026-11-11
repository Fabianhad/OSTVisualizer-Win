import json
import math
import struct
import unittest
from pathlib import Path
from ost_visualizer.domain.dtos.tower_crane_placement_dto import INCHES_PER_METRE
from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
    TOWER_CRANE_CREDIT,
    TOWER_CRANE_MODEL_PATH,
    glb_local_bounds,
    native_instance_corners,
    read_tower_crane_model,
)

REPO = Path(__file__).resolve().parents[4]


def _glb_json(data):
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + length])


def _json_only_glb(nodes, box_min=(-1.0, 0.0, -2.0), box_max=(3.0, 4.0, 2.0)):
    """A GLB whose only chunk is JSON: one box mesh and the given nodes."""
    document = {
        "asset": {"version": "2.0"},
        "nodes": nodes,
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [
            {
                "componentType": 5126,
                "count": 8,
                "type": "VEC3",
                "min": list(box_min),
                "max": list(box_max),
            }
        ],
    }
    body = bytearray(json.dumps(document).encode("utf-8"))
    while len(body) % 4:
        body += b" "
    return (
        struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(body))
        + struct.pack("<I4s", len(body), b"JSON")
        + bytes(body)
    )


_QUARTER_TURN_ABOUT_Y = [0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4)]
_TRANSLATE_UP_5 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 5, 0, 1]


class GlbLocalBoundsHierarchyTests(unittest.TestCase):
    def assertBounds(self, bounds, lo, hi):
        self.assertIsNotNone(bounds)
        for got, want in zip(bounds[0] + bounds[1], tuple(lo) + tuple(hi)):
            self.assertAlmostEqual(got, want, places=9)

    def test_parent_transforms_are_applied_down_a_nested_chain(self):
        # Root: x + 10 and scale 2; child: matrix y + 5; grandchild: the mesh,
        # turned a quarter about +Y (x, y, z) -> (z, y, -x).
        data = _json_only_glb(
            [
                {"translation": [10, 0, 0], "scale": [2, 2, 2], "children": [1]},
                {"matrix": _TRANSLATE_UP_5, "children": [2]},
                {"mesh": 0, "rotation": _QUARTER_TURN_ABOUT_Y},
            ]
        )
        self.assertBounds(glb_local_bounds(data), (6, 10, -6), (14, 18, 2))

    def test_a_child_listed_before_its_parent_still_gets_the_parent_transform(self):
        data = _json_only_glb(
            [{"mesh": 0}, {"translation": [0, 100, 0], "children": [0]}]
        )
        self.assertBounds(glb_local_bounds(data), (-1, 100, -2), (3, 104, 2))

    def test_translation_rotation_scale_on_the_mesh_node_itself_is_applied(self):
        data = _json_only_glb(
            [{"mesh": 0, "translation": [0, 0, 7], "scale": [1, 3, 1]}]
        )
        self.assertBounds(glb_local_bounds(data), (-1, 0, 5), (3, 12, 9))

    def test_a_plain_mesh_node_keeps_the_accessor_box(self):
        self.assertBounds(
            glb_local_bounds(_json_only_glb([{"mesh": 0}])), (-1, 0, -2), (3, 4, 2)
        )

    def test_a_hierarchy_cycle_or_bad_matrix_gives_no_bounds(self):
        cycle = [{"mesh": 0, "children": [1]}, {"children": [0]}]
        self.assertIsNone(glb_local_bounds(_json_only_glb(cycle)))
        self.assertIsNone(
            glb_local_bounds(_json_only_glb([{"mesh": 0, "matrix": [1.0] * 15}]))
        )


class ShippedTowerCraneModelTests(unittest.TestCase):
    def setUp(self):
        self.data = read_tower_crane_model()
        self.document = _glb_json(self.data)

    def test_model_is_a_small_untextured_quantized_glb_in_the_package(self):
        self.assertEqual(
            TOWER_CRANE_MODEL_PATH,
            REPO / "ost_visualizer" / "resources" / "models" / "tower_crane.glb",
        )
        self.assertEqual(self.data[:4], b"glTF")
        self.assertLess(len(self.data), 1_000_000)
        self.assertEqual(self.document["extensionsRequired"], ["KHR_mesh_quantization"])
        self.assertNotIn("images", self.document)
        self.assertNotIn("textures", self.document)
        names = [m["name"] for m in self.document["materials"]]
        self.assertEqual(
            names, ["material", "frame", "CONCRETE", "IRON", "BUCKET", "ROPE", "GLASS"]
        )
        glass = self.document["materials"][-1]
        self.assertEqual(glass["alphaMode"], "BLEND")
        self.assertLess(glass["pbrMetallicRoughness"]["baseColorFactor"][3], 0.99)

    def test_credit_travels_with_the_model(self):
        extras = self.document["asset"]["extras"]
        self.assertIn("Chamod", extras["author"])
        self.assertIn("CC-BY-4.0", extras["license"])
        self.assertEqual(extras["source"], TOWER_CRANE_CREDIT["source_url"])
        self.assertIn("base slab removed", extras["modified"])
        self.assertEqual(TOWER_CRANE_CREDIT["license"], "CC BY 4.0")

    def test_origin_is_the_mast_base_on_top_of_the_removed_footing(self):
        (lo, hi) = glb_local_bounds(self.data)
        # Anchors reach 0.37 m into the footing; the jib tip is ~37 m out on +X.
        self.assertAlmostEqual(lo[1], -0.372, places=2)
        self.assertAlmostEqual(hi[1], 50.796, places=2)
        self.assertAlmostEqual(hi[0], 37.172, places=1)
        self.assertLess(lo[0], -14.0)

    def test_native_frame_points_the_jib_to_scene_minus_x_and_keeps_it_upright(self):
        bounds = glb_local_bounds(self.data)
        corners = native_instance_corners(bounds, INCHES_PER_METRE, 0.0, 0.0, 48.0, 0.0)
        xs = [c[0] for c in corners]
        zs = [c[2] for c in corners]
        self.assertAlmostEqual(min(xs), -37.172 * INCHES_PER_METRE, delta=5.0)
        self.assertAlmostEqual(max(zs), 48.0 + 50.796 * INCHES_PER_METRE, delta=5.0)
        turned = native_instance_corners(
            bounds, INCHES_PER_METRE, 0.0, 0.0, 0.0, math.pi / 2
        )
        # A quarter turn about +Z swings the jib from -x to -y.
        self.assertAlmostEqual(min(c[1] for c in turned), min(xs), delta=1e-6)

    def test_unreadable_glb_has_no_bounds(self):
        self.assertIsNone(glb_local_bounds(b"not a glb"))
        self.assertIsNone(glb_local_bounds(b"glTF" + b"\x00" * 20))

    def test_both_build_scripts_package_the_model(self):
        for script in ("build.ps1", "build-visualizer.ps1"):
            with self.subTest(script=script):
                text = (REPO / "scripts" / script).read_text(encoding="utf-8")
                self.assertIn(
                    "--include-data-file=$TowerCraneModelPath="
                    "ost_visualizer/resources/models/tower_crane.glb",
                    text,
                )
                self.assertIn(
                    "'ost_visualizer\\resources\\models\\tower_crane.glb'", text
                )

    def test_source_model_is_kept_outside_the_package(self):
        source = REPO / "assets" / "models" / "tower_crane.source.glb"
        self.assertTrue(source.is_file())
        self.assertEqual(source.read_bytes()[:4], b"glTF")
        readme = (REPO / "assets" / "models" / "README.md").read_text(encoding="utf-8")
        self.assertIn("CC BY 4.0", readme)
        self.assertIn("tools\\prepare_tower_crane_asset.py", readme)


if __name__ == "__main__":
    unittest.main()
