from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("dash/", views.dashboard, name="dashboard"),
    path("dash/overview/", views.overview, name="overview"),
    path("dash/monitors/", views.monitor_create, name="monitor_create"),
    path("dash/monitors/keywords-from-url/", views.keywords_from_url, name="keywords_from_url"),
    path("dash/monitors/<int:pk>/deactivate/", views.monitor_deactivate, name="monitor_deactivate"),
    path("dash/monitors/<int:pk>/delete/", views.monitor_delete, name="monitor_delete"),
    path("dash/monitors/<int:pk>/edit/", views.monitor_edit, name="monitor_edit"),
    path("dash/monitors/<str:subreddit>/add/", views.monitor_add, name="monitor_add"),
    path("dash/monitors/<str:subreddit>/run-now/", views.monitor_run_now_group, name="monitor_run_now_group"),
    path("dash/monitors/<str:subreddit>/toggle/", views.monitor_toggle_group, name="monitor_toggle_group"),
    path("dash/monitors/<str:subreddit>/delete/", views.monitor_delete_group, name="monitor_delete_group"),
    path("dash/monitors/<str:subreddit>/cadence/", views.monitor_update_cadence, name="monitor_update_cadence"),
    path("dash/runs/", views.runs, name="runs"),
    path("dash/leads/", views.leads, name="leads"),
    path("dash/leads/<int:pk>/contacted/", views.lead_mark_contacted, name="lead_mark_contacted"),
    path("dash/leads/<int:pk>/new/", views.lead_mark_new, name="lead_mark_new"),
    path("dash/leads/<int:pk>/delete/", views.lead_delete, name="lead_delete"),
    path("dash/matches/", views.matches, name="matches"),
    path(
        "dash/matches/<str:reddit_item_id>/dismiss/",
        views.match_dismiss,
        name="match_dismiss",
    ),
    path("dash/settings/", views.dashboard_settings, name="dashboard_settings"),
    path("dash/settings/match-retention/", views.match_retention_update, name="match_retention_update"),
    path("dash/settings/keyword-extraction-url/", views.keyword_extraction_url_update, name="keyword_extraction_url_update"),
]
