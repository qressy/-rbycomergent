from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.http import JsonResponse
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from chattersift.alerts.models import NotificationCadence
from chattersift.core.extension_points import MonitorPolicyError
from chattersift.core.extension_points import get_dashboard_settings_context
from chattersift.core.extension_points import get_monitor_policy
from chattersift.reddit.contracts import MonitorMatchMode

from .forms import MATCH_RETENTION_FOREVER_VALUE
from .forms import CadenceForm
from .forms import MatchRetentionForm
from .forms import MonitorAddForm
from .forms import MonitorBatchForm
from .forms import MonitorEditForm
from .forms import normalize_subreddit
from .keyword_extraction import KeywordExtractionError
from .keyword_extraction import extract_keywords_from_url
from .models import LeadStatus
from .models import Match
from .models import MatchDismissal
from .models import MatchRetentionPreference
from .models import Monitor
from .querysets import MonitorAlreadyExistsError

if TYPE_CHECKING:
    from django.http import HttpRequest


_RUN_NOW_COOLDOWN_SECONDS = 30 * 60


def _run_now_cache_key(user_id: int, subreddit: str) -> str:
    return f"run_now:{user_id}:{subreddit.casefold()}"


def _run_now_cooldown_remaining(user_id: int, subreddit: str) -> int:
    expires_at = cache.get(_run_now_cache_key(user_id, subreddit))
    if not expires_at:
        return 0
    from time import time
    remaining = int(expires_at - time())
    return max(remaining, 0)


def _trigger_subreddit_fetch(user_id: int, subreddit: str, *, trigger: str = "manual") -> None:
    from time import time

    from chattersift.reddit.tasks import fetch_subreddit

    normalized = subreddit.casefold()
    cache.set(
        _run_now_cache_key(user_id, normalized),
        time() + _RUN_NOW_COOLDOWN_SECONDS,
        _RUN_NOW_COOLDOWN_SECONDS,
    )
    fetch_subreddit.delay(normalized, trigger=trigger, user_id=user_id)


@login_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    """Renders the authenticated Reddit keyword dashboard."""

    context = _dashboard_context(request)
    context["dash_active_nav"] = "monitors"
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_dashboard_content.html", context)
    return render(request, "tracking/dashboard.html", context)


@login_required
@require_GET
def leads(request: HttpRequest) -> HttpResponse:
    """Renders the leads workflow (CRM-style split-pane over matches)."""

    context = _leads_context(request)
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_leads_content.html", context)
    return render(request, "tracking/leads.html", context)


@login_required
@require_POST
def lead_mark_contacted(request: HttpRequest, pk: int) -> HttpResponse:
    from django.utils import timezone
    match = get_object_or_404(Match, pk=pk, monitor__user=request.user)
    match.lead_status = LeadStatus.CONTACTED
    match.contacted_at = timezone.now()
    match.save(update_fields=["lead_status", "contacted_at"])
    return render(request, "tracking/_leads_content.html", _leads_context(request, selected_pk=match.pk))


@login_required
@require_POST
def lead_mark_new(request: HttpRequest, pk: int) -> HttpResponse:
    match = get_object_or_404(Match, pk=pk, monitor__user=request.user)
    match.lead_status = LeadStatus.NEW
    match.contacted_at = None
    match.save(update_fields=["lead_status", "contacted_at"])
    return render(request, "tracking/_leads_content.html", _leads_context(request, selected_pk=match.pk))


@login_required
@require_POST
def lead_delete(request: HttpRequest, pk: int) -> HttpResponse:
    match = get_object_or_404(Match, pk=pk, monitor__user=request.user)
    reddit_item_id = match.reddit_item_id
    match.delete()
    MatchDismissal.objects.get_or_create(user=request.user, reddit_item_id=reddit_item_id)
    return render(request, "tracking/_leads_content.html", _leads_context(request))


