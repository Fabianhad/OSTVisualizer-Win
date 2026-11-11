"""Kit profile for "Liebherr tower crane" by Cem Alagozlu (Sketchfab, CC BY 4.0).

Model ``liebherr``. Source ``assets/models/liebherr_tower_crane.source.glb``;
kit ``ost_visualizer/resources/models/tower_crane_liebherr.glb``.
* the source has its jib along +Z; the kit is turned a quarter turn about Y so
  the jib runs along +X like every kit. The origin is the mast axis (the
  centre of the first mast section) at the bottom of the base block, so the
  base sits on top of the count takeoff that is the footing;
* the mast is 19 identical sections at an exact 1.6554 m pitch that overlap
  by 0.32 m; the stack is cut at its pitch, so one bay holds a section plus
  the top of the one below, and the stack repeats exactly;
* the jib bays are 1.2854 m (bottom cross members and bracing). The side
  diagonals zigzag every 1.0012 m, which does not repeat with the bay, so one
  modelled V of diagonals is stretched along the jib to one V per bay;
* the counterjib repeats every 0.841 m (cross members and rail posts) over
  its middle; its walkway panels (2.02 m) and one mid-run frame do not, so the
  walkway becomes a plate and the frame is dropped (the section it sat in is
  left out of the repeat check);
* the walkways become thin plates, the winch drums' coiled rope becomes
  plain drums, and the pendants and ropes are dropped (ropes are generated).
"""

from __future__ import annotations
import math
from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from tools.tower_crane_kit import (
    REPO,
    ROPE_RADIUS,
    CONCRETE_COLOUR,
    CRANE_YELLOW,
    GLASS_COLOUR,
    KitBuild,
    KitPart,
    Triangle,
    assert_periodic,
    assert_prismatic,
    bounds,
    box_triangles,
    check_measured,
    check_node_table,
    collect_material_samples,
    collect_node_texels,
    collect_nodes,
    components,
    drum_triangles,
    extent,
    kit_target,
    plate_node,
    read_glb,
    rope_triangles,
    rotate,
    shift,
    short_pieces,
    split_along,
    stretch_along,
    texture_colours,
)

