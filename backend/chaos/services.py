import os
import random
import traceback
import isodate
from googleapiclient.discovery import build
from django.utils import timezone
from django.conf import settings
from datetime import timedelta

from .models import Poll, Vote

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Inizializzazione client YouTube v3
youtube = build(
    "youtube", "v3",
    developerKey=os.getenv("YOUTUBE_API_KEY")
)


# -----------------------------
# UTILS: VIDEO FILTERS
# -----------------------------

def is_bad_title(title: str) -> bool:
    """Returns True if the video title suggests it's NOT a single song track."""
    bad_keywords = [
        "playlist", "mix", "remix", "live", "live set",
        "hour", "hours", "set", "dj", "dj set",
        "compilation", "album", "full album",
        "best of", "top 10", "top 50", "megamix"
    ]
    t = title.lower()
    return any(b in t for b in bad_keywords)


def get_duration_seconds(video_id: str):
    """Returns the real duration in seconds of a YouTube video, or None on failure."""
    try:
        res = youtube.videos().list(
            part="contentDetails",
            id=video_id
        ).execute()

        items = res.get("items", [])
        if not items:
            return None

        duration = items[0]["contentDetails"]["duration"]
        return int(isodate.parse_duration(duration).total_seconds())

    except Exception:
        return None


# -----------------------------
# FALLBACK: YOUTUBE SEARCH
# -----------------------------

def fetch_5_tracks(query="music"):
    """Fallback: fetches 5 tracks from YouTube with a varied query."""

    queries = [
        "rock hits", "pop songs", "hip hop beats",
        "electronic music", "jazz classics",
        "R&B songs", "lofi beats",
        "reggae vibes", "synthwave music",
        "alternative rock", "soul music"
    ]

    if query == "music":
        query = random.choice(queries)

    print(f"\nDEBUG: fetch_5_tracks() using query: '{query}'")

    try:
        res = youtube.search().list(
            q=query,
            part="snippet",
            type="video",
            maxResults=15,
            order="relevance",
            videoDuration="short"
        ).execute()

        tracks = []

        for item in res.get("items", []):
            title = item["snippet"]["title"]

            if is_bad_title(title):
                print(f"  SKIP (bad title): {title}")
                continue

            tracks.append({
                "video_id": item["id"]["videoId"],
                "title": title[:75],
                "thumbnail": item["snippet"]["thumbnails"]["default"]["url"],
            })

            if len(tracks) == 5:
                break

        print(f"DEBUG: Found {len(tracks)} tracks for query '{query}'")
        return tracks
    except Exception as e:
        print(f":x: Errore nella ricerca YouTube di fallback: {e}")
        return []


# -----------------------------
# AI TRACK GENERATOR (CONFIGURATO PER GEMINI)
# -----------------------------

SYSTEM_PROMPT = """\
You are a music expert. Your only job is to return exactly 5 real, officially released songs.

STRICT RULES:
- Every entry must be a single track (not an album, compilation, remix, mix, DJ set, live set, or playlist).
- Each song must come from a clearly different music genre (e.g. Rock, Hip-Hop, Pop, Jazz, Classical — or any 5 genuinely distinct genres).
- Each song must be under 4 minutes long.
- No two songs can be by the same artist.
- No instrumental versions unless the genre (e.g. Classical) requires it.
- Only include songs that actually exist and were officially released.

OUTPUT FORMAT — FOLLOW EXACTLY:
Return exactly 5 lines. Each line must be:
Song Title - Artist Name

RULES FOR THE OUTPUT:
- No numbering, no bullet points, no asterisks, no bold.
- No genre labels, no explanations, no intro text, no closing text.
- Output the 5 lines and nothing else.\
"""

USER_PROMPT_TEMPLATE = """\
Return 5 real songs, one per line, in the format: Song Title - Artist Name
Each song must be from a different genre. No mixes, no albums, no remixes.
Vary your choices — do not always pick the most famous songs.
Seed: {seed}\
"""


