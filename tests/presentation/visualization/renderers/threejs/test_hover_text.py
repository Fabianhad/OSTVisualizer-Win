import json
import shutil
import unittest
from ost_visualizer.domain.services.elevation import format_structural_elevation
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.renderers.threejs.adapters.threejs_mesh_adapter import (
    ThreejsMeshAdapter,
)
from ost_visualizer.presentation.visualization.renderers.threejs.hover_text import (
    hover_elevations,
    hover_name,
)
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    _generate_html,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.presentation.visualization.renderers.threejs.test_threejs_renderer import (
    _MINIMAL_SCENE,
    _compact_code,
    _extract_js_function,
    _run_node,
)

HINT = "Drag to orbit, scroll or pinch to zoom, right-drag or two fingers to pan."
_HOVER_FUNCTIONS = (
    "isShownInScene",
    "sectionCutRemovesPoint",
    "firstHoverHit",
    "elementHoverStats",
    "escapeHtml",
    "hoverTipHtml",
    "hoverInfo",
)


def _box(x0, x1, y0, y1, bottom, top_at_x0, top_at_x1=None, drop_face=None):
    """A closed box in native Z-up inches; the top may slope along x."""
    top_at_x1 = top_at_x0 if top_at_x1 is None else top_at_x1

    def c(x, y, up):
        return (x, y, (top_at_x0 if x == x0 else top_at_x1) if up else bottom)

    quads = [
        [c(x0, y0, 0), c(x0, y1, 0), c(x1, y1, 0), c(x1, y0, 0)],
        [c(x0, y0, 1), c(x1, y0, 1), c(x1, y1, 1), c(x0, y1, 1)],
        [c(x0, y0, 0), c(x1, y0, 0), c(x1, y0, 1), c(x0, y0, 1)],
        [c(x0, y1, 0), c(x0, y1, 1), c(x1, y1, 1), c(x1, y1, 0)],
        [c(x0, y0, 0), c(x0, y0, 1), c(x0, y1, 1), c(x0, y1, 0)],
        [c(x1, y0, 0), c(x1, y1, 0), c(x1, y1, 1), c(x1, y0, 1)],
    ]
    vertices, faces = [], []
    for number, quad in enumerate(quads):
        if number == drop_face:
            continue
        base = len(vertices)
        vertices.extend(quad)
        faces.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])
    return vertices, faces


class HoverElevationTests(unittest.TestCase):
    def test_elevations_use_the_app_formatter_to_the_nearest_eighth(self):
        cases = {
            3492.5: "291' - 0 1/2\"",
            3625.5: "302' - 1 1/2\"",
            3448.0: "287' - 4\"",
            3448.125: "287' - 4 1/8\"",
            3448.375: "287' - 4 3/8\"",
            3448.875: "287' - 4 7/8\"",
            3448.04: "287' - 4\"",
            3448.07: "287' - 4 1/8\"",
            120.125: "10' - 0 1/8\"",
            11.99: "1' - 0\"",
        }
        for inches, text in cases.items():
            with self.subTest(inches=inches):
                vertices, faces = _box(0, 120, 0, 120, inches, inches + 24)
                bottom, _top = hover_elevations(vertices, faces)
                self.assertEqual(bottom, text)
                self.assertEqual(bottom, format_structural_elevation(inches))

    def test_negative_values_and_rounding_to_zero(self):
        # A negative value that rounds to zero reads 0' - 0" (as the callouts).
        cases = {
            -6.5: "-0' - 6 1/2\"",
            -144.125: "-12' - 0 1/8\"",
            0.04: "0' - 0\"",
            0.0: "0' - 0\"",
            -0.04: "0' - 0\"",
        }
        for inches, text in cases.items():
            with self.subTest(inches=inches):
                vertices, faces = _box(0, 120, 0, 120, inches, inches + 24)
                self.assertEqual(hover_elevations(vertices, faces)[0], text)

    def test_a_flat_top_is_one_value_and_a_sloped_top_a_range(self):
        flat = hover_elevations(*_box(0, 120, 0, 144, 3412, 3448))
        self.assertEqual(flat, ("284' - 4\"", "287' - 4\""))
        sloped = hover_elevations(*_box(0, 120, 0, 120, 3412, 3448, 3516))
        self.assertEqual(sloped, ("284' - 4\"", "287' - 4\" to 293' - 0\""))
        # Reversed winding reads the same (the volume's sign gives the outside).
        vertices, faces = _box(0, 120, 0, 120, 3412, 3448, 3516)
        flipped = [face[::-1] for face in faces]
        self.assertEqual(hover_elevations(vertices, flipped), sloped)

    def test_missing_geometry_has_no_elevations(self):
        self.assertIsNone(hover_elevations([], []))
        self.assertIsNone(hover_elevations([(0, 0, 0), (1, 0, 0)], [(0, 1)]))

    def test_the_export_geometry_carries_name_and_elevation_text(self):
        vertices, faces = _box(0, 120, 0, 120, 24.0, 36.0)
        entry = ThreejsMeshAdapter(ColorService()).convert_mesh(
            MeshData(vertices, faces), {"name": "Pad @T 3'", "color": "#808080"}
        )
        self.assertEqual(entry["hover"], "Pad")
        self.assertEqual(entry["hover_bottom"], "2' - 0\"")
        self.assertEqual(entry["hover_top"], "3' - 0\"")

    def test_the_condition_name_drops_its_elevation_suffix(self):
        self.assertEqual(hover_name("Footing F1 @T 287' 4\""), "Footing F1")
        self.assertEqual(hover_name(""), "")


