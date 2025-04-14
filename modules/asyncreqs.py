import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

SESSION: Optional[aiohttp.ClientSession] = None
CLOSED: bool = False


async def get(*args, **kwargs) -> aiohttp.ClientResponse:
    global SESSION
    logger.debug("GET", args, kwargs)
    if CLOSED:
        logger.error("asyncreqs.get() called after shutdown")
        raise RuntimeError('asyncreqs.get() called after shutdown')

    if not SESSION or SESSION.closed:
        SESSION = aiohttp.ClientSession()
        logger.warning('<!> asyncreqs.get() had to create a session')

    try:
        async with SESSION.get(*args, **kwargs) as response:
            logger.debug("GET", response.url, response.status)
            try:
                await response.json()
            except:  # type: ignore
                await response.read()
            return response
    except aiohttp.ClientHttpProxyError as e:
        logger.error("Proxy error:", e, "retrying in 2s...")
        await asyncio.sleep(2)
        return await get(*args, **kwargs)


async def post(*args, **kwargs) -> aiohttp.ClientResponse:
    global SESSION
    if CLOSED:
        logger.error("asyncreqs.get() called after shutdown")
        raise RuntimeError('asyncreqs.get() called after shutdown')

    if not SESSION or SESSION.closed:
        SESSION = aiohttp.ClientSession()
        logger.warning('<!> asyncreqs.post() had to create a session')

    async with SESSION.post(*args, **kwargs) as response:
        logger.debug("POST", response.url, response.status)
        try:
            await response.json()
            logger.debug("successfully got json")
        except:  # type: ignore
            await response.read()
            logger.debug("successfully read response")
        return response
