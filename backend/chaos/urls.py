from django.urls import path
from . import slack, views

urlpatterns = [
    # Kiosk root serves the frontend index
    path("", views.kiosk_index),
    # API endpoints
    path("slack/start/", slack.slack_start),
    path("slack/interactions/", slack.slack_interactions),
    path("api/queue/next", views.next_track),
    path("api/queue/winner", views.winner),
    # Cron endpoint must come before the frontend catch-all so it's reachable
    path('cron/auto-start/', views.cron_trigger_start, name='cron_trigger_start'),
    path('cron/weekly-recap/', views.cron_weekly_recap, name='cron_weekly_recap'),
    # Serve frontend assets (app.js, etc.) from the frontend folder
    path("<path:path>", views.frontend_file),
]