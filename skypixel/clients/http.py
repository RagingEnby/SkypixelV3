import asyncio
import logging
from typing import Any, Literal
from urllib.parse import urlsplit

import curl_cffi
from curl_cffi.requests.exceptions import RequestException

from skypixel.settings import settings

logger = logging.getLogger(__name__)
SESSION: curl_cffi.AsyncSession | None = None
CLOSED = False
RETRY_STATUSES = {429, 500, 502, 503, 504}


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.hostname}{parsed.path}"


async def close() -> None:
    global CLOSED, SESSION
    if CLOSED:
        return
    CLOSED = True
    session, SESSION = SESSION, None
    if session is not None:
        await session.close()


async def get_session() -> curl_cffi.AsyncSession:
    global SESSION
    if CLOSED:
        raise RuntimeError("The HTTP client has shut down.")
    if SESSION is None:
        SESSION = curl_cffi.AsyncSession(discard_cookies=True, timeout=(10, 30))
    return SESSION


async def request(
    method: Literal["GET", "POST"], *args, **kwargs
) -> curl_cffi.Response:
    attempts = kwargs.pop("attempts", 3 if method == "GET" else 1)
    if not isinstance(attempts, int) or attempts < 1:
        raise ValueError("The request attempt count must be a positive integer.")
    session = await get_session()
    for attempt in range(attempts):
        try:
            response = await session.request(method, *args, **kwargs)
        except RequestException:
            if attempt == attempts - 1:
                raise
            logger.warning("HTTP %s failed. Retrying attempt %s.", method, attempt + 2)
        else:
            logger.info(
                "%s %s %s", method, safe_url(response.url), response.status_code
            )
            if (
                method != "GET"
                or response.status_code not in RETRY_STATUSES
                or attempt == attempts - 1
            ):
                return response
        await asyncio.sleep(min(2**attempt, 5))
    raise RuntimeError("The HTTP request did not complete.")


async def get(*args, **kwargs) -> curl_cffi.Response:
    return await request("GET", *args, **kwargs)


async def proxy_get(*args, **kwargs) -> curl_cffi.Response:
    proxy = settings.proxies.get("http")
    if not proxy:
        raise ValueError(
            "Set SKYPIXEL_HTTP_PROXY or scrts.PROXIES['http'] to use the wiki tracker."
        )
    kwargs.setdefault("proxy", proxy)
    kwargs.setdefault("impersonate", "chrome110")
    return await get(*args, **kwargs)


async def post(*args, **kwargs) -> curl_cffi.Response:
    return await request("POST", *args, **kwargs)


async def get_json(url: str, *, proxy: bool = False, **kwargs) -> Any:
    response = await (proxy_get(url, **kwargs) if proxy else get(url, **kwargs))
    response.raise_for_status()
    return response.json()
