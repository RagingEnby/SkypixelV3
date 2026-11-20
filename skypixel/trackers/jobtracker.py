import logging
from pathlib import Path

import disnake
from disnake.ext import commands

from skypixel import constants, utils
from skypixel.clients import http
from skypixel.storage.json import JsonWrapper
from skypixel.trackers.base import PollingCog

logger = logging.getLogger(__name__)

URL: str = http.API_URL + "/forums/jobs"


class Job:
    def __init__(
        self,
        title: str,
        listing_id: int,
        qualifications: list[str],
        responsibilities: list[str] | None,
        we_can_offer: list[str],
    ):
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
            lines.extend(
                [f"- {responsibility}" for responsibility in self.responsibilities]
            )
        lines.append("## We Can Offer")
        lines.extend([f"- {offer}" for offer in self.we_can_offer])
        lines.append(f"-# [Info]({self.url}) | [Apply]({self.application_url})")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        return cls(
            title=data["title"],
            listing_id=data["listingId"],
            qualifications=data["qualifications"],
            responsibilities=data.get("responsibilities"),
            we_can_offer=data["weCanOffer"],
        )

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "listingId": self.listing_id,
            "qualifications": self.qualifications,
            "responsibilities": self.responsibilities,
            "weCanOffer": self.we_can_offer,
        }


async def get_jobs() -> list[Job]:
    logger.debug("getting job openings from the RagingEnby API")
    data = await http.get_json(URL)
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("The job API did not return a jobs list.")
    return [Job.from_dict(job) for job in data["jobs"]]


async def send(bot: commands.InteractionBot, embed: disnake.Embed):
    await utils.broadcast(bot, constants.JOB_TRACKER_CHANNELS, embed=embed)


class JobTrackerCog(PollingCog):
    interval = 1800
    confirm_polls = 3

    def __init__(self, bot: commands.InteractionBot):
        super().__init__(bot)
        self.data = JsonWrapper(bot.settings.storage_dir / "jobs.json")
        self.empty_polls = 0
        # An empty file means no open jobs. A missing file means the first run.
        self.initialized = Path(self.data.file_path).exists()

    async def on_job_update(self, job: Job, added: bool):
        embed = utils.add_footer(
            disnake.Embed(
                title="New Job Opening!" if added else "Job Opening Removed!",
                description=job.to_markdown(),
                color=constants.COLOR_CODES["a"]
                if added
                else constants.COLOR_CODES["c"],
            )
        )
        await send(self.bot, embed)

    async def poll(self):
        jobs = await get_jobs()
        if not jobs and self.data:
            self.empty_polls += 1
            if self.empty_polls < self.confirm_polls:
                # An empty response would announce every job as removed.
                logger.warning(
                    "The job API returned no jobs. Check %s of %s.",
                    self.empty_polls,
                    self.confirm_polls,
                )
                return
        self.empty_polls = 0
        current = {job.title: job.to_dict() for job in jobs}
        for job in jobs:
            if self.initialized and job.title not in self.data:
                await self.on_job_update(job, True)
        for title, data in list(self.data.items()):
            if title not in current:
                await self.on_job_update(Job.from_dict(data), False)
        await self.data.replace(current)
        self.initialized = True
