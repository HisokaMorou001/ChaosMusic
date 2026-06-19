from django.db import models


class Track(models.Model):
    youtube_video_id = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=255)
    thumbnail_url = models.URLField()

    def __str__(self):
        return self.title


class Poll(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    is_open = models.BooleanField(default=True)

    channel_id = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    # Timestamp del messaggio Slack della leaderboard
    leaderboard_ts = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    # Data di chiusura del sondaggio
    ended_at = models.DateTimeField(
        null=True,
        blank=True
    )

    def __str__(self):
        status = "open" if self.is_open else "closed"
        return f"Poll {self.id} ({status})"


class Vote(models.Model):
    poll = models.ForeignKey(
        Poll,
        on_delete=models.CASCADE,
        related_name="votes"
    )

    track = models.ForeignKey(
        Track,
        on_delete=models.CASCADE,
        related_name="votes"
    )

    slack_user_id = models.CharField(max_length=100)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("poll", "slack_user_id")
        indexes = [
            models.Index(fields=["poll"]),
            models.Index(fields=["track"]),
            models.Index(fields=["slack_user_id"]),
        ]

    def __str__(self):
        return f"{self.slack_user_id} -> {self.track.title}"