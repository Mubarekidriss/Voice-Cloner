"""
Audio input validation for the Voice Cloner (ICS 499, Group 12) - FP5.

Checks a recorded or uploaded voice sample BEFORE it is sent to XTTS, and
raises an error with a plain-English message when the file cannot be used.

Public API (this is what the wiring code should call):

    from audio_validation import validate_audio, AudioValidationError

    info = validate_audio(path)          # path to the recorded/uploaded file
    # info.duration_seconds, info.sample_rate, info.channels, info.rms_dbfs

    validate_audio(path) returns an AudioInfo when the file is usable and
    raises AudioValidationError (a ValueError) otherwise. str(error) is
    written for the end user, so the UI can show it directly, e.g.:

        try:
            validate_audio(reference_audio)
        except AudioValidationError as e:
            raise gr.Error(str(e))

The module does not load XTTS or Gradio, so it runs and tests on any machine.

Formats: PCM WAV is read directly with the standard library. Any other
format (MP3, M4A, FLAC, OGG, 24/32-bit WAV ...) is decoded with ffmpeg, which
static-ffmpeg provides through the Python environment (see app.py). If
ffmpeg cannot decode a file, it is reported as unreadable.

Limits are the constants below, so the team can change them in one place.
"""
import static_ffmpeg
import array
import math
import os
import shutil
import subprocess
import wave
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

# XTTS v2 needs a few seconds of clean speech to clone a voice.
MIN_DURATION_SECONDS = 6.0

# Longer samples add no quality and slow generation down.
MAX_DURATION_SECONDS = 30.0

# Reject very large uploads before decoding them.
MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB

# Overall level below this (dB relative to full scale) counts as silence.
SILENCE_RMS_DBFS = -50.0

# Sample rate used when decoding non-WAV files for the checks.
_DECODE_RATE = 16000

# Seconds ffmpeg may take to decode one file.
_DECODE_TIMEOUT = 60


class AudioValidationError(ValueError):
    """The voice sample cannot be used. str(error) is safe to show the user."""


@dataclass(frozen=True)
class AudioInfo:
    path: str
    duration_seconds: float
    sample_rate: int
    channels: int
    rms_dbfs: float


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def validate_audio(path):
    """Validate a voice sample file. Return AudioInfo or raise AudioValidationError."""

    if path is None or str(path).strip() == "":
        raise AudioValidationError(
            "No voice sample found. Record or upload one first."
        )

    path = str(path)

    if not os.path.isfile(path):
        raise AudioValidationError(
            "The voice sample file could not be found. Please record or "
            "upload it again."
        )

    size = os.path.getsize(path)

    if size == 0:
        raise AudioValidationError(
            "The voice sample is empty. Please record or upload it again."
        )

    if size > MAX_FILE_BYTES:
        raise AudioValidationError(
            f"The voice sample is too large ({size / (1024 * 1024):.1f} MB). "
            f"Please use a file under {MAX_FILE_BYTES // (1024 * 1024)} MB."
        )

    samples, sample_rate, channels = _read_samples(path)

    if not samples:
        raise AudioValidationError(
            "The voice sample contains no audio. Please record it again."
        )

    duration = len(samples) / float(sample_rate)

    if duration < MIN_DURATION_SECONDS:
        raise AudioValidationError(
            f"The voice sample is too short ({duration:.1f} s). "
            f"Please use at least {MIN_DURATION_SECONDS:.0f} seconds of speech."
        )

    if duration > MAX_DURATION_SECONDS:
        raise AudioValidationError(
            f"The voice sample is too long ({duration:.0f} s). "
            f"Please use {MAX_DURATION_SECONDS:.0f} seconds or less."
        )

    rms_dbfs = _rms_dbfs(samples)

    if rms_dbfs < SILENCE_RMS_DBFS:
        raise AudioValidationError(
            "The voice sample is silent or almost silent. Check your "
            "microphone and try again."
        )

    return AudioInfo(
        path=path,
        duration_seconds=duration,
        sample_rate=sample_rate,
        channels=channels,
        rms_dbfs=rms_dbfs,
    )


# ---------------------------------------------------------------------------
# Reading audio
# ---------------------------------------------------------------------------

def _read_samples(path):
    """Return (mono int16 samples, sample_rate, original_channels)."""

    try:
        with wave.open(path, "rb") as wav:
            if wav.getsampwidth() == 2 and wav.getcomptype() == "NONE":
                channels = wav.getnchannels()
                rate = wav.getframerate()
                raw = wav.readframes(wav.getnframes())
                return _to_mono(raw, channels), rate, channels
    except (wave.Error, EOFError):
        pass  # not a plain PCM WAV; try ffmpeg below

    return _decode_with_ffmpeg(path)


def _to_mono(raw, channels):
    data = array.array("h")
    data.frombytes(raw[: len(raw) - (len(raw) % 2)])

    if channels <= 1:
        return data

    mono = array.array("h")
    for i in range(0, len(data) - channels + 1, channels):
        mono.append(sum(data[i:i + channels]) // channels)
    return mono


def _ffmpeg_path():
    try:
        # Ensure static_ffmpeg's bundled executable is available.
        static_ffmpeg.add_paths()

        found = shutil.which("ffmpeg")
        if found:
            return found

    except Exception as exc:
        raise AudioValidationError(
            "FFmpeg could not be initialized to read this audio file. "
            "Please try a WAV file or contact support."
        ) from exc

    raise AudioValidationError(
        "FFmpeg is unavailable, so this audio format cannot be checked. "
        "Please try a WAV file."
    )


def _decode_with_ffmpeg(path):
    ffmpeg = _ffmpeg_path()

    command = [
        ffmpeg, "-v", "error", "-nostdin", "-i", path,
        "-vn", "-f", "s16le", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", str(_DECODE_RATE), "pipe:1",
    ]

    try:
        result = subprocess.run(
            command, capture_output=True, timeout=_DECODE_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        raise AudioValidationError(
            "The voice sample took too long to read. Please use a shorter file."
        )

    if result.returncode != 0 or not result.stdout:
        raise AudioValidationError(
            "The voice sample could not be read. The file may be corrupt or "
            "not an audio file. Please record or upload it again."
        )

    data = array.array("h")
    data.frombytes(result.stdout[: len(result.stdout) - (len(result.stdout) % 2)])

    # Original channel count is not needed for the checks; report 1 after
    # the mono decode. Sample rate is the decode rate.
    return data, _DECODE_RATE, 1


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

def _rms_dbfs(samples):
    total = 0
    for s in samples:
        total += s * s
    rms = math.sqrt(total / len(samples))

    if rms <= 0:
        return -math.inf

    return 20.0 * math.log10(rms / 32768.0)
