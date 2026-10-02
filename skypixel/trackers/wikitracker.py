import logging
from typing import Any

import disnake
from disnake.ext import commands

from skypixel import constants
from skypixel import discord as utils
from skypixel.clients import http as asyncreqs
from skypixel.storage import json as datamanager
from skypixel.storage import mongo as mongodb
from skypixel.trackers.base import PollingCog

URL: str = "https://wiki.hypixel.net/api.php"
PARAMS: dict[str, str] = {
    "action": "query",
    "format": "json",
    "uselang": "user",
    "variant": "",
    "errorformat": "bc",
    "list": "recentchanges",
    "rcnamespace": "*",
    "rcprop": "|".join(
        [
            "comment",
            "flags",
            "ids",
            "loginfo",
            "parsedcomment",
            "redirect",
            "sha1",
            "sizes",
            "tags",
            "timestamp",
            "title",
            "user",
            "userid",
        ]
    ),
    "rctype": "|".join(["categorize", "edit", "external", "log", "new"]),
}
EDITOR_URL: str = "https://api.ragingenby.dev/wiki/user/{}"
EDITOR_CACHE: dict[str, dict[str, Any]] = {}
logger = logging.getLogger(__name__)


async def get_editor(name: str) -> dict[str, Any]:
    if name in EDITOR_CACHE:
        logger.debug(f"using cached data for wiki editor: {name}")
        return EDITOR_CACHE[name]
    EDITOR_CACHE[name] = await asyncreqs.get_json(EDITOR_URL.format(name))
    logger.debug(f"cached data for wiki editor {name} {EDITOR_CACHE[name]}")
    return EDITOR_CACHE[name]


async def get_edits() -> list[dict[str, Any]]:
    data = await asyncreqs.get_json(URL, proxy=True, params=PARAMS)
    return data["query"]["recentchanges"]


async def send(embed: disnake.Embed):
    await utils.broadcast(constants.WIKI_TRACKER_CHANNELS, embed=embed)


class WikiTrackerCog(PollingCog):
    interval = 30

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.db: mongodb.Collection | None = None
        self.db_queue = []
        self.data = datamanager.JsonWrapper(constants.STORAGE_DIR / "wikiedits.json")
        if not self.data.get("edits"):
            logger.warning("wikiedits.json is empty")
            self.data["edits"] = []

    async def upload_queue(self):
        if not self.db_queue:
            return
        if not self.db:
            self.db = mongodb.Collection("SkyBlock", "wikiedits")
        await mongodb.flush_queue(self.db, self.db_queue)

    def log_edit(self, edit: dict[str, Any]):
        doc = edit.copy()
        doc["_id"] = doc.pop("revid")
        self.db_queue.append(doc)

    async def on_wiki_edit(self, edit: dict[str, Any]):
        logger.debug(f"wiki edit: {edit}")
        self.log_edit(edit)
        editor = await get_editor(edit["user"])
        verb = "Created" if edit["type"] == "new" else "Edited"
        embed = utils.add_footer(
            disnake.Embed(
                title=f"{verb} {edit['title']}",
                description=f"```\n{edit['parsedcomment']}\n```\n-# **ID:** {edit['revid']}",
                url="https://hypixel.wiki/" + edit["title"].replace(" ", "_"),
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )
        embed.set_author(
            name=editor.get("displayName") or edit["user"],
            icon_url=editor.get("avatar"),
            url=editor.get("link"),
        )
        await send(embed)

    async def poll(self):
        edits = await get_edits()
        seen = set(self.data["edits"])
        initialized = bool(seen)
        for edit in edits:
            if edit.get("type") not in {"edit", "new"} or not edit.get("revid"):
                continue
            if edit["revid"] in seen:
                logger.debug(f"skipping already-processed edit: {edit['revid']}")
                continue
            if initialized:
                await self.on_wiki_edit(edit)
            self.data["edits"].append(edit["revid"])
            seen.add(edit["revid"])
            logger.debug(f"finished processing edit: {edit['revid']}")
        await self.upload_queue()
        logger.debug("logged edits to mongo")
        await self.data.save()

    async def close_resources(self):
        if self.db:
            await self.db.close()
            self.db = None