_BOX_JS = r"""
function box(x0, x1, y0, z0, z1, yTop, dropFace) {
  const c = (x, up, z) => [x, up ? yTop : y0, z];
  const quads = [
    [c(x0,0,z0), c(x1,0,z0), c(x1,0,z1), c(x0,0,z1)],
    [c(x0,1,z0), c(x0,1,z1), c(x1,1,z1), c(x1,1,z0)],
    [c(x0,0,z0), c(x0,1,z0), c(x1,1,z0), c(x1,0,z0)],
    [c(x0,0,z1), c(x1,0,z1), c(x1,1,z1), c(x0,1,z1)],
    [c(x0,0,z0), c(x0,0,z1), c(x0,1,z1), c(x0,1,z0)],
    [c(x1,0,z0), c(x1,1,z0), c(x1,1,z1), c(x1,0,z1)],
  ];
  const positions = [], index = [];
  quads.forEach((q, f) => {
    if (f === dropFace) return;
    const base = positions.length / 3;
    q.forEach((p) => positions.push(...p));
    index.push(base, base + 1, base + 2, base, base + 2, base + 3);
  });
  return {positions, index};
}
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is required to execute viewer JS")
class HoverTipScriptTests(unittest.TestCase):
    def setUp(self):
        self.html = _generate_html(_MINIMAL_SCENE, "Viewer")

    def _node(self, body, cut="[0, 0, 0, 0]"):
        functions = "\n".join(
            _extract_js_function(self.html, name) for name in _HOVER_FUNCTIONS
        )
        script = f"""
        const TIP_3D = {json.dumps(HINT)};
        const sectionCutUniform = {{value: {{
          x: {cut}[0], y: {cut}[1], z: {cut}[2], w: {cut}[3] }} }};
        {functions}
        {_BOX_JS}
        const ascii = (value) => JSON.stringify(value).replace(/[^\\x00-\\x7f]/g,
          (c) => "\\\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
        {body}
        """
        return json.loads(_run_node(script))

    def test_an_element_shows_its_name_then_elevations_area_and_volume(self):
        out = self._node(
            """
            console.log(ascii(hoverTipHtml({name: "Footing <F1> & \\"pad\\"",
              bottom: "291' - 0 1/2\\"", top: "302' - 1 1/2\\"",
              areaSf: 114.66, volumeCf: 47.1 * 27})));
            """
        )
        self.assertEqual(
            out,
            "<b>Footing &lt;F1&gt; &amp; &quot;pad&quot;</b><span>BOTTOM EL "
            "291' - 0 1/2&quot;   TOP EL 302' - 1 1/2&quot;   114.7 SF   47.1 CY</span>",
        )

    def test_a_sloped_top_range_is_shown_as_given(self):
        out = self._node(
            """
            console.log(ascii(hoverTipHtml({name: "Ramp", bottom: "284' - 4\\"",
              top: "287' - 4\\" to 293' - 0\\""})));
            """
        )
        self.assertEqual(
            out,
            "<b>Ramp</b><span>BOTTOM EL 284' - 4&quot;   "
            "TOP EL 287' - 4&quot; to 293' - 0&quot;</span>",
        )

    def test_nothing_under_the_pointer_gives_the_hint(self):
        out = self._node(
            "console.log(ascii([hoverTipHtml(hoverInfo(firstHoverHit([]))), TIP_3D]));"
        )
        self.assertEqual(out, [None, HINT])
        self.assertIn(HINT, " ".join(self.html.split()))

    def test_a_hovered_element_combines_app_elevations_and_page_stats(self):
        out = self._node(
            """
            const b = box(0, 120, 0, 0, 144, 24);
            const mesh = {visible: true, parent: null, userData: {
              hoverName: "Pad", hoverBottom: "0' - 0\\"", hoverTop: "2' - 0\\"",
              hoverGeometry: {positions: b.positions, index: b.index}}};
            const cap = {visible: true, parent: null, userData: {hoverName: "Pad", hoverOf: mesh}};
            const crane = {visible: true, parent: null, userData: {hoverName: "Crane pad"}};
            const at = (object) => hoverTipHtml(hoverInfo({object, point: {x: 0, y: 0, z: 0}}));
            console.log(ascii([at(mesh), at(cap), at(crane)]));
            """
        )
        element = "<b>Pad</b><span>BOTTOM EL 0' - 0&quot;   TOP EL 2' - 0&quot;   120 SF   8.9 CY</span>"
        self.assertEqual(out, [element, element, "<b>Crane pad</b>"])

    def test_missing_values_leave_their_fields_out(self):
        out = self._node(
            """
            const open = box(0, 120, 0, 0, 144, 24, 1);
            const stats = elementHoverStats(open.positions, open.index);
            console.log(ascii([
              stats,
              hoverTipHtml(Object.assign({name: "Open", bottom: "", top: "2' - 0\\""}, stats)),
              hoverTipHtml({name: "Odd", areaSf: NaN, volumeCf: null}),
            ]));
            """
        )
        stats, open_html, odd_html = out
        self.assertEqual(stats, {"areaSf": None, "volumeCf": None})
        self.assertEqual(open_html, "<b>Open</b><span>TOP EL 2' - 0&quot;</span>")
        self.assertEqual(odd_html, "<b>Odd</b>")

    def test_hidden_objects_and_the_cut_away_side_are_skipped(self):
        body = """
        const shown = {visible: true, parent: null};
        const hidden = {visible: false, parent: null};
        const hit = (name, point, parent = shown) => ({
          object: {visible: true, parent, userData: {hoverName: name}},
          point: {x: point[0], y: point[1], z: point[2]},
        });
        const pick = (hits) => { const h = firstHoverHit(hits); return h && h.object.userData.hoverName; };
        console.log(ascii([
          pick([hit("hidden", [0, 0, 0], hidden), hit("behind", [0, 0, 0])]),
          pick([hit("", [0, 0, 0])]),
          pick([hit("removed", [0, 0, -9]), hit("kept", [0, 0, 1])]),
        ]));
        """
        self.assertEqual(
            self._node(body, cut="[1, -5, 0, 0]"), ["behind", None, "kept"]
        )

    def test_picking_is_throttled_to_the_animation_frame_and_styled(self):
        compact = _compact_code(self.html)
        animate = _compact_code(_extract_js_function(self.html, "animate"))
        self.assertIn(_compact_code("if (hoverState.pending) {"), animate)
        self.assertIn(
            _compact_code(
                "hoverState.pending = { x: event.clientX, y: event.clientY };"
            ),
            compact,
        )
        self.assertIn(_compact_code("white-space: pre-wrap;"), compact)
        self.assertNotIn("function ftin(", self.html)


if __name__ == "__main__":
    unittest.main()
