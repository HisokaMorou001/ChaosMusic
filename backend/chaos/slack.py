import os
import json
import time
import traceback
import random
from threading import Thread
from html import unescape

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.conf import settings

from slack_sdk import WebClient

from .services import fetch_5_tracks_ai
from .models import Poll, Track, Vote

import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# Inizializzazione del client Slack
client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))

# Cache globali in memoria per gestire lo stato dei thread e dei dati stabili
POLL_TRACK_CACHE = {}
LEADERBOARD_MESSAGE_CACHE = {}
POLL_UPDATER_RUNNING = {}
LAST_GENERATED_TRACKS = []


# -----------------------------
# MODAL (solo input)
# -----------------------------
def build_modal(tracks, poll_id):
    """Costruisce la finestra modale per la votazione delle tracce."""
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
                            "text": {"type": "plain_text", "text": unescape(t.title[:75])},
                            "value": str(t.id) 
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
    """Recupera l'elenco delle tracce ordinate per numero di voti."""
    votes = Vote.objects.filter(poll=poll)

    counts = {}
    for v in votes:
        counts[v.track_id] = counts.get(v.track_id, 0) + 1

    track_ids = POLL_TRACK_CACHE.get(poll.id, [])
    leaderboard = []
    
    for track_id in track_ids:
        track_obj = Track.objects.filter(id=track_id).first()
        if track_obj:
            leaderboard.append({
                "id": track_obj.id,
                "title": unescape(track_obj.title),
                "votes": counts.get(track_id, 0)
            })

    leaderboard.sort(key=lambda x: x["votes"], reverse=True)
    return leaderboard


def build_leaderboard_text(poll):
    """Genera il layout testuale grafico della classifica."""
    leaderboard = get_leaderboard(poll)

    if not leaderboard:
        return ":bar_chart: Nessun voto ancora"

    max_votes = max(x["votes"] for x in leaderboard) if leaderboard else 1
    total = sum(x["votes"] for x in leaderboard)

    lines = [":trophy: *LEADERBOARD LIVE*\n"]

    for i, item in enumerate(leaderboard, start=1):
        percentage = int((item["votes"] / total) * 100) if total > 0 else 0
        bar_len = int((item["votes"] / max_votes) * 20) if max_votes > 0 else 0
        bar = "█" * bar_len + "░" * (20 - bar_len)
        votes_text = f"{item['votes']} voto" if item['votes'] == 1 else f"{item['votes']} voti"

        lines.append(f"{i}) {unescape(item['title'])}")
        lines.append(f"{bar} {votes_text} ({percentage}%)\n")

    lines.append("\n━━━━━━━━━━━━━━━━━━")
    lines.append(f"\n:busts_in_silhouette: Totale voti: {total}")

    return "\n".join(lines)


def update_leaderboard(poll):
    """Esegue l'aggiornamento parziale del solo messaggio di classifica."""
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
    """Calcola il vincitore gestendo eventuali pareggi in modo casuale."""
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


def send_weekly_recap(channel_id, count=3):
    """Collect the winners of the most recent `count` finished polls and post a recap."""
    try:
        polls = Poll.objects.filter(is_open=False, ended_at__isnull=False).order_by("-ended_at")[:count]
        if not polls:
            client.chat_postMessage(channel=channel_id, text="Nessun sondaggio recente da riepilogare.")
            return

        lines = [":trophy: Weekly Recap — vincitori degli ultimi sondaggi :trophy:\n"]
        for i, p in enumerate(polls, start=1):
            try:
                winner = compute_winner(p)
                title = unescape(winner.title) if winner else "(nessun voto)"
                vid = winner.youtube_video_id if winner else None
                if vid:
                    lines.append(f"{i}) {title} — https://youtu.be/{vid}")
                else:
                    lines.append(f"{i}) {title}")
            except Exception:
                lines.append(f"{i}) Errore nel calcolare il vincitore")

        text = "\n".join(lines)
        client.chat_postMessage(channel=channel_id, text=text)

        # also post to alternate channel if configured
        try:
            alt = getattr(settings, "CRON_SLACK_ALT_CHANNEL", "")
            if alt:
                client.chat_postMessage(channel=alt, text=text)
        except Exception:
            logger.exception("failed to post weekly recap to alt channel")

    except Exception:
        logger.exception("send_weekly_recap failed")

    # Reset votes and reopen polls for the next week
    try:
        from .models import Vote
        for p in polls:
            try:
                Vote.objects.filter(poll=p).delete()
                p.is_open = True
                p.ended_at = None
                p.leaderboard_ts = None
                p.kiosk_played = False
                p.save()
            except Exception:
                logger.exception("failed to reset poll %s", getattr(p, 'id', 'unknown'))
    except Exception:
        logger.exception("failed to clear votes after recap")


