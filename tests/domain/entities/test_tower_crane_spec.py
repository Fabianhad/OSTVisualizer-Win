import copy
import unittest
from ost_visualizer.domain.entities import tower_crane_spec as crane
from ost_visualizer.domain.entities.tower_crane_spec import (
    TowerCraneCatalog,
    TowerCraneModel,
    TowerCraneSpec,
    default_tower_crane_spec,
    has_tower_crane_tag,
    resolve_tower_crane,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
    tower_crane_catalog,
    tower_crane_kit,
)

FEET_PER_METRE = 1 / 0.3048
# The shipped kits: every number below comes from their metadata.
CATALOG = tower_crane_catalog()
CLASSIC = CATALOG.get("classic")
LIEBHERR = CATALOG.get("liebherr")


def _spec(notes, catalog=CATALOG):
    return resolve_tower_crane(notes, catalog).spec


def _warnings(notes, catalog=CATALOG):
    return resolve_tower_crane(notes, catalog).warnings


class TowerCraneDefaultsTests(unittest.TestCase):
    def test_a_bare_tag_is_the_model_as_built_with_lengths_in_feet(self):
        tag = resolve_tower_crane("[crane]", CATALOG)
        self.assertTrue(tag.present)
        self.assertEqual(tag.warnings, ())
        self.assertEqual(
            tag.spec,
            TowerCraneSpec(
                mast=25,
                jib=18,
                counterjib=7,
                trolley_ft=95.297,
                hook_rope_ft=12.4,
                model="classic",
            ),
        )
        self.assertEqual(default_tower_crane_spec(CATALOG), tag.spec)
        self.assertEqual(CLASSIC.default_hook_rope_ft, 12.4)
        # 12.4 ft is the model's own hoist rope (about 3.77 m).
        self.assertAlmostEqual(CLASSIC.default_hook_rope_ft / FEET_PER_METRE, 3.78, 2)

    def test_schema_defaults_and_ranges_are_shown_in_feet(self):
        schema = crane.tower_crane_schema(CLASSIC, CATALOG.ids)
        keys = {key.name: key for key in schema.keys}
        self.assertEqual(keys["hook"].default_text, "12.4 ft")
        self.assertEqual(keys["hook"].range_text, "3 ft or more")
        self.assertEqual(keys["hook"].minimum, 3.0)
        self.assertEqual(keys["hookheight"].range_text, "0 ft or more")
        self.assertEqual(keys["mast"].default_text, "25")
        self.assertEqual(keys["trolley"].default_text, "79%")
        self.assertEqual(keys["model"].default_text, "classic")
        self.assertEqual(CLASSIC.default_trolley_fraction, 0.79)
        self.assertEqual(_spec("[crane trolley=79%]"), _spec("[crane]"))
        self.assertAlmostEqual(keys["mast"].kind.pitch_ft, 1.52 * FEET_PER_METRE)
        self.assertAlmostEqual(keys["jib"].kind.pitch_ft, 1.9973 * FEET_PER_METRE)
        self.assertAlmostEqual(
            keys["counterjib"].kind.pitch_ft, 1.8973 * FEET_PER_METRE
        )

    def test_notes_without_the_tag_have_no_crane(self):
        for notes in ("", "crane", "(CRANE)", "[cranes]", "[tower crane]"):
            with self.subTest(notes=notes):
                tag = resolve_tower_crane(notes, CATALOG)
                self.assertFalse(tag.present)
                self.assertIsNone(tag.spec)
                self.assertEqual(tag.warnings, ())
                self.assertFalse(has_tower_crane_tag(notes))

    def test_the_proposed_example_parses(self):
        notes = "[crane mast=30 jib=19 counterjib=6 trolley=70% hook=40ft]"
        spec = _spec(notes)
        self.assertEqual((spec.mast, spec.jib, spec.counterjib), (30, 19, 6))
        self.assertEqual(spec.hook_rope_ft, 40.0)
        low, high = CLASSIC.trolley_travel_ft(19)
        self.assertAlmostEqual(spec.trolley_ft, low + 0.7 * (high - low), places=3)
        self.assertEqual(_warnings(notes), ())


