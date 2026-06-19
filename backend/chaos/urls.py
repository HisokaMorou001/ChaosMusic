from django.urls import path
from . import slack

urlpatterns = [
    path("slack/start/", slack.slack_start),
    path("slack/interactions/", slack.slack_interactions),
]