from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

import httpx
import pytest

from chattersift.reddit._fetcher import InvalidFeedSpecError
from chattersift.reddit._fetcher import RedditHttpStatusError
from chattersift.reddit._fetcher import RedditRateLimitError
from chattersift.reddit._fetcher import RedditTimeoutError
from chattersift.reddit._fetcher import RedditTransportError
from chattersift.reddit._fetcher import UnsupportedFeedSpecError
from chattersift.reddit._fetcher import build_request_url
from chattersift.reddit._fetcher import fetch_and_parse
from chattersift.reddit.contracts import RedditFeedFormat
from chattersift.reddit.contracts import RedditFeedKind
from chattersift.reddit.contracts import RedditFeedSpec

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "reddit" / "raw"


def _spec(
    *,
    kind: RedditFeedKind,
    feed_format: RedditFeedFormat,
    subreddit: str,
    query: str = "",
) -> RedditFeedSpec:
    return RedditFeedSpec(
        kind=kind,
        format=feed_format,
        subreddit=subreddit,
        query=query,
        query_fingerprint="fp",
    )


def _split_url(url: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urlparse(url)
    return parsed.path, parse_qs(parsed.query)


def _run(coro):
    return asyncio.run(coro)


def test_build_request_url_post_stream_rss() -> None:
    path, query = _split_url(
        build_request_url(
            _spec(
                kind=RedditFeedKind.POST_STREAM,
                feed_format=RedditFeedFormat.RSS,
                subreddit="django",
            ),
        ),
    )

    assert path == "/r/django/new.rss"
    assert query["limit"] == ["100"]


def test_build_request_url_comment_stream_json() -> None:
    path, query = _split_url(
        build_request_url(
            _spec(
                kind=RedditFeedKind.COMMENT_STREAM,
                feed_format=RedditFeedFormat.JSON,
                subreddit="django+Python",
            ),
        ),
    )

    assert path == "/r/django+Python/comments.json"
    assert query["limit"] == ["100"]


def test_build_request_url_post_search_sitewide_json() -> None:
    path, query = _split_url(
        build_request_url(
            _spec(
                kind=RedditFeedKind.POST_SEARCH,
                feed_format=RedditFeedFormat.JSON,
                subreddit="",
                query='"django" OR "htmx"',
            ),
        ),
    )

    assert path == "/search.json"
    assert query["q"] == ['"django" OR "htmx"']
    assert query["sort"] == ["new"]
    assert query["limit"] == ["100"]
    assert query["raw_json"] == ["1"]
    assert "restrict_sr" not in query


def test_build_request_url_post_search_subreddit_rss() -> None:
    path, query = _split_url(
        build_request_url(
            _spec(
                kind=RedditFeedKind.POST_SEARCH,
                feed_format=RedditFeedFormat.RSS,
                subreddit="django",
                query='"postgres"',
            ),
        ),
    )

    assert path == "/r/django/search.rss"
    assert query["q"] == ['"postgres"']
    assert query["restrict_sr"] == ["1"]
    assert "raw_json" not in query


def test_build_request_url_comment_search_json() -> None:
    path, query = _split_url(
        build_request_url(
            _spec(
                kind=RedditFeedKind.COMMENT_SEARCH,
                feed_format=RedditFeedFormat.JSON,
                subreddit="django",
                query='"postgres"',
            ),
        ),
    )

    assert path == "/r/django/search.json"
    assert query["type"] == ["comment"]
    assert query["raw_json"] == ["1"]
    assert query["restrict_sr"] == ["1"]


def test_comment_search_rss_is_rejected() -> None:
    with pytest.raises(UnsupportedFeedSpecError, match="COMMENT_SEARCH"):
        build_request_url(
            _spec(
                kind=RedditFeedKind.COMMENT_SEARCH,
                feed_format=RedditFeedFormat.RSS,
                subreddit="django",
                query="django",
            ),
        )


def test_invalid_subreddit_path_tokens_are_rejected() -> None:
    with pytest.raises(InvalidFeedSpecError):
        build_request_url(
            _spec(
                kind=RedditFeedKind.POST_STREAM,
                feed_format=RedditFeedFormat.RSS,
                subreddit="django/../bad",
            ),
        )


def test_fetch_and_parse_json_sets_user_agent(settings) -> None:
    settings.CHATTERSIFT_REDDIT_USER_AGENT = "chattersift-test-agent"
    raw_json = json.loads((FIXTURE_ROOT / "single_subreddit_django_new.json").read_text())
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, json=raw_json)

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(base_url="https://www.reddit.com", transport=transport)
    with asyncio.Runner() as runner:
        payloads = runner.run(
            fetch_and_parse(
                _spec(
                    kind=RedditFeedKind.POST_STREAM,
                    feed_format=RedditFeedFormat.JSON,
                    subreddit="django",
                ),
                client=async_client,
            ),
        )
        runner.run(async_client.aclose())

    assert seen["path"] == "/r/django/new.json"
    assert seen["ua"] == "chattersift-test-agent"
    assert payloads
    assert payloads[0].reddit_id.startswith("t3_")


