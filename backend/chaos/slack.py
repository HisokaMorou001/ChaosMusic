import os
import json
import time
import traceback
import random
from threading import Thread

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from slack_sdk import WebClient

from .services import fetch_5_tracks
from .models import Poll, Track, Vote


client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))

# poll_id -> tracks fissi
POLL_TRACK_CACHE = {}

# poll_id -> leaderboard message ts (NON channel)
LEADERBOARD_MESSAGE_CACHE = {}


# -----------------------------
# MODAL (solo input)
# -----------------------------
def build_modal(tracks, poll_id):
    return {
        "type": "modal",
        "callback_id": "vote_modal",
        "private_metadata": str(poll_id),
        "title": {"type": "plain_text", "text": "Vota brano"},
        "submit": {"type": "plain_text", "text": "Vota"},
        "blocks": [
            {
                "type": "input",
                "block_id": "track_block",
                "label": {"type": "plain_text", "text": "Scegli un brano"},
                "element": {
                    "type": "radio_buttons",
                    "action_id": "track",
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": t["title"][:75]},
                            "value": t["video_id"]
                        }
                        for t in tracks
                    ]
                }
            }
        ]
    }


# -----------------------------
# LEADERBOARD
# -----------------------------
def get_leaderboard(poll):
    votes = Vote.objects.filter(poll=poll)

    counts = {}
    for v in votes:
        counts[v.track_id] = counts.get(v.track_id, 0) + 1

    tracks = Track.objects.filter(id__in=counts.keys())

    leaderboard = []
    for t in tracks:
        leaderboard.append({
            "id": t.id,
            "title": t.title,
            "votes": counts.get(t.id, 0)
        })

    # include anche canzoni senza voti
    all_tracks = POLL_TRACK_CACHE.get(poll.id, [])
    for t in all_tracks:
        track_obj = Track.objects.filter(youtube_video_id=t["video_id"]).first()
        if track_obj and track_obj.id not in counts:
            leaderboard.append({
                "id": track_obj.id,
                "title": track_obj.title,
                "votes": 0
            })

    leaderboard.sort(key=lambda x: x["votes"], reverse=True)
    return leaderboard


def build_leaderboard_text(poll):
    leaderboard = get_leaderboard(poll)

    if not leaderboard:
        return "📊 Nessun voto ancora"

    max_votes = max(x["votes"] for x in leaderboard)

    lines = ["📊 *Leaderboard live*\n"]

    total = sum(x["votes"] for x in leaderboard)

    for i, item in enumerate(leaderboard, start=1):
        bar_len = int((item["votes"] / max_votes) * 10) if max_votes else 0
        bar = "█" * bar_len

        lines.append(
            f"{i}. *{item['title']}*\n"
            f"{bar} {item['votes']} voti"
        )

    lines.append(f"\n👥 Totale voti: {total}")

    return "\n\n".join(lines)


def update_leaderboard(poll):
    ts = LEADERBOARD_MESSAGE_CACHE.get(poll.id)
    if not ts:
        return

    client.chat_update(
        channel=poll.channel_id,
        ts=ts,
        text=build_leaderboard_text(poll)
    )


# -----------------------------
# WINNER
# -----------------------------
def compute_winner(poll):
    votes = Vote.objects.filter(poll=poll)

    if not votes.exists():
        return None

    counts = {}

    for v in votes:
        counts[v.track_id] = counts.get(v.track_id, 0) + 1

    max_votes = max(counts.values())
    top = [tid for tid, c in counts.items() if c == max_votes]

    winner_id = random.choice(top)

    return Track.objects.get(id=winner_id)


