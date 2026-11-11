"""Kit profile for "Tower Crane" by Chamod (Sketchfab, CC BY 4.0): model ``classic``.

Source ``assets/models/tower_crane.source.glb``; kit
``ost_visualizer/resources/models/tower_crane_classic.glb``.
* node transforms are baked; the origin is the mast axis (the centre of the
  four mast legs) on top of the model's own footing, so ``(0, 0, 0)`` sits on
  top of the count takeoff that is the footing;
* every source node is assigned to a part by an explicit table (an unassigned
  node fails the build). The model's footing, tie bars and hoist ropes are
  dropped: the takeoff is the footing and every rope is generated;
* the mast, jib and counterjib are cut at their lattice bay planes. The mast
  and jib keep two alternating bays each because their diagonals zigzag;
* the counter-jib walkway grating (16k triangles on one plane) becomes a thin
  plate. glTF conventions are kept: metres, Y-up, jib along +X.
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from tools.tower_crane_kit import (
    REPO,
    KitBuild,
    KitPart,
    Triangle,
    Vec3,
    assert_periodic,
    centre,
    check_measured,
    check_node_table,
    collect_material_samples,
    collect_nodes,
    collect_points,
    components,
    extent,
    kit_target,
    plate_node,
    read_glb,
    rope_triangles,
    shift,
    split_along,
    texture_colours,
    ROPE_RADIUS,
    CONCRETE_COLOUR,
    CRANE_YELLOW,
    GLASS_COLOUR,
)

MODEL_ID = "classic"
LABEL = "Classic"
SOURCE = REPO / "assets" / "models" / "tower_crane.source.glb"
TARGET = kit_target(MODEL_ID)
CREDIT = {
    "title": "Tower Crane",
    "author": "Chamod",
    "author_url": "https://sketchfab.com/Chamodp",
    "source_url": (
        "https://sketchfab.com/3d-models/tower-crane-49851dc7a51b43bda6aea06856c26a85"
    ),
    "site": "Sketchfab",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "modified": (
        "cut into reusable parts, textures removed, painted yellow (#edcf0c), "
        "geometry quantized, base slab and ropes removed (ropes are generated)"
    ),
}
MODIFIED = (
    "cut into reusable parts (base, mast bays, slewing unit, tower head, jib bays, "
    "counterjib sections, trolley, hook block); textures removed (flat material "
    "colours, the yellow steel #edcf0c), primitives welded, positions and normals "
    "quantized, edge lines baked, base slab, tie bars and ropes removed (ropes are "
    "generated), origin moved to the mast base"
)
FOOTING_NODE_PREFIX = "Cube.073"
MAST_LEGS_NODE_PREFIX = "Cube.052"
GLASS_MATERIAL = "GLASS"
ROPE_MATERIAL = "ROPE"
# Colours set instead of the sampled texture medians: the yellow steel (the
# main structure and the counterjib frame) is the crane yellow, and the glass
# and concrete keep the values every kit shares.
SET_COLOURS = {
    "material": CRANE_YELLOW,
    "frame": CRANE_YELLOW,
    GLASS_MATERIAL: GLASS_COLOUR,
    "CONCRETE": CONCRETE_COLOUR,
}
DEFAULT_MAST_BAYS = 25
DEFAULT_JIB_BAYS = 18
DEFAULT_COUNTERJIB_SECTIONS = 7
MAST_LIMITS = (1, 80)
JIB_LIMITS = (4, 40)
COUNTERJIB_LIMITS = (2, 12)
DEFAULT_TROLLEY_FRACTION = 0.79
DEFAULT_HOOK_ROPE_FT = 12.4
MIN_HOOK_ROPE_FT = 3.0
TROLLEY_TRAVEL_START_M = 3.0
TROLLEY_TIP_CLEARANCE_M = 1.2
TROLLEY_ROPE_START_M = 0.2
TROLLEY_ROPE_END_M = 0.3
PENDANT_THICKNESS = 1.5
LUG_INNER_MIN_BAYS = 8
MAST_CANONICAL_BAYS = (10, 11)
JIB_CANONICAL_BAYS = (2, 3)
COUNTERJIB_CANONICAL_SECTION = 2
# The source model's jib diagonals wander up to about 7 cm from a perfect grid.
JIB_PERIOD_TOLERANCE = 0.08
# The bay planes the kit is cut at; the tool checks the model against them.
EXPECTED = {
    "mast_base": 0.604,
    "mast_pitch": 1.52,
    "mast_bays": DEFAULT_MAST_BAYS,
    "jib_first_bay": 1.103,
    "jib_pitch": 1.9973,
    "counterjib_first": -1.597,
    "counterjib_pitch": 1.8973,
}


def _numbered(prefix: str, first: int, last: int) -> Tuple[str, ...]:
    return tuple(f"{prefix}.{number:03d}" for number in range(first, last + 1))


MAST_LATTICE_NODES = _numbered("Cube", 74, 85)
MAST_NODES = ("Cube.052",) + MAST_LATTICE_NODES + ("Cylinder.016", "Plane.029")
JIB_LATTICE_NODES = ("Cube.102", "Cube.103")
JIB_NODES = ("Cube.055", "Plane.023") + JIB_LATTICE_NODES
JIB_LUG_NODES = ("Cube.070", "Plane.027")
COUNTERJIB_POST_NODES = ("Cube.057", "Cube.058")
COUNTERJIB_PLATE_NODE = "Cube.056"
COUNTERJIB_NODES = (
    "Cube.054",
    "Plane.024",
    COUNTERJIB_PLATE_NODE,
) + COUNTERJIB_POST_NODES
SHEAVE_NODES = ("Cylinder.010", "Cylinder.011")
HOIST_ROPE_NODES = ("Plane.005_Curve.002", "Plane.005_Curve.003")
JIB_TIE_NODES = ("Plane.026", "Plane.028", "Plane.030", "Plane.032")
COUNTERJIB_TIE_NODES = ("Plane.034", "Plane.035")
RIGID_PART_NODES: Dict[str, Tuple[str, ...]] = {
    "slewing": ("Cube.086", "Cube.087", "Cylinder.017", "Cube.100", "Cube.101")
    + ("Cylinder.018", "Cylinder.019", "Plane.043", "Plane.044", "Plane.045")
    + ("Cube.072",)
    + _numbered("Slice", 5, 9),
    "head": ("Cube.053", "Cube.059", "Cube.069")
    + _numbered("Cube", 88, 99)
    + ("Plane.040", "Plane.041", "Plane.038", "Plane.039")
    + _numbered("Cylinder", 12, 15),
    "counterweight": ("Cube.060", "Cube.061"),
    "cjib_lug": ("Cube.071", "Plane.036", "Plane.037"),
    "trolley": _numbered("Cube", 62, 67) + SHEAVE_NODES,
    "hook_block": ("Cube.068", "Plane.025"),
}
# The model's own footing, tie bars and hoist ropes are not shipped (the count
# takeoff is the footing and every rope is generated from the layout), and the
# outer jib lug pieces are replaced by a second instance of the inner lug.
DROPPED_NODES = (
    (FOOTING_NODE_PREFIX, "Plane.031", "Plane.033")
    + JIB_TIE_NODES
    + COUNTERJIB_TIE_NODES
    + HOIST_ROPE_NODES
)
PART_ORDER = (
    "base",
    "mast_a",
    "mast_b",
    "slewing",
    "head",
    "jib_root",
    "jib_a",
    "jib_b",
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


def base_origin(mast_legs: List[Vec3], footing: List[Vec3]) -> Vec3:
    """The mast axis (centre of the four mast legs) on top of the footing."""
    if not footing:
        raise ValueError(f"footing node {FOOTING_NODE_PREFIX!r} not found")
    if not mast_legs:
        raise ValueError(f"mast legs node {MAST_LEGS_NODE_PREFIX!r} not found")
    slab_top = max(p[1] for p in footing)
    cx = (min(p[0] for p in mast_legs) + max(p[0] for p in mast_legs)) / 2.0
    cz = (min(p[2] for p in mast_legs) + max(p[2] for p in mast_legs)) / 2.0
    return (cx, slab_top, cz)


def measure_layout(nodes: Dict[str, List[Triangle]]) -> dict:
    """The model's own bay pitches and first-bay positions (crane frame)."""
    frames = sorted(extent(c, 1)[0] for c in components(nodes[MAST_LATTICE_NODES[0]]))
    diagonals = sorted(
        {round(extent(c, 0)[0], 3) for c in components(nodes["Cube.102"])}
    )
    posts = sorted(centre(c, 0) for c in components(nodes[COUNTERJIB_POST_NODES[0]]))
    post_gap = (posts[-1] - posts[0]) / (len(posts) - 1)
    return {
        "mast_base": frames[0],
        "mast_pitch": (frames[-1] - frames[0]) / (len(frames) - 1),
        "mast_bays": len(frames) - 1,
        "jib_first_bay": diagonals[0],
        "jib_pitch": (diagonals[-1] - diagonals[0]) / (2 * (len(diagonals) - 1)),
        "counterjib_first": posts[-1] + post_gap / 2.0,
        "counterjib_pitch": 2.0 * post_gap,
    }