def test_fetch_and_parse_atom_content(settings) -> None:
    settings.CHATTERSIFT_REDDIT_USER_AGENT = "chattersift-test-agent"
    atom_text = (FIXTURE_ROOT / "single_subreddit_django_new.atom").read_text()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=atom_text)

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(base_url="https://www.reddit.com", transport=transport)
    with asyncio.Runner() as runner:
        payloads = runner.run(
            fetch_and_parse(
                _spec(
                    kind=RedditFeedKind.POST_STREAM,
                    feed_format=RedditFeedFormat.RSS,
                    subreddit="django",
                ),
                client=async_client,
            ),
        )
        runner.run(async_client.aclose())

    assert payloads
    assert payloads[0].reddit_id.startswith("t3_")


def test_429_raises_rate_limit_error(settings) -> None:
    settings.CHATTERSIFT_REDDIT_USER_AGENT = "chattersift-test-agent"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(base_url="https://www.reddit.com", transport=transport)
    with pytest.raises(RedditRateLimitError):
        _run(
            fetch_and_parse(
                _spec(
                    kind=RedditFeedKind.POST_STREAM,
                    feed_format=RedditFeedFormat.JSON,
                    subreddit="django",
                ),
                client=async_client,
            ),
        )
    _run(async_client.aclose())


def test_non_2xx_raises_http_status_error(settings) -> None:
    settings.CHATTERSIFT_REDDIT_USER_AGENT = "chattersift-test-agent"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(base_url="https://www.reddit.com", transport=transport)
    with pytest.raises(RedditHttpStatusError):
        _run(
            fetch_and_parse(
                _spec(
                    kind=RedditFeedKind.POST_STREAM,
                    feed_format=RedditFeedFormat.JSON,
                    subreddit="django",
                ),
                client=async_client,
            ),
        )
    _run(async_client.aclose())


def test_timeout_raises_reddit_timeout_error(settings) -> None:
    settings.CHATTERSIFT_REDDIT_USER_AGENT = "chattersift-test-agent"

    async def handler(request: httpx.Request) -> httpx.Response:
        msg = "timed out"
        raise httpx.ReadTimeout(msg)

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(base_url="https://www.reddit.com", transport=transport)
    with pytest.raises(RedditTimeoutError, match="ReadTimeout: timed out"):
        _run(
            fetch_and_parse(
                _spec(
                    kind=RedditFeedKind.POST_STREAM,
                    feed_format=RedditFeedFormat.JSON,
                    subreddit="django",
                ),
                client=async_client,
            ),
        )
    _run(async_client.aclose())


def test_transport_error_raises_reddit_transport_error(settings) -> None:
    settings.CHATTERSIFT_REDDIT_USER_AGENT = "chattersift-test-agent"

    async def handler(request: httpx.Request) -> httpx.Response:
        msg = "network down"
        raise httpx.ConnectError(msg)

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(base_url="https://www.reddit.com", transport=transport)
    with pytest.raises(RedditTransportError, match="ConnectError: network down"):
        _run(
            fetch_and_parse(
                _spec(
                    kind=RedditFeedKind.POST_STREAM,
                    feed_format=RedditFeedFormat.JSON,
                    subreddit="django",
                ),
                client=async_client,
            ),
        )
    _run(async_client.aclose())
