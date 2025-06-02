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
from modules import mongodb

API_BLOCKS_SERVER: bool = False
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


async def get_edits(attempts: int = 0) -> list[dict[str, Any]]:
    global API_BLOCKS_SERVER
    if not API_BLOCKS_SERVER and attempts <= 5:
        response = await asyncreqs.get(URL, params=PARAMS)
        if response.status == 403:
            logger.warning("wiki API blocked server, retrying in 5s...")
            await asyncio.sleep(5)
            return await get_edits(attempts+1)
    else:
        API_BLOCKS_SERVER = True
        logger.warning("wiki API seems to be blocking IP, switching to proxy")
        response = await asyncreqs.proxy_get(URL, params=PARAMS)
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
        self.db: mongodb.Collection | None = None
        self.db_queue = []
        self.data = datamanager.JsonWrapper("storage/wikiedits.json")
        if not self.data.get('edits'):
            logger.warning("wikiedits.json is empty")
            self.data['edits'] = []

    async def upload_queue(self):
        if not self.db_queue:
            return
        if not self.db:
            self.db = mongodb.Collection('SkyBlock', 'wikiedits')
        await self.db.insert_many(self.db_queue)
        self.db_queue.clear()

    def log_edit(self, edit: dict[str, Any]):
        doc = edit.copy()
        doc['_id'] = doc.pop('revid')
        self.db_queue.append(doc)

    async def on_wiki_edit(self, edit: dict[str, Any]):
        logger.debug(f"wiki edit: {edit}")
        self.log_edit(edit)
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
                await self.upload_queue()
                logger.debug("logged edits to mongo")
                await self.data.save()
            except Exception:
                logger.error(traceback.format_exc())
            finally:
                await asyncio.sleep(30)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
        if self.db:
            await self.db.close()
            self.db = None

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
