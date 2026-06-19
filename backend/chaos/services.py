import os
from googleapiclient.discovery import build
from django.utils import timezone
from datetime import timedelta
import random

from .models import Poll, Vote

youtube = build(
    "youtube", "v3",
    developerKey=os.getenv("YOUTUBE_API_KEY")
)

def fetch_5_tracks(query="music"):
    res = youtube.search().list(
        q=query,
        part="snippet",
        type="video",
        maxResults=5
    ).execute()

    tracks = []

    for item in res["items"]:
        tracks.append({
            "video_id": item["id"]["videoId"][:50],
            "title": item["snippet"]["title"][:75],
            "thumbnail": item["snippet"]["thumbnails"]["default"]["url"],
        })

    return tracks

def close_poll_and_compute_winner(poll_id):
    poll = Poll.objects.get(id=poll_id)
    poll.is_open = False

    votes = Vote.objects.filter(poll=poll)

    if not votes.exists():
        poll.save()
        return None

    # conta voti
    counts = {}
    for v in votes:
        counts[v.track_id] = counts.get(v.track_id, 0) + 1

    max_votes = max(counts.values())

    top_tracks = [
        track_id for track_id, c in counts.items()
        if c == max_votes
    ]

    winner_id = random.choice(top_tracks)

    poll.winner_id = winner_id
    poll.save()

    return poll.winner