class TowerCraneUnitTests(unittest.TestCase):
    def test_hook_reads_no_unit_as_feet_and_takes_ft_or_m(self):
        self.assertEqual(_spec("[crane hook=40]").hook_rope_ft, 40.0)
        self.assertEqual(_spec("[crane hook=40ft]").hook_rope_ft, 40.0)
        self.assertEqual(_spec("[crane hook=40 ft]").hook_rope_ft, 40.0)
        self.assertEqual(_spec("[crane hook=12.192m]").hook_rope_ft, 40.0)
        for notes in ("[crane hook=40]", "[crane hook=40ft]", "[crane hook=12.192m]"):
            self.assertEqual(_warnings(notes), ())

    def test_hookheight_reads_no_unit_as_feet_and_takes_ft_or_m(self):
        longest = CLASSIC.max_hook_rope_ft(25)
        for notes in (
            "[crane hookheight=10]",
            "[crane hookheight=10ft]",
            "[crane hookheight=3.048m]",
        ):
            with self.subTest(notes=notes):
                self.assertAlmostEqual(
                    _spec(notes).hook_rope_ft, longest - 10.0, places=3
                )
                self.assertEqual(_warnings(notes), ())

    def test_sections_keys_count_sections_without_a_unit(self):
        self.assertEqual(_spec("[crane mast=30]").mast, 30)
        self.assertEqual(_spec("[crane mast=150ft]").mast, 30)
        # A length is the real reach: 45 m (147.6 ft) is nearest 29 sections'
        # mast top (146.6 ft), 50 m (164.0 ft) nearest 24 sections' jib tip.
        self.assertEqual(_spec("[crane mast=45m]").mast, 29)
        self.assertEqual(_spec("[crane jib=120ft]").jib, 18)
        self.assertEqual(_spec("[crane jib=50m]").jib, 24)
        self.assertEqual(_spec("[crane counterjib=10m]").counterjib, 5)
        self.assertEqual(_spec("[crane counterjib=31ft]").counterjib, 5)

    def test_trolley_takes_a_percentage_of_the_travel_or_feet_from_the_mast(self):
        low, high = CLASSIC.trolley_travel_ft(18)
        self.assertAlmostEqual(
            _spec("[crane trolley=50%]").trolley_ft, (low + high) / 2, places=3
        )
        self.assertEqual(_warnings("[crane trolley=50%]"), ())
        self.assertEqual(_spec("[crane trolley=60]").trolley_ft, 60.0)
        self.assertEqual(_spec("[crane trolley=60ft]").trolley_ft, 60.0)
        self.assertEqual(_spec("[crane trolley=18.288m]").trolley_ft, 60.0)
        for notes in ("[crane trolley=60]", "[crane trolley=18.288m]"):
            self.assertEqual(_warnings(notes), ())

    def test_other_units_are_refused_with_a_warning_in_feet(self):
        for notes in ("[crane hook=40in]", "[crane hook=40']", "[crane hook=40cm]"):
            with self.subTest(notes=notes):
                self.assertEqual(_spec(notes), _spec("[crane]"))
                (warning,) = _warnings(notes)
                self.assertIn("a length in feet", warning)
                self.assertIn("using 12.4 ft", warning)


class TowerCraneSectionTests(unittest.TestCase):
    def test_limits_are_inclusive_and_outside_them_the_default_is_used(self):
        for key, low, high, default in (
            ("mast", 1, 80, 25),
            ("jib", 4, 40, 18),
            ("counterjib", 2, 12, 7),
        ):
            with self.subTest(key=key):
                self.assertEqual(getattr(_spec(f"[crane {key}={low}]"), key), low)
                self.assertEqual(getattr(_spec(f"[crane {key}={high}]"), key), high)
                for outside in (low - 1, high + 1):
                    notes = f"[crane {key}={outside}]"
                    self.assertEqual(getattr(_spec(notes), key), default)
                    self.assertEqual(len(_warnings(notes)), 1)
                    self.assertIn(f"{key}={outside}", _warnings(notes)[0])

    def test_a_count_with_a_decimal_is_refused(self):
        notes = "[crane mast=30.5]"
        self.assertEqual(_spec(notes), _spec("[crane]"))
        self.assertIn("a whole number of sections", _warnings(notes)[0])
        self.assertIn("ft or m", _warnings(notes)[0])


