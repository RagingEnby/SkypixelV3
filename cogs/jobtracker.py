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

URL: str = "https://api.ragingenby.dev/forums/jobs?cache=false"


class Job:
    def __init__(self, title: str, listing_id: int, qualifications: list[str], responsibilities: list[str] | None, we_can_offer: list[str]):
        self.title = title
        self.listing_id = listing_id
        self.qualifications = qualifications
        self.responsibilities = responsibilities
        self.we_can_offer = we_can_offer
        
    @property
    def clean_title(self) -> str:
        return self.title.replace(" - Minecraft Project", "")
        
    @property
    def url(self) -> str:
        return f"https://hypixel.net/jobs/#listing-{self.listing_id}"
    
    @property
    def application_url(self) -> str:
        return f"https://hypixel.bamboohr.com/careers/{self.listing_id}"
    
    def to_markdown(self) -> str:
        lines = [f"# {self.clean_title}"]
        lines.append("## Qualifications")
        lines.extend([f"- {qualification}" for qualification in self.qualifications])
        if self.responsibilities:
            lines.append("## Responsibilities")
            lines.extend([f"- {responsibility}" for responsibility in self.responsibilities])
        lines.append("## We Can Offer")
        lines.extend([f"- {offer}" for offer in self.we_can_offer])
        lines.append(f"-# [Info]({self.url}) | [Apply]({self.application_url})")
        return "\n".join(lines)
        
    @classmethod
    def from_dict(cls, data: dict) -> 'Job':
        return cls(
            title=data['title'],
            listing_id=data['listingId'],
            qualifications=data['qualifications'],
            responsibilities=data.get('responsibilities'),
            we_can_offer=data['weCanOffer']
        )
        
    def to_dict(self) -> dict:
        return {
            'title': self.title,
            'listingId': self.listing_id,
            'qualifications': self.qualifications,
            'responsibilities': self.responsibilities,
            'weCanOffer': self.we_can_offer
        }


async def get_jobs() -> list[Job]:
    logger.debug("getting job openings from api.ragingenby.dev")
    response = await asyncreqs.get(URL)
    return [Job.from_dict(job) for job in response.json()['jobs']]


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
    async def on_job_update(job: Job, added: bool):
        embed = utils.add_footer(disnake.Embed(
            title=f"New Job Opening!" if added else f"Job Opening Removed!",
            description=job.to_markdown(),
            color=constants.COLOR_CODES['a'] if added else constants.COLOR_CODES['c']
        ))
        await send(embed)
    
    def to_dict(self) -> dict:
        return {job.title: job.to_dict() for job in self.data.get('jobs', [])}

    async def main(self):
        while True:
            try:
                jobs = await get_jobs()
                jobs_dict: dict[str, Job] = {job.title: job for job in jobs}
                for job in jobs:
                    if not self.data.get(job.title): 
                        await self.on_job_update(job, True)
                for job in self.data.keys():
                    if job not in jobs_dict:
                        await self.on_job_update(Job.from_dict(self.data[job]), False)
                self.data.update({job.title: job.to_dict() for job in jobs})
                await self.data.save()
            except Exception:
                logger.error(traceback.format_exc())
            finally:
                await asyncio.sleep(60*30)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.close()
        self.task = asyncio.create_task(self.main())
