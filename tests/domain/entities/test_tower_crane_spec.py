import unittest
from ost_visualizer.domain.entities import tower_crane_spec as crane
from ost_visualizer.domain.entities.tower_crane_spec import (
    TowerCraneSpec,
    resolve_tower_crane,
)

FEET_PER_METRE = 1 / 0.3048


def _spec(notes):
    return resolve_tower_crane(notes).spec


def _warnings(notes):
    return resolve_tower_crane(notes).warnings


class TowerCraneDefaultsTests(unittest.TestCase):
    def test_a_bare_tag_is_the_model_as_built_with_lengths_in_feet(self):
        tag = resolve_tower_crane("[crane]")
        self.assertTrue(tag.present)
        self.assertEqual(tag.warnings, ())
        self.assertEqual(
            tag.spec,
            TowerCraneSpec(
                mast=25, jib=18, counterjib=7, trolley_ft=95.297, hook_rope_ft=12.4
            ),
        )
        self.assertEqual(crane.DEFAULT_HOOK_ROPE_FT, 12.4)
        # 12.4 ft is the model's own hoist rope (about 3.77 m).
        self.assertAlmostEqual(crane.DEFAULT_HOOK_ROPE_FT / FEET_PER_METRE, 3.78, 2)

    def test_schema_defaults_and_ranges_are_shown_in_feet(self):
        keys = {key.name: key for key in crane.TOWER_CRANE_SCHEMA.keys}
        self.assertEqual(keys["hook"].default_text, "12.4 ft")
        self.assertEqual(keys["hook"].range_text, "3 ft or more")
        self.assertEqual(keys["hook"].minimum, 3.0)
        self.assertEqual(keys["hookheight"].range_text, "0 ft or more")
        self.assertEqual(keys["mast"].default_text, "25")
        self.assertEqual(keys["trolley"].default_text, "79%")
        self.assertEqual(crane.DEFAULT_TROLLEY_FRACTION, 0.79)
        self.assertEqual(_spec("[crane trolley=79%]"), _spec("[crane]"))
        self.assertAlmostEqual(keys["mast"].kind.pitch_ft, 1.52 * FEET_PER_METRE)
        self.assertAlmostEqual(keys["jib"].kind.pitch_ft, 1.9973 * FEET_PER_METRE)
        self.assertAlmostEqual(
            keys["counterjib"].kind.pitch_ft, 1.8973 * FEET_PER_METRE
        )

    def test_notes_without_the_tag_have_no_crane(self):
        for notes in ("", "crane", "(CRANE)", "[cranes]", "[tower crane]"):
            with self.subTest(notes=notes):
                tag = resolve_tower_crane(notes)
                self.assertFalse(tag.present)
                self.assertIsNone(tag.spec)
                self.assertEqual(tag.warnings, ())

    def test_the_proposed_example_parses(self):
        notes = "[crane mast=30 jib=19 counterjib=6 trolley=70% hook=40ft]"
        spec = _spec(notes)
        self.assertEqual((spec.mast, spec.jib, spec.counterjib), (30, 19, 6))
        self.assertEqual(spec.hook_rope_ft, 40.0)
        low, high = crane.trolley_travel_ft(19)
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
        longest = crane.max_hook_rope_ft(25)
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
        self.assertEqual(_spec("[crane mast=45m]").mast, 30)
        self.assertEqual(_spec("[crane jib=120ft]").jib, 18)
        self.assertEqual(_spec("[crane jib=50m]").jib, 25)
        self.assertEqual(_spec("[crane counterjib=10m]").counterjib, 5)
        self.assertEqual(_spec("[crane counterjib=31ft]").counterjib, 5)

    def test_trolley_takes_a_percentage_of_the_travel_or_feet_from_the_mast(self):
        low, high = crane.trolley_travel_ft(18)
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
            low, high = crane.trolley_travel_ft(jib)
            self.assertLess(low, high)
            self.assertAlmostEqual(
                _spec(f"[crane jib={jib} trolley=0%]").trolley_ft, low, places=3
            )
            self.assertAlmostEqual(
                _spec(f"[crane jib={jib} trolley=100%]").trolley_ft, high, places=3
            )

    def test_a_distance_is_measured_from_the_mast_and_clamped_to_the_travel(self):
        low, high = crane.trolley_travel_ft(18)
        for text, expected in (("5", low), ("2m", low), ("400", high), ("200m", high)):
            notes = f"[crane trolley={text}]"
            with self.subTest(notes=notes):
                self.assertAlmostEqual(_spec(notes).trolley_ft, expected, places=3)
                (warning,) = _warnings(notes)
                self.assertIn("outside its travel", warning)
                self.assertIn(f"({low:.1f} ft to {high:.1f} ft from the mast)", warning)

    def test_a_plain_number_is_feet_even_when_it_is_one_or_less(self):
        low, _high = crane.trolley_travel_ft(18)
        for text in ("0.7", "1", "0"):
            notes = f"[crane trolley={text}]"
            with self.subTest(notes=notes):
                self.assertAlmostEqual(_spec(notes).trolley_ft, low, places=3)
                self.assertIn("outside its travel", _warnings(notes)[0])

    def test_a_percentage_above_100_clamps_to_the_jib_tip_with_a_warning(self):
        _low, high = crane.trolley_travel_ft(18)
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
            longest = crane.max_hook_rope_ft(mast)
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
            crane.hoist_top_ft(40) - crane.hoist_top_ft(10), 30 * crane.MAST_PITCH_FT
        )

    def test_a_rope_longer_than_the_crane_rests_the_hook_on_the_footing(self):
        notes = "[crane mast=3 hook=500]"
        longest = crane.max_hook_rope_ft(3)
        self.assertAlmostEqual(_spec(notes).hook_rope_ft, longest, places=3)
        (warning,) = _warnings(notes)
        self.assertIn("a hook rope of 500.0 ft is longer", warning)
        self.assertIn(f"({longest:.1f} ft)", warning)
        self.assertIn("rests at the footing", warning)

    def test_a_hook_height_above_the_jib_raises_the_hook_fully(self):
        notes = "[crane hookheight=500]"
        self.assertEqual(_spec(notes).hook_rope_ft, crane.MIN_HOOK_ROPE_FT)
        self.assertIn("a hook height of 500.0 ft is above the jib", _warnings(notes)[0])

    def test_hookheight_wins_over_hook(self):
        notes = "[crane hook=10 hookheight=10]"
        self.assertEqual(_spec(notes), _spec("[crane hookheight=10]"))
        self.assertEqual(
            _warnings(notes),
            ("[crane]: hook and hookheight are both given; hookheight is used.",),
        )

    def test_the_shortest_mast_still_takes_the_default_rope(self):
        self.assertGreater(crane.max_hook_rope_ft(1), crane.DEFAULT_HOOK_ROPE_FT)
        self.assertEqual(_warnings("[crane mast=1]"), ())