class TowerCraneTrolleyTests(unittest.TestCase):
    def test_a_fraction_runs_along_the_travel_of_the_chosen_jib(self):
        for jib in (4, 18, 40):
            low, high = CLASSIC.trolley_travel_ft(jib)
            self.assertLess(low, high)
            self.assertAlmostEqual(
                _spec(f"[crane jib={jib} trolley=0%]").trolley_ft, low, places=3
            )
            self.assertAlmostEqual(
                _spec(f"[crane jib={jib} trolley=100%]").trolley_ft, high, places=3
            )

    def test_a_distance_is_measured_from_the_mast_and_clamped_to_the_travel(self):
        low, high = CLASSIC.trolley_travel_ft(18)
        for text, expected in (("5", low), ("2m", low), ("400", high), ("200m", high)):
            notes = f"[crane trolley={text}]"
            with self.subTest(notes=notes):
                self.assertAlmostEqual(_spec(notes).trolley_ft, expected, places=3)
                (warning,) = _warnings(notes)
                self.assertIn("outside its travel", warning)
                self.assertIn(f"({low:.1f} ft to {high:.1f} ft from the mast)", warning)

    def test_a_plain_number_is_feet_even_when_it_is_one_or_less(self):
        low, _high = CLASSIC.trolley_travel_ft(18)
        for text in ("0.7", "1", "0"):
            notes = f"[crane trolley={text}]"
            with self.subTest(notes=notes):
                self.assertAlmostEqual(_spec(notes).trolley_ft, low, places=3)
                self.assertIn("outside its travel", _warnings(notes)[0])

    def test_a_percentage_above_100_clamps_to_the_jib_tip_with_a_warning(self):
        _low, high = CLASSIC.trolley_travel_ft(18)
        notes = "[crane trolley=150%]"
        self.assertAlmostEqual(_spec(notes).trolley_ft, high, places=3)
        (warning,) = _warnings(notes)
        self.assertIn("a trolley position of 150% is outside 0% to 100%", warning)

    def test_an_unreadable_trolley_value_uses_the_default_percentage(self):
        for text in ("half", "-5%", "5%ft", "60in"):
            notes = f"[crane trolley={text}]"
            with self.subTest(notes=notes):
                self.assertEqual(_spec(notes), _spec("[crane]"))
                (warning,) = _warnings(notes)
                self.assertIn("a percentage, or a distance in feet", warning)
                self.assertIn("using 79%", warning)

    def test_a_longer_jib_carries_the_default_trolley_further_out(self):
        self.assertGreater(
            _spec("[crane jib=30]").trolley_ft, _spec("[crane jib=18]").trolley_ft
        )


class TowerCraneHookTests(unittest.TestCase):
    def test_a_rope_shorter_than_the_minimum_uses_the_default(self):
        self.assertEqual(_spec("[crane hook=3]").hook_rope_ft, 3.0)
        notes = "[crane hook=2]"
        self.assertEqual(_spec(notes), _spec("[crane]"))
        self.assertIn("outside 3 ft or more; using 12.4 ft", _warnings(notes)[0])

    def test_hookheight_is_measured_up_from_the_footing(self):
        for mast in (5, 25, 60):
            longest = CLASSIC.max_hook_rope_ft(mast)
            spec = _spec(f"[crane mast={mast} hookheight=10]")
            self.assertAlmostEqual(spec.hook_rope_ft, longest - 10.0, places=3)
            self.assertAlmostEqual(
                _spec(f"[crane mast={mast} hookheight=0]").hook_rope_ft,
                longest,
                places=3,
            )

    def test_the_same_rope_hangs_higher_under_a_taller_mast(self):
        low = _spec("[crane mast=10 hook=15]")
        tall = _spec("[crane mast=40 hook=15]")
        self.assertEqual(low.hook_rope_ft, tall.hook_rope_ft)
        self.assertAlmostEqual(
            CLASSIC.hoist_top_ft(40) - CLASSIC.hoist_top_ft(10),
            30 * CLASSIC.mast_pitch_ft,
        )

    def test_a_rope_longer_than_the_crane_rests_the_hook_on_the_footing(self):
        notes = "[crane mast=3 hook=500]"
        longest = CLASSIC.max_hook_rope_ft(3)
        self.assertAlmostEqual(_spec(notes).hook_rope_ft, longest, places=3)
        (warning,) = _warnings(notes)
        self.assertIn("a hook rope of 500.0 ft is longer", warning)
        self.assertIn(f"({longest:.1f} ft)", warning)
        self.assertIn("rests at the footing", warning)

    def test_a_hook_height_above_the_jib_raises_the_hook_fully(self):
        notes = "[crane hookheight=500]"
        self.assertEqual(_spec(notes).hook_rope_ft, CLASSIC.min_hook_rope_ft)
        highest = CLASSIC.max_hook_rope_ft(25) - CLASSIC.min_hook_rope_ft
        self.assertIn(
            f"a hook height of 500.0 ft is above the highest hook position "
            f"({highest:.1f} ft)",
            _warnings(notes)[0],
        )

    def test_a_hook_height_just_below_the_jib_is_not_called_above_it(self):
        # 138 ft is below the jib (about 146 ft at mast=25) but above the highest
        # hook position, so the hook is raised fully without claiming otherwise.
        notes = "[crane hookheight=138]"
        self.assertEqual(_spec(notes).hook_rope_ft, CLASSIC.min_hook_rope_ft)
        (warning,) = _warnings(notes)
        self.assertNotIn("above the jib", warning)
        self.assertIn("highest hook position", warning)

    def test_hookheight_wins_over_hook(self):
        notes = "[crane hook=10 hookheight=10]"
        self.assertEqual(_spec(notes), _spec("[crane hookheight=10]"))
        self.assertEqual(
            _warnings(notes),
            ("[crane]: hook and hookheight are both given; hookheight is used.",),
        )

    def test_the_shortest_mast_still_takes_the_default_rope(self):
        self.assertGreater(CLASSIC.max_hook_rope_ft(1), CLASSIC.default_hook_rope_ft)
        self.assertEqual(_warnings("[crane mast=1]"), ())


