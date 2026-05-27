from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

from allauth.account.models import EmailAddress
from celery import current_app
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists
from django.db.models import OuterRef
from django.template.loader import render_to_string
from django.utils import timezone

from chattersift.core.text_snippets import highlighted_snippet
from chattersift.core.text_snippets import plain_snippet
from chattersift.reddit.contracts import MonitorMatchMode
from chattersift.tracking.models import Match

from .models import EmailMatchDelivery
from .models import EmailNotificationPreference
from .models import EmailNotificationSchedule
from .models import NotificationCadence
from .schedules import CADENCE_INTERVALS
from .schedules import ensure_email_notifications_started
from .schedules import next_send_at

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from django.utils.safestring import SafeString

User = get_user_model()
EMAIL_TITLE_SNIPPET_LENGTH = 180
EMAIL_BODY_SNIPPET_LENGTH = 500


@dataclass(frozen=True, kw_only=True)
class UserMatchAlert:
    """Aggregated alert payload for one user and one Reddit item.

    Delivery code should use this payload when a user has several monitor
        rows matching the same Reddit item. Match rows stay per monitor for
        persistence, while alert payloads collapse duplicates for display.
    """

    user_id: int
    subreddit: str
    reddit_item_id: str
    matched_keywords: tuple[str, ...]
    monitor_labels: tuple[str, ...]
    match_ids: tuple[int, ...]
    monitor_ids: tuple[int, ...]
    title: str
    body: str
    permalink: str
    occurred_at: datetime


@dataclass(frozen=True, kw_only=True)
class RenderedUserMatchAlert:
    """Display-safe email content for one aggregated Reddit item."""

    user_id: int
    subreddit: str
    reddit_item_id: str
    matched_keywords: tuple[str, ...]
    monitor_labels: tuple[str, ...]
    match_ids: tuple[int, ...]
    monitor_ids: tuple[int, ...]
    title: str
    body: str
    title_snippet: str
    body_snippet: str
    highlighted_title_snippet: SafeString
    highlighted_body_snippet: SafeString
    highlighted_title: SafeString
    highlighted_body: SafeString
    permalink: str
    occurred_at: datetime


def update_email_notification_preference(*, user: User) -> EmailNotificationPreference:
    """Ensures the user's email delivery baseline exists."""

    return ensure_email_notifications_started(user=user)


def enqueue_immediate_match_notifications(match_ids: Iterable[int]) -> None:
    """Enqueues one immediate delivery task after the current transaction commits."""

    ids = sorted(set(match_ids))
    if not ids:
        return

    transaction.on_commit(
        lambda: current_app.send_task("chattersift.alerts.tasks.send_immediate_match_notifications", args=[ids]),
    )


def send_immediate_email_digests(match_ids: Iterable[int]) -> int:
    """Send grouped immediate digests for newly created matches from one ingest batch."""

    matches = Match.objects.filter(pk__in=match_ids).select_related("monitor", "monitor__user")
    user_ids = {match.monitor.user_id for match in matches if match.monitor.user_id is not None}
    sent_count = 0
    for preference in _eligible_preferences(user_ids=user_ids):
        pending_matches = _pending_matches_for_user(
            preference,
            monitor_cadences=[NotificationCadence.IMMEDIATE],
            match_ids=match_ids,
        )
        sent_count += int(_send_preference_digest(preference, pending_matches))
    return sent_count


def send_due_email_digests() -> int:
    """Send due periodic digests and retry any pending immediate notifications."""

    now = timezone.now()
    due_schedules = EmailNotificationSchedule.objects.filter(
        cadence__in=CADENCE_INTERVALS,
        next_send_at__lte=now,
        user__emailnotificationpreference__started_at__isnull=False,
    )
    sent_count = 0
    for preference in _preferences_with_monitor_cadence(cadence=NotificationCadence.IMMEDIATE):
        pending_matches = _pending_matches_for_user(
            preference,
            monitor_cadences=[NotificationCadence.IMMEDIATE],
        )
        sent_count += int(_send_preference_digest(preference, pending_matches, now=now))

    for schedule in due_schedules.select_related("user", "user__emailnotificationpreference"):
        preference = schedule.user.emailnotificationpreference
        pending_matches = _pending_matches_for_user(
            preference,
            monitor_cadences=[schedule.cadence],
        )
        sent_count += int(_send_preference_digest(preference, pending_matches, schedule=schedule, now=now))
        schedule.next_send_at = next_send_at(schedule.cadence, now=now)
        schedule.save(update_fields=["next_send_at", "updated_at"])
    return sent_count


