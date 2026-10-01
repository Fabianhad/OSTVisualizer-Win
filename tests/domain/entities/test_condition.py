import unittest
from dataclasses import fields
from ost_visualizer.domain.entities.condition import Condition


class ConditionConditionBehaviorTests(unittest.TestCase):
    def test_condition_entity_does_not_expose_label_style_fields(self):
        condition_fields = {field.name for field in fields(Condition)}
        self.assertFalse(
            {
                "name_font_name",
                "name_font_color",
                "name_font_size",
                "name_font_bold",
                "name_font_italic",
                "name_font_underline",
            }
            & condition_fields
        )
