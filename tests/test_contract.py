import json
import unittest
from pathlib import Path

from tests.support import colors, command_schema, utils
from cogs import itemdb, ranktracker
from cogs.alphatracker import flatten_status
from cogs.jobtracker import Job


class ContractTests(unittest.TestCase):
    def test_discord_command_schema(self):
        expected = json.loads(
            (Path(__file__).parent / "fixtures" / "commands.json").read_text()
        )
        self.assertEqual(command_schema(), expected)

    def test_item_queries(self):
        self.assertEqual(
            itemdb.search_souls_query({"owner": None}),
            {
                "itemId": "CAKE_SOUL",
                "extraAttributes.captured_player": {"$exists": True},
            },
        )
        self.assertEqual(itemdb.make_rank_regex("NON"), {"$not": {"$regex": " "}})
        self.assertEqual(
            itemdb.make_playername_regex("A.B"),
            {
                "$regex": r"(§7| )A\.B(§[0-9a-fk-or])*$",
                "$options": "i",
            },
        )

    def test_display_helpers(self):
        self.assertEqual(utils.numerize(1234567), "1.23M")
        self.assertEqual(utils.commaize(1234567), "1,234,567")
        self.assertEqual(
            utils.remove_color_codes("§c[ADMIN] &aPlayer"), "[ADMIN] Player"
        )
        self.assertEqual(ranktracker.format_rank("pig_plus_plus_plus"), "[PIG+++]")
        self.assertEqual(ranktracker.format_rank("staff"), "[ዞ]")
        self.assertEqual(utils.normalize_timestamp(1700000000000), 1700000000)
        self.assertEqual(utils.timestamp_to_unix("1700000000000L"), 1700000000000)

    def test_exotic_rules(self):
        examples = [
            ("TEST_HELMET", "010203", None),
            ("TEST_HELMET", "a06540", "bleached"),
            ("TEST_HELMET", "1F0030", "crystal"),
            ("TEST_HELMET", "330066", "fairy"),
            ("TEST_HELMET", "070008", "spook"),
            ("TEST_HELMET", "123456", "exotic"),
            ("SHARK_SCALE", "FFDC51", "glitched"),
            ("VELVET_TOP_HAT", "123456", None),
        ]
        for item_id, color, expected in examples:
            with self.subTest(item_id=item_id, color=color):
                self.assertEqual(colors.get_exotic_type(item_id, color), expected)
        self.assertIsNone(
            colors.get_exotic_type("TEST_HELMET", "123456", {"dye_item": "DYE"})
        )

    def test_alpha_status_format(self):
        status = {
            "version": {"name": "1.8", "protocol": 47},
            "players": {"max": 100},
            "description": "Alpha",
        }
        self.assertEqual(
            flatten_status(status),
            {
                "MC Version": "1.8",
                "Version Protocol": 47,
                "Max Players": 100,
                "MOTD": "Alpha",
            },
        )

    def test_job_data_and_markdown(self):
        data = {
            "title": "Developer - Minecraft Project",
            "listingId": 42,
            "qualifications": ["Python"],
            "responsibilities": None,
            "weCanOffer": ["Remote"],
        }
        job = Job.from_dict(data)
        self.assertEqual(job.to_dict(), data)
        self.assertEqual(
            job.to_markdown(),
            "# Developer\n## Qualifications\n- Python\n## We Can Offer\n- Remote\n-# [Info](https://hypixel.net/jobs/#listing-42) | [Apply](https://hypixel.bamboohr.com/careers/42)",
        )