def build(source: Path = SOURCE) -> KitBuild:
    """Cut the source crane into the reusable parts of the classic kit."""
    document, binary = read_glb(source)
    footing = collect_points(document, binary, lambda chain: FOOTING_NODE_PREFIX in chain)
    mast_legs = collect_points(
        document,
        binary,
        lambda chain: MAST_LEGS_NODE_PREFIX in chain and FOOTING_NODE_PREFIX not in chain,
    )
    origin = base_origin(mast_legs, footing)
    samples = collect_material_samples(
        document, binary, skip=lambda chain: FOOTING_NODE_PREFIX in chain
    )
    colours = texture_colours(document, binary, samples)
    material_names = [
        m.get("name", f"material{i}") for i, m in enumerate(document["materials"])
    ]
    for name, colour in SET_COLOURS.items():
        colours[material_names.index(name)] = colour
    nodes = {
        name: shift(tris, origin)
        for name, tris in collect_nodes(document, binary).items()
    }
    assigned = list(
        MAST_NODES + JIB_NODES + JIB_LUG_NODES + COUNTERJIB_NODES + DROPPED_NODES
    )
    for part_nodes in RIGID_PART_NODES.values():
        assigned.extend(part_nodes)
    check_node_table(nodes, assigned)
    measured = measure_layout(nodes)
    check_measured(measured, EXPECTED, MODEL_ID)
    y0, mast_pitch = EXPECTED["mast_base"], EXPECTED["mast_pitch"]
    x0, jib_pitch = EXPECTED["jib_first_bay"], EXPECTED["jib_pitch"]
    c0, cjib_pitch = EXPECTED["counterjib_first"], EXPECTED["counterjib_pitch"]
    y_top = y0 + DEFAULT_MAST_BAYS * mast_pitch
    parts: Dict[str, KitPart] = {}

    def gather(names: Sequence[str]) -> List[Triangle]:
        return [triangle for name in names for triangle in nodes[name]]

    # Mast: base stub, two alternating bays, and what is left above the last bay.
    mast_planes = [y0 + k * mast_pitch for k in range(DEFAULT_MAST_BAYS + 1)]
    mast_slabs = split_along(gather(MAST_NODES), 1, mast_planes, 1.2 * mast_pitch)
    lattice_slabs = split_along(
        gather(MAST_LATTICE_NODES), 1, mast_planes, 1.2 * mast_pitch
    )
    assert_periodic(
        lattice_slabs[1:-1],
        range(DEFAULT_MAST_BAYS),
        MAST_CANONICAL_BAYS,
        1,
        mast_pitch,
        0.03,
        "mast bay",
    )
    parts["base"] = KitPart("base", mast_slabs[0], [(1, y0)])
    for name, bay in zip(("mast_a", "mast_b"), MAST_CANONICAL_BAYS):
        parts[name] = KitPart(
            name,
            shift(mast_slabs[bay + 1], (0.0, mast_planes[bay], 0.0)),
            [(1, 0.0), (1, mast_pitch)],
        )
    upper = (0.0, y_top, 0.0)
    parts["slewing"] = KitPart(
        "slewing",
        shift(mast_slabs[-1] + gather(RIGID_PART_NODES["slewing"]), upper),
        [(1, 0.0)],
    )
    parts["head"] = KitPart("head", shift(gather(RIGID_PART_NODES["head"]), upper))
    # Jib: a root bay, two alternating bays and the tip bay.
    jib_planes = [x0 + i * jib_pitch for i in range(1, DEFAULT_JIB_BAYS)]
    jib_slabs = split_along(gather(JIB_NODES), 0, jib_planes, 1.2 * jib_pitch)
    jib_lattice = split_along(gather(JIB_LATTICE_NODES), 0, jib_planes, 1.2 * jib_pitch)
    assert_periodic(
        jib_lattice,
        range(1, DEFAULT_JIB_BAYS - 1),
        JIB_CANONICAL_BAYS,
        0,
        jib_pitch,
        JIB_PERIOD_TOLERANCE,
        "jib bay",
    )
    parts["jib_root"] = KitPart(
        "jib_root", shift(jib_slabs[0], upper), [(0, x0 + jib_pitch)]
    )
    for name, bay in zip(("jib_a", "jib_b"), JIB_CANONICAL_BAYS):
        parts[name] = KitPart(
            name,
            shift(jib_slabs[bay], (x0 + bay * jib_pitch, y_top, 0.0)),
            [(0, 0.0), (0, jib_pitch)],
        )
    tip_start = x0 + (DEFAULT_JIB_BAYS - 1) * jib_pitch
    parts["jib_tip"] = KitPart(
        "jib_tip", shift(jib_slabs[-1], (tip_start, y_top, 0.0)), [(0, 0.0)]
    )
    mid_jib = (x0 + tip_start) / 2.0

    def lug_side(names: Sequence[str], inner: bool) -> List[Triangle]:
        return [
            triangle
            for component in components(gather(names))
            if (centre(component, 0) < mid_jib) == inner
            for triangle in component
        ]

    inner_lug_x = centre(lug_side(("Cube.070",), True), 0)
    outer_lug_x = centre(lug_side(("Cube.070",), False), 0)
    parts["jib_lug"] = KitPart(
        "jib_lug", shift(lug_side(JIB_LUG_NODES, True), (inner_lug_x, y_top, 0.0))
    )
    # Counterjib: a short root, a repeated section and the end with its ballast.
    nodes[COUNTERJIB_PLATE_NODE] = plate_node(nodes[COUNTERJIB_PLATE_NODE])
    mid_sections = DEFAULT_COUNTERJIB_SECTIONS - 1
    cjib_planes = sorted(c0 - k * cjib_pitch for k in range(mid_sections + 1))
    cjib_slabs = split_along(gather(COUNTERJIB_NODES), 0, cjib_planes, 1.2 * cjib_pitch)
    post_slabs = split_along(
        gather(COUNTERJIB_POST_NODES), 0, cjib_planes, 1.2 * cjib_pitch
    )
    # Slab ``mid_sections - k`` is section ``k`` counted outward from the mast.
    assert_periodic(
        post_slabs[1:-1],
        range(mid_sections),
        (0,),
        0,
        cjib_pitch,
        0.01,
        "counterjib section",
    )
    end_plane = c0 - mid_sections * cjib_pitch
    parts["cjib_root"] = KitPart("cjib_root", shift(cjib_slabs[-1], upper), [(0, c0)])
    section_slab = mid_sections - COUNTERJIB_CANONICAL_SECTION
    parts["cjib_section"] = KitPart(
        "cjib_section",
        shift(
            cjib_slabs[section_slab],
            (c0 - COUNTERJIB_CANONICAL_SECTION * cjib_pitch, y_top, 0.0),
        ),
        [(0, 0.0), (0, -cjib_pitch)],
    )
    end_origin = (end_plane, y_top, 0.0)
    parts["cjib_end"] = KitPart("cjib_end", shift(cjib_slabs[0], end_origin), [(0, 0.0)])
    for name in ("counterweight", "cjib_lug"):
        parts[name] = KitPart(name, shift(gather(RIGID_PART_NODES[name]), end_origin))
    # Trolley, hook block and the unit rope.
    sheaves = [
        (centre(nodes[name], 0), centre(nodes[name], 1)) for name in SHEAVE_NODES
    ]
    trolley_x = (sheaves[0][0] + sheaves[1][0]) / 2.0
    sheave_y = (sheaves[0][1] + sheaves[1][1]) / 2.0
    rope_bottom = min(extent(nodes[name], 1)[0] for name in HOIST_ROPE_NODES)
    rope_feet = [
        sum(v[0][0] for t in nodes[name] for v in t[:3] if v[0][1] < rope_bottom + 0.05)
        / max(
            1,
            sum(1 for t in nodes[name] for v in t[:3] if v[0][1] < rope_bottom + 0.05),
        )
        for name in HOIST_ROPE_NODES
    ]
    parts["trolley"] = KitPart(
        "trolley", shift(gather(RIGID_PART_NODES["trolley"]), (trolley_x, y_top, 0.0))
    )
    hook = gather(RIGID_PART_NODES["hook_block"])
    parts["hook_block"] = KitPart(
        "hook_block", shift(hook, (trolley_x, rope_bottom, 0.0))
    )
    rope_material = material_names.index(ROPE_MATERIAL)
    parts["rope"] = KitPart("rope", rope_triangles(rope_material), edges=False)
    inner_tie, outer_tie = nodes[JIB_TIE_NODES[0]], nodes[JIB_TIE_NODES[2]]
    cjib_tie = nodes[COUNTERJIB_TIE_NODES[0]]
    inner_bay = round((inner_lug_x - x0) / jib_pitch - 0.5)
    sheave_dx = round((sheaves[1][0] - sheaves[0][0]) / 2.0, 4)
    hoist_dy = round(sheave_y - y_top, 4)
    bottom_dx = round((rope_feet[1] - rope_feet[0]) / 2.0, 4)
    jib_lateral = round(max(abs(c) for c in extent(inner_tie, 2)), 4)
    cjib_lateral = round(max(abs(c) for c in extent(cjib_tie, 2)), 4)
    kit = {
        "frame": "metres, Y-up, jib along +X; origin = mast axis on top of the footing",
        "mast": {
            "base_y": y0,
            "pitch": mast_pitch,
            "cycle": ["mast_a", "mast_b"],
            "default": DEFAULT_MAST_BAYS,
            "min": MAST_LIMITS[0],
            "max": MAST_LIMITS[1],
        },
        "jib": {
            "first_bay_x": x0,
            "pitch": jib_pitch,
            "cycle": ["jib_a", "jib_b"],
            "tip_length": round(extent(parts["jib_tip"].triangles, 0)[1], 4),
            "start_x": round(extent(parts["jib_root"].triangles, 0)[0], 4),
            "default": DEFAULT_JIB_BAYS,
            "min": JIB_LIMITS[0],
            "max": JIB_LIMITS[1],
            # The outer lug sits on the tip; the inner one at a share of the jib
            # once the jib is long enough to need it.
            "lugs": [
                {
                    "at": "tip",
                    "dx": round(outer_lug_x - tip_start, 4),
                    "attach_dx": round(extent(outer_tie, 0)[1] - outer_lug_x, 4),
                    "min_bays": 0,
                },
                {
                    "at": "fraction",
                    "fraction": round(inner_bay / DEFAULT_JIB_BAYS, 4),
                    "dx": round(inner_lug_x - (x0 + inner_bay * jib_pitch), 4),
                    "attach_dx": round(extent(inner_tie, 0)[1] - inner_lug_x, 4),
                    "min_bays": LUG_INNER_MIN_BAYS,
                },
            ],
        },
        "counterjib": {
            "first_x": c0,
            "pitch": cjib_pitch,
            "default": DEFAULT_COUNTERJIB_SECTIONS,
            "min": COUNTERJIB_LIMITS[0],
            "max": COUNTERJIB_LIMITS[1],
        },
        "anchors": {
            "head_jib": [
                round(extent(inner_tie, 0)[0], 4),
                round(extent(inner_tie, 1)[1] - y_top, 4),
                0.0,
            ],
            "jib_pendant": {
                "dy": round(extent(inner_tie, 1)[0] - y_top, 4),
                "lateral": [-jib_lateral, jib_lateral],
            },
            "head_counterjib": [
                round(extent(cjib_tie, 0)[1], 4),
                round(extent(cjib_tie, 1)[1] - y_top, 4),
                0.0,
            ],
            "counterjib_pendant": {
                "dx": round(extent(cjib_tie, 0)[0] - end_plane, 4),
                "dy": round(extent(cjib_tie, 1)[0] - y_top, 4),
                "lateral": [-cjib_lateral, cjib_lateral],
            },
            "hoist_top": [sheave_dx, hoist_dy, 0.0],
            "hoist_falls": [[-sheave_dx, -bottom_dx, 0.0], [sheave_dx, bottom_dx, 0.0]],
            "trolley_rope": [sheave_dx, hoist_dy, 0.0],
        },
        "hook": {
            "default_rope_ft": DEFAULT_HOOK_ROPE_FT,
            "min_rope_ft": MIN_HOOK_ROPE_FT,
            "below_rope": round(rope_bottom - extent(hook, 1)[0], 4),
            "modelled_rope": round(sheave_y - rope_bottom, 4),
        },
        "trolley": {
            "default_fraction": DEFAULT_TROLLEY_FRACTION,
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
