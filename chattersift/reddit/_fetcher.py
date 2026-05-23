from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from django.conf import settings

from .contracts import RedditFeedFormat
from .contracts import RedditFeedKind
from .contracts import RedditFeedSpec
from .contracts import RedditItemPayload
from .parsers import parse_reddit_atom_response
from .parsers import parse_reddit_json_response

REDDIT_BASE_URL = "https://www.reddit.com"
# Public Reddit endpoints are requested without OAuth in core mode. Reddit may
# throttle or block high-volume unauthenticated traffic; User-Agent is required.
DEFAULT_FETCH_LIMIT = 100
DEFAULT_HTTP_TIMEOUT_SECONDS = 10.0
HTTP_STATUS_RATE_LIMIT = 429
HTTP_STATUS_OK_MIN = 200
HTTP_STATUS_REDIRECT_MIN = 300
_UNSAFE_SUBREDDIT_TOKENS = ("/", "?", "#", "..")


class RedditFetchError(RuntimeError):
    """Base class for Reddit fetch failures."""


class UnsupportedFeedSpecError(RedditFetchError):
    """Raised when a feed kind/format combination is unsupported."""


class InvalidFeedSpecError(RedditFetchError):
    """Raised when a feed spec contains invalid subreddit/path inputs."""


class RedditHttpStatusError(RedditFetchError):
    """Raised when Reddit returns a non-success HTTP status code."""


class RedditRateLimitError(RedditHttpStatusError):
    """Raised when Reddit returns HTTP 429."""


class RedditTimeoutError(RedditFetchError):
    """Raised when a network timeout occurs."""


class RedditTransportError(RedditFetchError):
    """Raised when an HTTP transport/network error occurs."""


class RedditParseError(RedditFetchError):
    """Raised when parsing a Reddit response fails."""


@dataclass(frozen=True, kw_only=True)
class RequestSpec:
    """Resolved request path and query params for a Reddit feed spec."""

    path: str
    params: dict[str, str]


def fetch_and_parse_sync(
    spec: RedditFeedSpec,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[RedditItemPayload]:
    """Synchronously fetch and parse one Reddit feed."""
    return asyncio.run(fetch_and_parse(spec, client=client))


async def fetch_and_parse(
    spec: RedditFeedSpec,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[RedditItemPayload]:
    """Fetch and parse one Reddit feed asynchronously."""
    request_spec = build_request_spec(spec)
    timeout = httpx.Timeout(get_http_timeout_seconds())
    headers = {"User-Agent": settings.CHATTERSIFT_REDDIT_USER_AGENT}

    if client is not None:
        response = await _send_request(client, request_spec, headers=headers)
    else:
        async with httpx.AsyncClient(base_url=REDDIT_BASE_URL, timeout=timeout) as async_client:
            response = await _send_request(async_client, request_spec, headers=headers)

    try:
        if spec.format == RedditFeedFormat.RSS:
            return parse_reddit_atom_response(response.content)
        return parse_reddit_json_response(response.content)
    except Exception as error:
        msg = f"Failed to parse Reddit response for {spec.kind} {spec.format}"
        raise RedditParseError(msg) from error


async def _send_request(
    client: httpx.AsyncClient,
    request_spec: RequestSpec,
    *,
    headers: dict[str, str],
) -> httpx.Response:
    """Execute one Reddit request and normalize transport/status failures."""
    try:
        response = await client.get(request_spec.path, params=request_spec.params, headers=headers)
    except httpx.TimeoutException as error:
        msg = f"Reddit request timed out: {_format_httpx_error(error)}"
        raise RedditTimeoutError(msg) from error
    except httpx.TransportError as error:
        msg = f"Reddit transport error: {_format_httpx_error(error)}"
        raise RedditTransportError(msg) from error

    if response.status_code == HTTP_STATUS_RATE_LIMIT:
        msg = "Reddit rate limit hit (HTTP 429)"
        raise RedditRateLimitError(msg)
    if response.status_code < HTTP_STATUS_OK_MIN or response.status_code >= HTTP_STATUS_REDIRECT_MIN:
        msg = f"Reddit request failed with HTTP {response.status_code}"
        raise RedditHttpStatusError(msg)
    return response


def _format_httpx_error(error: httpx.HTTPError) -> str:
    """Return the concrete HTTPX exception type and message for diagnostics."""
    error_message = str(error)
    if not error_message:
        return error.__class__.__name__
    return f"{error.__class__.__name__}: {error_message}"


def build_request_url(spec: RedditFeedSpec) -> str:
    """Return the absolute URL for one feed spec."""
    request_spec = build_request_spec(spec)
    query = urlencode(request_spec.params)
    if not query:
        return f"{REDDIT_BASE_URL}{request_spec.path}"
    return f"{REDDIT_BASE_URL}{request_spec.path}?{query}"


def build_request_spec(spec: RedditFeedSpec) -> RequestSpec:
    """Return request path and query params for a Reddit feed spec."""
    subreddit = _validated_subreddit(spec.subreddit)
    limit = str(get_fetch_limit())

    if spec.kind == RedditFeedKind.POST_STREAM:
        return RequestSpec(path=f"/r/{subreddit}/new.{spec.format}", params={"limit": limit})

    if spec.kind == RedditFeedKind.COMMENT_STREAM:
        return RequestSpec(path=f"/r/{subreddit}/comments.{spec.format}", params={"limit": limit})

    if spec.kind == RedditFeedKind.POST_SEARCH:
        path = "/search" if not subreddit else f"/r/{subreddit}/search"
        params = {"q": spec.query, "limit": limit, "sort": "new"}
        if spec.format == RedditFeedFormat.JSON:
            params["raw_json"] = "1"
        if subreddit:
            params["restrict_sr"] = "1"
        return RequestSpec(path=f"{path}.{spec.format}", params=params)

    if spec.kind == RedditFeedKind.COMMENT_SEARCH:
        if spec.format == RedditFeedFormat.RSS:
            msg = "COMMENT_SEARCH is not supported for RSS"
            raise UnsupportedFeedSpecError(msg)
        path = "/search" if not subreddit else f"/r/{subreddit}/search"
        params = {
            "q": spec.query,
            "type": "comment",
            "sort": "new",
            "limit": limit,
            "raw_json": "1",
        }
        if subreddit:
            params["restrict_sr"] = "1"
        return RequestSpec(path=f"{path}.{spec.format}", params=params)

    msg = f"Unsupported Reddit feed kind: {spec.kind}"
    raise UnsupportedFeedSpecError(msg)


def get_fetch_limit() -> int:
    """Return configured reddit fetch page limit."""
    configured = int(getattr(settings, "CHATTERSIFT_REDDIT_FETCH_LIMIT", DEFAULT_FETCH_LIMIT))
    return max(configured, 1)


def get_http_timeout_seconds() -> float:
    """Return configured HTTP timeout in seconds."""
    configured = float(
        getattr(
            settings,
            "CHATTERSIFT_REDDIT_HTTP_TIMEOUT_SECONDS",
            DEFAULT_HTTP_TIMEOUT_SECONDS,
        ),
    )
    return configured if configured > 0 else DEFAULT_HTTP_TIMEOUT_SECONDS


def _validated_subreddit(subreddit: str) -> str:
    """Return a cleaned subreddit value after rejecting unsafe path/query tokens."""
    value = subreddit.strip()
    if not value:
        return ""

    if any(token in value for token in _UNSAFE_SUBREDDIT_TOKENS):
        msg = f"Invalid subreddit token: {subreddit!r}"
        raise InvalidFeedSpecError(msg)
    return value
