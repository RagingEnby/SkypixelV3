import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from skypixel import subscriptions
from skypixel.settings import ConfigurationError

VALID = """
[[version]]
channel = 1
ping = "<@&10>"

[[fire_sale]]
channel = 2
ping = "use code rail :)"

[[rank.youtube]]
channel = 3
ping = ""

[[rank.special]]
channel = 4
ping = "<@&11>"
"""


def parse(text: str) -> subscriptions.Subscriptions:
    return subscriptions.parse(tomllib.loads(text), "test.toml")


class LoadTests(unittest.TestCase):
    def write(self, text: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "subscriptions.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_load_reads_channels_and_pings(self):
        loaded = subscriptions.load(self.write(VALID))
        self.assertEqual(loaded.version, {1: "<@&10>"})
        self.assertEqual(loaded.fire_sale, {2: "use code rail :)"})
        self.assertEqual(loaded.motd, {})
        self.assertEqual(loaded.rank, {"youtube": {3: ""}, "special": {4: "<@&11>"}})

    def test_the_tracked_file_is_valid(self):
        loaded = subscriptions.load(subscriptions.DEFAULT_PATH)
        self.assertIn("special", loaded.rank)
        self.assertTrue(loaded.version)

    def test_environment_variable_overrides_the_path(self):
        path = self.write(VALID)
        with patch.dict(os.environ, {"SKYPIXEL_SUBSCRIPTIONS": str(path)}):
            self.assertEqual(subscriptions.configured_path(), path)
            self.assertEqual(subscriptions.load().version, {1: "<@&10>"})
        with patch.dict(os.environ, clear=True):
            self.assertEqual(
                subscriptions.configured_path(), subscriptions.DEFAULT_PATH
            )

    def test_current_loads_once_and_install_replaces_it(self):
        path = self.write(VALID)
        with (
            patch.object(subscriptions, "_current", None),
            patch.dict(os.environ, {"SKYPIXEL_SUBSCRIPTIONS": str(path)}),
        ):
            first = subscriptions.current()
            self.assertIs(subscriptions.current(), first)
            replacement = subscriptions.Subscriptions()
            subscriptions.install(replacement)
            self.assertIs(subscriptions.current(), replacement)

    def test_missing_file_names_the_path_and_variable(self):
        path = Path(tempfile.gettempdir()) / "skypixel-missing-subscriptions.toml"
        with self.assertRaisesRegex(ConfigurationError, "SKYPIXEL_SUBSCRIPTIONS"):
            subscriptions.load(path)

    def test_invalid_toml_is_a_configuration_error(self):
        with self.assertRaisesRegex(ConfigurationError, "not valid TOML"):
            subscriptions.load(self.write("[[version]\n"))


class ValidationTests(unittest.TestCase):
    def assertInvalid(self, text: str, message: str):
        with self.assertRaises(subscriptions.SubscriptionError) as caught:
            parse(text)
        self.assertIn(message, str(caught.exception))
        self.assertIn("test.toml", str(caught.exception))

    def test_channel_id_must_be_an_integer(self):
        self.assertInvalid(
            '[[version]]\nchannel = "1"\nping = ""\n[[rank.special]]\n'
            'channel = 4\nping = ""\n',
            "version[0]: channel must be a positive integer channel ID, got '1'",
        )

    def test_channel_id_must_not_be_a_boolean_or_float(self):
        for value in ("true", "1.0", "0"):
            with self.subTest(value=value):
                self.assertInvalid(
                    f'[[zone]]\nchannel = {value}\nping = ""\n', "zone[0]: channel"
                )

    def test_ping_must_be_a_string(self):
        self.assertInvalid(
            "[[rank.special]]\nchannel = 4\nping = 5\n",
            "rank.special[0] (channel 4): ping must be a string",
        )

    def test_missing_ping_is_an_error(self):
        self.assertInvalid(
            "[[motd]]\nchannel = 4\n", "motd[0] (channel 4): ping must be a string"
        )

    def test_rank_keys_must_be_known(self):
        self.assertInvalid(
            '[[rank.admin]]\nchannel = 4\nping = ""\n', "Unknown rank keys: admin"
        )

    def test_rank_special_is_required(self):
        self.assertInvalid(
            '[[rank.youtube]]\nchannel = 4\nping = ""\n', "rank.special is missing"
        )

    def test_unknown_sections_and_keys_are_errors(self):
        self.assertInvalid('[[versions]]\nchannel = 1\nping = ""\n', "versions")
        self.assertInvalid(
            '[[job]]\nchannel = 1\nping = ""\nrole = 2\n', "job[0] has unknown keys"
        )

    def test_section_must_be_a_list_of_entries(self):
        self.assertInvalid("[alpha]\nchannel = 1\n", "alpha must be a list")

    def test_duplicate_channel_in_one_section_is_an_error(self):
        self.assertInvalid(
            '[[job]]\nchannel = 1\nping = "a"\n[[job]]\nchannel = 1\nping = "b"\n',
            "job[1]: channel 1 is listed twice",
        )