MODEL_ID = "liebherr"
LABEL = "Liebherr"
SOURCE = REPO / "assets" / "models" / "liebherr_tower_crane.source.glb"
TARGET = kit_target(MODEL_ID)
CREDIT = {
    "title": "Liebherr tower crane",
    "author": "Cem Alagozlu",
    "author_url": "https://sketchfab.com/cem.alagozlu",
    "source_url": (
        "https://sketchfab.com/3d-models/"
        "liebherr-tower-crane-0f8befc223734608a5d54aad4904951f"
    ),
    "site": "Sketchfab",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "modified": (
        "cut into reusable parts, turned so the jib runs along +X, textures "
        "replaced by flat colours (yellow #edcf0c, a white cab with glass "
        "windows, a concrete counterweight), geometry quantized, jib side "
        "diagonals made one per bay, winch drums simplified, walkways replaced by "
        "plates, pendants and ropes removed (ropes are generated)"
    ),
}
MODIFIED = (
    "cut into reusable parts (base, mast bay, slewing unit, tower head, jib bay, "
    "counterjib section, trolley, hook block); turned so the jib runs along +X; "
    "textures removed (flat material colours: every yellow made #edcf0c, the cab "
    "white with glass windows, the counterweight concrete), primitives welded, "
    "positions and "
    "normals quantized, edge lines baked; jib side diagonals stretched to one V "
    "per bay; coiled winch rope replaced by plain drums; walkway gratings "
    "replaced by plates; one counterjib mid-run frame removed; pendants and "
    "ropes removed (ropes are generated); origin moved to the mast base"
)
# glTF (x, y, z) -> kit (z, y, -x): a quarter turn about +Y, jib from +Z to +X.
KIT_ROTATION = ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
BASE_NODES = ("Box020", "Object004", "Object007")
MAST_NODES = ("Object001",) + tuple(f"Object{n:03d}" for n in range(8, 26))
MAST_AXIS_NODE = "Object001"
BASE_BOTTOM_NODE = "Box020"
SLEWING_NODES = ("Box021", "Plane002")
HEAD_NODE = "Object053"
JIB_NODE = "Box069"
COUNTERJIB_NODE = "Object052"
ROPE_MATERIAL = "ROPE"
ROPE_COLOUR = (0.18, 0.18, 0.18)
# Colours the profile sets instead of the sampled texture medians (display
# values, like the samples). The source's yellows (the mast's darker one, the
# slewing ring's brighter one, the pale tan counterjib and the rest) all become
# the crane yellow every kit shares.
YELLOW_SOURCE_MATERIALS = (
    "Material_24",
    "Material_43",
    "Material_44",
    "Material_45",
    "Material_46",
    "Material_64",
)
YELLOW_MATERIAL = "YELLOW"
# The operator cab is the piece of the slewing deck node that stands on the
# deck under the jib root; its texture paints the window panes light grey
# (0.42) on a dark body (0.22). The cab is white and its windows are the
# classic kit's glass.
CAB_NODE = "Plane002"
CAB_BOTTOM_Y = 33.3
CAB_TOP_Y = 34.5
CAB_MATERIAL = "CAB"
CAB_COLOUR = (0.95, 0.95, 0.95)
GLASS_MATERIAL = "GLASS"
WINDOW_MIN_TEXEL = 0.3
# The counterweight is the concrete block hanging below the counterjib end,
# the only piece of that node that reaches below the deck. It takes the classic
# kit's concrete.
CONCRETE_MATERIAL = "CONCRETE"
COUNTERWEIGHT_BOTTOM_Y = 34.0
MAST_LIMITS = (4, 75)  # the base frames reach 6.15 m: four bays clear them
JIB_LIMITS = (8, 64)
COUNTERJIB_LIMITS = (2, 24)
MIN_HOOK_ROPE_FT = 3.0
TROLLEY_TRAVEL_START_M = 3.0
TROLLEY_TIP_CLEARANCE_M = 1.2
TROLLEY_ROPE_START_M = 0.2
TROLLEY_ROPE_END_M = 0.3
# The trolley ropes run inside the jib, just above its bottom chords.
TROLLEY_ROPE_Y = 34.85
PENDANT_THICKNESS = 1.0
MAST_CANONICAL_BAY = 9
JIB_CANONICAL_BAY = 10
COUNTERJIB_CANONICAL_SECTION = 1  # counted outward from the mast
MAST_PERIOD_TOLERANCE = 0.005
JIB_PERIOD_TOLERANCE = 0.005
COUNTERJIB_PERIOD_TOLERANCE = 0.01
# Members that occur at least this often are lattice, never fittings.
LATTICE_SIGNATURE_COUNT = 10
# The winch drum on the jib root and the frame mid-way along the counterjib.
JIB_DRUM_X = (4.1, 4.75)
COUNTERJIB_MID_FRAME_X = (-5.35, -4.65)
COUNTERJIB_WINCH_X = (-14.4, -13.0)
TROLLEY_X = (20.5, 21.45)
HOOK_TOP_Y = 25.0
EXPECTED = {
    "mast_base": -0.0019,
    "mast_pitch": 1.6554,
    "mast_bays": 19,
    "jib_first_bay": 0.8326,
    "jib_pitch": 1.2854,
    "jib_bays": 32,
    "diagonal_period": 1.0012,
    "counterjib_first": -1.5886,
    "counterjib_pitch": 0.8411,
    "counterjib_sections": 8,
}
PART_ORDER = (
    "base",
    "mast_a",
    "slewing",
    "head",
    "jib_root",
    "jib_a",
    "jib_tip",
    "jib_lug",
    "cjib_root",
    "cjib_section",
    "cjib_end",
    "counterweight",
    "cjib_lug",
    "trolley",
    "hook_block",
    "rope",
)
FEET_PER_METRE = 1.0 / 0.3048


def _spans(component: Sequence[Triangle]) -> Tuple[float, float, float]:
    return tuple(extent(component, k)[1] - extent(component, k)[0] for k in range(3))


def _signature(component: Sequence[Triangle]) -> Tuple:
    return (len(component),) + tuple(round(s, 2) for s in _spans(component))


def _near(value: float, target: float, tolerance: float) -> bool:
    return abs(value - target) <= tolerance


def _within(component: Sequence[Triangle], axis: int, window: Tuple[float, float]) -> bool:
    low, high = extent(component, axis)
    return window[0] <= low and high <= window[1]


def _flatten(groups: Sequence[Sequence[Triangle]]) -> List[Triangle]:
    return [triangle for group in groups for triangle in group]


def _points(groups: Sequence[Sequence[Triangle]]) -> List[Tuple[float, float, float]]:
    return [vertex[0] for group in groups for triangle in group for vertex in triangle[:3]]


def kit_origin(nodes: Dict[str, List[Triangle]]) -> Tuple[float, float, float]:
    """The mast axis (centre of the first mast section) at the base bottom."""
    if MAST_AXIS_NODE not in nodes or BASE_BOTTOM_NODE not in nodes:
        raise ValueError(
            f"mast node {MAST_AXIS_NODE!r} or base node {BASE_BOTTOM_NODE!r} not found"
        )
    mast = nodes[MAST_AXIS_NODE]
    return (
        sum(extent(mast, 0)) / 2.0,
        extent(nodes[BASE_BOTTOM_NODE], 1)[0],
        sum(extent(mast, 2)) / 2.0,
    )


