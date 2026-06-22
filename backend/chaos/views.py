from django.http import JsonResponse
import random

from .models import Track, Poll, Vote
from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from pathlib import Path
import mimetypes

from django.views.decorators.csrf import csrf_exempt
from . import slack  # Importa il tuo file slack.py

@csrf_exempt
def cron_trigger_start(request):
    """
    Endpoint segreto chiamato da cron-job.org per
    avviare il sondaggio in automatico a orari prestabiliti.
    """
    # Verifica token di sicurezza (passare ?token=... dalla chiamata di cron-job.org)
    token = request.GET.get("token") or request.POST.get("token")
    if not token or token != getattr(settings, "CRON_SECRET", ""):
        return HttpResponse("Forbidden", status=403)

    # Legge l'ID canale Slack dalla configurazione (env CRON_SLACK_CHANNEL)
    channel = getattr(settings, "CRON_SLACK_CHANNEL", "")
    if not channel:
        return HttpResponse("Server misconfigured: CRON_SLACK_CHANNEL not set", status=500)

    try:
        # Avvia il sondaggio esattamente come se qualcuno avesse scritto /start
        slack.start_new_poll(channel)
        return HttpResponse("Sondaggio avviato con successo via Cronjob!", status=200)
    except Exception as e:
        return HttpResponse(f"Errore durante l'avvio: {str(e)}", status=500)


@csrf_exempt
def cron_weekly_recap(request):
    """Endpoint sicuro chiamato da cron-job.org per inviare il riepilogo settimanale."""
    token = request.GET.get("token") or request.POST.get("token")
    if not token or token != getattr(settings, "CRON_SECRET", ""):
        return HttpResponse("Forbidden", status=403)

    channel = getattr(settings, "CRON_SLACK_CHANNEL", "")
    if not channel:
        return HttpResponse("Server misconfigured: CRON_SLACK_CHANNEL not set", status=500)

    try:
        slack.send_weekly_recap(channel, count=3)
        return HttpResponse("Weekly recap inviato", status=200)
    except Exception as e:
        return HttpResponse(f"Errore durante invio recap: {e}", status=500)

def winner(request):
    """Returns the winning track for the most recent closed poll that hasn't
    yet been played on the kiosk. Marks the poll as played so the winner is
    returned only once.
    """
    poll = Poll.objects.filter(is_open=False, kiosk_played=False, ended_at__isnull=False).order_by("-ended_at").first()

    if not poll:
        return JsonResponse({"video_id": None, "youtube_video_id": None, "title": ""})

    votes = Vote.objects.filter(poll=poll)

    if not votes.exists():
        poll.kiosk_played = True
        poll.save(update_fields=["kiosk_played"])
        return JsonResponse({"video_id": None, "youtube_video_id": None, "title": ""})

    counts = {}
    for v in votes:
        counts[v.track_id] = counts.get(v.track_id, 0) + 1

    max_votes = max(counts.values())
    top = [tid for tid, c in counts.items() if c == max_votes]
    winner_id = random.choice(top)

    track = Track.objects.filter(id=winner_id).first()
    # Mark as played regardless of whether we found the Track
    poll.kiosk_played = True
    poll.save(update_fields=["kiosk_played"])

    if not track:
        return JsonResponse({"video_id": None, "youtube_video_id": None, "title": ""})

    return JsonResponse({"video_id": track.youtube_video_id, "youtube_video_id": track.youtube_video_id, "title": track.title})


def next_track(request):
    track = Track.objects.order_by("?").first()

    if not track:
        return JsonResponse({
            "video_id": None,
            "youtube_video_id": None,
            "title": ""
        })

    return JsonResponse({
        "video_id": track.youtube_video_id,
        "youtube_video_id": track.youtube_video_id,
        "title": track.title
    })


def kiosk_index(request):
    """Serve frontend/index.html so the kiosk can open the page via the backend."""
    # Locate the frontend directory by searching upward from BASE_DIR so this
    # works whether BASE_DIR points to the `backend` folder or the project
    # root (e.g. inside Docker where code may be at /app).
    base = Path(settings.BASE_DIR)
    frontend_root = None
    for p in [base] + list(base.parents)[:4]:
        candidate = Path(p) / "frontend"
        if candidate.exists() and candidate.is_dir():
            frontend_root = candidate
            break

    if frontend_root is None:
        raise Http404("Frontend index not found")

    index = frontend_root / "index.html"
    if not index.exists():
        raise Http404("Frontend index not found")
    return FileResponse(open(index, "rb"), content_type="text/html")


def frontend_file(request, path):
    """Serve arbitrary frontend file from the `frontend` folder.

    This is a small helper for development/kiosk usage so the browser can
    request `/app.js` or other assets from the same origin without a separate
    static server.
    """
    base = Path(settings.BASE_DIR)
    frontend_root = None
    for p in [base] + list(base.parents)[:4]:
        candidate = Path(p) / "frontend"
        if candidate.exists() and candidate.is_dir():
            frontend_root = candidate
            break

    if frontend_root is None:
        raise Http404()

    target = frontend_root / path
    if not target.exists() or not target.is_file():
        raise Http404()
    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(open(target, "rb"), content_type=mime or "application/octet-stream")