class TowerCraneSectionNoteTests(unittest.TestCase):
    def test_a_length_reports_the_whole_sections_it_became(self):
        tag = resolve_tower_crane("[crane mast=150ft]")
        self.assertEqual(tag.spec.mast, 30)
        self.assertEqual(
            tag.notes, ("[crane]: mast=150ft \u2192 30 sections (149.6 ft).",)
        )
        self.assertEqual(tag.warnings, ())

    def test_each_length_key_gets_its_own_note_in_feet(self):
        tag = resolve_tower_crane("[crane mast=45m jib=120ft counterjib=31ft]")
        self.assertEqual(
            tag.notes,
            (
                "[crane]: mast=45m \u2192 30 sections (149.6 ft).",
                "[crane]: jib=120ft \u2192 18 sections (118.0 ft).",
                "[crane]: counterjib=31ft \u2192 5 sections (31.1 ft).",
            ),
        )

    def test_rounding_goes_to_the_nearest_whole_section(self):
        pitch = crane.MAST_PITCH_FT
        self.assertEqual(_spec(f"[crane mast={pitch * 30.49:.3f}ft]").mast, 30)
        self.assertEqual(_spec(f"[crane mast={pitch * 30.51:.3f}ft]").mast, 31)

    def test_counts_and_rejected_lengths_have_no_note(self):
        for notes in ("[crane]", "[crane mast=30]", "[crane mast=1000ft]", ""):
            with self.subTest(notes=notes):
                self.assertEqual(resolve_tower_crane(notes).notes, ())
        self.assertEqual(len(_warnings("[crane mast=1000ft]")), 1)


class TowerCraneSpecIdentityTests(unittest.TestCase):
    def test_specs_are_hashable_values_rounded_to_a_thousandth_of_a_foot(self):
        first = _spec("[crane hook=10.0004]")
        second = _spec("[crane hook=10ft]")
        self.assertEqual(first, second)
        self.assertEqual(hash(first), hash(second))
        self.assertEqual(len({first, second, _spec("[crane hook=10.001]")}), 2)
        self.assertEqual(_spec("[crane hook=3.048m]"), second)

    def test_registry_warnings_travel_with_the_crane_tag(self):
        self.assertEqual(len(_warnings("[cran mast=3]")), 1)
        self.assertEqual(len(_warnings("[crane mast=3")), 1)
        tag = resolve_tower_crane("[crane] [crane mast=2]")
        self.assertEqual(tag.spec, _spec("[crane]"))
        self.assertEqual(len(tag.warnings), 1)

    def test_resolution_is_cached_per_notes_text(self):
        first = resolve_tower_crane("[crane mast=7]")
        self.assertIs(resolve_tower_crane("[crane mast=7]"), first)


if __name__ == "__main__":
    unittest.main()
