import math
import unittest
from ost_visualizer.domain.dtos.tower_crane_placement_dto import (
    INCHES_PER_METRE,
    TowerCranePlacement,
)
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.tower_crane_spec import resolve_tower_crane
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.infrastructure.visualization_provider import _MeshGeneratorAdapter
from ost_visualizer.presentation.visualization.core.geometry.takeoff_geometry import (
    point_takeoff_vertical_extent,
)
from ost_visualizer.presentation.visualization.factories.coordinate_transformer_factory import (
    CoordinateTransformerFactory,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
    native_instance_corners,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
    tower_crane_catalog,
    tower_crane_kit,
)
from ost_visualizer.presentation.visualization.meshing.mesh_factory import MeshFactory
from ost_visualizer.presentation.visualization.meshing.tower_crane import (
    tower_crane_placement,
)
from ost_visualizer.presentation.visualization.utils.mesh import meshes_to_geometries
from tests.presentation.visualization.assets.glb_positions import mast_anchor_bounds
from tests.presentation.visualization.meshing.page_flip_support import (
    _ColorService,
    _TakeoffService,
    _page_info,
)


def _crane_condition(**overrides):
    values = dict(
        uid="footing",
        name="Crane footing",
        condition_type=Condition.TYPE_COUNT,
        width=240.0,
        depth=240.0,
        height=48.0,
        notes="Tower crane base [crane]",
    )
    values.update(overrides)
    return Condition(**values)


def _takeoff(uid="t1", position=(1200.0, 600.0), rotation=0.0, **overrides):
    return Takeoff(
        uid=uid,
        condition_uid=overrides.pop("condition_uid", "footing"),
        page_uid=overrides.pop("page_uid", "page"),
        position=list(position),
        rotation=rotation,
        **overrides,
    )


def _footing_centre_and_top(takeoff, condition, coord_system):
    mesh = MeshFactory(coord_system).create_mesh_for_takeoff(takeoff, condition)
    xs = [v[0] for v in mesh.vertices]
    ys = [v[1] for v in mesh.vertices]
    zs = [v[2] for v in mesh.vertices]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(zs)


class _InactiveColorService(_ColorService):
    def __init__(self, inactive_uids=()):
        self.inactive_uids = set(inactive_uids)

    def is_inactive_area_takeoff(self, takeoff, _page_area_selections):
        return takeoff.uid in self.inactive_uids


class TowerCranePlacementTests(unittest.TestCase):
    def setUp(self):
        self.coord_system = OSTCoordinateSystem()

    def test_crane_stands_on_the_footing_centre_and_top_however_it_is_sized(self):
        cases = {
            "plain": _crane_condition(),
            "top elevation": _crane_condition(z_value=120.0, is_top=True),
            "raised": _crane_condition(z_value=-36.0),
            "display size": _crane_condition(display_size=50.0),
            "missing dimensions": _crane_condition(width=0.0, depth=0.0, height=0.0),
            "circle": _crane_condition(shape=shapes.CIRCLE),
        }
        for label, condition in cases.items():
            with self.subTest(label):
                takeoff = _takeoff(rotation=0.4)
                crane = tower_crane_placement(takeoff, condition, self.coord_system)
                x, y, top = _footing_centre_and_top(
                    takeoff, condition, self.coord_system
                )
                self.assertAlmostEqual(crane.x, x, places=6)
                self.assertAlmostEqual(crane.y, y, places=6)
                self.assertAlmostEqual(crane.z, top, places=6)

    def test_vertical_extent_matches_the_count_solid(self):
        condition = _crane_condition(z_value=100.0, is_top=True, display_size=50.0)
        bottom, height = point_takeoff_vertical_extent(condition)
        self.assertEqual((bottom, height), (76.0, 24.0))
        # Missing heights fall back to 1 inch, scaled like the footing.
        self.assertEqual(
            point_takeoff_vertical_extent(
                _crane_condition(height=0.0, display_size=200.0)
            ),
            (0, 2.0),
        )

    def test_rotation_follows_the_footing_and_identity_is_kept(self):
        crane = tower_crane_placement(
            _takeoff(uid="t9", rotation=math.radians(30.0), page_uid="p2"),
            _crane_condition(),
            self.coord_system,
            inactive=True,
        )
        self.assertEqual(
            crane,
            TowerCranePlacement(
                takeoff_uid="t9",
                condition_uid="footing",
                page_uid="p2",
                x=-1200.0,
                y=600.0,
                z=48.0,
                rotation=-math.radians(30.0),
                inactive=True,
                spec=resolve_tower_crane("[crane]", tower_crane_catalog()).spec,
            ),
        )
        shaped = tower_crane_placement(
            _takeoff(),
            _crane_condition(notes="[crane mast=30 jib=20]"),
            self.coord_system,
        )
        self.assertEqual((shaped.spec.mast, shaped.spec.jib), (30, 20))
        not_finite = tower_crane_placement(
            _takeoff(rotation=float("nan")), _crane_condition(), self.coord_system
        )
        self.assertEqual(not_finite.rotation, 0.0)

    def test_only_positive_count_takeoffs_with_the_tag_and_a_position_get_one(self):
        condition = _crane_condition()
        self.assertIsNone(
            tower_crane_placement(
                _takeoff(is_negative=True), condition, self.coord_system
            )
        )
        self.assertIsNone(
            tower_crane_placement(_takeoff(position=()), condition, self.coord_system)
        )
        for other in (
            _crane_condition(notes="footing"),
            _crane_condition(notes="Tower crane base (CRANE)"),
            _crane_condition(condition_type=Condition.TYPE_ATTACHMENT),
        ):
            with self.subTest(other=other):
                self.assertIsNone(
                    tower_crane_placement(_takeoff(), other, self.coord_system)
                )


