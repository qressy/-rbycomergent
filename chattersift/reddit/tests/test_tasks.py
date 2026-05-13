from __future__ import annotations

from chattersift.reddit.clients import RedditClient
from chattersift.reddit.tasks import fetch_subreddit


class StubClient(RedditClient):
    def fetch_feed(self, spec):  # pragma: no cover
        return []


def test_fetch_subreddit_uses_default_client_factory(monkeypatch) -> None:
    expected_result = 3
    calls = {"factory": 0, "service": 0}

    def fake_build_default_reddit_client() -> RedditClient:
        calls["factory"] += 1
        return StubClient()

    def fake_fetch_normalize_and_match(subreddit: str, *, client: RedditClient) -> int:
        calls["service"] += 1
        assert subreddit == "django"
        assert isinstance(client, StubClient)
        return expected_result

    monkeypatch.setattr(
        "chattersift.reddit.tasks.build_default_reddit_client",
        fake_build_default_reddit_client,
    )
    monkeypatch.setattr(
        "chattersift.reddit.tasks.fetch_normalize_and_match",
        fake_fetch_normalize_and_match,
    )

    assert fetch_subreddit("django") == expected_result
    assert calls == {"factory": 1, "service": 1}