# -----------------------------
# TIMER
# -----------------------------
def poll_timer(poll_id):
    time.sleep(300)

    try:
        poll = Poll.objects.get(id=poll_id)

        if not poll.is_open:
            return

        poll.is_open = False
        poll.ended_at = timezone.now()
        poll.save()

        winner = compute_winner(poll)

        final_text = build_leaderboard_text(poll) + "\n\n"

        if winner:
            final_text += (
                "🏆 *SONDAGGIO TERMINATO*\n"
                f"*Vincitore: {winner.title}*\n"
                f"https://youtu.be/{winner.youtube_video_id}"
            )
        else:
            final_text += "❌ Nessun voto ricevuto"

        update_leaderboard(poll)

        ts = LEADERBOARD_MESSAGE_CACHE.get(poll.id)
        if ts:
            client.chat_update(
                channel=poll.channel_id,
                ts=ts,
                text=final_text
            )
        else:
            client.chat_postMessage(
                channel=poll.channel_id,
                text=final_text
            )

        POLL_TRACK_CACHE.pop(poll.id, None)
        LEADERBOARD_MESSAGE_CACHE.pop(poll.id, None)

    except Exception:
        traceback.print_exc()


# -----------------------------
# START
# -----------------------------
@csrf_exempt
def slack_start(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    trigger_id = request.POST.get("trigger_id")
    channel_id = request.POST.get("channel_id")

    if not trigger_id or not channel_id:
        return HttpResponse("missing data", status=400)

    try:
        tracks = fetch_5_tracks("music")

        poll = Poll.objects.create(
            is_open=True,
            channel_id=channel_id,
            created_at=timezone.now()
        )

        POLL_TRACK_CACHE[poll.id] = tracks

        # 1) leaderboard iniziale (MESSAGGIO FISSO)
        msg = client.chat_postMessage(
            channel=channel_id,
            text=build_leaderboard_text(poll)
        )

        LEADERBOARD_MESSAGE_CACHE[poll.id] = msg["ts"]

        # 2) messaggio voto (sempre sotto)
        client.chat_postMessage(
            channel=channel_id,
            text="<!channel> 🎵 Sondaggio attivo (5 minuti)",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "🎵 *Vota la tua canzone preferita*"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Vota"},
                            "action_id": "open_vote",
                            "value": str(poll.id)
                        }
                    ]
                }
            ]
        )

        Thread(target=poll_timer, args=(poll.id,)).start()

        return JsonResponse({"ok": True})

    except Exception:
        traceback.print_exc()
        return HttpResponse("error", status=500)


# -----------------------------
# INTERACTIONS
# -----------------------------
@csrf_exempt
def slack_interactions(request):
    try:
        payload = json.loads(request.POST.get("payload", "{}"))

        # OPEN MODAL
        if payload.get("type") == "block_actions":
            action = payload["actions"][0]

            if action["action_id"] == "open_vote":
                poll_id = int(action["value"])
                poll = Poll.objects.get(id=poll_id)

                if not poll.is_open:
                    return JsonResponse({"text": "Sondaggio chiuso"})

                tracks = POLL_TRACK_CACHE.get(poll_id)

                client.views_open(
                    trigger_id=payload["trigger_id"],
                    view=build_modal(tracks, poll.id)
                )

                return JsonResponse({"ok": True})

        # VOTE
        if payload.get("type") == "view_submission":
            user_id = payload["user"]["id"]
            poll_id = int(payload["view"]["private_metadata"])
            poll = Poll.objects.get(id=poll_id)

            if not poll.is_open:
                return JsonResponse({"response_action": "clear"})

            if Vote.objects.filter(poll=poll, slack_user_id=user_id).exists():
                return JsonResponse({
                    "response_action": "errors",
                    "errors": {"track_block": "Hai già votato"}
                })

            value = payload["view"]["state"]["values"]["track_block"]["track"]["selected_option"]["value"]

            track, _ = Track.objects.get_or_create(
                youtube_video_id=value,
                defaults={"title": "", "thumbnail_url": ""}
            )

            Vote.objects.create(
                poll=poll,
                track=track,
                slack_user_id=user_id
            )

            update_leaderboard(poll)

            return JsonResponse({"response_action": "clear"})

        return JsonResponse({"ok": True})

    except Exception:
        traceback.print_exc()
        return HttpResponse("error", status=500)