import asyncio
import logging
import traceback

import disnake
from disnake.ext import commands

import constants
from modules import datamanager
from modules import utils
from modules import asyncreqs

logger = logging.getLogger(__name__)

URL: str = "https://api.ragingenby.dev/forums/jobs"


async def get_jobs() -> list[str]:
    logger.debug("getting job openings from api.ragingenby.dev")
    response = await asyncreqs.get(URL)
    return response.json()['jobs']


async def send(embed: disnake.Embed):
    tasks = [
        utils.send_to_channel(channel_id, content, embed=embed)
        for channel_id, content in constants.JOB_TRACKER_CHANNELS.items()
    ]
    await asyncio.gather(*tasks)


class JobTrackerCog(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.data = datamanager.JsonWrapper("storage/jobs.json")

    @staticmethod
    async def on_job_update(before: list[str], after: list[str]):
        removed = [job for job in before if job not in after]
        added = [job for job in after if job not in before]
        embed = utils.add_footer(disnake.Embed(
            title="Hypixel Job Openings Updated!",
            color=constants.DEFAULT_EMBED_COLOR,
            #description=f"-# [Source](https://hypixel.net/jobs#Current%20Job%20Openings)"
        ))
        if removed:
            embed.add_field(
                name="Removed",
                value='\n'.join('* ' + disnake.utils.escape_markdown(job) for job in removed)
            )
        if added:
            embed.add_field(
                name="Added",
                value='\n'.join('* ' + disnake.utils.escape_markdown(job) for job in added)
            )
        await send(embed)

    async def main(self):
        while True:
            try:
                jobs = await get_jobs()
                if jobs != self.data.get('jobs'):
                    if self.data.get('jobs'):
                        await self.on_job_update(self.data.get('jobs'), jobs)
                    self.data['jobs'] = jobs
                    await self.data.save()
            except Exception:
                logger.error(traceback.format_exc())
            finally:
                await asyncio.sleep(240)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
