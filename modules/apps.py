import os
import static_ffmpeg
from django.apps import AppConfig

# Allow XTTS to load non-interactively.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

# Make FFmpeg and ffprobe available to audio processing.
static_ffmpeg.add_paths()


class VoiceClonerWebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules"