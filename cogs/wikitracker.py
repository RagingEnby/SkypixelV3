import asyncio
import logging
import traceback
from typing import Any

import disnake
from disnake.ext import commands

import constants
from modules import asyncreqs
from modules import datamanager
from modules import utils

URL: str = "https://wiki.hypixel.net/api.php"
PARAMS: dict[str, str] = {
    "action": "query",
    "format": "json",
    "uselang": "user",
    "variant": "",
    "errorformat": "bc",
    "list": "recentchanges",
    "rcnamespace": "*",
    "rcprop": '|'.join([
        "comment", "flags", "ids", "loginfo", "parsedcomment", "redirect",
        "sha1", "sizes", "tags", "timestamp", "title", "user", "userid"
    ]),
    "rctype": '|'.join(["categorize", "edit", "external", "log", "new"])
}
EDITOR_URL: str = "https://api.ragingenby.dev/wiki/user/{}"
EDITOR_CACHE: dict[str, dict[str, Any]] = {}
logger = logging.getLogger(__name__)


async def get_editor(name: str) -> dict[str, Any]:
    global EDITOR_CACHE
    if name in EDITOR_CACHE:
        logger.debug(f"using cached data for wiki editor: {name}")
        return EDITOR_CACHE[name]
    response = await asyncreqs.get(EDITOR_URL.format(name))
    EDITOR_CACHE[name] = await response.json()
    logger.debug(f"cached data for wiki editor {name} {EDITOR_CACHE[name]}")
    return EDITOR_CACHE[name]


async def get_edits() -> list[dict[str, Any]]:
    response = await asyncreqs.get(URL, params=PARAMS)
    data = await response.json()
    return data['query']['recentchanges']


async def send(embed: disnake.Embed):
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.WIKI_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class WikiTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/wikiedits.json")
        if not self.data.get('edits'):
            logger.warning("wikiedits.json is empty")
            self.data['edits'] = []

    @staticmethod
    async def on_wiki_edit(edit: dict[str, Any]):
        logger.debug(f"wiki edit: {edit}")
        editor = await get_editor(edit['user'])
        verb = "Created" if edit['type'] == 'new' else "Edited"
        embed = utils.add_footer(disnake.Embed(
            title=f"{verb} {edit['title']}",
            description=f"```\n{edit['parsedcomment']}\n```\n-# **ID:** {edit['revid']}",
            url="https://hypixel.wiki/" + edit['title'].replace(' ', '_'),
            color=constants.DEFAULT_EMBED_COLOR
        ))
        embed.set_author(
            name=editor.get('displayName') or edit['user'],
            icon_url=editor.get('avatar'),
            url=editor.get('link')
        )
        await send(embed)

    async def main(self):
        while True:
            try:
                edits = await get_edits()
                for edit in edits:
                    if edit['revid'] in self.data['edits']:
                        logger.debug(f"skipping already-processed edit: {edit['revid']}")
                        continue
                    if self.data.get('edits'):
                        await self.on_wiki_edit(edit)
                    self.data['edits'].append(edit['revid'])
                    logger.debug(f"finished processing edit: {edit['revid']}")
                await self.data.save()
            except Exception:
                logger.error(traceback.format_exc())
            finally:
                await asyncio.sleep(90)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