def build_user_match_alerts(matches: Iterable[Match]) -> list[UserMatchAlert]:
    """Return user/item alert payloads aggregated from per-monitor matches.

    Input matches must have their related Monitor available. Callers with a
        queryset should prefer ``select_related("monitor")`` to avoid per-row
        database lookups. The output groups rows by user, subreddit, and Reddit
        item so delivery can send one alert with all matched keywords.
    """
    grouped_matches: dict[tuple[int, str, str], list[Match]] = {}
    subreddit_labels: dict[tuple[int, str, str], str] = {}

    for match in matches:
        monitor_user_id = cast("int", match.monitor.user_id)
        subreddit = cast("str", match.monitor.subreddit)
        reddit_item_id = cast("str", match.reddit_item_id)
        subreddit_key = subreddit.casefold()
        key = (monitor_user_id, subreddit_key, reddit_item_id)
        if key not in grouped_matches:
            grouped_matches[key] = []
            subreddit_labels[key] = subreddit
        grouped_matches[key].append(match)

    alerts: list[UserMatchAlert] = []
    for key, grouped in grouped_matches.items():
        first_match = grouped[0]
        alerts.append(
            UserMatchAlert(
                user_id=key[0],
                subreddit=subreddit_labels[key],
                reddit_item_id=key[2],
                matched_keywords=_matched_keywords(grouped),
                monitor_labels=_monitor_labels(grouped),
                match_ids=tuple(
                    sorted(match.pk for match in grouped if match.pk is not None),
                ),
                monitor_ids=tuple(sorted(match.monitor_id for match in grouped)),
                title=cast("str", first_match.title),
                body=cast("str", first_match.body),
                permalink=cast("str", first_match.permalink),
                occurred_at=cast("datetime", first_match.occurred_at),
            ),
        )

    return sorted(
        alerts,
        key=lambda alert: (
            alert.user_id,
            alert.subreddit.casefold(),
            alert.reddit_item_id,
        ),
    )


def _matched_keywords(matches: Iterable[Match]) -> tuple[str, ...]:
    """Return display keywords deduplicated case-insensitively."""
    keywords_by_key: dict[str, str] = {}
    for match in matches:
        if match.monitor.match_mode == MonitorMatchMode.SEMANTIC or not match.monitor.keyword:
            continue
        keyword = match.monitor.keyword
        keywords_by_key.setdefault(keyword.casefold(), keyword)

    return tuple(sorted(keywords_by_key.values(), key=str.casefold))


def _monitor_labels(matches: Iterable[Match]) -> tuple[str, ...]:
    """Return monitor labels deduplicated case-insensitively."""
    labels_by_key: dict[str, str] = {}
    for match in matches:
        label = match.monitor.label
        if label:
            labels_by_key.setdefault(label.casefold(), label)
    return tuple(sorted(labels_by_key.values(), key=str.casefold))


def render_user_match_alerts(alerts: Iterable[UserMatchAlert]) -> list[RenderedUserMatchAlert]:
    """Interface: add bounded text and HTML snippets for email rendering."""

    rendered_alerts = []
    for alert in alerts:
        title_snippet = plain_snippet(
            alert.title,
            keywords=alert.matched_keywords,
            max_length=EMAIL_TITLE_SNIPPET_LENGTH,
        )
        body_snippet = plain_snippet(
            alert.body,
            keywords=alert.matched_keywords,
            max_length=EMAIL_BODY_SNIPPET_LENGTH,
        )
        highlighted_title_snippet = highlighted_snippet(
            alert.title,
            keywords=alert.matched_keywords,
            max_length=EMAIL_TITLE_SNIPPET_LENGTH,
        )
        highlighted_body_snippet = highlighted_snippet(
            alert.body,
            keywords=alert.matched_keywords,
            max_length=EMAIL_BODY_SNIPPET_LENGTH,
        )
        rendered_alerts.append(
            RenderedUserMatchAlert(
                user_id=alert.user_id,
                subreddit=alert.subreddit,
                reddit_item_id=alert.reddit_item_id,
                matched_keywords=alert.matched_keywords,
                monitor_labels=alert.monitor_labels,
                match_ids=alert.match_ids,
                monitor_ids=alert.monitor_ids,
                title=alert.title,
                body=alert.body,
                title_snippet=title_snippet,
                body_snippet=body_snippet,
                highlighted_title_snippet=highlighted_title_snippet,
                highlighted_body_snippet=highlighted_body_snippet,
                highlighted_title=highlighted_title_snippet,
                highlighted_body=highlighted_body_snippet,
                permalink=alert.permalink,
                occurred_at=alert.occurred_at,
            ),
        )
    return rendered_alerts


