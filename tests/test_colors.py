import unittest

from skypixel.clients import hypixel
from skypixel.domain import colorcompare, colors
from tests import support


class ColorTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(hypixel.initialize, support.ITEMS)

    def test_optional_catalog_fields_and_invalid_dyes_do_not_break_startup(self):
        hypixel.initialize(
            [
                {"id": "EMPTY", "material": None, "description": None},
                {
                    "id": "DYE_SHORT",
                    "description": "Combinable in Anvil Changes the color of an armor piece to #123!",
                },
                {
                    "id": "DYE_VALID",
                    "description": "Combinable in Anvil Changes the color of an armor piece to #123456!",
                },
            ]
        )
        self.assertNotIn("DYE_SHORT", colors.ARMOR_COLORS["other"])
        self.assertEqual(
            colors.ARMOR_COLORS["other"]["DYE_VALID"],
            colorcompare.hex_to_lab("123456"),
        )

    def test_reloading_the_catalog_invalidates_color_matches(self):
        colors.get_top_5("helmet", "010203")
        hypixel.initialize(
            [
                {
                    "id": "NEW",
                    "name": "New Helmet",
                    "material": "LEATHER_HELMET",
                    "color": "1,2,3",
                }
            ]
        )
        matches = colors.get_top_5("helmet", "010203")
        self.assertEqual(next(iter(matches)), "New Helmet")
        self.assertEqual(matches["New Helmet"], 0)

    def test_lab_white_and_black_match_the_reference_endpoints(self):
        for rgb, expected in (((0, 0, 0), (0, 0, 0)), ((255, 255, 255), (100, 0, 0))):
            with self.subTest(rgb=rgb):
                for value, reference in zip(
                    colorcompare.rgb_to_lab(rgb), expected, strict=True
                ):
                    self.assertAlmostEqual(value, reference, delta=0.02)

    def test_color_distances_are_symmetric_and_zero_for_identical_colors(self):
        first = colorcompare.hex_to_lab("123456")
        second = colorcompare.hex_to_lab("ABCDEF")
        for distance in (
            colorcompare.compare_delta_cie,
            colorcompare.compare_delta_e_2000,
        ):
            with self.subTest(distance=distance.__name__):
                self.assertEqual(distance(first, first), 0)
                self.assertAlmostEqual(distance(first, second), distance(second, first))