class TowerCraneMeshPipelineTests(unittest.TestCase):
    def _generate(self, conditions, takeoffs, page_infos=None, color_service=None):
        generator = _MeshGeneratorAdapter(
            CoordinateTransformerFactory(),
            color_service or _InactiveColorService(),
            _TakeoffService(),
        )
        return generator.generate_meshes(
            conditions,
            takeoffs,
            inactive_object_color="#d0d0d0",
            page_infos=page_infos,
        )

    def test_each_crane_takeoff_carries_one_placement_and_bounds_are_unchanged(self):
        crane = _crane_condition()
        plain = Condition("slab", condition_type=Condition.TYPE_AREA, thickness=6.0)
        takeoffs = [
            _takeoff("a", (100.0, 100.0)),
            _takeoff("b", (900.0, 400.0), rotation=1.0),
            Takeoff(
                "s",
                "slab",
                page_uid="page",
                position=[0.0, 0.0, 1000.0, 0.0, 1000.0, 800.0, 0.0, 800.0],
            ),
        ]
        conditions = {crane.uid: crane, plain.uid: plain}
        meshes, colors, bounds = self._generate(
            conditions, takeoffs, color_service=_InactiveColorService({"b"})
        )
        cranes = {
            entry["takeoff_uid"]: entry.get("tower_crane") for entry in colors.values()
        }
        self.assertEqual(set(cranes), {"a", "b", "s"})
        self.assertIsNone(cranes["s"])
        self.assertEqual((cranes["a"].x, cranes["a"].y), (-100.0, 100.0))
        self.assertFalse(cranes["a"].inactive)
        self.assertTrue(cranes["b"].inactive)
        self.assertAlmostEqual(cranes["b"].rotation, -1.0)
        # The footing is meshed and bounded exactly as without the tag.
        untagged = _crane_condition(notes="")
        meshes_plain, colors_plain, bounds_plain = self._generate(
            {untagged.uid: untagged, plain.uid: plain}, takeoffs
        )
        self.assertEqual(bounds, bounds_plain)
        self.assertEqual(
            [m.vertices for m in meshes], [m.vertices for m in meshes_plain]
        )
        self.assertTrue(all("tower_crane" not in e for e in colors_plain.values()))
        geometries = meshes_to_geometries(meshes, colors, _GeometryColors())
        self.assertEqual({g.takeoff_uid: g.tower_crane for g in geometries}, cranes)

    def test_a_rotated_page_turns_the_crane_with_its_footing(self):
        crane = _crane_condition(width=400.0, depth=100.0, shape=shapes.RECTANGLE)
        takeoff = _takeoff(position=(300.0, 200.0), rotation=0.0)
        page_info = dict(_page_info(), rotation=90)
        meshes, colors, _ = self._generate(
            {crane.uid: crane}, [takeoff], page_infos={"page": page_info}
        )
        placement = colors["mesh_0"]["tower_crane"]
        mesh = meshes[0]
        xs = [v[0] for v in mesh.vertices]
        ys = [v[1] for v in mesh.vertices]
        self.assertAlmostEqual(placement.x, (min(xs) + max(xs)) / 2, places=6)
        self.assertAlmostEqual(placement.y, (min(ys) + max(ys)) / 2, places=6)
        # The footing's long side (its local x axis) is axis-aligned after a
        # quarter-turn page and runs along the crane heading.
        long_axis = math.pi / 2 if max(ys) - min(ys) > max(xs) - min(xs) else 0.0
        self.assertAlmostEqual(abs((max(ys) - min(ys)) - (max(xs) - min(xs))), 300.0)
        heading = math.atan2(
            abs(math.sin(placement.rotation)), abs(math.cos(placement.rotation))
        )
        self.assertAlmostEqual(heading, long_axis, places=6)


