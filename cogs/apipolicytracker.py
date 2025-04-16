import asyncio
import json
import logging
import traceback
from typing import Any

import disnake
from disnake.ext import commands

import constants
from modules import asyncreqs
from modules import datamanager
from modules import utils

logger = logging.getLogger(__name__)
URL: str = "https://api.ragingenby.dev/apipolicy"


async def get_api_policy() -> dict[str, Any]:
    response = await asyncreqs.get(URL)
    data = await response.json()
    logger.debug("got api policy:", data)
    return data


def get_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, tuple[Any, Any] | dict[str, Any]]:
    diff = {}
    keys = set(before.keys()) | set(after.keys())
    for k in keys:
        v1, v2 = before.get(k), after.get(k)
        if isinstance(v1, dict) and isinstance(v2, dict):
            diff[k] = get_diff(v1, v2)
        elif v1 != v2:
            diff[k] = (v1, v2)
    return diff


async def send(embed: disnake.Embed):
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.API_POLICY_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class ApiPolicyTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/apipolicy.json")
        if not self.data.get('API Policy'):
            logger.warning("apipolicy.json is empty")

    @staticmethod
    async def on_policy_update(before: dict[str, Any], after: dict[str, Any]):
        diff = get_diff(before, after)
        logger.info("diff:", json.dumps(diff, indent=2))

    async def main(self):
        while True:
            try:
                policy = await get_api_policy()
                if policy != self.data.to_dict():
                    if self.data.to_dict():
                        await self.on_policy_update(self.data.to_dict(), policy)
                    self.data.update(policy)
                    await self.data.save()
            except Exception:
                logger.error(traceback.format_exc())
            finally:
                await asyncio.sleep(120)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
