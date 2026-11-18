import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

import disnake

from skypixel import constants, utils
from skypixel.clients import http
from skypixel.domain.types import JSONInput
from skypixel.storage.database import Alert, TrackerState
from skypixel.trackers.base import PollingCog

if TYPE_CHECKING:
    from skypixel.app import SkypixelBot


logger: logging.Logger = logging.getLogger(__name__)

URL: str = "https://api.ragingenby.dev/forums/jobs?cache=false"

# A job as the API returns it and as jobs.json stores it.
type JobData = dict[str, JSONInput]


def _job_text(data: Mapping[str, JSONInput], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise ValueError(f"The job {key} is not text.")
    return value


def _job_number(data: Mapping[str, JSONInput], key: str) -> int:
    value = data[key]
    if not isinstance(value, int):
        raise ValueError(f"The job {key} is not a number.")
    return value


def _job_lines(value: JSONInput, key: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(line, str) for line in value):
        raise ValueError(f"The job {key} is not a list of text.")
    return [line for line in value if isinstance(line, str)]


class Job:
    def __init__(
        self,
        title: str,
        listing_id: int,
        qualifications: list[str],
        responsibilities: list[str] | None,
        we_can_offer: list[str],
    ) -> None:
        self.title: str = title
        self.listing_id: int = listing_id
        self.qualifications: list[str] = qualifications
        self.responsibilities: list[str] | None = responsibilities
        self.we_can_offer: list[str] = we_can_offer

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
    def from_dict(cls, data: Mapping[str, JSONInput]) -> Job:
        responsibilities = data.get("responsibilities")
        return cls(
            title=_job_text(data, "title"),
            listing_id=_job_number(data, "listingId"),
            qualifications=_job_lines(data["qualifications"], "qualifications"),
            responsibilities=None
            if responsibilities is None
            else _job_lines(responsibilities, "responsibilities"),
            we_can_offer=_job_lines(data["weCanOffer"], "weCanOffer"),
        )

    def to_dict(self) -> JobData:
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
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        raise ValueError("The job API did not return a jobs list.")
    return [Job.from_dict(job) for job in jobs if isinstance(job, dict)]


def send(embed: disnake.Embed) -> list[Alert]:
    return utils.broadcast(constants.JOB_TRACKER_CHANNELS, embed=embed)


class JobTrackerCog(PollingCog):
    interval: float = 1800
    confirm_polls: int = 3

    def __init__(self, bot: SkypixelBot) -> None:
        super().__init__(bot)
        self.data: TrackerState[JobData] = TrackerState(bot.database, "jobs")
        self.empty_polls: int = 0
        # Saved empty state means no open jobs. No saved state means the first run.
        self.initialized: bool = self.data.exists

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

    async def poll(self) -> None:
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