# -----------------------------
# THREADS TIMERS
# -----------------------------
def leaderboard_updater(poll_id):
    """Thread: Aggiorna la classifica visiva su Slack ogni 5 secondi."""
    try:
        while POLL_UPDATER_RUNNING.get(poll_id, False):
            time.sleep(5)
            
            if not POLL_UPDATER_RUNNING.get(poll_id, False):
                break

            try:
                poll = Poll.objects.get(id=poll_id)
                if poll.is_open:
                    update_leaderboard(poll)
            except Poll.DoesNotExist:
                break
            except Exception:
                pass
    except Exception:
        traceback.print_exc()
    finally:
        POLL_UPDATER_RUNNING.pop(poll_id, None)


def finalize_poll(poll_id):
    """Finalize a poll: close, compute winner, and announce it on Slack.

    This is factored out so we can call it both from the timer and manually
    during tests.
    """
    try:
        poll = Poll.objects.get(id=poll_id)

        if not poll.is_open:
            logger.info("finalize_poll: poll %s already closed", poll_id)
            return

        # stop leaderboard updates
        POLL_UPDATER_RUNNING[poll_id] = False
        time.sleep(1)

        poll.is_open = False
        poll.ended_at = timezone.now()
        poll.save()

        # compute winner
        votes = Vote.objects.filter(poll=poll)
        logger.info("finalize_poll: poll=%s channel=%s votes=%s", poll.id, poll.channel_id, votes.count())
        winner = compute_winner(poll)
        final_text = build_leaderboard_text(poll) + "\n\n"

        if winner:
            final_text += (
                ":trophy: *SONDAGGIO TERMINATO*\n"
                f"Vincitore: {unescape(winner.title)}\n"
                f"https://youtu.be/{winner.youtube_video_id}"
            )
            logger.info("finalize_poll: winner for poll %s is track %s", poll.id, getattr(winner, 'id', None))
        else:
            final_text += ":x: Nessun voto ricevuto"
            logger.info("finalize_poll: no winner for poll %s (no votes)", poll.id)

        ts = LEADERBOARD_MESSAGE_CACHE.get(poll.id)
        # Try update first, fall back to postMessage on failure
        if ts:
            try:
                resp = client.chat_update(channel=poll.channel_id, ts=ts, text=final_text)
                logger.info("finalize_poll: chat_update response=%s", resp)
            except Exception as e:
                logger.exception("finalize_poll: chat_update failed, falling back to postMessage")
                try:
                    resp = client.chat_postMessage(channel=poll.channel_id, text=final_text)
                    logger.info("finalize_poll: fallback postMessage response=%s", resp)
                except Exception:
                    logger.exception("finalize_poll: fallback postMessage also failed")
        else:
            try:
                resp = client.chat_postMessage(channel=poll.channel_id, text=final_text)
                logger.info("finalize_poll: postMessage response=%s", resp)
            except Exception:
                logger.exception("finalize_poll: postMessage failed")

        POLL_TRACK_CACHE.pop(poll.id, None)
        LEADERBOARD_MESSAGE_CACHE.pop(poll.id, None)

    except Poll.DoesNotExist:
        logger.warning("finalize_poll: poll %s does not exist", poll_id)
    except Exception:
        logger.exception("finalize_poll: unexpected error")


def poll_timer(poll_id):
    """Thread wrapper: sleep then finalize (test: 10s)."""
    time.sleep(10)
    finalize_poll(poll_id)


