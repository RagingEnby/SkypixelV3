from importlib import import_module

EXTENSIONS = {
    "AlphaTrackerCog": "skypixel.trackers.alphatracker",
    "AuctionTrackerCog": "skypixel.trackers.auctionhouse",
    "FireSaleTrackerCog": "skypixel.trackers.firesaletracker",
    "GuildCog": "skypixel.commands.guild",
    "ItemDBCog": "skypixel.commands.itemdb",
    "LoggerCog": "skypixel.commands.logger",
    "MotdTrackerCog": "skypixel.trackers.motdtracker",
    "RankTrackerCog": "skypixel.trackers.ranktracker",
    "StatusUpdaterCog": "skypixel.trackers.status",
    "VersionTrackerCog": "skypixel.trackers.versiontracker",
    "WikiTrackerCog": "skypixel.trackers.wikitracker",
    "ZoneTrackerCog": "skypixel.trackers.zonetracker",
    "JobTrackerCog": "skypixel.trackers.jobtracker",
}


def get_extension(name: str):
    return getattr(import_module(EXTENSIONS[name]), name)


def __getattr__(name: str):
    if name in EXTENSIONS:
        return get_extension(name)
    raise AttributeError(name)
