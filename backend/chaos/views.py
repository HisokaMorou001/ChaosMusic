from django.http import JsonResponse
from .models import Track

def next_track(request):
    track = Track.objects.order_by("?").first()

    return JsonResponse({
        "video_id": track.youtube_video_id,
        "title": track.title
    })