def background_poll_initializer(channel_id, poll_id):
    """Thread principale: elabora la pulizia pesante del DB, chiama l'AI e invia i blocchi a Slack."""
    global LAST_GENERATED_TRACKS
    try:
        logger.info("background_poll_initializer starting poll_id=%s channel=%s", poll_id, channel_id)
        # 1. Pulizia asincrona delle sessioni precedenti (spostata qui dal flusso principale)
        open_polls = Poll.objects.filter(is_open=True).exclude(id=poll_id)
        for p in open_polls:
            p.is_open = False
            p.save()
            POLL_UPDATER_RUNNING[p.id] = False 
        
        from django.db.models import Count
        Track.objects.annotate(vote_count=Count('votes')).filter(vote_count=0).delete()
        Vote.objects.filter(poll__is_open=False).delete()
        
        # 2. Recupero e validazione tracce AI
        tracks = fetch_5_tracks_ai()
        
        current_video_ids = {t['video_id'] for t in tracks}
        if LAST_GENERATED_TRACKS and current_video_ids == set(LAST_GENERATED_TRACKS):
            max_attempts = 3
            for _ in range(max_attempts):
                tracks = fetch_5_tracks_ai()
                current_video_ids = {t['video_id'] for t in tracks}
                if current_video_ids != set(LAST_GENERATED_TRACKS):
                    break
        
        if isinstance(LAST_GENERATED_TRACKS, list):
            LAST_GENERATED_TRACKS.clear()
            LAST_GENERATED_TRACKS.extend([t['video_id'] for t in tracks])

        # 3. Associazione e salvataggio delle tracce a DB
        poll = Poll.objects.get(id=poll_id)
        track_objs = []
        for t in tracks:
            track_obj = Track.objects.create(
                youtube_video_id=t["video_id"],
                title=t["title"],
                thumbnail_url=t["thumbnail"]
            )
            track_objs.append(track_obj)

        POLL_TRACK_CACHE[poll.id] = [t.id for t in track_objs]

        # 4. MESSAGGIO DI VOTO (SOPRA)
        try:
            resp = client.chat_postMessage(
                channel=channel_id,
                text="<!channel> :musical_note: Sondaggio attivo (60 minuti)",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "<!channel> *Vota la tua canzone preferita* :musical_note:"
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
            logger.info("chat_postMessage response: %s", resp)

            # Also post to alternate public channel if configured (helps visibility)
            try:
                alt = getattr(settings, "CRON_SLACK_ALT_CHANNEL", "")
                if alt:
                    alt_resp = client.chat_postMessage(
                        channel=alt,
                        text="Sondaggio attivo (60 minuti)",
                        blocks=[
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": "*Vota la tua canzone preferita* :musical_note:"
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
                    logger.info("chat_postMessage alt response: %s", alt_resp)
            except Exception:
                logger.exception("chat_postMessage to alt channel failed")

        except Exception:
            logger.exception("chat_postMessage failed")
        
        # 5. MESSAGGIO LEADERBOARD INIZIALE (SOTTO)
        try:
            msg = client.chat_postMessage(
                channel=channel_id,
                text=build_leaderboard_text(poll)
            )
            LEADERBOARD_MESSAGE_CACHE[poll.id] = msg["ts"]
            logger.info("leaderboard message sent, ts=%s", msg.get("ts"))
        except Exception:
            logger.exception("leaderboard chat_postMessage failed")

        # 6. Avvio dei timer asincroni separati
        POLL_UPDATER_RUNNING[poll.id] = True
        Thread(target=leaderboard_updater, args=(poll.id,)).start()
        Thread(target=poll_timer, args=(poll.id,)).start()

    except Exception:
        traceback.print_exc()


# -----------------------------
# START (Comando Slack)
# -----------------------------
@csrf_exempt
def slack_start(request):
    """Endpoint attivato dal comando Slash di Slack per iniziare il gioco."""
    # Support both: POST from Slack slash command, and GET from cron (secure)
    if request.method == "GET":
        token = request.GET.get("token")
        if not token or token != getattr(settings, "CRON_SECRET", ""):
            return HttpResponse("Forbidden", status=403)

        channel = getattr(settings, "CRON_SLACK_CHANNEL", "")
        if not channel:
            return HttpResponse("Server misconfigured: CRON_SLACK_CHANNEL not set", status=500)

        try:
            start_new_poll(channel)
            return HttpResponse("Sondaggio avviato via Cron", status=200)
        except Exception as e:
            return HttpResponse(f"Errore: {e}", status=500)

    if request.method != "POST":
        return HttpResponse(status=405)

    trigger_id = request.POST.get("trigger_id")
    channel_id = request.POST.get("channel_id")

    if not trigger_id or not channel_id:
        return HttpResponse("Missing data (trigger_id/channel_id)", status=400)

    try:
        # Creazione record a DB istantanea per generare il poll.id
        poll = Poll.objects.create(
            is_open=True,
            channel_id=channel_id,
            created_at=timezone.now()
        )

        # Avvio del thread in background a cui viene delegata tutta l'elaborazione pesante
        Thread(target=background_poll_initializer, args=(channel_id, poll.id)).start()

        # Risposta immediata a Slack entro pochissimi millisecondi
        return HttpResponse("")

    except Exception:
        traceback.print_exc()
        return HttpResponse("Internal Server Error", status=500)


def start_new_poll(channel_id):
    """Programmatic entry point to start a poll (used by cron endpoint).

    Creates the Poll record and launches the background initializer thread,
    mirroring the behaviour of the `/start` Slack command.
    """
    poll = Poll.objects.create(
        is_open=True,
        channel_id=channel_id,
        created_at=timezone.now()
    )

    Thread(target=background_poll_initializer, args=(channel_id, poll.id)).start()
    return poll.id


# -----------------------------
# INTERACTIONS (Pulsanti e Modal)
# -----------------------------
@csrf_exempt
def slack_interactions(request):
    """Endpoint unico per gestire i clic sui pulsanti e l'invio del modal."""
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        payload = json.loads(request.POST.get("payload", "{}"))
        payload_type = payload.get("type")

        # EVENTO A: Clic sul pulsante "Vota" -> Apertura Modal
        if payload_type == "block_actions":
            action = payload["actions"][0]

            if action["action_id"] == "open_vote":
                poll_id = int(action["value"])
                poll = Poll.objects.get(id=poll_id)

                if not poll.is_open:
                    return JsonResponse({"text": "Sondaggio chiuso"})

                track_ids = POLL_TRACK_CACHE.get(poll_id, [])
                tracks = Track.objects.filter(id__in=track_ids).order_by("id")

                if not tracks.exists():
                    return JsonResponse({"text": "Nessun brano disponibile per questo sondaggio."})

                client.views_open(
                    trigger_id=payload["trigger_id"],
                    view=build_modal(tracks, poll.id)
                )
                return HttpResponse("")

        # EVENTO B: Invio del Form dal Modal -> Registrazione Voto
        if payload_type == "view_submission":
            user_id = payload["user"]["id"]
            poll_id = int(payload["view"]["private_metadata"])
            poll = Poll.objects.get(id=poll_id)

            if not poll.is_open:
                return JsonResponse({"response_action": "clear"})

            # Verifica unicità del voto
            if Vote.objects.filter(poll=poll, slack_user_id=user_id).exists():
                return JsonResponse({
                    "response_action": "errors",
                    "errors": {"track_block": "Hai già votato in questo sondaggio."}
                })

            selected_values = payload["view"]["state"]["values"]["track_block"]["track"]["selected_option"]
            if not selected_values:
                return JsonResponse({
                    "response_action": "errors",
                    "errors": {"track_block": "Seleziona un'opzione prima di inviare."}
                })
                
            track_db_id = int(selected_values["value"])

            try:
                track = Track.objects.get(id=track_db_id)
            except Track.DoesNotExist:
                return JsonResponse({
                    "response_action": "errors",
                    "errors": {"track_block": "Traccia non trovata a database."}
                })

            # Salvataggio effettivo
            Vote.objects.create(
                poll=poll,
                track=track,
                slack_user_id=user_id
            )

            # Aggiornamento grafico della classifica in tempo reale
            update_leaderboard(poll)

            # Svuota e chiude il modal correttamente su Slack
            return JsonResponse({"response_action": "clear"})

        return HttpResponse("")

    except Exception:
        traceback.print_exc()
        return HttpResponse("Internal Error", status=500)