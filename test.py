from contextlib import suppress
from cogs import wikitracker
from modules import asyncreqs
import asyncio


async def main():
    try:
        no_proxy, proxy = await asyncio.gather(
            asyncreqs.get('https://api.ipify.org?format=text'),
            asyncreqs.proxy_get('https://api.ipify.org?format=text')
        )
        print('ip', no_proxy.text)
        print('proxy ip', proxy.text)
        if no_proxy.text == proxy.text:
            print('proxying mega broken')
        try:
            edits = await wikitracker.get_edits()
            print(edits)
        except Exception as e:
            print('unable to fetch wiki edits:', e)
    finally:
        await asyncreqs.close()


asyncio.run(main())