def _leads_context(request: HttpRequest, *, selected_pk: int | None = None) -> dict[str, object]:
    status = request.GET.get("status") or LeadStatus.NEW
    if status not in {LeadStatus.NEW, LeadStatus.CONTACTED}:
        status = LeadStatus.NEW

    selected_monitor: Monitor | None = None
    try:
        monitor_param = int(request.GET.get("monitor", "") or 0)
    except (TypeError, ValueError):
        monitor_param = 0
    if monitor_param:
        selected_monitor = Monitor.objects.filter(pk=monitor_param, user=request.user).first()

    base_qs = Match.objects.filter(monitor__user=request.user, lead_status=status)
    if selected_monitor is not None:
        base_qs = base_qs.filter(monitor=selected_monitor)

    leads_list = list(base_qs.select_related("monitor").order_by("-occurred_at")[:200])

    counts_qs = Match.objects.filter(monitor__user=request.user)
    if selected_monitor is not None:
        counts_qs = counts_qs.filter(monitor=selected_monitor)
    new_count = counts_qs.filter(lead_status=LeadStatus.NEW).count()
    contacted_count = counts_qs.filter(lead_status=LeadStatus.CONTACTED).count()

    selected = None
    if selected_pk:
        selected = next((m for m in leads_list if m.pk == selected_pk), None)
    if selected is None:
        try:
            selected_param = int(request.GET.get("lead", "") or 0)
        except (TypeError, ValueError):
            selected_param = 0
        if selected_param:
            selected = next((m for m in leads_list if m.pk == selected_param), None)
    if selected is None and leads_list:
        selected = leads_list[0]

    llm_enabled = bool(settings.CHATTERSIFT_SEMANTIC_LLM_MODEL and settings.CHATTERSIFT_SEMANTIC_LLM_API_KEY)

    return {
        "dash_active_nav": "leads",
        "leads": leads_list,
        "selected": selected,
        "selected_monitor": selected_monitor,
        "status": status,
        "new_count": new_count,
        "contacted_count": contacted_count,
        "llm_enabled": llm_enabled,
    }


@login_required
@require_GET
def runs(request: HttpRequest) -> HttpResponse:
    """Lists every fetch run, newest first, optionally filtered by subreddit."""

    from chattersift.reddit.models import FetchRun
    selected_sub = (request.GET.get("subreddit") or "").strip().casefold()
    runs_qs = FetchRun.objects.all().select_related("user")
    if selected_sub:
        runs_qs = runs_qs.filter(subreddit=selected_sub)
    runs_list = list(runs_qs[:200])
    subreddit_options = list(
        FetchRun.objects.values_list("subreddit", flat=True).distinct().order_by("subreddit"),
    )
    context = {
        "dash_active_nav": "runs",
        "runs": runs_list,
        "selected_subreddit": selected_sub,
        "subreddit_options": subreddit_options,
    }
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_runs_content.html", context)
    return render(request, "tracking/runs.html", context)


@login_required
@require_GET
def overview(request: HttpRequest) -> HttpResponse:
    """Renders the at-a-glance Dashboard with KPIs and activity."""

    range_key = request.GET.get("range") or "7d"
    context = {
        "dash_active_nav": "dashboard",
        "overview": _build_dashboard_overview(request.user, range_key=range_key),
    }
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_overview_content.html", context)
    return render(request, "tracking/overview.html", context)


@login_required
@require_POST
def keywords_from_url(request: HttpRequest) -> JsonResponse:
    """Extracts candidate keywords from a public URL and remembers it for the user."""

    raw_url = (request.POST.get("url") or request.user.keyword_extraction_url or "").strip()
    if not raw_url:
        return JsonResponse({"error": "Set your company URL in Settings first."}, status=400)
    try:
        keywords = extract_keywords_from_url(raw_url)
    except KeywordExtractionError as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse({"keywords": keywords})


@login_required
@require_POST
def monitor_create(request: HttpRequest) -> HttpResponse:
    """Creates or reactivates keyword monitors for one subreddit."""

    form = MonitorBatchForm(request.POST, user=request.user)
    is_valid = form.is_valid()
    inline_info: dict[str, object] | None = None
    if is_valid:
        try:
            Monitor.objects.upsert_from_intent(
                user=request.user,
                subreddit=form.cleaned_data["subreddit"],
                match_mode=form.cleaned_data["match_mode"],
                keywords=form.cleaned_data["keywords"],
                semantic_description=form.cleaned_data["semantic_description"],
                cadence=form.cleaned_data["cadence"],
            )
        except MonitorPolicyError as error:
            form.add_error(error.field, str(error))
        else:
            subreddit = form.cleaned_data["subreddit"]
            if _run_now_cooldown_remaining(request.user.id, subreddit) == 0:
                _trigger_subreddit_fetch(request.user.id, subreddit, trigger="auto")
                inline_info = {
                    "kind": "auto_run",
                    "subreddit": subreddit,
                    "message": f"Monitor created — fetching r/{subreddit} now.",
                }
            form = MonitorBatchForm(user=request.user)

    return _render_dashboard_content(request, form=form, inline_info=inline_info)