class TowerCraneQuantityTests(unittest.TestCase):
    def test_the_crane_tag_never_changes_footing_quantities(self):
        takeoffs = [_takeoff("a"), _takeoff("b", (500.0, 500.0), rotation=0.7)]
        for calc_type in (0, 1, 2, 3):
            with self.subTest(calc_type=calc_type):
                tagged = _crane_condition(calc_type1=calc_type, uom1=1)
                untagged = _crane_condition(calc_type1=calc_type, uom1=1, notes="")
                self.assertEqual(
                    compute_page_quantities({"footing": tagged}, takeoffs),
                    compute_page_quantities({"footing": untagged}, takeoffs),
                )


class _GeometryColors:
    @staticmethod
    def as_hex_with_opacity(entry):
        return entry["color"], entry["opacity"]


if __name__ == "__main__":
    unittest.main()


class TowerCraneBaseCentringTests(unittest.TestCase):
    """The mast stands on the centre of its footing, however the footing is turned."""

    TOLERANCE_IN = 0.5

    @classmethod
    def setUpClass(cls):
        cls.anchor_bounds = mast_anchor_bounds(tower_crane_kit("classic").read_bytes())

    def _crane_base(self, crane):
        corners = native_instance_corners(
            self.anchor_bounds,
            INCHES_PER_METRE,
            crane.x,
            crane.y,
            crane.z,
            crane.rotation,
        )
        return (
            sum(c[0] for c in corners) / len(corners),
            sum(c[1] for c in corners) / len(corners),
            max(c[2] for c in corners),
        )

    def assertBaseOnFootingCentre(self, crane, centre_x, centre_y, top):
        base_x, base_y, _anchor_top = self._crane_base(crane)
        self.assertAlmostEqual(base_x, centre_x, delta=self.TOLERANCE_IN)
        self.assertAlmostEqual(base_y, centre_y, delta=self.TOLERANCE_IN)
        self.assertAlmostEqual(crane.x, centre_x, places=6)
        self.assertAlmostEqual(crane.y, centre_y, places=6)
        self.assertAlmostEqual(crane.z, top, places=6)

    def test_the_mast_base_sits_on_the_footing_centre_for_any_footing_rotation(self):
        coord_system = OSTCoordinateSystem()
        condition = _crane_condition(width=400.0, depth=100.0, shape=shapes.RECTANGLE)
        for degrees in (0.0, 30.0, 90.0, 137.0, 215.0, -45.0):
            with self.subTest(degrees=degrees):
                takeoff = _takeoff(
                    position=(1200.0, 600.0), rotation=math.radians(degrees)
                )
                crane = tower_crane_placement(takeoff, condition, coord_system)
                centre_x, centre_y, top = _footing_centre_and_top(
                    takeoff, condition, coord_system
                )
                self.assertBaseOnFootingCentre(crane, centre_x, centre_y, top)

    def test_the_mast_base_follows_the_footing_on_rotated_and_flipped_pages(self):
        generator = _MeshGeneratorAdapter(
            CoordinateTransformerFactory(), _InactiveColorService(), _TakeoffService()
        )
        condition = _crane_condition(width=400.0, depth=100.0, shape=shapes.RECTANGLE)
        cases = (
            {"rotation": 90},
            {"rotation": 180},
            {"rotation": 270},
            {"flip_x": True},
            {"flip_y": True},
            {"rotation": 90, "flip_x": True},
        )
        for overrides in cases:
            with self.subTest(page=overrides):
                page_info = dict(_page_info(), **overrides)
                takeoff = _takeoff(position=(300.0, 200.0), rotation=math.radians(40.0))
                meshes, colors, _ = generator.generate_meshes(
                    {condition.uid: condition},
                    [takeoff],
                    inactive_object_color="#d0d0d0",
                    page_infos={"page": page_info},
                )
                crane = colors["mesh_0"]["tower_crane"]
                xs = [v[0] for v in meshes[0].vertices]
                ys = [v[1] for v in meshes[0].vertices]
                zs = [v[2] for v in meshes[0].vertices]
                self.assertBaseOnFootingCentre(
                    crane,
                    (min(xs) + max(xs)) / 2,
                    (min(ys) + max(ys)) / 2,
                    max(zs),
                )

    def test_the_mast_anchors_reach_into_the_footing_below_the_crane_origin(self):
        crane = tower_crane_placement(
            _takeoff(), _crane_condition(), OSTCoordinateSystem()
        )
        _x, _y, anchor_top = self._crane_base(crane)
        self.assertLess(anchor_top, crane.z)
        self.assertGreater(anchor_top, crane.z - 0.5 * INCHES_PER_METRE)
