from __future__ import annotations

import logging
import os
import sys
import time
import traceback
from dataclasses import asdict

from celery import shared_task

from .clients import build_default_reddit_client
from .ingestion import fetch_due_feeds
from .models import RedditItem
from .policy import DEFAULT_REDDIT_COLLECTION_LANE
from .services import fetch_normalize_and_match

logger = logging.getLogger(__name__)


def _diag(msg: str) -> None:
    """Print diagnostic to stdout directly, bypassing logging config."""
    print(f"[DIAG pid={os.getpid()} t={time.strftime('%H:%M:%S')}] {msg}", flush=True)
    sys.stdout.flush()


@shared_task(bind=True)
def fetch_due_reddit_feeds(
    self,
    limit: int | None = None,
    lane: str = DEFAULT_REDDIT_COLLECTION_LANE,
) -> dict:
    """Fetch currently due Reddit feeds through the synchronous core pipeline."""
    _diag(f"fetch_due_reddit_feeds ENTER task_id={self.request.id} lane={lane} limit={limit}")
    logger.info("scheduler tick: fetch_due_reddit_feeds lane=%s limit=%s", lane, limit)
    started = time.monotonic()
    try:
        _diag("fetch_due_reddit_feeds -> calling fetch_due_feeds()")
        result = asdict(fetch_due_feeds(limit=limit, lane=lane))
        elapsed = time.monotonic() - started
        _diag(f"fetch_due_reddit_feeds DONE in {elapsed:.2f}s result={result}")
        logger.info("scheduler tick complete in %.2fs: %s", elapsed, result)
        return result
    except Exception as exc:
        elapsed = time.monotonic() - started
        _diag(f"fetch_due_reddit_feeds RAISED after {elapsed:.2f}s: {exc.__class__.__name__}: {exc}")
        _diag(f"traceback:\n{traceback.format_exc()}")
        logger.exception("scheduler tick failed after %.2fs", elapsed)
        raise


@shared_task(bind=True)
def fetch_subreddit(
    self, subreddit: str, *, trigger: str = "scheduled", user_id: int | None = None,
) -> int:
    """Fetch a single subreddit and log the run."""

    from django.utils import timezone

    from .models import FetchRun, FetchRunStatus, FetchRunTrigger

    _diag(f"fetch_subreddit ENTER task_id={self.request.id} subreddit={subreddit} trigger={trigger} user_id={user_id}")
    run = FetchRun.objects.create(
        subreddit=subreddit,
        trigger=trigger if trigger in FetchRunTrigger.values else FetchRunTrigger.SCHEDULED,
        user_id=user_id,
    )
    _diag(f"fetch_subreddit created FetchRun id={run.id}")
    logger.info("fetch_subreddit start: run_id=%s subreddit=%s trigger=%s user_id=%s", run.id, subreddit, trigger, user_id)
    started = time.monotonic()
    try:
        _diag(f"fetch_subreddit -> calling fetch_normalize_and_match({subreddit!r})")
        matches_created = fetch_normalize_and_match(subreddit, client=build_default_reddit_client())
        _diag(f"fetch_subreddit fetch_normalize_and_match returned matches={matches_created}")
    except Exception as exc:
        elapsed = time.monotonic() - started
        message = str(exc) or exc.__class__.__name__
        run.status = (
            FetchRunStatus.RATE_LIMITED if "rate limit" in message.lower() else FetchRunStatus.FAILED
        )
        run.error = message[:500]
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        _diag(f"fetch_subreddit FAILED run_id={run.id} after {elapsed:.2f}s status={run.status} error={message}")
        _diag(f"traceback:\n{traceback.format_exc()}")
        logger.exception(
            "fetch_subreddit failed: run_id=%s subreddit=%s status=%s error=%s",
            run.id, subreddit, run.status, message,
        )
        raise
    run.status = FetchRunStatus.SUCCESS
    run.matches_created = matches_created or 0
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "matches_created", "finished_at"])
    elapsed = time.monotonic() - started
    _diag(f"fetch_subreddit SUCCESS run_id={run.id} matches={matches_created} in {elapsed:.2f}s")
    logger.info(
        "fetch_subreddit success: run_id=%s subreddit=%s matches_created=%s duration=%.2fs",
        run.id, subreddit, matches_created, elapsed,
    )
    return matches_created


@shared_task()
def prune_unmatched_reddit_items(retention_days: int | None = None) -> int:
    """Delete old unmatched RedditItem cache rows."""
    return RedditItem.objects.prune_expired(retention_days=retention_days)