class TowerCraneSectionNoteTests(unittest.TestCase):
    def test_a_length_reports_the_whole_sections_it_became(self):
        tag = resolve_tower_crane("[crane mast=150ft]", CATALOG)
        self.assertEqual(tag.spec.mast, 30)
        self.assertEqual(
            tag.notes,
            ("[crane]: mast=150ft → 30 sections (151.6 ft reach).",),
        )
        self.assertEqual(tag.warnings, ())

    def test_each_length_key_gets_its_own_note_in_feet(self):
        tag = resolve_tower_crane("[crane mast=45m jib=120ft counterjib=31ft]", CATALOG)
        self.assertEqual(
            tag.notes,
            (
                "[crane]: mast=45m → 29 sections (146.6 ft reach).",
                "[crane]: jib=120ft → 18 sections (121.9 ft reach).",
                "[crane]: counterjib=31ft → 5 sections (31.1 ft).",
            ),
        )

    def test_a_length_is_the_real_reach_and_picks_the_closest_count(self):
        tag = resolve_tower_crane("[crane jib=40m]", CATALOG)
        self.assertEqual(tag.spec.jib, 19)
        self.assertEqual(
            tag.notes, ("[crane]: jib=40m → 19 sections (128.5 ft reach).",)
        )

        # The note's reach is the drawn jib tip and the mast top above the footing,
        # for every model; a length nearest a count outside the model's limits
        # falls back to its default.
        def nearest(count_range, reach, feet):
            return min(
                range(1, count_range[1] + 30), key=lambda n: abs(reach(n) - feet)
            )

        for model in CATALOG.models:
            prefix = f"model={model.id} "
            top = lambda n, m=model: (m.mast_base_m + n * m.mast_pitch_m) / 0.3048
            for feet in (30.0, 75.0, 131.2, 200.0):
                with self.subTest(model=model.id, jib=feet):
                    best = nearest(model.jib_range, model.jib_tip_ft, feet)
                    low, high = model.jib_range
                    expected = best if low <= best <= high else model.default_jib
                    self.assertEqual(
                        _spec(f"[crane {prefix}jib={feet}ft]").jib, expected
                    )
                with self.subTest(model=model.id, mast=feet):
                    best = nearest(model.mast_range, top, feet)
                    self.assertTrue(model.mast_range[0] <= best <= model.mast_range[1])
                    self.assertEqual(_spec(f"[crane {prefix}mast={feet}ft]").mast, best)
                    note = resolve_tower_crane(
                        f"[crane {prefix}mast={feet}ft]", CATALOG
                    ).notes[0]
                    self.assertIn(f"({top(best):.1f} ft reach)", note)
        self.assertEqual(_spec("[crane model=liebherr jib=30ft]").jib, 32)
        self.assertIn(
            "outside 8 to 64 sections", _warnings("[crane model=liebherr jib=30ft]")[0]
        )

    def test_rounding_goes_to_the_nearest_whole_section(self):
        pitch = CLASSIC.mast_pitch_ft
        base = CLASSIC.mast_base_m / 0.3048
        self.assertEqual(_spec(f"[crane mast={base + pitch * 30.49:.3f}ft]").mast, 30)
        self.assertEqual(_spec(f"[crane mast={base + pitch * 30.51:.3f}ft]").mast, 31)

    def test_counts_and_rejected_lengths_have_no_note(self):
        for notes in ("[crane]", "[crane mast=30]", "[crane mast=1000ft]", ""):
            with self.subTest(notes=notes):
                self.assertEqual(resolve_tower_crane(notes, CATALOG).notes, ())
        self.assertEqual(len(_warnings("[crane mast=1000ft]")), 1)


