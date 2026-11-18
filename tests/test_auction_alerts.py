import annotationlib
import inspect
import json
import os
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import disnake

import tests.support as support
from skypixel import alerts
from skypixel.domain.nbt import NBTData
from skypixel.domain.types import JSON
from skypixel.trackers import auctionhouse, ranktracker

FIXTURE = Path(__file__).parent / "fixtures" / "auction_alerts.json"
SELLER = "a" * 32
POI = "b" * 32


def auction(**fields: JSON) -> auctionhouse.Auction:
    return {
        "uuid": "auction-uuid",
        "auctioneer": SELLER,
        "item_name": "Test Item",
        "starting_bid": 1_000,
        "bin": True,
        "tier": "EPIC",
        "end": 1_700_000_000_000,
        **fields,
    }


def item(
    extra: dict[str, NBTData] | None = None,
    color: int | None = None,
    **fields: NBTData,
) -> auctionhouse.Item:
    tag: auctionhouse.Item = {
        "ExtraAttributes": {"uuid": "item-uuid", "id": "TEST_HELMET", **(extra or {})}
    }
    if color is not None:
        tag["display"] = {"color": color}
    return {"tag": tag, **fields}


# One case per alert rule, plus cases that hit the branches inside a rule and
# one auction that matches several rules at once.
CASES: dict[str, tuple[auctionhouse.Auction, auctionhouse.Item]] = {
    "admin_spawned": (auction(), item({"originTag": "ITEM_MENU"})),
    "og_reforge": (auction(), item({"modifier": "forceful"})),
    "semi_og_reforge": (
        auction(category="accessories"),
        item({"modifier": "rich"}),
    ),
    "poi": (auction(auctioneer=POI), item()),
    "old_item": (
        auction(starting_bid=50_000_000),
        item({"timestamp": "1/1/19 12:00 PM"}),
    ),
    "seymour": (auction(), item({"id": "VELVET_TOP_HAT"}, color=0x123456)),
    "exotic_with_thread": (auction(), item(color=0)),
    "exotic_bleached": (auction(), item(color=0xFFFFFF)),
    "cake_soul_cheap_red": (
        auction(starting_bid=4_000_000),
        item({"id": "CAKE_SOUL", "cake_owner": "§bOwner"}, Damage=1),
    ),
    "cake_soul_auction_no_dye": (
        auction(bin=False, starting_bid=1),
        item({"id": "CAKE_SOUL"}),
    ),
    "editioned": (
        auction(),
        item(
            {
                "edition": 1234,
                "recipient_name": "§aSome_Player",
                "timestamp": 1_600_000_000_000,
            }
        ),
    ),
    "basket_edition": (auction(), item({"basket_edition": 7})),
    "several_rules": (
        auction(auctioneer=POI, category="accessories", starting_bid=10),
        item(
            {
                "originTag": "ITEM_COMMAND",
                "modifier": "odd",
                "timestamp": 1_500_000_000,
                "edition": 2,
            },
            color=0,
        ),
    ),
}

# One recorded alert send, as the fixture stores it.
type SentAlert = dict[str, object]

NOTIFY: inspect.Signature = inspect.signature(
    alerts.notify_to_channel, annotation_format=annotationlib.Format.FORWARDREF
)


def describe(args: tuple[object, ...], kwargs: Mapping[str, object]) -> SentAlert:
    """Return the destination, content, and embeds of one alert send."""
    bound = NOTIFY.bind(*args, **kwargs)
    bound.apply_defaults()
    options: dict[str, object] = dict(bound.arguments["kwargs"])
    for key, value in options.items():
        if isinstance(value, disnake.Embed):
            options[key] = value.to_dict()
    return {
        "channel_id": bound.arguments["channel_id"],
        "content": bound.arguments["content"],
        "kwargs": options,
    }


async def run_case(name: str) -> list[SentAlert]:
    cog = auctionhouse.AuctionTrackerCog(support.make_bot())
    case_auction, case_item = CASES[name]
    with (
        patch.object(alerts, "notify_to_channel", new_callable=AsyncMock) as notify,
        patch.object(
            auctionhouse.mojang,
            "get",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(name="Seller"),
        ),
        patch.object(
            ranktracker,
            "get_rankname",
            new_callable=AsyncMock,
            return_value="§c[ADMIN] Special",
        ),
        patch.object(ranktracker, "POI_UUIDS", {POI}),
    ):
        await cog.on_auction(case_auction, case_item)
    return sorted(
        (describe(call.args, call.kwargs) for call in notify.await_args_list),
        key=lambda sent: json.dumps(sent, sort_keys=True),
    )


class AuctionAlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_alert_sends_the_recorded_embed_and_destination(self) -> None:
        """Compare each alert with the output recorded before the rule table."""
        expected = json.loads(FIXTURE.read_text())
        self.assertEqual(set(expected), set(CASES))
        for name in CASES:
            with self.subTest(case=name):
                self.assertTrue(expected[name])
                self.assertEqual(await run_case(name), expected[name])


async def record() -> None:
    results = {name: await run_case(name) for name in CASES}
    FIXTURE.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__" and os.environ.get("RECORD_AUCTION_ALERTS"):
    import asyncio

    asyncio.run(record())