def _drum(coils: Sequence[Sequence[Triangle]]) -> List[Triangle]:
    """The coiled rope of a winch (rings across the jib) as one plain drum."""
    radii = sorted(max(_spans(c)[0], _spans(c)[1]) / 2.0 for c in coils)
    points = _points(coils)
    middle = (
        (min(p[0] for p in points) + max(p[0] for p in points)) / 2.0,
        (min(p[1] for p in points) + max(p[1] for p in points)) / 2.0,
    )
    return drum_triangles(
        2,
        middle,
        radii[len(radii) // 2],
        min(p[2] for p in points),
        max(p[2] for p in points),
        coils[0][0][3],
    )


def _rising(component: Sequence[Triangle]) -> bool:
    """Whether a side diagonal climbs toward the jib tip (+X)."""
    points = [vertex[0] for triangle in component for vertex in triangle[:3]]
    low, high = extent(component, 1)
    middle = (low + high) / 2.0
    below = [p[0] for p in points if p[1] < middle]
    above = [p[0] for p in points if p[1] >= middle]
    return sum(above) / len(above) > sum(below) / len(below)


def regular_diagonals(
    diagonals: Sequence[Sequence[Triangle]], first_bay: float, pitch: float, bays: int
) -> Tuple[List[Triangle], float]:
    """One modelled V of side diagonals per side, stretched to one V per bay.
    Returns the diagonals for ``bays`` bays from ``first_bay`` and the
    modelled zigzag period."""
    generated: List[Triangle] = []
    periods = []
    for side in (-1.0, 1.0):
        on_side = [d for d in diagonals if (sum(extent(d, 2)) / 2.0) * side > 0.0]
        rising = sorted((d for d in on_side if _rising(d)), key=lambda d: extent(d, 0)[0])
        falling = sorted(
            (d for d in on_side if not _rising(d)), key=lambda d: extent(d, 0)[0]
        )
        if len(rising) < 3 or not falling:
            raise ValueError("the jib side diagonals were not found")
        starts = [extent(d, 0)[0] for d in rising]
        period = (starts[-1] - starts[0]) / (len(starts) - 1)
        periods.append(period)
        up = rising[len(rising) // 2]
        start = extent(up, 0)[0]
        down = min(
            (d for d in falling if extent(d, 0)[0] > start), key=lambda d: extent(d, 0)[0]
        )
        v_shape = stretch_along(list(up) + list(down), 0, start, pitch / period)
        for bay in range(bays):
            generated.extend(shift(v_shape, (start - (first_bay + bay * pitch), 0.0, 0.0)))
    return generated, sum(periods) / len(periods)


def _regular_run(values: Sequence[float]) -> Tuple[float, int]:
    """The step of a run of evenly spaced values and how many steps it has."""
    steps = [b - a for a, b in zip(values, values[1:])]
    run = 1
    while run < len(steps) and abs(steps[run] - steps[0]) < 0.003:
        run += 1
    return (values[run] - values[0]) / run, run


def paint(
    nodes: Dict[str, List[Triangle]],
    material_names: Sequence[str],
    cab_texels: Sequence,
    painted: Dict[str, int],
) -> Tuple[int, int]:
    """Give every yellow source material the one yellow, the operator cab its
    white body and glass windows, and the counterweight its concrete. Returns
    the cab's (body, window) triangle counts."""
    yellow_sources = set()
    for name in YELLOW_SOURCE_MATERIALS:
        if name not in material_names:
            raise ValueError(f"the source has no material {name!r} to paint yellow")
        yellow_sources.add(material_names.index(name))
    yellow = painted[YELLOW_MATERIAL]
    for name, triangles in nodes.items():
        nodes[name] = [
            t[:3] + (yellow,) if t[3] in yellow_sources else t for t in triangles
        ]
    deck = nodes[CAB_NODE]
    if len(cab_texels) != len(deck):
        raise ValueError("the cab node's texture samples do not match its triangles")
    texel_of = {id(t): texel for t, texel in zip(deck, cab_texels)}
    cabs = [
        piece
        for piece in components(deck)
        if extent(piece, 1)[0] > CAB_BOTTOM_Y and extent(piece, 1)[1] > CAB_TOP_Y
    ]
    if len(cabs) != 1:
        raise ValueError(f"expected one operator cab on the deck, found {len(cabs)}")
    material_of = {}
    for t in cabs[0]:
        texel = texel_of[id(t)]
        if texel is None:
            raise ValueError("the operator cab has no texture to find its windows")
        is_window = max(texel) >= WINDOW_MIN_TEXEL
        material_of[id(t)] = painted[GLASS_MATERIAL if is_window else CAB_MATERIAL]
    nodes[CAB_NODE] = [
        t[:3] + (material_of[id(t)],) if id(t) in material_of else t for t in deck
    ]
    weights = [c for c in components(nodes[COUNTERJIB_NODE]) if is_counterweight(c)]
    if not weights:
        raise ValueError("the counterweight below the counterjib was not found")
    concrete = {id(t) for piece in weights for t in piece}
    nodes[COUNTERJIB_NODE] = [
        t[:3] + (painted[CONCRETE_MATERIAL],) if id(t) in concrete else t
        for t in nodes[COUNTERJIB_NODE]
    ]
    windows = sum(1 for m in material_of.values() if m == painted[GLASS_MATERIAL])
    return len(material_of) - windows, windows


def is_counterweight(component: Sequence[Triangle]) -> bool:
    """A piece of the counterjib node that hangs below its deck."""
    return extent(component, 1)[0] < COUNTERWEIGHT_BOTTOM_Y


def end_point(
    component: Sequence[Triangle], axis: int, high: bool
) -> Tuple[float, float, float]:
    """The centre of a piece's high (or low) end along an axis: its points
    within 2 cm of its largest (or smallest) value there."""
    points = _points([component])
    edge = max(p[axis] for p in points) if high else min(p[axis] for p in points)
    end = [p for p in points if abs(p[axis] - edge) <= 0.02]
    return tuple(sum(p[k] for p in end) / len(end) for k in range(3))


def strut_foot(strut: Sequence[Triangle]) -> Tuple[float, float, float]:
    """The centre of a strut's lower end (its points within 2 cm of its bottom)."""
    return end_point(strut, 1, high=False)


def holds(component: Sequence[Triangle], point: Sequence[float]) -> bool:
    """Whether a small fitting's box (grown by 3 cm) holds the point."""
    low, high = bounds(component)
    small = max(high[k] - low[k] for k in range(3)) < 0.5
    return small and all(low[k] - 0.03 <= point[k] <= high[k] + 0.03 for k in range(3))


def build(source: Path = SOURCE) -> KitBuild:
    """Cut the source crane into the reusable parts of the Liebherr kit."""
    document, binary = read_glb(source)
    samples = collect_material_samples(document, binary)
    colours = texture_colours(document, binary, samples)
    material_names = [
        m.get("name", f"material{i}") for i, m in enumerate(document["materials"])
    ]
    rope_material = len(material_names)
    material_names.append(ROPE_MATERIAL)
    colours[rope_material] = ROPE_COLOUR
    painted = {}
    for name, colour in (
        (YELLOW_MATERIAL, CRANE_YELLOW),
        (CAB_MATERIAL, CAB_COLOUR),
        (GLASS_MATERIAL, GLASS_COLOUR),
        (CONCRETE_MATERIAL, CONCRETE_COLOUR),
    ):
        painted[name] = len(material_names)
        material_names.append(name)
        colours[painted[name]] = colour
    raw = collect_nodes(document, binary)
    cab_texels = collect_node_texels(document, binary, lambda key: key == CAB_NODE)
    check_node_table(
        raw,
        BASE_NODES
        + MAST_NODES
        + SLEWING_NODES
        + (HEAD_NODE, JIB_NODE, COUNTERJIB_NODE),
    )
    origin = kit_origin(raw)
    nodes = {
        name: rotate(shift(tris, origin), KIT_ROTATION) for name, tris in raw.items()
    }
    paint(nodes, material_names, cab_texels.get(CAB_NODE, []), painted)
    parts: Dict[str, KitPart] = {}

    def gather(names: Sequence[str]) -> List[Triangle]:
        return [triangle for name in names for triangle in nodes[name]]

    # Mast: the stack of identical sections, cut exactly at each section's
    # bottom (a plane even 0.3 mm off a bottom would leave a sliver there).
    bottoms = sorted(extent(nodes[name], 1)[0] for name in MAST_NODES)
    mast_bays = len(bottoms)
    exact_pitch = (bottoms[-1] - bottoms[0]) / (mast_bays - 1)
    y0 = round(bottoms[0], 5)
    mast_pitch = round(exact_pitch, 5)
    y_top = y0 + mast_bays * mast_pitch
    mast_planes = bottoms + [y_top]
    mast_slabs = split_along(gather(MAST_NODES), 1, mast_planes, 0.5 * mast_pitch)
    # Bay 0 has no section below it, so it lacks the overlap the others share.
    assert_periodic(
        mast_slabs[1:-1],
        range(1, mast_bays),
        (MAST_CANONICAL_BAY,),
        1,
        exact_pitch,
        MAST_PERIOD_TOLERANCE,
        "mast bay",
    )
    upper = (0.0, y_top, 0.0)
    parts["base"] = KitPart("base", mast_slabs[0] + gather(BASE_NODES), [(1, y0)])
    parts["mast_a"] = KitPart(
        "mast_a",
        shift(mast_slabs[MAST_CANONICAL_BAY + 1], (0.0, bottoms[MAST_CANONICAL_BAY], 0.0)),
        [(1, 0.0), (1, mast_pitch)],
    )
    parts["slewing"] = KitPart(
        "slewing", shift(mast_slabs[-1] + gather(SLEWING_NODES), upper), [(1, 0.0)]
    )
    # Tower head, with the jib pendant chain taken out (the lug stays). The
    # chain is everything on the jib's centre line, from its fitting on the
    # apex pin to the lug.
    head, chain = [], []
    for component in components(nodes[HEAD_NODE]):
        if max(abs(c) for c in extent(component, 2)) <= 0.07:
            chain.append(component)
        else:
            head.append(component)
    if not chain:
        raise ValueError("the jib pendant chain was not found")
    # Every pendant hangs on one pin between the two apex plates: the piece
    # that holds the jib chain's apex end. The generated ropes start at its
    # centre, so they leave the head where the chains did.
    apex_end = end_point(min(chain, key=lambda c: extent(c, 0)[0]), 0, high=False)
    pins = [c for c in head if holds(c, apex_end)]
    if len(pins) != 1:
        raise ValueError(f"expected one apex pin for the pendants, found {len(pins)}")
    apex_pin = pins[0]
    pin_low, pin_high = bounds(apex_pin)
    pin_centre = [(pin_low[k] + pin_high[k]) / 2.0 for k in range(3)]
    chain_end = max(extent(c, 0)[1] for c in chain)
    lug = [c for c in chain if extent(c, 0)[0] > chain_end - 0.3]
    links = [c for c in chain if c not in lug]
    lug_x = (min(extent(c, 0)[0] for c in lug) + max(extent(c, 0)[1] for c in lug)) / 2.0
    parts["head"] = KitPart("head", shift(_flatten(head), upper))
    link_points = _points(links)
    # Jib: sort the pieces of the one jib node.
    jib_parts = components(nodes[JIB_NODE])
    signatures = Counter(_signature(c) for c in jib_parts)
    hook, rope, coils, walkway, diagonals, trolley, drum_frame, lattice = (
        [], [], [], [], [], [], [], []
    )
    for component in jib_parts:
        spans = _spans(component)
        repeated = signatures[_signature(component)] >= LATTICE_SIGNATURE_COUNT
        if extent(component, 1)[1] < HOOK_TOP_Y:
            hook.append(component)
        elif spans[1] > 5.0 and spans[0] < 0.1 and spans[2] < 0.1:
            rope.append(component)
        elif spans[0] > 30.0 and spans[1] > 0.3:
            pass  # the trolley rope sloping along the jib (ropes are generated)
        elif (
            spans[2] <= 0.035
            and 0.15 <= spans[0] <= 0.25
            and 0.15 <= spans[1] <= 0.25
            and _within(component, 0, JIB_DRUM_X)
        ):
            coils.append(component)
        elif (len(component) == 2 and spans[1] < 0.002 and 0.5 < spans[0] < 0.7) or (
            spans[1] < 0.03 and spans[0] > 30.0
        ):
            walkway.append(component)
        elif (
            len(component) == 24
            and _near(spans[1], 1.02, 0.03)
            and _near(spans[0], 0.51, 0.03)
            and _near(spans[2], 0.81, 0.03)
        ):
            diagonals.append(component)
        elif not repeated and _within(component, 0, TROLLEY_X):
            trolley.append(component)
        elif not repeated and _within(component, 0, JIB_DRUM_X):
            drum_frame.append(component)
        else:
            lattice.append(component)
    if len(rope) != 1 or not hook or not trolley or not coils or not walkway:
        raise ValueError(
            "the jib node no longer splits into hook, rope, trolley, drum and walkway"
        )
    members = sorted(
        extent(c, 0)[0]
        for c in lattice
        if len(c) == 8 and _near(_spans(c)[0], 0.11, 0.02) and _near(_spans(c)[2], 1.37, 0.03)
    )
    # The first cross member sits short of the regular run; it stays in the root.
    jib_pitch, jib_steps = _regular_run(members[1:])
    if jib_steps != len(members) - 2:
        raise ValueError("the jib cross members are not evenly spaced")
    jib_pitch = round(jib_pitch, 4)
    x0 = round(members[1] - jib_pitch, 4)
    jib_bays = round((members[-1] - jib_pitch - x0) / jib_pitch) + 1
    tip_start = x0 + (jib_bays - 1) * jib_pitch
    generated, diagonal_period = regular_diagonals(diagonals, x0, jib_pitch, jib_bays)
    jib_lattice = _flatten(lattice) + generated + plate_node(_flatten(walkway))
    jib_planes = [x0 + i * jib_pitch for i in range(1, jib_bays)]
    whole = 1.2 * jib_pitch
    jib_slabs = split_along(jib_lattice, 0, jib_planes, whole)
    assert_periodic(
        split_along(short_pieces(jib_lattice, 0, whole), 0, jib_planes, whole),
        range(1, jib_bays - 1),
        (JIB_CANONICAL_BAY,),
        0,
        jib_pitch,
        JIB_PERIOD_TOLERANCE,
        "jib bay",
    )
    assert_prismatic(
        jib_lattice, 0, (jib_planes[0], jib_planes[-1]), whole, JIB_PERIOD_TOLERANCE, "jib"
    )
    parts["jib_root"] = KitPart(
        "jib_root",
        shift(jib_slabs[0] + _flatten(drum_frame) + _drum(coils), upper),
        [(0, x0 + jib_pitch)],
    )
    parts["jib_a"] = KitPart(
        "jib_a",
        shift(jib_slabs[JIB_CANONICAL_BAY], (x0 + JIB_CANONICAL_BAY * jib_pitch, y_top, 0.0)),
        [(0, 0.0), (0, jib_pitch)],
    )
    parts["jib_tip"] = KitPart(
        "jib_tip", shift(jib_slabs[-1], (tip_start, y_top, 0.0)), [(0, 0.0)]
    )
    parts["jib_lug"] = KitPart("jib_lug", shift(_flatten(lug), (lug_x, y_top, 0.0)))
    # Counterjib: a root, a repeated section and the end with winch and weights.
    cjib_parts = components(nodes[COUNTERJIB_NODE])
    pendants, lead, struts, winch, deck, weights, cjib_lattice = [], [], [], [], [], [], []
    for component in cjib_parts:
        spans = _spans(component)
        if len(component) == 24 and _near(spans[1], 1.9, 0.05) and _near(spans[0], 3.25, 0.05):
            pendants.append(component)
        elif len(component) in (28, 60) and extent(component, 1)[0] > 36.0 and spans[2] <= 0.07:
            pendants.append(component)  # the joints of the pendant chains
        elif (
            len(component) == 24
            and spans[2] <= 0.07
            and holds(apex_pin, end_point(component, 0, high=True))
        ):
            pendants.append(component)  # the chains' first links, off the apex pin
        elif spans[1] > 5.0 and spans[0] > 10.0:
            # The hoist rope from the winch to the apex; it is welded to the
            # few coils it leaves the drum from, which the drum replaces.
            lead.append(component)
        elif is_counterweight(component):
            weights.append(component)
        elif len(component) == 24 and 0.7 < spans[1] < 0.9 and 1.2 < spans[0] < 1.5:
            # The pendants' last links: struts from the chain down to pins on
            # the deck edge, on the chain's own line.
            struts.append(component)
        elif (
            spans[2] <= 0.06
            and 0.3 <= spans[0] <= 0.42
            and 0.3 <= spans[1] <= 0.42
            and _within(component, 0, COUNTERJIB_WINCH_X)
        ):
            winch.append(component)
        elif len(component) == 12 and 1.3 < spans[2] < 1.45 and 0.1 < spans[1] < 0.14 and 0.8 < spans[0] < 1.0:
            deck.append(component)
        else:
            cjib_lattice.append(component)
    if (
        len(lead) != 1
        or len(struts) != 2
        or len(weights) != 1
        or not winch
        or not deck
        or not pendants
    ):
        raise ValueError(
            "the counterjib node no longer splits into pendants, struts, lead rope, "
            "counterweight, winch and deck"
        )
    # The generated pendant runs through the strut to its foot, and the pins
    # the struts stand on are the counterjib lugs.
    feet = [strut_foot(strut) for strut in struts]
    pins = [c for c in cjib_lattice if any(holds(c, foot) for foot in feet)]
    if len(pins) != 2:
        raise ValueError(f"expected a pin under each counterjib strut, found {len(pins)}")
    pin_ids = {id(pin) for pin in pins}
    cjib_lattice = [c for c in cjib_lattice if id(c) not in pin_ids]
    cross = sorted(
        (
            extent(c, 0)[0]
            for c in cjib_lattice
            if len(c) == 8 and _near(_spans(c)[0], 0.06, 0.02) and _near(_spans(c)[2], 1.23, 0.03)
        ),
        reverse=True,
    )
    cjib_step, cjib_sections = _regular_run(cross)
    cjib_pitch = round(-cjib_step, 4)
    c0 = round(cross[0], 4)
    end_plane = c0 - cjib_sections * cjib_pitch
    # In the gap the mid-run frame leaves, keep only the members that every
    # section has; that frame and the rail post it replaced are not repeated.
    regular = {
        _signature(c)
        for c in cjib_lattice
        if _within(c, 0, (c0 - 2 * cjib_pitch, c0 - cjib_pitch))
    }
    cjib_lattice = [
        c
        for c in cjib_lattice
        if not _within(c, 0, COUNTERJIB_MID_FRAME_X) or _signature(c) in regular
    ]
    cjib_planes = sorted(c0 - k * cjib_pitch for k in range(cjib_sections + 1))
    cjib_whole = 1.2 * cjib_pitch
    # The deck has two layers of panels; each becomes its own plate, run over
    # the whole repeat (the lower layer stops 0.34 m short of the mast end).
    layers: Dict[float, List[Triangle]] = {}
    for panel in deck:
        layers.setdefault(round(extent(panel, 1)[0], 2), []).extend(panel)
    plates: List[Triangle] = []
    for _y, layer in sorted(layers.items()):
        low, high = bounds(layer)
        low[0], high[0] = min(low[0], end_plane), max(high[0], c0)
        plates.extend(box_triangles(tuple(low), tuple(high), layer[0][3]))
    cjib_all = _flatten(cjib_lattice) + plates
    cjib_slabs = split_along(cjib_all, 0, cjib_planes, cjib_whole)
    irregular = {
        index
        for index in range(cjib_sections)
        if end_plane + index * cjib_pitch < COUNTERJIB_MID_FRAME_X[1]
        and end_plane + (index + 1) * cjib_pitch > COUNTERJIB_MID_FRAME_X[0]
    }
    canonical = cjib_sections - 1 - COUNTERJIB_CANONICAL_SECTION
    assert_periodic(
        split_along(short_pieces(cjib_all, 0, cjib_whole), 0, cjib_planes, cjib_whole)[1:-1],
        [index for index in range(cjib_sections) if index not in irregular],
        (canonical,),
        0,
        cjib_pitch,
        COUNTERJIB_PERIOD_TOLERANCE,
        "counterjib section",
    )
    assert_prismatic(
        cjib_all,
        0,
        (end_plane, c0),
        cjib_whole,
        COUNTERJIB_PERIOD_TOLERANCE,
        "counterjib",
    )
    end_origin = (end_plane, y_top, 0.0)
    parts["cjib_root"] = KitPart("cjib_root", shift(cjib_slabs[-1], upper), [(0, c0)])
    parts["cjib_section"] = KitPart(
        "cjib_section",
        shift(
            cjib_slabs[canonical + 1],
            (c0 - COUNTERJIB_CANONICAL_SECTION * cjib_pitch, y_top, 0.0),
        ),
        [(0, 0.0), (0, -cjib_pitch)],
    )
    parts["cjib_end"] = KitPart(
        "cjib_end", shift(cjib_slabs[0] + _drum(winch), end_origin), [(0, 0.0)]
    )
    parts["counterweight"] = KitPart("counterweight", shift(_flatten(weights), end_origin))
    parts["cjib_lug"] = KitPart("cjib_lug", shift(_flatten(pins), end_origin))
    # Trolley, hook block and the unit rope.
    rope_points = _points(rope)
    rope_top = max(p[1] for p in rope_points)
    rope_bottom = min(p[1] for p in rope_points)
    trolley_x = sum(extent(rope[0], 0)) / 2.0
    rope_z = round(sum(extent(rope[0], 2)) / 2.0, 4)
    parts["trolley"] = KitPart(
        "trolley", shift(_flatten(trolley), (trolley_x, y_top, 0.0))
    )
    parts["hook_block"] = KitPart(
        "hook_block", shift(_flatten(hook), (trolley_x, rope_bottom, 0.0))
    )
    parts["rope"] = KitPart("rope", rope_triangles(rope_material), edges=False)
    tip_length = round(extent(parts["jib_tip"].triangles, 0)[1], 4)
    lug_bay = round((lug_x - x0) / jib_pitch - 0.5)
    lead_points = _points(lead)
    lead_low = min(lead_points, key=lambda p: p[1])
    lead_high = max(lead_points, key=lambda p: p[1])
    foot_x = sum(foot[0] for foot in feet) / len(feet)
    foot_y = sum(foot[1] for foot in feet) / len(feet)
    cjib_lateral = round(sum(abs(foot[2]) for foot in feet) / len(feet), 4)
    trolley_half = round(max(extent(c, 0)[1] for c in trolley) - trolley_x, 4)
    modelled_rope = rope_top - rope_bottom
    reach = x0 + (jib_bays - 1) * jib_pitch + tip_length
    trolley_fraction = round(
        (trolley_x - TROLLEY_TRAVEL_START_M)
        / (reach - TROLLEY_TIP_CLEARANCE_M - TROLLEY_TRAVEL_START_M),
        2,
    )
    measured = {
        "mast_base": y0,
        "mast_pitch": mast_pitch,
        "mast_bays": mast_bays,
        "jib_first_bay": x0,
        "jib_pitch": jib_pitch,
        "jib_bays": jib_bays,
        "diagonal_period": diagonal_period,
        "counterjib_first": c0,
        "counterjib_pitch": cjib_pitch,
        "counterjib_sections": cjib_sections,
    }
    check_measured(measured, EXPECTED, MODEL_ID)
    kit = {
        "frame": "metres, Y-up, jib along +X; origin = mast axis at the bottom of the base",
        "mast": {
            "base_y": y0,
            "pitch": mast_pitch,
            "cycle": ["mast_a"],
            "default": mast_bays,
            "min": MAST_LIMITS[0],
            "max": MAST_LIMITS[1],
        },
        "jib": {
            "first_bay_x": x0,
            "pitch": jib_pitch,
            "cycle": ["jib_a"],
            "tip_length": tip_length,
            "start_x": round(extent(parts["jib_root"].triangles, 0)[0], 4),
            "default": jib_bays,
            "min": JIB_LIMITS[0],
            "max": JIB_LIMITS[1],
            "lugs": [
                {
                    "at": "fraction",
                    "fraction": round(lug_bay / jib_bays, 4),
                    "dx": round(lug_x - (x0 + lug_bay * jib_pitch), 4),
                    "attach_dx": round(max(p[0] for p in link_points) - lug_x, 4),
                    "min_bays": 0,
                }
            ],
        },
        "counterjib": {
            "first_x": c0,
            "pitch": cjib_pitch,
            "default": cjib_sections + 1,
            "min": COUNTERJIB_LIMITS[0],
            "max": COUNTERJIB_LIMITS[1],
        },
        "anchors": {
            "head_jib": [
                round(pin_centre[0], 4),
                round(pin_centre[1] - y_top, 4),
                round(pin_centre[2], 4),
            ],
            "jib_pendant": {
                "dy": round(min(p[1] for p in link_points) - y_top, 4),
                "lateral": [round(sum(p[2] for p in link_points) / len(link_points), 4)],
            },
            "head_counterjib": [
                round(pin_centre[0], 4),
                round(pin_centre[1] - y_top, 4),
                round(pin_centre[2], 4),
            ],
            "counterjib_pendant": {
                "dx": round(foot_x - end_plane, 4),
                "dy": round(foot_y - y_top, 4),
                "lateral": [-cjib_lateral, cjib_lateral],
            },
            "hoist_top": [0.0, round(rope_top - y_top, 4), rope_z],
            "hoist_falls": [[0.0, 0.0, rope_z]],
            "trolley_rope": [trolley_half, round(TROLLEY_ROPE_Y - y_top, 4), 0.0],
            "hoist_lead": {
                "from": [
                    round(lead_low[0] - end_plane, 4),
                    round(lead_low[1] - y_top, 4),
                    round(lead_low[2], 4),
                ],
                "to": [
                    round(lead_high[0], 4),
                    round(lead_high[1] - y_top, 4),
                    round(lead_high[2], 4),
                ],
            },
        },
        "hook": {
            "default_rope_ft": round(modelled_rope * FEET_PER_METRE, 1),
            "min_rope_ft": MIN_HOOK_ROPE_FT,
            "below_rope": round(rope_bottom - min(p[1] for p in _points(hook)), 4),
            "modelled_rope": round(modelled_rope, 4),
        },
        "trolley": {
            "default_fraction": trolley_fraction,
            "travel_start": TROLLEY_TRAVEL_START_M,
            "tip_clearance": TROLLEY_TIP_CLEARANCE_M,
            "rope_start_dx": TROLLEY_ROPE_START_M,
            "rope_end_dx": TROLLEY_ROPE_END_M,
            "modelled_x": round(trolley_x, 4),
        },
        "pendant_thickness": PENDANT_THICKNESS,
        "rope_radius": ROPE_RADIUS,
    }
    return KitBuild(
        parts=parts,
        part_order=PART_ORDER,
        kit=kit,
        colours=colours,
        material_names=material_names,
        source_extras=dict(document.get("asset", {}).get("extras", {})),
        modified=MODIFIED,
        measured=measured,
        glass_material=GLASS_MATERIAL,
    )