class TowerCraneModelKeyTests(unittest.TestCase):
    def test_the_shipped_models_are_classic_then_liebherr(self):
        self.assertEqual(CATALOG.ids, ("classic", "liebherr"))
        self.assertIs(CATALOG.default, CLASSIC)
        self.assertEqual(LIEBHERR.label, "Liebherr")

    def test_a_tag_without_a_model_is_the_first_model(self):
        self.assertEqual(_spec("[crane]").model, "classic")
        self.assertEqual(_spec("[crane model=classic]"), _spec("[crane]"))

    def test_the_liebherr_defaults_come_from_its_kit(self):
        tag = resolve_tower_crane("[crane model=liebherr]", CATALOG)
        self.assertEqual(tag.warnings, ())
        self.assertEqual(
            tag.spec,
            TowerCraneSpec(
                mast=19,
                jib=32,
                counterjib=9,
                trolley_ft=68.492,
                hook_rope_ft=31.0,
                model="liebherr",
            ),
        )
        kit = tower_crane_kit("liebherr").metadata
        self.assertEqual(tag.spec.mast, kit["mast"]["default"])
        self.assertEqual(tag.spec.jib, kit["jib"]["default"])
        self.assertEqual(tag.spec.counterjib, kit["counterjib"]["default"])
        self.assertEqual(tag.spec.hook_rope_ft, kit["hook"]["default_rope_ft"])
        low, high = LIEBHERR.trolley_travel_ft(32)
        self.assertAlmostEqual(
            tag.spec.trolley_ft,
            low + kit["trolley"]["default_fraction"] * (high - low),
            places=3,
        )

    def test_the_model_name_ignores_case_and_quotes(self):
        for text in ("Liebherr", "LIEBHERR", '"liebherr"'):
            with self.subTest(text=text):
                self.assertEqual(
                    _spec(f"[crane model={text}]"), _spec("[crane model=liebherr]")
                )

    def test_an_unknown_model_warns_and_uses_the_first_model(self):
        notes = "[crane model=potain mast=30]"
        self.assertEqual(_spec(notes), _spec("[crane mast=30]"))
        self.assertEqual(
            _warnings(notes),
            ("[crane]: model=potain is not one of classic, liebherr; using classic.",),
        )

    def test_lengths_turn_into_sections_of_the_chosen_model(self):
        tag = resolve_tower_crane("[crane model=liebherr jib=50m]", CATALOG)
        self.assertEqual(tag.spec.jib, 38)
        self.assertEqual(
            tag.notes, ("[crane]: jib=50m → 38 sections (163.9 ft reach).",)
        )
        self.assertEqual(_spec("[crane jib=50m]").jib, 24)
        self.assertEqual(_spec("[crane model=liebherr counterjib=10m]").counterjib, 12)

    def test_limits_and_their_warning_come_from_the_chosen_model(self):
        notes = "[crane model=liebherr mast=2]"
        self.assertEqual(_spec(notes).mast, 19)
        self.assertEqual(
            _warnings(notes),
            ("[crane]: mast=2 is outside 4 to 75 sections; using 19.",),
        )
        self.assertEqual(_spec("[crane mast=2]").mast, 2)
        self.assertEqual(_spec("[crane model=liebherr jib=64]").jib, 64)
        self.assertEqual(_spec("[crane model=liebherr counterjib=24]").counterjib, 24)

    def test_the_model_key_is_listed_with_the_others(self):
        (warning,) = _warnings("[crane colour=red]")
        self.assertIn(
            "(keys: mast, jib, counterjib, trolley, hook, hookheight, model)", warning
        )

    def test_the_schema_reads_each_models_pitches_and_reach(self):
        for model in CATALOG.models:
            kit = tower_crane_kit(model.id).metadata
            keys = {
                k.name: k for k in crane.tower_crane_schema(model, CATALOG.ids).keys
            }
            with self.subTest(model=model.id):
                self.assertAlmostEqual(
                    keys["mast"].kind.pitch_ft, kit["mast"]["pitch"] * FEET_PER_METRE
                )
                self.assertAlmostEqual(
                    keys["jib"].kind.pitch_ft, kit["jib"]["pitch"] * FEET_PER_METRE
                )
                self.assertAlmostEqual(
                    keys["counterjib"].kind.pitch_ft,
                    kit["counterjib"]["pitch"] * FEET_PER_METRE,
                )
                self.assertAlmostEqual(
                    keys["mast"].kind.reach_base_ft,
                    kit["mast"]["base_y"] * FEET_PER_METRE,
                )
                jib = kit["jib"]
                self.assertAlmostEqual(
                    keys["jib"].kind.reach_base_ft,
                    (jib["first_bay_x"] - jib["pitch"] + jib["tip_length"])
                    * FEET_PER_METRE,
                )
                self.assertEqual(
                    (keys["mast"].minimum, keys["mast"].maximum),
                    (kit["mast"]["min"], kit["mast"]["max"]),
                )

    def test_without_any_model_a_tag_shows_no_crane(self):
        empty = TowerCraneCatalog(())
        tag = resolve_tower_crane("[crane mast=3]", empty)
        self.assertTrue(tag.present)
        self.assertIsNone(tag.spec)
        self.assertIsNone(default_tower_crane_spec(empty))


