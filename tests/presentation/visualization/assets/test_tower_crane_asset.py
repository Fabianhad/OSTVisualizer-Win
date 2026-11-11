import json
import math
import struct
import unittest
from pathlib import Path
from ost_visualizer.domain.dtos.tower_crane_placement_dto import INCHES_PER_METRE
from ost_visualizer.domain.entities.tower_crane_spec import (
    TowerCraneModel,
    default_tower_crane_spec,
    resolve_tower_crane,
)
from tests.presentation.visualization.assets.glb_positions import (
    bounds_of,
    glb_positions,
    mast_anchor_bounds,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
    TOWER_CRANE_KIT_VERSION,
    TOWER_CRANE_REQUIRED_PARTS,
    native_instance_corners,
    tower_crane_kit_metadata,
    tower_crane_kit_parts,
    tower_crane_parts_without_edges,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_layout import (
    tower_crane_layout,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
    TOWER_CRANE_KIT_FILES,
    TOWER_CRANE_MODELS_DIR,
    tower_crane_catalog,
    tower_crane_kit,
)

REPO = Path(__file__).resolve().parents[4]
FEET_PER_METRE = 1 / 0.3048


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


class _ShippedKitChecks:
    """What every kit must be: the crane cut into reusable parts, with the
    layout metadata and every constant the app reads for that model."""

    MODEL = ""

    @classmethod
    def setUpClass(cls):
        cls.data = tower_crane_kit(cls.MODEL).read_bytes()
        cls.document = _glb_json(cls.data)
        cls.kit = tower_crane_kit_metadata(cls.data)
        cls.model = tower_crane_catalog().get(cls.MODEL)

    def test_the_kit_is_a_small_quantized_glb_with_one_node_per_part(self):
        self.assertEqual(
            tower_crane_kit(self.MODEL).path,
            REPO
            / "ost_visualizer"
            / "resources"
            / "models"
            / f"tower_crane_{self.MODEL}.glb",
        )
        self.assertEqual(self.data[:4], b"glTF")
        self.assertLess(len(self.data), 1_000_000)
        self.assertEqual(self.document["extensionsRequired"], ["KHR_mesh_quantization"])
        self.assertNotIn("images", self.document)
        nodes = self.document["nodes"]
        self.assertEqual([node["name"] for node in nodes], list(self.kit["parts"]))
        self.assertEqual(
            sorted(tower_crane_kit_parts(self.kit)), sorted(self.kit["parts"])
        )
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

    def test_only_the_rope_is_marked_to_draw_no_edges(self):
        parts = self.kit["parts"]
        self.assertIs(parts["rope"]["edges"], False)
        self.assertTrue(
            all("edges" not in parts[name] for name in parts if name != "rope")
        )
        self.assertEqual(tower_crane_parts_without_edges(self.kit), ("rope",))
        self.assertEqual(tower_crane_kit(self.MODEL).parts_without_edges, ("rope",))

    def test_the_kit_carries_its_model_and_credit(self):
        self.assertEqual(self.kit["version"], TOWER_CRANE_KIT_VERSION)
        self.assertEqual(self.kit["model"]["id"], self.MODEL)
        credit = self.kit["credit"]
        self.assertEqual(
            sorted(credit),
            [
                "author",
                "author_url",
                "license",
                "license_url",
                "modified",
                "site",
                "source_url",
                "title",
            ],
        )
        self.assertEqual(credit["license"], "CC BY 4.0")
        self.assertEqual(credit["site"], "Sketchfab")
        self.assertIn("cut into reusable parts", credit["modified"])
        self.assertIn("ropes are generated", credit["modified"])
        # The source file's own credit is kept beside it.
        extras = self.document["asset"]["extras"]
        self.assertIn(credit["author"], extras["author"])
        self.assertIn("CC-BY-4.0", extras["license"])
        self.assertEqual(extras["source"], credit["source_url"])
        self.assertEqual(extras["title"], credit["title"])
        self.assertIn("ropes removed", extras["modified"])

    def test_the_spec_reads_its_constants_from_this_kit(self):
        kit = self.kit
        model = TowerCraneModel.from_kit_metadata(kit)
        self.assertEqual(model, self.model)
        self.assertEqual(model.mast_pitch_m, kit["mast"]["pitch"])
        self.assertEqual(model.mast_base_m, kit["mast"]["base_y"])
        self.assertEqual(model.jib_pitch_m, kit["jib"]["pitch"])
        self.assertEqual(model.jib_first_bay_m, kit["jib"]["first_bay_x"])
        self.assertEqual(model.jib_tip_length_m, kit["jib"]["tip_length"])
        self.assertEqual(model.counterjib_pitch_m, kit["counterjib"]["pitch"])
        self.assertEqual(model.hoist_top_above_mast_m, kit["anchors"]["hoist_top"][1])
        self.assertEqual(model.hook_below_rope_m, kit["hook"]["below_rope"])
        self.assertEqual(
            (model.default_mast, model.default_jib, model.default_counterjib),
            (
                kit["mast"]["default"],
                kit["jib"]["default"],
                kit["counterjib"]["default"],
            ),
        )
        self.assertEqual(model.mast_range, (kit["mast"]["min"], kit["mast"]["max"]))
        self.assertEqual(model.jib_range, (kit["jib"]["min"], kit["jib"]["max"]))
        # The default hook rope is the model's own, to the nearest tenth of a foot.
        self.assertAlmostEqual(
            kit["hook"]["modelled_rope"] * FEET_PER_METRE,
            kit["hook"]["default_rope_ft"],
            delta=0.06,
        )
        # The default trolley is where the model has it.
        default = resolve_tower_crane(
            f"[crane model={self.MODEL}]", tower_crane_catalog()
        ).spec
        self.assertAlmostEqual(
            default.trolley_ft / FEET_PER_METRE,
            kit["trolley"]["modelled_x"],
            delta=0.25,
        )

    def test_the_default_layout_rebuilds_the_model_as_built(self):
        spec = resolve_tower_crane(
            f"[crane model={self.MODEL}]", tower_crane_catalog()
        ).spec
        layout = tower_crane_layout(spec)
        jib = self.kit["jib"]
        reach = jib["first_bay_x"] + (spec.jib - 1) * jib["pitch"] + jib["tip_length"]
        self.assertAlmostEqual(layout.bounds[1][0], reach, delta=0.001)
        self.assertAlmostEqual(
            self.model.jib_tip_ft(spec.jib) / FEET_PER_METRE, reach, places=6
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

    def test_repeated_parts_are_one_pitch_long_between_their_cut_planes(self):
        parts = self.kit["parts"]
        mast_pitch = self.kit["mast"]["pitch"]
        jib_pitch = self.kit["jib"]["pitch"]
        for name in self.kit["mast"]["cycle"]:
            with self.subTest(part=name):
                # Legs are cut at 0 and one pitch; only whole diagonals reach past.
                self.assertLessEqual(parts[name]["min"][1], 0.0)
                self.assertGreaterEqual(parts[name]["max"][1], mast_pitch - 0.001)
                self.assertLess(parts[name]["max"][1], mast_pitch + 0.15)
        for name in self.kit["jib"]["cycle"]:
            with self.subTest(part=name):
                self.assertGreaterEqual(parts[name]["max"][0], jib_pitch - 0.001)
                self.assertLess(parts[name]["max"][0], jib_pitch + 0.15)
        self.assertAlmostEqual(
            parts["cjib_section"]["min"][0],
            -self.kit["counterjib"]["pitch"],
            delta=0.001,
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
        self.assertEqual(list(components), list(self.kit["parts"]))
        self.assertEqual([p["lines"] for p in components["rope"]["parts"]], [0])
        # Scene frame (-x, z, y) x inches: a mast bay rises one pitch along +z.
        mast = components[self.kit["mast"]["cycle"][0]]
        self.assertAlmostEqual(mast["min"][2], 0.0, delta=0.05)
        self.assertGreater(
            mast["max"][2], self.kit["mast"]["pitch"] * INCHES_PER_METRE - 0.05
        )


class ClassicKitTests(_ShippedKitChecks, unittest.TestCase):
    MODEL = "classic"

    def test_materials_keep_the_models_colours_and_the_glass_blend(self):
        names = [m["name"] for m in self.document["materials"]]
        self.assertEqual(
            names, ["material", "frame", "CONCRETE", "IRON", "BUCKET", "ROPE", "GLASS"]
        )
        # The yellow steel, structure and counterjib frame alike, is #edcf0c.
        for material in self.document["materials"][:2]:
            self.assertEqual(
                material["pbrMetallicRoughness"]["baseColorFactor"],
                [0.9294, 0.8118, 0.0471, 1.0],
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
        bounds = tower_crane_layout(
            default_tower_crane_spec(tower_crane_catalog())
        ).bounds
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

    def test_classic_layout_keeps_its_two_bay_cycles_and_two_lugs(self):
        self.assertEqual(self.kit["mast"]["cycle"], ["mast_a", "mast_b"])
        self.assertEqual(self.kit["jib"]["cycle"], ["jib_a", "jib_b"])
        self.assertEqual(
            [lug["at"] for lug in self.kit["jib"]["lugs"]], ["tip", "fraction"]
        )
        self.assertEqual(self.kit["jib"]["lugs"][1]["min_bays"], 8)
        self.assertNotIn("hoist_lead", self.kit["anchors"])


class LiebherrKitTests(_ShippedKitChecks, unittest.TestCase):
    MODEL = "liebherr"

    def test_the_base_sits_flush_on_the_footing_around_the_mast_axis(self):
        base = glb_positions(self.data, "base")
        lo, hi = bounds_of(base)
        # The base block's bottom is the origin: nothing reaches into the footing.
        self.assertAlmostEqual(lo[1], 0.0, delta=0.001)
        self.assertAlmostEqual((lo[0] + hi[0]) / 2, 0.0, delta=0.01)
        self.assertAlmostEqual((lo[2] + hi[2]) / 2, 0.0, delta=0.01)
        self.assertAlmostEqual(hi[0] - lo[0], 2.69, delta=0.02)
        mast_lo, mast_hi = bounds_of(glb_positions(self.data, "mast_a"))
        self.assertAlmostEqual((mast_lo[0] + mast_hi[0]) / 2, 0.0, delta=0.01)
        self.assertAlmostEqual(mast_hi[2] - mast_lo[2], 1.12, delta=0.01)

    def test_the_jib_runs_along_plus_x_and_the_counterjib_along_minus_x(self):
        spec = resolve_tower_crane("[crane model=liebherr]", tower_crane_catalog()).spec
        lo, hi = tower_crane_layout(spec).bounds
        self.assertAlmostEqual(hi[0], 42.24, delta=0.02)
        self.assertAlmostEqual(lo[0], -15.0, delta=0.02)
        self.assertAlmostEqual(hi[1], 42.77, delta=0.02)
        self.assertLess(hi[2] - lo[2], 5.0)

    def test_one_bay_each_repeats_at_the_measured_pitches(self):
        self.assertEqual(self.kit["mast"]["cycle"], ["mast_a"])
        self.assertEqual(self.kit["jib"]["cycle"], ["jib_a"])
        self.assertAlmostEqual(self.kit["mast"]["pitch"], 1.6554, delta=0.0001)
        self.assertAlmostEqual(self.kit["jib"]["pitch"], 1.2854, delta=0.0001)
        self.assertAlmostEqual(self.kit["counterjib"]["pitch"], 0.8411, delta=0.0001)
        self.assertEqual(
            (
                self.kit["mast"]["default"],
                self.kit["jib"]["default"],
                self.kit["counterjib"]["default"],
            ),
            (19, 32, 9),
        )
        # The base frames reach 6.15 m, so the mast needs four bays to clear them.
        self.assertEqual(self.kit["mast"]["min"], 4)
        self.assertGreater(
            self.kit["mast"]["base_y"] + 4 * self.kit["mast"]["pitch"],
            self.kit["parts"]["base"]["max"][1],
        )
        self.assertNotIn("mast_b", self.kit["parts"])
        self.assertNotIn("jib_b", self.kit["parts"])

    def test_the_classic_yellow_glass_and_concrete_with_a_white_cab(self):
        materials = {m["name"]: m for m in self.document["materials"]}
        self.assertEqual(
            list(materials),
            ["Material_23", "ROPE", "YELLOW", "CAB", "GLASS", "CONCRETE"],
        )
        classic = {
            m["name"]: m
            for m in _glb_json(tower_crane_kit("classic").read_bytes())["materials"]
        }
        # Both cranes are #edcf0c; the windows and the counterweight are the
        # classic crane's own glass and concrete, transparency included.
        self.assertEqual(
            materials["YELLOW"]["pbrMetallicRoughness"]["baseColorFactor"],
            [0.9294, 0.8118, 0.0471, 1.0],
        )
        self.assertEqual(
            materials["YELLOW"]["pbrMetallicRoughness"],
            classic["material"]["pbrMetallicRoughness"],
        )
        for name in ("GLASS", "CONCRETE"):
            with self.subTest(material=name):
                self.assertEqual(materials[name], classic[name])
        self.assertEqual(materials["GLASS"]["alphaMode"], "BLEND")
        cab_r, cab_g, cab_b, cab_a = materials["CAB"]["pbrMetallicRoughness"][
            "baseColorFactor"
        ]
        self.assertGreater(min(cab_r, cab_g, cab_b), 0.9)
        self.assertEqual(cab_a, 1.0)
        # Every part is yellow but the grey base, the ropes, the cab and the
        # counterweight.
        slots = {name: index for index, name in enumerate(materials)}
        for node in self.document["nodes"]:
            used = {
                p["material"]
                for p in self.document["meshes"][node["mesh"]]["primitives"]
                if p["mode"] == 4
            }
            with self.subTest(part=node["name"]):
                expected = {
                    "base": {slots["Material_23"]},
                    "rope": {slots["ROPE"]},
                    "slewing": {slots["YELLOW"], slots["CAB"], slots["GLASS"]},
                    "counterweight": {slots["CONCRETE"]},
                }.get(node["name"], {slots["YELLOW"]})
                self.assertEqual(used, expected)

    def test_the_counterweight_hangs_below_the_counterjib_end(self):
        weight = self.kit["parts"]["counterweight"]
        deck = self.kit["parts"]["cjib_section"]
        # The concrete block reaches about 2.2 m below the deck, as modelled.
        self.assertLess(weight["min"][1], deck["min"][1] - 1.5)
        self.assertGreater(weight["max"][0] - weight["min"][0], 1.5)
        self.assertLess(max(abs(weight["min"][2]), abs(weight["max"][2])), 0.7)

    def test_one_centreline_pendant_and_a_lead_rope_from_the_winch(self):
        anchors = self.kit["anchors"]
        self.assertEqual(len(anchors["jib_pendant"]["lateral"]), 1)
        self.assertLess(abs(anchors["jib_pendant"]["lateral"][0]), 0.07)
        self.assertEqual(len(anchors["counterjib_pendant"]["lateral"]), 2)
        self.assertEqual(len(anchors["hoist_falls"]), 1)
        self.assertIn("hoist_lead", anchors)
        (lug,) = self.kit["jib"]["lugs"]
        self.assertEqual(lug["at"], "fraction")
        self.assertAlmostEqual(lug["fraction"], 0.5625)


class TowerCraneKitMetadataTests(unittest.TestCase):
    def setUp(self):
        self.data = tower_crane_kit("classic").read_bytes()

    def test_unreadable_or_mismatched_kits_are_refused(self):
        plain_model = _json_glb({"asset": {"version": "2.0"}, "nodes": [{"mesh": 0}]})
        for data in (b"", b"not a glb", b"glTF" + bytes(20), plain_model):
            with self.subTest(data=data[:8]):
                with self.assertRaisesRegex(ValueError, "tower crane kit"):
                    tower_crane_kit_metadata(data)
        document = _glb_json(self.data)
        document["asset"]["extras"]["kit"]["version"] = 1
        with self.assertRaisesRegex(ValueError, "version 1 is not 2"):
            tower_crane_kit_metadata(_json_glb(document))
        document = _glb_json(self.data)
        document["nodes"] = [n for n in document["nodes"] if n["name"] != "rope"]
        with self.assertRaisesRegex(ValueError, "lacks parts: rope"):
            tower_crane_kit_metadata(_json_glb(document))
        document = _glb_json(self.data)
        del document["asset"]["extras"]["kit"]["mast"]["cycle"]
        with self.assertRaisesRegex(ValueError, "unreadable"):
            tower_crane_kit_metadata(_json_glb(document))

    def test_the_parts_a_kit_needs_follow_its_cycles_and_lugs(self):
        kit = tower_crane_kit_metadata(self.data)
        self.assertEqual(
            set(tower_crane_kit_parts(kit)),
            set(TOWER_CRANE_REQUIRED_PARTS)
            | {"mast_a", "mast_b", "jib_a", "jib_b", "jib_lug"},
        )
        without_lugs = dict(kit, jib=dict(kit["jib"], lugs=[], cycle=["jib_a"]))
        self.assertNotIn("jib_lug", tower_crane_kit_parts(without_lugs))
        self.assertNotIn("jib_b", tower_crane_kit_parts(without_lugs))


class TowerCranePackagingTests(unittest.TestCase):
    def test_both_build_scripts_package_every_kit(self):
        for script in ("build.ps1", "build-visualizer.ps1"):
            with self.subTest(script=script):
                text = (REPO / "scripts" / script).read_text(encoding="utf-8")
                self.assertIn(
                    "--include-data-dir=$TowerCraneModelsDir="
                    "ost_visualizer/resources/models",
                    text,
                )
                self.assertIn("'ost_visualizer\\resources\\models'", text)
                self.assertNotIn("tower_crane_kit.glb", text)
        # The packaged folder holds exactly the registered kits, nothing else.
        self.assertEqual(
            sorted(path.name for path in TOWER_CRANE_MODELS_DIR.iterdir()),
            sorted(TOWER_CRANE_KIT_FILES),
        )

    def test_source_models_are_kept_outside_the_package_and_credited(self):
        readme = (REPO / "assets" / "models" / "README.md").read_text(encoding="utf-8")
        self.assertIn("tools\\prepare_tower_crane_asset.py", readme)
        for name, model in (
            ("tower_crane.source.glb", "classic"),
            ("liebherr_tower_crane.source.glb", "liebherr"),
        ):
            with self.subTest(source=name):
                # A source that is on this machine is the binary glTF original.
                source = REPO / "assets" / "models" / name
                if source.is_file():
                    self.assertEqual(source.read_bytes()[:4], b"glTF")
                credit = tower_crane_kit(model).credit
                self.assertIn(f"## {name}", readme)
                self.assertIn(credit["title"], readme)
                self.assertIn(credit["author"], readme)
                self.assertIn(credit["source_url"], readme)
                self.assertIn(f"tower_crane_{model}.glb", readme)
        self.assertIn("CC BY 4.0", readme)

    def test_source_models_stay_out_of_git_and_the_readme_says_how_to_get_one(self):
        ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("assets/models/*.source.glb", [line.strip() for line in ignored])
        readme = (REPO / "assets" / "models" / "README.md").read_text(encoding="utf-8")
        credit = tower_crane_kit("liebherr").credit
        # The download steps name the page, the file to save and the credit.
        steps = readme[readme.index("## Download the Liebherr source") :]
        steps = steps[: steps.index("\n## ", 1)]
        for text in (
            credit["source_url"],
            "assets/models/liebherr_tower_crane.source.glb",
            "tools\\prepare_tower_crane_asset.py",
            f'"{credit["title"]}" by {credit["author"]}',
            "CC BY 4.0",
            credit["license_url"],
        ):
            with self.subTest(text=text):
                self.assertIn(text, steps)


if __name__ == "__main__":
    unittest.main()
