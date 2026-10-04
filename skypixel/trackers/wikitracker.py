import logging
import time
from typing import Any
from urllib.parse import quote

import disnake
from disnake.ext import commands

from skypixel import constants, utils
from skypixel.clients import http
from skypixel.settings import settings
from skypixel.storage.json import JsonWrapper
from skypixel.storage.mongo import UploadQueue
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
EDITOR_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
EDITOR_CACHE_TTL = 24 * 60 * 60
EDITOR_CACHE_LIMIT = 512
logger = logging.getLogger(__name__)


async def get_editor(name: str) -> dict[str, Any]:
    cached = EDITOR_CACHE.get(name)
    if cached is not None and time.monotonic() - cached[0] < EDITOR_CACHE_TTL:
        return cached[1]
    editor = await http.get_json(EDITOR_URL.format(quote(name, safe="")))
    if not isinstance(editor, dict):
        raise ValueError("The wiki API did not return an editor object.")
    EDITOR_CACHE.pop(name, None)
    EDITOR_CACHE[name] = (time.monotonic(), editor)
    while len(EDITOR_CACHE) > EDITOR_CACHE_LIMIT:
        EDITOR_CACHE.pop(next(iter(EDITOR_CACHE)))
    return editor


async def get_edits() -> list[dict[str, Any]]:
    data = await http.get_json(URL, proxy=True, params=PARAMS)
    return data["query"]["recentchanges"]


async def send(embed: disnake.Embed):
    await utils.broadcast(constants.WIKI_TRACKER_CHANNELS, embed=embed)


class WikiTrackerCog(PollingCog):
    interval = 30
    history_limit = 1000

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.uploads = UploadQueue("SkyBlock", "wikiedits")
        self.data = JsonWrapper(settings.storage_dir / "wikiedits.json")
        if not self.data.get("edits"):
            logger.warning("wikiedits.json is empty")
            self.data["edits"] = []

    def log_edit(self, edit: dict[str, Any]):
        doc = edit.copy()
        doc["_id"] = doc.pop("revid")
        self.uploads.append(doc)

    async def on_wiki_edit(self, edit: dict[str, Any]):
        logger.debug("wiki edit: %s", edit)
        self.log_edit(edit)
        try:
            editor = await get_editor(edit["user"])
        except Exception:
            logger.exception("Cannot load wiki editor %s.", edit["user"])
            editor = {}
        verb = "Created" if edit["type"] == "new" else "Edited"
        comment = edit.get("comment", "").replace("`", "\u02cb")
        embed = utils.add_footer(
            disnake.Embed(
                title=f"{verb} {edit['title']}",
                description=f"```\n{comment}\n```\n-# **ID:** {edit['revid']}",
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
        history = self.data["edits"].copy()
        initialized = bool(seen)
        for edit in edits:
            if edit.get("type") not in {"edit", "new"} or not edit.get("revid"):
                continue
            if edit["revid"] in seen:
                logger.debug("skipping already-processed edit: %s", edit["revid"])
                continue
            if initialized:
                await self.on_wiki_edit(edit)
            history.append(edit["revid"])
            seen.add(edit["revid"])
            logger.debug("finished processing edit: %s", edit["revid"])
        await self.data.replace({**self.data, "edits": history[-self.history_limit :]})
        await self.uploads.flush()

    async def close_resources(self):
        await self.uploads.close()