class TowerCraneModelTests(unittest.TestCase):
    def _kit(self):
        return copy.deepcopy(tower_crane_kit("classic").metadata)

    def test_a_model_reads_every_constant_from_the_kit(self):
        self.assertEqual(TowerCraneModel.from_kit_metadata(self._kit()), CLASSIC)
        self.assertEqual(CLASSIC.mast_range, (1, 80))
        self.assertEqual(CLASSIC.hoist_top_above_mast_m, 5.4831)

    def test_incomplete_or_inconsistent_metadata_is_refused(self):
        missing = self._kit()
        del missing["trolley"]["travel_start"]
        bad_id = self._kit()
        bad_id["model"]["id"] = "Big Crane"
        bad_default = self._kit()
        bad_default["mast"]["default"] = 90
        for kit, message in (
            (missing, "incomplete"),
            (bad_id, "not valid"),
            (bad_default, "outside 1 to 80"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    TowerCraneModel.from_kit_metadata(kit)

    def test_a_catalog_refuses_two_models_with_one_id(self):
        with self.assertRaisesRegex(ValueError, "repeat"):
            TowerCraneCatalog((CLASSIC, CLASSIC))
        self.assertIsNone(CATALOG.get("missing"))


class TowerCraneSpecIdentityTests(unittest.TestCase):
    def test_specs_are_hashable_values_rounded_to_a_thousandth_of_a_foot(self):
        first = _spec("[crane hook=10.0004]")
        second = _spec("[crane hook=10ft]")
        self.assertEqual(first, second)
        self.assertEqual(hash(first), hash(second))
        self.assertEqual(len({first, second, _spec("[crane hook=10.001]")}), 2)
        self.assertEqual(_spec("[crane hook=3.048m]"), second)
        self.assertNotEqual(
            _spec("[crane hook=10]"), _spec("[crane model=liebherr hook=10]")
        )

    def test_registry_warnings_travel_with_the_crane_tag(self):
        self.assertEqual(len(_warnings("[cran mast=3]")), 1)
        self.assertEqual(len(_warnings("[crane mast=3")), 1)
        tag = resolve_tower_crane("[crane] [crane mast=2]", CATALOG)
        self.assertEqual(tag.spec, _spec("[crane]"))
        self.assertEqual(len(tag.warnings), 1)

    def test_resolution_is_cached_per_notes_text_and_catalog(self):
        first = resolve_tower_crane("[crane mast=7]", CATALOG)
        self.assertIs(resolve_tower_crane("[crane mast=7]", CATALOG), first)

    def test_any_crane_tag_counts_whatever_its_arguments(self):
        self.assertTrue(has_tower_crane_tag("[crane]"))
        self.assertTrue(has_tower_crane_tag("Base [crane mast=bad colour=red]"))
        self.assertFalse(has_tower_crane_tag("[crane mast=3"))


if __name__ == "__main__":
    unittest.main()
