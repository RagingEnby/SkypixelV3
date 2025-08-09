import logging
from typing import Literal
import curl_cffi

import constants

logger = logging.getLogger(__name__)

SESSION: curl_cffi.AsyncSession | None = None
CLOSED: bool = False


async def close():
    global CLOSED, SESSION
    if CLOSED:
        logger.error("asyncreqs.close() called after shutdown")
        raise RuntimeError("asyncreqs.close() called after shutdown")
    CLOSED = True
    try:
        await SESSION.close()  # type: ignore
        logger.info("Closed curl_cffi session")
    except Exception as e:
        logger.warning(f"unable to close asyncreqs session {e} (this is 99% prob ok)")
    SESSION = None


async def get_session() -> curl_cffi.AsyncSession:
    global SESSION, CLOSED
    if CLOSED:
        logger.error("asyncreqs.get_session() called after shutdown")
        raise RuntimeError('asyncreqs.get_session() called after shutdown')
    if not SESSION:
        SESSION = curl_cffi.AsyncSession(discard_cookies=True)
    return SESSION


async def request(
    # this can handle other methods but only GET and POST are needed
    # in skypixel
    method: Literal['GET', 'POST'],
    *args, **kwargs
) -> curl_cffi.Response:
    global CLOSED
    if CLOSED:
        logger.error("asyncreqs.request() called after shutdown")
        raise RuntimeError('asyncreqs.request() called after shutdown')
    session = await get_session()

    response = await session.request(method, *args, **kwargs)
    logger.info(f"{method} {response.url} {response.status_code}")
    return response


async def get(*args, **kwargs) -> curl_cffi.Response:
    return await request('GET', *args, **kwargs)


async def proxy_get(*args, **kwargs) -> curl_cffi.Response:
    impersonate = kwargs.pop('impersonate', 'chrome110')
    return await request(
        'GET',
        *args,
        proxy=constants.PROXIES['http'],
        impersonate=impersonate,
        **kwargs
    )


async def post(*args, **kwargs) -> curl_cffi.Response:
    return await request('POST', *args, **kwargs)
