from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from ._fetcher import fetch_and_parse_sync
from .contracts import RedditFeedFormat

if TYPE_CHECKING:
    from .contracts import RedditFeedSpec
    from .contracts import RedditItemPayload


class RedditClient:
    """Interface for fetching normalized items from a Reddit feed spec."""

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        """Return feed entries normalized as Reddit item payloads."""
        raise NotImplementedError


class RssRedditClient(RedditClient):
    """RSS-backed Reddit feed client."""

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        """Fetch and parse the Reddit RSS feed represented by the spec."""
        return fetch_and_parse_sync(spec)


class JsonRedditClient(RedditClient):
    """JSON-backed Reddit feed client."""

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        """Fetch and parse the Reddit JSON feed represented by the spec."""
        return fetch_and_parse_sync(spec)


class DefaultRedditClient(RedditClient):
    """Client dispatcher that selects RSS or JSON implementation per spec."""

    def __init__(self) -> None:
        self._rss_client = RssRedditClient()
        self._json_client = JsonRedditClient()

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        if spec.format == RedditFeedFormat.RSS:
            return self._rss_client.fetch_feed(spec)
        return self._json_client.fetch_feed(spec)


def build_default_reddit_client() -> RedditClient:
    """Return the default synchronous Reddit client used by ingestion/tasks."""
    preferred_format = RedditFeedFormat(settings.CHATTERSIFT_REDDIT_FEED_FORMAT)
    if preferred_format == RedditFeedFormat.RSS:
        return RssRedditClient()
    if preferred_format == RedditFeedFormat.JSON:
        return JsonRedditClient()
    return DefaultRedditClient()