def fetch_5_tracks_ai():
    """Generates 5 unique songs via Google Gemini (gemini-2.5-flash), then finds them on YouTube."""

    print("\n" + "="*70)
    print("FETCH_5_TRACKS_AI: START WITH GOOGLE GEMINI")
    print("="*70)

    try:
        print(f"DEBUG: OpenAI module available? {OpenAI is not None}")
        print(f"DEBUG: GEMINI_API_KEY set? {bool(os.getenv('GEMINI_API_KEY'))}")

        # ADATTAMENTO: Verifica la presenza della chiave di Gemini
        if not OpenAI or not os.getenv("GEMINI_API_KEY"):
            print("✗ Gemini AI not configured — falling back to YouTube search")
            print("="*70)
            return fetch_5_tracks()

        # ADATTAMENTO: Client impostato con l'endpoint di compatibilità Google
        client = OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=os.getenv("GEMINI_API_KEY")
        )
        print("✓ Client configured for Google Gemini API")

        seed = random.randint(1, 999999)
        print(f"✓ Seed: {seed}")

        print("\n→ Calling Google Gemini (gemini-2.5-flash)...")

        # ADATTAMENTO: Utilizzo del modello gemini-2.5-flash
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            temperature=0.7,
            max_tokens=2500,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": ( f"{ USER_PROMPT_TEMPLATE.format(seed=seed)}\n"
                        "CRITICAL: Write exactly five lines in plain text. "
                        "Do not troncate or stop until all five songs are fully written"
                    )
                }
            ]
        )

        ai_text = response.choices[0].message.content.strip()
        print(f"✓ AI response received ({len(ai_text)} chars):")
        print(f"---\n{ai_text}\n---")

        # Parse AI output into song strings
        songs = []
        for idx, line in enumerate(ai_text.split("\n")):
            original = line
            line = line.strip().lstrip("•-*1234567890. ").strip()
            if "-" in line and len(line) > 5:
                songs.append(line)
                print(f"  Line {idx}: '{original}' → ACCEPTED → '{line}'")
            else:
                print(f"  Line {idx}: '{original}' → SKIPPED")

        print(f"\n✓ Songs parsed: {len(songs)}")
        for i, s in enumerate(songs, 1):
            print(f"  {i}. {s}")

        if len(songs) < 5:
            print(f"✗ Gemini returned only {len(songs)} songs — falling back to YouTube")
            print("="*70)
            return fetch_5_tracks()

        # Search each song on YouTube with filtering
        tracks = []

        for idx, song in enumerate(songs[:10], 1):
            print(f"\n→ YouTube search {idx}: '{song}'")

            query = f"{song} official audio"

            try:
                res = youtube.search().list(
                    q=query,
                    part="snippet",
                    type="video",
                    maxResults=10,
                    order="relevance",
                    videoDuration="short"
                ).execute()

                items = res.get("items", [])
                print(f"  Results found: {len(items)}")

                matched = False
                for item in items:
                    video_id = item["id"]["videoId"]
                    video_title = item["snippet"]["title"]

                    # Filter by title
                    if is_bad_title(video_title):
                        print(f"  SKIP (bad title): {video_title[:60]}")
                        continue

                    # Filter by real duration (max 4 minutes = 240 seconds)
                    duration = get_duration_seconds(video_id)
                    if duration is None or duration > 240:
                        print(f"  SKIP (duration={duration}s): {video_title[:60]}")
                        continue

                    tracks.append({
                        "video_id": video_id,
                        "title": song,
                        "thumbnail": item["snippet"]["thumbnails"]["default"]["url"],
                    })
                    print(f"  ✓ Matched: {video_id} | {video_title[:60]} ({duration}s)")
                    matched = True
                    break

                if not matched:
                    print(f"  ✗ No valid result for: {song}")

            except Exception as e:
                print(f"  ✗ YouTube error: {e}")
                continue

            if len(tracks) == 5:
                break

        print(f"\n✓ Tracks found: {len(tracks)}/5")
        for i, t in enumerate(tracks, 1):
            print(f"  {i}. {t['title']} (ID: {t['video_id']})")

        if len(tracks) != 5:
            print(f"✗ Only {len(tracks)} valid tracks filtered — falling back to YouTube")
            print("="*70)
            return fetch_5_tracks()

        print("\n✓ SUCCESS — 5 Gemini-generated songs found on YouTube!")
        print("="*70 + "\n")
        return tracks

    except Exception as e:
        print(f"\n✗ CRITICAL ERROR IN CORE AI: {e}")
        traceback.print_exc()
        print("FALLBACK to YouTube search")
        print("="*70 + "\n")
        return fetch_5_tracks()


# -----------------------------
# POLL: WINNER COMPUTATION
# -----------------------------

def close_poll_and_compute_winner(poll_id):
    """Chiude il sondaggio e determina la traccia vincitrice."""
    try:
        poll = Poll.objects.get(id=poll_id)
        poll.is_open = False

        votes = Vote.objects.filter(poll=poll)

        if not votes.exists():
            poll.save()
            return None

        # Count votes per track
        counts = {}
        for v in votes:
            counts[v.track_id] = counts.get(v.track_id, 0) + 1

        max_votes = max(counts.values())

        # Handle ties with random choice
        top_tracks = [
            track_id for track_id, c in counts.items()
            if c == max_votes
        ]

        winner_id = random.choice(top_tracks)

        poll.winner_id = winner_id
        poll.save()

        return poll.winner
    except Exception:
        traceback.print_exc()
        return None 