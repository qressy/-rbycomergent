from __future__ import annotations

import logging
from dataclasses import asdict

from celery import shared_task

from .clients import build_default_reddit_client
from .ingestion import fetch_due_feeds
from .models import RedditItem
from .policy import DEFAULT_REDDIT_COLLECTION_LANE
from .services import fetch_normalize_and_match

logger = logging.getLogger(__name__)


@shared_task()
def fetch_due_reddit_feeds(
    limit: int | None = None,
    lane: str = DEFAULT_REDDIT_COLLECTION_LANE,
) -> dict:
    """Fetch currently due Reddit feeds through the synchronous core pipeline."""
    logger.info("scheduler tick: fetch_due_reddit_feeds lane=%s limit=%s", lane, limit)
    result = asdict(fetch_due_feeds(limit=limit, lane=lane))
    logger.info("scheduler tick complete: %s", result)
    return result


@shared_task()
def fetch_subreddit(subreddit: str, *, trigger: str = "scheduled", user_id: int | None = None) -> int:
    """Fetch a single subreddit and log the run."""

    from django.utils import timezone

    from .models import FetchRun, FetchRunStatus, FetchRunTrigger

    run = FetchRun.objects.create(
        subreddit=subreddit,
        trigger=trigger if trigger in FetchRunTrigger.values else FetchRunTrigger.SCHEDULED,
        user_id=user_id,
    )
    logger.info("fetch_subreddit start: run_id=%s subreddit=%s trigger=%s user_id=%s", run.id, subreddit, trigger, user_id)
    try:
        matches_created = fetch_normalize_and_match(subreddit, client=build_default_reddit_client())
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        run.status = (
            FetchRunStatus.RATE_LIMITED if "rate limit" in message.lower() else FetchRunStatus.FAILED
        )
        run.error = message[:500]
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        logger.exception(
            "fetch_subreddit failed: run_id=%s subreddit=%s status=%s error=%s",
            run.id, subreddit, run.status, message,
        )
        raise
    run.status = FetchRunStatus.SUCCESS
    run.matches_created = matches_created or 0
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "matches_created", "finished_at"])
    logger.info(
        "fetch_subreddit success: run_id=%s subreddit=%s matches_created=%s duration=%.2fs",
        run.id, subreddit, matches_created,
        (run.finished_at - run.started_at).total_seconds(),
    )
    return matches_created


@shared_task()
def prune_unmatched_reddit_items(retention_days: int | None = None) -> int:
    """Delete old unmatched RedditItem cache rows."""
    return RedditItem.objects.prune_expired(retention_days=retention_days)
