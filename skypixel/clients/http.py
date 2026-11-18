import asyncio
import logging
from typing import TYPE_CHECKING, Literal, Unpack
from urllib.parse import urlsplit

import curl_cffi
from curl_cffi.requests.exceptions import RequestException

from skypixel.domain.types import JSON

if TYPE_CHECKING:
    from curl_cffi.requests.session import RequestParams

    class RequestOptions(RequestParams, total=False):
        attempts: int


logger: logging.Logger = logging.getLogger(__name__)
SESSION: curl_cffi.AsyncSession[curl_cffi.Response] | None = None
CLOSED: bool = False
RETRY_STATUSES: set[int] = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER: int = 30


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.hostname}{parsed.path}"


async def close() -> None:
    global CLOSED, SESSION
    if CLOSED:
        return
    # Tests patch CLOSED and SESSION by name, so they keep their names.
    CLOSED = True  # pyright: ignore[reportConstantRedefinition]
    session, SESSION = SESSION, None  # pyright: ignore[reportConstantRedefinition]
    if session is not None:
        await session.close()


async def get_session() -> curl_cffi.AsyncSession[curl_cffi.Response]:
    global SESSION
    if CLOSED:
        raise RuntimeError("The HTTP client has shut down.")
    if SESSION is None:
        SESSION = curl_cffi.AsyncSession(discard_cookies=True, timeout=(10, 30))  # pyright: ignore[reportConstantRedefinition]
    return SESSION


async def request(
    method: Literal["GET", "POST"],
    url: str,
    *,
    attempts: int | None = None,
    **kwargs: Unpack[RequestParams],
) -> curl_cffi.Response:
    if attempts is None:
        attempts = 3 if method == "GET" else 1
    # Untyped callers can pass anything, so keep the runtime check.
    if not isinstance(attempts, int) or attempts < 1:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError("The request attempt count must be a positive integer.")
    session = await get_session()
    for attempt in range(attempts):
        delay = min(2**attempt, 5)
        try:
            response = await session.request(method, url, **kwargs)  # pyright: ignore[reportUnknownMemberType]
        except RequestException as error:
            if attempt == attempts - 1:
                raise
            logger.warning(
                "HTTP %s %s failed with %s: %s. Retrying attempt %s.",
                method,
                safe_url(url),
                type(error).__name__,
                error,
                attempt + 2,
            )
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
            retry_after = response.headers.get("Retry-After")
            if isinstance(retry_after, str) and retry_after.isdigit():
                delay = max(delay, min(int(retry_after), MAX_RETRY_AFTER))
        await asyncio.sleep(delay)
    raise RuntimeError("The HTTP request did not complete.")


async def get(url: str, **kwargs: Unpack[RequestOptions]) -> curl_cffi.Response:
    return await request("GET", url, **kwargs)


async def post(url: str, **kwargs: Unpack[RequestOptions]) -> curl_cffi.Response:
    return await request("POST", url, **kwargs)


def read_json(response: curl_cffi.Response) -> JSON:
    """Parse the response body. curl_cffi leaves the result of json() untyped."""
    return response.json()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


async def get_json(url: str, **kwargs: Unpack[RequestOptions]) -> JSON:
    response = await get(url, **kwargs)
    response.raise_for_status()
    return read_json(response)
