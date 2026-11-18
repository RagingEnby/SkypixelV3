import logging
from typing import TYPE_CHECKING

import disnake

from skypixel import constants, utils
from skypixel.clients import http
from skypixel.storage.database import Alert, TrackerState
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger = logging.getLogger(__name__)

URL: str = "https://api.ragingenby.dev/forums/jobs?cache=false"


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
    logger.debug("getting job openings from api.ragingenby.dev")
    data = await http.get_json(URL)
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("The job API did not return a jobs list.")
    return [Job.from_dict(job) for job in data["jobs"]]


def send(embed: disnake.Embed) -> list[Alert]:
    return utils.broadcast(constants.JOB_TRACKER_CHANNELS, embed=embed)


class JobTrackerCog(PollingCog):
    interval = 1800
    confirm_polls = 3

    def __init__(self, bot: SkypixelBot):
        super().__init__(bot)
        self.data = TrackerState(bot.database, "jobs")
        self.empty_polls = 0
        # Saved empty state means no open jobs. No saved state means the first run.
        self.initialized = self.data.exists

    def on_job_update(self, job: Job, added: bool) -> list[Alert]:
        embed = utils.add_footer(
            disnake.Embed(
                title="New Job Opening!" if added else "Job Opening Removed!",
                description=job.to_markdown(),
                color=constants.COLOR_CODES["a"]
                if added
                else constants.COLOR_CODES["c"],
            )
        )
        return send(embed)

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
        alerts: list[Alert] = []
        for job in jobs:
            if self.initialized and job.title not in self.data:
                alerts += self.on_job_update(job, True)
        for title, data in list(self.data.items()):
            if title not in current:
                alerts += self.on_job_update(Job.from_dict(data), False)
        await self.data.replace(current, alerts)
        self.initialized = True