def _eligible_preferences(*, user_ids: set[int]) -> list[EmailNotificationPreference]:
    """Load started email preferences for users that have pending match alerts."""
    return list(
        EmailNotificationPreference.objects.filter(
            user_id__in=user_ids,
            started_at__isnull=False,
        ).select_related("user"),
    )


def _preferences_with_monitor_cadence(*, cadence: str) -> list[EmailNotificationPreference]:
    """Load distinct started preferences for users with active monitors at a cadence."""
    return list(
        EmailNotificationPreference.objects.filter(
            started_at__isnull=False,
            user__monitor__is_active=True,
            user__monitor__notification_cadence=cadence,
        )
        .distinct()
        .select_related("user"),
    )


def _pending_matches_for_user(
    preference: EmailNotificationPreference,
    *,
    monitor_cadences: Iterable[str],
    match_ids: Iterable[int] | None = None,
):
    """Return undelivered matches for one user filtered by monitor cadence and ids."""
    delivered_items = EmailMatchDelivery.objects.filter(
        user_id=preference.user_id,
        reddit_item_id=OuterRef("reddit_item_id"),
    )
    matches = Match.objects.filter(
        monitor__user_id=preference.user_id,
        monitor__is_active=True,
        monitor__notification_cadence__in=monitor_cadences,
        created_at__gte=preference.started_at,
    )
    if match_ids is not None:
        matches = matches.filter(pk__in=match_ids)
    return (
        matches.annotate(already_delivered=Exists(delivered_items))
        .filter(already_delivered=False)
        .select_related("monitor")
    )


def _send_preference_digest(
    preference: EmailNotificationPreference,
    matches,
    *,
    schedule: EmailNotificationSchedule | None = None,
    now: datetime | None = None,
) -> bool:
    """Send one digest email and enqueue delivery tracking for included Reddit items."""
    alerts = build_user_match_alerts(matches)
    if not alerts or not _has_verified_account_email(preference):
        return False

    rendered_alerts = render_user_match_alerts(alerts)
    subject = _digest_subject(len(rendered_alerts))
    body = render_to_string("alerts/emails/match_digest.txt", {"alerts": rendered_alerts})
    html_body = render_to_string("alerts/emails/match_digest.html", {"alerts": rendered_alerts})
    sent_at = now or timezone.now()
    send_signature = current_app.signature(
        "chattersift.alerts.tasks.send_mail",
        kwargs={
            "subject": subject,
            "message": body,
            "from_email": settings.DEFAULT_FROM_EMAIL,
            "recipient_list": [preference.user.email],
            "html_message": html_body,
        },
    )
    delivery_signature = current_app.signature(
        "chattersift.alerts.tasks.record_match_email_delivery",
        kwargs={
            "user_id": preference.user_id,
            "reddit_item_ids": [alert.reddit_item_id for alert in alerts],
            "preference_id": preference.pk,
            "schedule_id": schedule.pk if schedule else None,
            "sent_at": sent_at.isoformat(),
        },
    )
    send_signature.apply_async(link=delivery_signature)
    return True


def _has_verified_account_email(preference: EmailNotificationPreference) -> bool:
    """Check whether the preference user has a verified account email address."""
    return EmailAddress.objects.filter(
        user_id=preference.user_id,
        email=preference.user.email,
        verified=True,
    ).exists()


def _digest_subject(alert_count: int) -> str:
    """Build singular/plural digest subject text based on alert count."""
    item_label = "match" if alert_count == 1 else "matches"
    return f"ChatterSift: {alert_count} new Reddit {item_label}"
