"""Load the alert subscriptions: the channels that receive each alert.

The list lives in a TOML file so that adding or removing a subscriber server
does not need a code change. See config/subscriptions.toml for the format.
"""

import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args

import disnake

from skypixel.domain.types import SpecialRank
from skypixel.settings import ConfigurationError

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot

logger = logging.getLogger(__name__)

ENVIRONMENT_VARIABLE = "SKYPIXEL_SUBSCRIPTIONS"
DEFAULT_PATH = Path("config/subscriptions.toml")
# The rank tracker sends a rank without its own section to "special".
RANK_KEYS: frozenset[str] = frozenset((*get_args(SpecialRank), "special"))

type Channels = dict[int, str]


class SubscriptionError(ConfigurationError):
    pass


@dataclass(frozen=True)
class Subscriptions:
    version: Channels = field(default_factory=dict)
    motd: Channels = field(default_factory=dict)
    job: Channels = field(default_factory=dict)
    fire_sale: Channels = field(default_factory=dict)
    alpha: Channels = field(default_factory=dict)
    zone: Channels = field(default_factory=dict)
    rank: dict[str, Channels] = field(default_factory=dict)

    def sections(self) -> dict[str, Channels]:
        """Return every channel list by its name in the file, such as rank.staff."""
        result = {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name != "rank"
        }
        for rank, channels in self.rank.items():
            result[f"rank.{rank}"] = channels
        return result


FLAT_SECTIONS: tuple[str, ...] = tuple(
    item.name for item in fields(Subscriptions) if item.name != "rank"
)


def configured_path() -> Path:
    return Path(os.environ.get(ENVIRONMENT_VARIABLE, DEFAULT_PATH))


def _channels(entries: Any, where: str) -> Channels:
    if not isinstance(entries, list):
        raise SubscriptionError(
            f"{where} must be a list of [[{where}]] entries, not {type(entries).__name__}."
        )
    channels: Channels = {}
    for index, entry in enumerate(entries):
        name = f"{where}[{index}]"
        if not isinstance(entry, dict):
            raise SubscriptionError(f"{name} must be a table with channel and ping.")
        unknown = set(entry) - {"channel", "ping"}
        if unknown:
            raise SubscriptionError(
                f"{name} has unknown keys: {', '.join(sorted(unknown))}."
            )
        channel = entry.get("channel")
        if type(channel) is not int or channel <= 0:
            raise SubscriptionError(
                f"{name}: channel must be a positive integer channel ID, "
                f"got {channel!r}."
            )
        ping = entry.get("ping")
        if not isinstance(ping, str):
            raise SubscriptionError(
                f"{name} (channel {channel}): ping must be a string, got {ping!r}. "
                'Use ping = "" for no ping.'
            )
        if channel in channels:
            raise SubscriptionError(f"{name}: channel {channel} is listed twice.")
        channels[channel] = ping
    return channels


def parse(data: Mapping[str, Any], source: str = "subscriptions") -> Subscriptions:
    """Check the parsed TOML and return the subscriptions it lists."""
    try:
        unknown = set(data) - {*FLAT_SECTIONS, "rank"}
        if unknown:
            raise SubscriptionError(
                f"Unknown sections: {', '.join(sorted(unknown))}. "
                f"Use {', '.join((*FLAT_SECTIONS, 'rank'))}."
            )
        flat = {name: _channels(data.get(name, []), name) for name in FLAT_SECTIONS}
        ranks = data.get("rank", {})
        if not isinstance(ranks, dict):
            raise SubscriptionError("rank must be a table of [[rank.<rank>]] lists.")
        unknown = set(ranks) - RANK_KEYS
        if unknown:
            raise SubscriptionError(
                f"Unknown rank keys: {', '.join(sorted(unknown))}. "
                f"Use {', '.join(sorted(RANK_KEYS))}."
            )
        if "special" not in ranks:
            raise SubscriptionError(
                "rank.special is missing. Ranks without their own list use it."
            )
        rank = {key: _channels(value, f"rank.{key}") for key, value in ranks.items()}
    except SubscriptionError as error:
        raise SubscriptionError(f"{source}: {error}") from None
    return Subscriptions(**flat, rank=rank)


def load(path: Path | None = None) -> Subscriptions:
    path = configured_path() if path is None else path
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except FileNotFoundError:
        raise SubscriptionError(
            f"The subscriptions file {path} does not exist. "
            f"Set {ENVIRONMENT_VARIABLE} to its path."
        ) from None
    except tomllib.TOMLDecodeError as error:
        raise SubscriptionError(f"{path} is not valid TOML: {error}") from None
    return parse(data, str(path))


_current: Subscriptions | None = None


def install(subscriptions: Subscriptions) -> Subscriptions:
    global _current
    _current = subscriptions
    return subscriptions


def current() -> Subscriptions:
    """Return the loaded subscriptions, loading the configured file on first use."""
    if _current is None:
        return install(load())
    return _current


def channel_problems(bot: SkypixelBot, subscriptions: Subscriptions) -> list[str]:
    """Describe each subscribed channel the bot cannot find, view, or post to."""
    sections: dict[int, list[str]] = {}
    for section, channels in subscriptions.sections().items():
        for channel_id in channels:
            sections.setdefault(channel_id, []).append(section)
    problems = []
    for channel_id, names in sections.items():
        where = f"channel {channel_id} ({', '.join(names)})"
        channel = bot.get_channel(channel_id)
        if channel is None:
            problems.append(f"{where}: the bot cannot find it")
            continue
        if not isinstance(channel, disnake.abc.GuildChannel | disnake.Thread):
            problems.append(f"{where}: it is not a server channel")
            continue
        permissions = channel.permissions_for(channel.guild.me)
        missing = [
            label
            for label, allowed in (
                ("View Channel", permissions.view_channel),
                ("Send Messages", permissions.send_messages),
                ("Embed Links", permissions.embed_links),
            )
            if not allowed
        ]
        if missing:
            problems.append(f"{where} in {channel.guild}: missing {', '.join(missing)}")
    return problems


def check_channels(bot: SkypixelBot, subscriptions: Subscriptions | None = None):
    """Log a warning for each subscribed channel the bot cannot use."""
    for problem in channel_problems(bot, subscriptions or current()):
        logger.warning("Alert subscription problem: %s.", problem)
