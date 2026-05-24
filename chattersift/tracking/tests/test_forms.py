from __future__ import annotations

from chattersift.alerts.models import NotificationCadence
from chattersift.tracking.forms import MonitorBatchForm


def test_monitor_batch_form_normalizes_subreddit_prefix() -> None:
    form = MonitorBatchForm(data={"subreddit": "r/Django", "keywords": "postgres"})

    assert form.is_valid()
    assert form.cleaned_data["subreddit"] == "django"
    assert form.cleaned_data["cadence"] == NotificationCadence.THIRTY_MINUTES


def test_monitor_batch_form_rejects_unsafe_subreddit_tokens() -> None:
    form = MonitorBatchForm(data={"subreddit": "django/new", "keywords": "postgres"})

    assert not form.is_valid()
    assert "subreddit" in form.errors


def test_monitor_batch_form_rejects_empty_keywords() -> None:
    form = MonitorBatchForm(data={"subreddit": "django", "keywords": "\n,  "})

    assert not form.is_valid()
    assert "keywords" in form.errors


def test_monitor_batch_form_dedupes_keywords_case_insensitively() -> None:
    form = MonitorBatchForm(data={"subreddit": "django", "keywords": "Postgres\npostgres\nHTMX", "cadence": "off"})

    assert form.is_valid()
    assert form.cleaned_data["keywords"] == ["Postgres", "HTMX"]


def test_monitor_batch_form_enforces_model_field_lengths() -> None:
    form = MonitorBatchForm(data={"subreddit": "a" * 101, "keywords": "b" * 256})

    assert not form.is_valid()
    assert "subreddit" in form.errors
    assert "keywords" in form.errors


def test_monitor_batch_form_accepts_semantic_only_without_keywords(settings) -> None:
    settings.CHATTERSIFT_SEMANTIC_LLM_MODEL = "openai/gpt-4o-mini"
    form = MonitorBatchForm(
        data={
            "subreddit": "django",
            "match_mode": "semantic",
            "keywords": "",
            "semantic_description": "Django performance problems",
        },
    )

    assert form.is_valid()
    assert form.cleaned_data["keywords"] == []


def test_monitor_batch_form_rejects_semantic_when_model_missing(settings) -> None:
    settings.CHATTERSIFT_SEMANTIC_LLM_MODEL = ""
    form = MonitorBatchForm(
        data={
            "subreddit": "django",
            "match_mode": "semantic",
            "semantic_description": "Django performance problems",
        },
    )

    assert not form.is_valid()
    assert "semantic_description" in form.errors
