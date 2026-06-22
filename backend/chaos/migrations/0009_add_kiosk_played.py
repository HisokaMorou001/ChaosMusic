"""Migration: add `kiosk_played` boolean to `Poll`.

This file was created to add a simple boolean flag used by the kiosk
frontend to mark a poll as already played.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chaos", "0008_rename_message_ts_poll_leaderboard_ts"),
    ]

    operations = [
        migrations.AddField(
            model_name="poll",
            name="kiosk_played",
            field=models.BooleanField(default=False),
        ),
    ]