@login_required
@require_POST
def monitor_add(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Adds one monitor (keyword, semantic, or hybrid) to an existing group."""

    try:
        normalized_subreddit = normalize_subreddit(subreddit)
    except ValidationError as error:
        inline_error = {
            "kind": "add",
            "subreddit": subreddit.casefold(),
            "match_mode": request.POST.get("match_mode") or "",
            "message": _validation_first_error(error),
        }
        return _render_dashboard_content(
            request,
            form=MonitorBatchForm(user=request.user),
            inline_error=inline_error,
        )

    form = MonitorAddForm(request.POST, user=request.user, subreddit=normalized_subreddit)
    inline_error: dict[str, object] | None = None
    if form.is_valid():
        try:
            Monitor.objects.add_to_subreddit(
                user=request.user,
                subreddit=normalized_subreddit,
                match_mode=form.cleaned_data["match_mode"],
                keyword=form.cleaned_data["keyword"],
                semantic_description=form.cleaned_data["semantic_description"],
            )
        except MonitorAlreadyExistsError:
            inline_error = {
                "kind": "add",
                "subreddit": normalized_subreddit,
                "match_mode": form.cleaned_data["match_mode"],
                "message": "A monitor with these settings already exists for this subreddit.",
            }
        except MonitorPolicyError as error:
            inline_error = {
                "kind": "add",
                "subreddit": normalized_subreddit,
                "match_mode": form.cleaned_data["match_mode"],
                "message": str(error),
            }
    else:
        inline_error = {
            "kind": "add",
            "subreddit": normalized_subreddit,
            "match_mode": form.cleaned_data.get("match_mode") or "",
            "message": _form_first_error(form),
        }

    return _render_dashboard_content(
        request,
        form=MonitorBatchForm(user=request.user),
        inline_error=inline_error,
    )


@login_required
@require_POST
def monitor_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edits one monitor's mode and content in place."""

    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    form = MonitorEditForm(request.POST, user=request.user, subreddit=monitor.subreddit, monitor=monitor)
    inline_error: dict[str, object] | None = None
    if form.is_valid():
        try:
            Monitor.objects.update_for_user(
                user=request.user,
                pk=monitor.pk,
                match_mode=form.cleaned_data["match_mode"],
                keyword=form.cleaned_data["keyword"],
                semantic_description=form.cleaned_data["semantic_description"],
            )
        except MonitorAlreadyExistsError:
            inline_error = {
                "kind": "edit",
                "monitor_pk": monitor.pk,
                "message": "A monitor with these settings already exists for this subreddit.",
            }
        except MonitorPolicyError as error:
            inline_error = {
                "kind": "edit",
                "monitor_pk": monitor.pk,
                "message": str(error),
            }
    else:
        inline_error = {
            "kind": "edit",
            "monitor_pk": monitor.pk,
            "message": _form_first_error(form),
        }

    return _render_dashboard_content(
        request,
        form=MonitorBatchForm(user=request.user),
        inline_error=inline_error,
    )


@login_required
@require_POST
def monitor_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Permanently deletes one keyword monitor."""

    Monitor.objects.delete_for_user(user=request.user, pk=pk)
    return _render_dashboard_content(request, form=MonitorBatchForm(user=request.user))


@login_required
@require_POST
def monitor_deactivate(request: HttpRequest, pk: int) -> HttpResponse:
    """Deactivates one current-user monitor without deleting history."""

    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    if monitor.is_active:
        monitor.is_active = False
        monitor.save(update_fields=["is_active", "updated_at"])

    return _render_dashboard_content(request, form=MonitorBatchForm(user=request.user))


@login_required
@require_POST
def monitor_run_now_group(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Triggers an immediate Reddit fetch for the given subreddit, with a 30-minute cooldown."""

    normalized = subreddit.casefold()
    remaining = _run_now_cooldown_remaining(request.user.id, normalized)
    if remaining > 0:
        minutes = max(1, (remaining + 59) // 60)
        return _render_dashboard_content(
            request,
            form=MonitorBatchForm(user=request.user),
            inline_error={
                "kind": "run_now",
                "subreddit": normalized,
                "message": f"r/{normalized} was fetched recently. Try again in {minutes} min.",
            },
        )
    _trigger_subreddit_fetch(request.user.id, normalized)
    return _render_dashboard_content(
        request,
        form=MonitorBatchForm(user=request.user),
        inline_info={
            "kind": "run_now",
            "subreddit": normalized,
            "message": f"Fetching r/{normalized} now — new matches will appear in a moment.",
        },
    )


@login_required
@require_POST
def monitor_toggle_group(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Pauses or resumes all monitors for a subreddit."""

    inline_error: dict[str, object] | None = None
    try:
        Monitor.objects.toggle_subreddit_group(user=request.user, subreddit=subreddit)
    except MonitorPolicyError as error:
        inline_error = {
            "kind": "group",
            "subreddit": subreddit.casefold(),
            "message": str(error),
        }
    return _render_dashboard_content(request, form=MonitorBatchForm(user=request.user), inline_error=inline_error)


@login_required
@require_POST
def monitor_delete_group(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Permanently deletes all monitors for a subreddit."""

    Monitor.objects.delete_subreddit_group(user=request.user, subreddit=subreddit)
    return _render_dashboard_content(request, form=MonitorBatchForm(user=request.user))


@login_required
@require_POST
def monitor_update_cadence(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Updates notification cadence for all monitors in a subreddit group."""

    form = CadenceForm(request.POST, user=request.user, subreddit=subreddit.casefold())
    inline_error: dict[str, object] | None = None
    if form.is_valid():
        try:
            Monitor.objects.update_group_cadence(
                user=request.user,
                subreddit=subreddit,
                cadence=form.cleaned_data["cadence"],
            )
        except MonitorPolicyError as error:
            inline_error = {
                "kind": "cadence",
                "subreddit": subreddit.casefold(),
                "message": str(error),
            }
    else:
        inline_error = {
            "kind": "cadence",
            "subreddit": subreddit.casefold(),
            "message": _form_first_error(form),
        }

    return _render_dashboard_content(
        request,
        form=MonitorBatchForm(user=request.user),
        inline_error=inline_error,
    )


@login_required
@require_GET
def matches(request: HttpRequest) -> HttpResponse:
    """Renders the matched content page."""

    selected_subreddit = request.GET.get("subreddit")
    page = _positive_int_or_default(request.GET.get("page"), default=1)
    feed = Match.objects.feed_for_user(request.user, subreddit=selected_subreddit, page=page)

    previous_page_url = _matches_query_url(
        subreddit=feed.selected_subreddit,
        page=feed.page - 1,
    )
    next_page_url = _matches_query_url(
        subreddit=feed.selected_subreddit,
        page=feed.page + 1,
    )
    page_links = _matches_page_links(
        subreddit=feed.selected_subreddit,
        current_page=feed.page,
        total_pages=feed.total_pages,
    )

    context = {
        "feed": feed,
        "has_matches": bool(feed.items),
        "has_monitors": bool(feed.subreddit_options),
        "previous_page_url": previous_page_url,
        "next_page_url": next_page_url,
        "page_links": page_links,
        "dash_active_nav": "matches",
    }
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_matches_content.html", context)
    return render(request, "tracking/matches.html", context)


@login_required
@require_POST
def match_dismiss(request: HttpRequest, reddit_item_id: str) -> HttpResponse:
    """Dismiss one Reddit item from the user's matches feed; HTMX removes the row."""

    MatchDismissal.objects.dismiss(user=request.user, reddit_item_id=reddit_item_id)
    # Empty body so hx-swap="outerHTML" removes the matched row.
    return HttpResponse(status=200)


@login_required
@require_GET
def dashboard_settings(request: HttpRequest) -> HttpResponse:
    """Renders the consolidated dashboard settings page."""

    context = _settings_context(request)
    if request.headers.get("HX-Request"):
        return render(request, "dash/_settings_content.html", context)
    return render(request, "dash/settings.html", context)


@login_required
@require_POST
def keyword_extraction_url_update(request: HttpRequest) -> HttpResponse:
    """Saves the user's company URL used for keyword suggestions."""

    raw = (request.POST.get("keyword_extraction_url") or "").strip()
    if raw and not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    request.user.keyword_extraction_url = raw[:500]
    request.user.save(update_fields=["keyword_extraction_url"])
    return render(request, "dash/_settings_content.html", _settings_context(request))


@login_required
@require_POST
def match_retention_update(request: HttpRequest) -> HttpResponse:
    """Updates matched-item retention and prunes newly expired current-user matches."""

    form = MatchRetentionForm(request.POST)
    if form.is_valid():
        MatchRetentionPreference.objects.update_days_for_user(
            user=request.user,
            retention_days=form.cleaned_data["retention_days"],
        )
        Match.objects.prune_expired_for_user(user=request.user)
        form = _match_retention_form(request)

    return render(request, "dash/_settings_content.html", _settings_context(request, match_retention_form=form))


_RANGE_CHOICES = {
    "7d": {"days": 7, "label": "7 days", "bucket": "day"},
    "30d": {"days": 30, "label": "30 days", "bucket": "day"},
    "90d": {"days": 90, "label": "90 days", "bucket": "week"},
    "all": {"days": None, "label": "All time", "bucket": "month"},
}


def _build_dashboard_overview(user, range_key: str = "7d") -> dict[str, object]:
    """Aggregates KPIs, a sparkline, and top lists for the dashboard overview."""
    from datetime import timedelta
    from django.db.models import Count, Min
    from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
    from django.utils import timezone

    cfg = _RANGE_CHOICES.get(range_key, _RANGE_CHOICES["7d"])
    now = timezone.now()
    today = now.date()

    user_matches = Match.objects.filter(monitor__user=user)

    if cfg["days"] is None:
        first_dt = user_matches.aggregate(d=Min("created_at"))["d"]
        range_start = first_dt.date() if first_dt else today
        range_count = user_matches.count()
        prev_count = 0
    else:
        range_start = today - timedelta(days=cfg["days"] - 1)
        prev_start = today - timedelta(days=cfg["days"] * 2 - 1)
        range_count = user_matches.filter(created_at__date__gte=range_start).count()
        prev_count = user_matches.filter(
            created_at__date__gte=prev_start, created_at__date__lt=range_start,
        ).count()

    today_count = user_matches.filter(created_at__date=today).count()
    yesterday_count = user_matches.filter(created_at__date=today - timedelta(days=1)).count()

    bucket = cfg["bucket"]
    trunc = {"day": TruncDate, "week": TruncWeek, "month": TruncMonth}[bucket]
    counts = dict(
        user_matches.filter(created_at__date__gte=range_start)
        .annotate(b=trunc("created_at"))
        .values("b")
        .annotate(n=Count("id"))
        .values_list("b", "n"),
    )

    def _normalize(key):
        if hasattr(key, "date"):
            return key.date()
        return key

    counts_by_date = {_normalize(k): v for k, v in counts.items()}
    spark_points = []
    if bucket == "day":
        days = (today - range_start).days + 1
        for i in range(days):
            d = range_start + timedelta(days=i)
            spark_points.append({"day": d.strftime("%b %-d"), "n": counts_by_date.get(d, 0)})
    elif bucket == "week":
        cur = range_start - timedelta(days=range_start.weekday())
        while cur <= today:
            spark_points.append({"day": cur.strftime("%b %-d"), "n": counts_by_date.get(cur, 0)})
            cur += timedelta(weeks=1)
    else:
        from datetime import date as _date
        cur = _date(range_start.year, range_start.month, 1)
        end_marker = _date(today.year, today.month, 1)
        while cur <= end_marker:
            spark_points.append({"day": cur.strftime("%b %Y"), "n": counts_by_date.get(cur, 0)})
            if cur.month == 12:
                cur = _date(cur.year + 1, 1, 1)
            else:
                cur = _date(cur.year, cur.month + 1, 1)

    if not spark_points:
        spark_points = [{"day": today.strftime("%b %-d"), "n": 0}]
    spark_max = max((p["n"] for p in spark_points), default=0) or 1
    spark_divisor = max(len(spark_points) - 1, 1)
    label_every = 1 if len(spark_points) <= 8 else max(len(spark_points) // 7, 1)
    for i, p in enumerate(spark_points):
        p["show_label"] = (i % label_every == 0) or (i == len(spark_points) - 1)
    show_dots = len(spark_points) <= 14

    top_subs = list(
        user_matches.filter(created_at__date__gte=range_start)
        .values("monitor__subreddit")
        .annotate(n=Count("id"))
        .order_by("-n")[:5]
        .values_list("monitor__subreddit", "n"),
    )
    top_keywords = list(
        user_matches.filter(created_at__date__gte=range_start)
        .exclude(monitor__keyword="")
        .values("monitor__keyword")
        .annotate(n=Count("id"))
        .order_by("-n")[:5]
        .values_list("monitor__keyword", "n"),
    )

    active_monitors = Monitor.objects.filter(user=user, is_active=True).count()

    def _delta_pct(now_val: int, prev_val: int) -> int | None:
        if prev_val == 0:
            return None if now_val == 0 else 100
        return round((now_val - prev_val) / prev_val * 100)

    return {
        "total_matches": user_matches.count(),
        "range_matches": range_count,
        "range_delta_pct": _delta_pct(range_count, prev_count) if cfg["days"] else None,
        "range_label": cfg["label"],
        "range_key": range_key,
        "range_choices": [(k, v["label"]) for k, v in _RANGE_CHOICES.items()],
        "today_matches": today_count,
        "today_delta_pct": _delta_pct(today_count, yesterday_count),
        "active_monitors": active_monitors,
        "spark_points": spark_points,
        "spark_max": spark_max,
        "spark_divisor": spark_divisor,
        "show_dots": show_dots,
        "top_subreddits": [{"name": s, "n": n} for s, n in top_subs],
        "top_keywords": [{"name": k, "n": n} for k, n in top_keywords],
    }


def _resolve_selected_subreddit(request: HttpRequest, subreddit_groups) -> str | None:
    requested = (request.GET.get("subreddit") or "").strip().casefold()
    available = [g.subreddit for g in subreddit_groups]
    if requested and requested in available:
        return requested
    if available:
        return available[0]
    return None


def _dashboard_context(
    request: HttpRequest,
    *,
    form: MonitorBatchForm | None = None,
    inline_error: dict[str, object] | None = None,
    inline_info: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the dashboard template context for full-page and partial renders."""
    subreddit_groups = Monitor.objects.dashboard_groups_for_user(request.user, include_matches=False)
    from django.db.models import Count, Min, Max
    from chattersift.reddit.models import FetchRun, SubredditFetchState

    subreddit_names = [g.subreddit for g in subreddit_groups]
    next_fetch_by_subreddit: dict[str, object] = dict(
        SubredditFetchState.objects.filter(subreddit__in=subreddit_names)
        .values("subreddit")
        .annotate(next=Min("next_fetch_at"))
        .values_list("subreddit", "next"),
    )
    last_run_by_subreddit: dict[str, object] = dict(
        FetchRun.objects.filter(subreddit__in=subreddit_names)
        .values("subreddit")
        .annotate(last=Max("started_at"))
        .values_list("subreddit", "last"),
    )
    run_count_by_subreddit: dict[str, int] = dict(
        FetchRun.objects.filter(subreddit__in=subreddit_names)
        .values("subreddit")
        .annotate(n=Count("id"))
        .values_list("subreddit", "n"),
    )

    match_counts_by_monitor: dict[int, int] = dict(
        Match.objects.filter(monitor__user=request.user)
        .values_list("monitor_id")
        .annotate(n=Count("id"))
        .values_list("monitor_id", "n"),
    )
    match_counts_by_subreddit: dict[str, int] = {}
    for group in subreddit_groups:
        total = sum(match_counts_by_monitor.get(m.pk, 0) for m in group.monitors)
        if total:
            match_counts_by_subreddit[group.subreddit] = total
    run_now_cooldowns: dict[str, int] = {}
    for group in subreddit_groups:
        subreddit_value = getattr(group, "subreddit", None) or (group.get("subreddit") if isinstance(group, dict) else None)
        if not subreddit_value:
            continue
        remaining = _run_now_cooldown_remaining(request.user.id, subreddit_value)
        if remaining > 0:
            run_now_cooldowns[subreddit_value.casefold()] = max(1, (remaining + 59) // 60)
    form = form or MonitorBatchForm(user=request.user)
    policy = get_monitor_policy()
    cadence_choices = policy.filter_cadence_choices(
        user=request.user,
        choices=NotificationCadence.choices,
    )
    match_mode_choices = policy.filter_match_mode_choices(
        user=request.user,
        choices=MonitorMatchMode.choices,
    )
    return {
        "form": form,
        "show_monitor_form": form.is_bound and bool(form.errors),
        "subreddit_groups": subreddit_groups,
        "selected_subreddit": _resolve_selected_subreddit(request, subreddit_groups),
        "cadence_choices": cadence_choices,
        "match_mode_choices": match_mode_choices,
        "allowed_match_modes": tuple(value for value, _ in match_mode_choices),
        "inline_error": inline_error,
        "inline_info": inline_info,
        "run_now_cooldowns": run_now_cooldowns,
        "match_counts_by_monitor": match_counts_by_monitor,
        "match_counts_by_subreddit": match_counts_by_subreddit,
        "next_fetch_by_subreddit": next_fetch_by_subreddit,
        "last_run_by_subreddit": last_run_by_subreddit,
        "run_count_by_subreddit": run_count_by_subreddit,
        "overview": _build_dashboard_overview(request.user),
    }


def _settings_context(
    request: HttpRequest,
    *,
    match_retention_form: MatchRetentionForm | None = None,
) -> dict[str, object]:
    """Build the settings template context for full-page and partial renders."""

    context = {
        "dash_active_nav": "settings",
        "match_retention_form": match_retention_form or _match_retention_form(request),
        "dashboard_settings_extension_template": settings.CHATTERSIFT_DASHBOARD_SETTINGS_EXTENSION_TEMPLATE,
    }
    context.update(get_dashboard_settings_context(request))
    return context


def _match_retention_form(request: HttpRequest) -> MatchRetentionForm:
    """Return the current user's matched-item retention form."""

    retention_days = MatchRetentionPreference.objects.get_days_for_user(request.user)
    initial = MATCH_RETENTION_FOREVER_VALUE if retention_days is None else str(retention_days)
    return MatchRetentionForm(initial={"retention_days": initial})


def _render_dashboard_content(
    request: HttpRequest,
    *,
    form: MonitorBatchForm,
    inline_error: dict[str, object] | None = None,
    inline_info: dict[str, object] | None = None,
) -> HttpResponse:
    """Render just the dashboard content fragment used by HTMX updates."""
    html = render_to_string(
        "tracking/_dashboard_content.html",
        _dashboard_context(request, form=form, inline_error=inline_error, inline_info=inline_info),
        request=request,
    )
    return HttpResponse(html)


def _form_first_error(form: CadenceForm | MonitorAddForm | MonitorEditForm) -> str:
    """Return the first error message from a bound form for inline display."""
    for errors in form.errors.values():
        if errors:
            return str(errors[0])
    return "Invalid input."


def _validation_first_error(error: ValidationError) -> str:
    """Return the first message from a standalone validation error."""
    if error.messages:
        return str(error.messages[0])
    return "Invalid input."


def _matches_query_url(*, subreddit: str | None, page: int) -> str:
    """Build a stable query string for matches filters and pagination links."""
    params = QueryDict(mutable=True)
    if subreddit:
        params["subreddit"] = subreddit
    if page > 1:
        params["page"] = str(page)
    query_string = params.urlencode()
    if not query_string:
        return ""
    return f"?{query_string}"


def _matches_page_links(
    *,
    subreddit: str | None,
    current_page: int,
    total_pages: int,
) -> tuple[dict[str, object], ...]:
    """Build numbered pager links with ellipses for jumping across pages.

    Always shows the first and last page, the current page, and one neighbour
    on either side. Inserts ellipsis markers across gaps so the pager stays
    compact regardless of total_pages.
    """
    if total_pages <= 1:
        return ()
    visible = sorted(
        {
            1,
            total_pages,
            current_page - 1,
            current_page,
            current_page + 1,
        },
    )
    visible = [p for p in visible if 1 <= p <= total_pages]
    links: list[dict[str, object]] = []
    previous_page = 0
    for page_number in visible:
        if page_number - previous_page > 1:
            links.append({"is_ellipsis": True})
        links.append(
            {
                "page": page_number,
                "url": _matches_query_url(subreddit=subreddit, page=page_number),
                "is_current": page_number == current_page,
                "is_ellipsis": False,
            },
        )
        previous_page = page_number
    return tuple(links)


def _positive_int_or_default(raw_value: str | None, *, default: int) -> int:
    """Parse a positive integer, or fall back to the provided default value."""
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
