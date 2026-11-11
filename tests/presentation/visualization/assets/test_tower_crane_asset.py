import json
import math
import struct
import unittest
from pathlib import Path
from ost_visualizer.domain.dtos.tower_crane_placement_dto import INCHES_PER_METRE
from tests.presentation.visualization.assets.glb_positions import mast_anchor_bounds
from ost_visualizer.domain.entities import tower_crane_spec as spec
from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
    TOWER_CRANE_CREDIT,
    TOWER_CRANE_KIT_PARTS,
    TOWER_CRANE_KIT_PATH,
    TOWER_CRANE_KIT_VERSION,
    native_instance_corners,
    read_tower_crane_kit,
    tower_crane_kit_metadata,
    tower_crane_parts_without_edges,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_layout import (
    tower_crane_layout,
)

REPO = Path(__file__).resolve().parents[4]


def _glb_json(data):
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + length])


def _json_glb(document):
    """A GLB holding only this JSON chunk (enough for metadata checks)."""
    body = bytearray(json.dumps(document).encode("utf-8"))
    while len(body) % 4:
        body += b" "
    return (
        struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(body))
        + struct.pack("<I4s", len(body), b"JSON")
        + bytes(body)
    )


class ShippedTowerCraneKitTests(unittest.TestCase):
    """The kit: the crane cut into reusable parts, with its layout metadata."""

    @classmethod
    def setUpClass(cls):
        cls.data = read_tower_crane_kit()
        cls.document = _glb_json(cls.data)
        cls.kit = tower_crane_kit_metadata(cls.data)

    def test_the_kit_is_a_small_quantized_glb_with_one_node_per_part(self):
        self.assertEqual(
            TOWER_CRANE_KIT_PATH,
            REPO / "ost_visualizer" / "resources" / "models" / "tower_crane_kit.glb",
        )
        self.assertEqual(self.data[:4], b"glTF")
        self.assertLess(len(self.data), 1_000_000)
        self.assertEqual(self.document["extensionsRequired"], ["KHR_mesh_quantization"])
        self.assertNotIn("images", self.document)
        nodes = self.document["nodes"]
        self.assertEqual([node["name"] for node in nodes], list(TOWER_CRANE_KIT_PARTS))
        self.assertEqual(self.document["scenes"][0]["nodes"], list(range(len(nodes))))
        scales = set()
        for node in nodes:
            matrix = node["matrix"]
            # A pure uniform scale: every part's origin is its attach point.
            self.assertEqual(matrix[12:15], [0, 0, 0])
            self.assertEqual({matrix[0], matrix[5], matrix[10]}, {matrix[0]})
            self.assertEqual([matrix[i] for i in (1, 2, 4, 6, 8, 9)], [0] * 6)
            scales.add(matrix[0])
        self.assertEqual(len(scales), 1)
        self.assertLess(scales.pop(), 0.0005)

    def test_parts_bake_their_edge_lines_and_the_rope_has_none(self):
        meshes = self.document["meshes"]
        for node in self.document["nodes"]:
            primitives = meshes[node["mesh"]]["primitives"]
            triangles = [p for p in primitives if p["mode"] == 4]
            lines = [p for p in primitives if p["mode"] == 1]
            with self.subTest(part=node["name"]):
                self.assertTrue(triangles)
                if node["name"] == "rope":
                    self.assertEqual(lines, [])
                    continue
                self.assertTrue(lines)
                for line in lines:
                    shared = [
                        t
                        for t in triangles
                        if t["attributes"]["POSITION"] == line["attributes"]["POSITION"]
                        and t["material"] == line["material"]
                    ]
                    self.assertEqual(len(shared), 1)

    def test_materials_keep_the_models_colours_and_the_glass_blend(self):
        names = [m["name"] for m in self.document["materials"]]
        self.assertEqual(
            names, ["material", "frame", "CONCRETE", "IRON", "BUCKET", "ROPE", "GLASS"]
        )
        glass = self.document["materials"][-1]
        self.assertEqual(glass["alphaMode"], "BLEND")
        self.assertEqual(glass["pbrMetallicRoughness"]["baseColorFactor"][3], 0.5)
        for material in self.document["materials"][:-1]:
            self.assertNotIn("alphaMode", material)
            self.assertEqual(
                material["pbrMetallicRoughness"]["baseColorFactor"][3], 1.0
            )
        # The crane's yellow, as sampled from the original texture.
        yellow = self.document["materials"][0]["pbrMetallicRoughness"][
            "baseColorFactor"
        ]
        self.assertGreater(yellow[0], yellow[2] + 0.3)

    def test_credit_travels_with_the_kit(self):
        extras = self.document["asset"]["extras"]
        self.assertIn("Chamod", extras["author"])
        self.assertIn("CC-BY-4.0", extras["license"])
        self.assertEqual(extras["source"], TOWER_CRANE_CREDIT["source_url"])
        self.assertIn("base slab", extras["modified"])
        self.assertIn("ropes removed", extras["modified"])
        self.assertEqual(TOWER_CRANE_CREDIT["license"], "CC BY 4.0")
        self.assertIn("cut into reusable parts", TOWER_CRANE_CREDIT["modified"])

    def test_the_origin_is_on_the_mast_axis_on_top_of_the_footing(self):
        # The four mast legs enter the footing around (0, 0): the crane stands on
        # the centre of its footing and turns about its own mast.
        lo, hi = mast_anchor_bounds(self.data)
        self.assertAlmostEqual((lo[0] + hi[0]) / 2, 0.0, delta=0.01)
        self.assertAlmostEqual((lo[2] + hi[2]) / 2, 0.0, delta=0.01)
        self.assertAlmostEqual(hi[0] - lo[0], 2.35, delta=0.05)
        self.assertAlmostEqual(hi[2] - lo[2], 2.44, delta=0.05)
        # Anchors reach 0.37 m into the footing.
        self.assertAlmostEqual(lo[1], -0.372, places=2)
        self.assertLess(hi[1], -0.05)

    def test_native_frame_points_the_jib_to_scene_minus_x_and_keeps_it_upright(self):
        bounds = tower_crane_layout(spec.DEFAULT_TOWER_CRANE_SPEC).bounds
        corners = native_instance_corners(bounds, INCHES_PER_METRE, 0.0, 0.0, 48.0, 0.0)
        xs = [c[0] for c in corners]
        zs = [c[2] for c in corners]
        self.assertAlmostEqual(min(xs), -37.17 * INCHES_PER_METRE, delta=1.0)
        self.assertAlmostEqual(max(zs), 48.0 + 50.796 * INCHES_PER_METRE, delta=1.0)
        turned = native_instance_corners(
            bounds, INCHES_PER_METRE, 0.0, 0.0, 0.0, math.pi / 2
        )
        # A quarter turn about +Z swings the jib from -x to -y.
        self.assertAlmostEqual(min(c[1] for c in turned), min(xs), delta=1e-6)

    def test_only_the_rope_is_marked_to_draw_no_edges(self):
        parts = self.kit["parts"]
        self.assertIs(parts["rope"]["edges"], False)
        self.assertTrue(
            all("edges" not in parts[name] for name in parts if name != "rope")
        )
        self.assertEqual(tower_crane_parts_without_edges(self.kit), ("rope",))
        self.assertEqual(tower_crane_parts_without_edges({"parts": {}}), ())

    def test_metadata_agrees_with_the_domain_constants(self):
        kit = self.kit
        self.assertEqual(kit["version"], TOWER_CRANE_KIT_VERSION)
        self.assertEqual(
            kit["mast"],
            {
                "base_y": spec.MAST_BASE_M,
                "pitch": spec.MAST_PITCH_M,
                "default": spec.DEFAULT_MAST_SECTIONS,
            },
        )
        self.assertEqual(kit["jib"]["first_bay_x"], spec.JIB_FIRST_BAY_M)
        self.assertEqual(kit["jib"]["pitch"], spec.JIB_PITCH_M)
        self.assertEqual(kit["jib"]["default"], spec.DEFAULT_JIB_SECTIONS)
        self.assertAlmostEqual(
            kit["jib"]["tip_length"], spec.JIB_TIP_LENGTH_M, delta=0.002
        )
        self.assertEqual(
            kit["counterjib"],
            {
                "first_x": spec.COUNTERJIB_FIRST_M,
                "pitch": spec.COUNTERJIB_PITCH_M,
                "default": spec.DEFAULT_COUNTERJIB_SECTIONS,
            },
        )
        self.assertAlmostEqual(
            kit["anchors"]["hoist_top"][1], spec.HOIST_TOP_ABOVE_MAST_M, delta=0.002
        )
        self.assertAlmostEqual(
            kit["hook"]["below_rope"], spec.HOOK_BELOW_ROPE_M, delta=0.002
        )
        # The default hook rope (12.4 ft) is the model's own, to the nearest inch.
        self.assertAlmostEqual(
            kit["hook"]["default_rope"] / 0.3048, spec.DEFAULT_HOOK_ROPE_FT, delta=0.1
        )
        # The default trolley (79 % of the travel) is where the model has it.
        default = spec.resolve_tower_crane("[crane]").spec
        self.assertAlmostEqual(
            default.trolley_ft * 0.3048, kit["trolley"]["default_x"], delta=0.1
        )

    def test_part_bounds_in_the_metadata_match_the_geometry(self):
        positions = {}
        scale = self.document["nodes"][0]["matrix"][0]
        for node in self.document["nodes"]:
            low = [math.inf] * 3
            high = [-math.inf] * 3
            for primitive in self.document["meshes"][node["mesh"]]["primitives"]:
                accessor = self.document["accessors"][
                    primitive["attributes"]["POSITION"]
                ]
                for k in range(3):
                    low[k] = min(low[k], accessor["min"][k] * scale)
                    high[k] = max(high[k], accessor["max"][k] * scale)
            positions[node["name"]] = (low, high)
        for name, (low, high) in positions.items():
            with self.subTest(part=name):
                box = self.kit["parts"][name]
                for got, want in zip(box["min"] + box["max"], low + high):
                    self.assertAlmostEqual(got, want, delta=0.001)

    def test_repeated_parts_are_exactly_one_pitch_long_between_their_cut_planes(self):
        parts = self.kit["parts"]
        for name in ("mast_a", "mast_b"):
            # Legs are cut at 0 and one pitch; only whole diagonals reach past.
            self.assertLessEqual(parts[name]["min"][1], 0.0)
            self.assertGreaterEqual(parts[name]["max"][1], spec.MAST_PITCH_M - 0.001)
            self.assertLess(parts[name]["max"][1], spec.MAST_PITCH_M + 0.15)
        for name in ("jib_a", "jib_b"):
            self.assertGreaterEqual(parts[name]["max"][0], spec.JIB_PITCH_M - 0.001)
            self.assertLess(parts[name]["max"][0], spec.JIB_PITCH_M + 0.15)
        self.assertAlmostEqual(
            parts["cjib_section"]["min"][0], -spec.COUNTERJIB_PITCH_M, delta=0.001
        )
        self.assertAlmostEqual(parts["cjib_section"]["max"][0], 0.0, delta=0.001)
        self.assertAlmostEqual(parts["rope"]["min"][1], 0.0)
        self.assertAlmostEqual(parts["rope"]["max"][1], 1.0, delta=0.001)

    def test_the_native_parser_reads_the_kit_as_named_components(self):
        from ost_visualizer.presentation.components import ost_renderer

        summary = ost_renderer.parse_instanced_model_summary(
            self.data, INCHES_PER_METRE
        )
        self.assertIs(summary["baked_lines"], True)
        components = {c["name"]: c for c in summary["components"]}
        self.assertEqual(list(components), list(TOWER_CRANE_KIT_PARTS))
        self.assertEqual([p["lines"] for p in components["rope"]["parts"]], [0])
        self.assertEqual(
            [p["name"] for p in components["slewing"]["parts"]], ["material", "GLASS"]
        )
        # Scene frame (-x, z, y) x inches: a mast bay rises one pitch along +z.
        self.assertAlmostEqual(components["mast_a"]["min"][2], 0.0, delta=0.05)
        self.assertGreater(
            components["mast_a"]["max"][2], spec.MAST_PITCH_M * INCHES_PER_METRE - 0.05
        )

    def test_unreadable_or_mismatched_kits_are_refused(self):
        plain_model = _json_glb({"asset": {"version": "2.0"}, "nodes": [{"mesh": 0}]})
        for data in (b"", b"not a glb", b"glTF" + bytes(20), plain_model):
            with self.subTest(data=data[:8]):
                with self.assertRaisesRegex(ValueError, "tower crane kit"):
                    tower_crane_kit_metadata(data)
        document = _glb_json(self.data)
        document["asset"]["extras"]["kit"]["version"] = TOWER_CRANE_KIT_VERSION + 1
        with self.assertRaisesRegex(ValueError, "version"):
            tower_crane_kit_metadata(_json_glb(document))
        document = _glb_json(self.data)
        document["nodes"] = [n for n in document["nodes"] if n["name"] != "rope"]
        with self.assertRaisesRegex(ValueError, "lacks parts: rope"):
            tower_crane_kit_metadata(_json_glb(document))

    def test_both_build_scripts_package_the_kit(self):
        for script in ("build.ps1", "build-visualizer.ps1"):
            with self.subTest(script=script):
                text = (REPO / "scripts" / script).read_text(encoding="utf-8")
                self.assertIn(
                    "--include-data-file=$TowerCraneKitPath="
                    "ost_visualizer/resources/models/tower_crane_kit.glb",
                    text,
                )
                self.assertIn(
                    "'ost_visualizer\\resources\\models\\tower_crane_kit.glb'", text
                )
                # The one-piece model is gone and no longer packaged.
                self.assertNotIn("tower_crane.glb", text)
        self.assertEqual(
            sorted(path.name for path in TOWER_CRANE_KIT_PATH.parent.iterdir()),
            ["tower_crane_kit.glb"],
        )

    def test_source_model_is_kept_outside_the_package(self):
        source = REPO / "assets" / "models" / "tower_crane.source.glb"
        self.assertTrue(source.is_file())
        self.assertEqual(source.read_bytes()[:4], b"glTF")
        readme = (REPO / "assets" / "models" / "README.md").read_text(encoding="utf-8")
        self.assertIn("CC BY 4.0", readme)
        self.assertIn("tools\\prepare_tower_crane_asset.py", readme)
        self.assertIn("tower_crane_kit.glb", readme)


if __name__ == "__main__":
    unittest.main()
