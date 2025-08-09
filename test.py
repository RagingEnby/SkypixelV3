from contextlib import suppress
from cogs import wikitracker
from modules import asyncreqs
import asyncio


async def main():
    edits = await wikitracker.get_edits()
    print(edits)
    await asyncreqs.close()


asyncio.run(main())