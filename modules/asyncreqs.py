import asyncio
from typing import Optional

import aiohttp

SESSION: Optional[aiohttp.ClientSession] = None
CLOSED: bool = False


async def get(*args, **kwargs) -> aiohttp.ClientResponse:
    global SESSION
    if CLOSED:
        raise RuntimeError('asyncreqs.get() called after shutdown')

    if not SESSION or SESSION.closed:
        SESSION = aiohttp.ClientSession()
        print('<!> asyncreqs.get() had to create a session')

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
    if CLOSED:
        raise RuntimeError('asyncreqs.get() called after shutdown')

    if not SESSION or SESSION.closed:
        SESSION = aiohttp.ClientSession()
        print('<!> asyncreqs.post() had to create a session')

    async with SESSION.post(*args, **kwargs) as response:
        try:
            await response.json()
        except:  # type: ignore
            await response.read()
        return response
