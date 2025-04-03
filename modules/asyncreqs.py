from typing import Optional
import aiohttp
import asyncio


SESSION: Optional[aiohttp.ClientSession] = None


async def get(*args, **kwargs) -> aiohttp.ClientResponse:
    global SESSION
    if not SESSION or SESSION.closed:
        SESSION = aiohttp.ClientSession()
        print('<!> asyncreqs.get() had to create a session', args[0])
    try:
        async with SESSION.get(*args, **kwargs) as response:
            try:
                await response.json()
            except:  # type: ignore
                await response.read()
            return response
    except aiohttp.ClientHttpProxyError:
        await asyncio.sleep(2)
        return await get(*args, **kwargs)


async def post(*args, **kwargs) -> aiohttp.ClientResponse:
    global SESSION
    if not SESSION or SESSION.closed:
        SESSION = aiohttp.ClientSession()
        print('<!> asyncreqs.post() had to create a session', args[0])
    async with SESSION.post(*args, **kwargs) as response:
        try:
            await response.json()
        except:  # type: ignore
            await response.read()
        return response
