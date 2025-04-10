import asyncio
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


async def get_editor(name: str) -> dict[str, Any]:
    global EDITOR_CACHE
    if name in EDITOR_CACHE:
        return EDITOR_CACHE[name]
    response = await asyncreqs.get(EDITOR_URL.format(name))
    EDITOR_CACHE[name] = await response.json()
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
            self.data['edits'] = []

    async def on_wiki_edit(self, edit: dict[str, Any]):
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
                        continue
                    if self.data.get('edits'):
                        await self.on_wiki_edit(edit)
                    self.data['edits'].append(edit['revid'])
                await self.data.save()
                await asyncio.sleep(120)
            except Exception:
                print("wiki tracker error:", traceback.format_exc())

    @commands.Cog.listener()
    async def on_ready(self):
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self.main())
