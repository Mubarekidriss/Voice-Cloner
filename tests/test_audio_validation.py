"""Tests for modules/audio_validation.py. Run from the repo root: pytest"""

import math
import os
import shutil
import struct
import subprocess
import sys
import wave

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "modules"))

import audio_validation as av  # noqa: E402
from audio_validation import AudioValidationError, validate_audio  # noqa: E402


def make_wav(path, seconds, amplitude=0.5, rate=16000, channels=1, freq=220):
    """Write a sine wave (amplitude 0 = silence) as 16-bit PCM WAV."""
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        chunk = bytearray()
        for n in range(frames):
            value = int(amplitude * 32767 * math.sin(2 * math.pi * freq * n / rate))
            chunk += struct.pack("<h", value) * channels
        wav.writeframes(bytes(chunk))
    return str(path)


# ---------------------------------------------------------------------------
# Valid input
# ---------------------------------------------------------------------------

def test_valid_wav_passes(tmp_path):
    info = validate_audio(make_wav(tmp_path / "ok.wav", 8))
    assert info.duration_seconds == pytest.approx(8.0, abs=0.01)
    assert info.sample_rate == 16000
    assert info.channels == 1


def test_stereo_and_other_rate_pass(tmp_path):
    info = validate_audio(make_wav(tmp_path / "st.wav", 7, rate=44100, channels=2))
    assert info.channels == 2
    assert info.sample_rate == 44100


def test_exact_minimum_duration_passes(tmp_path):
    validate_audio(make_wav(tmp_path / "min.wav", av.MIN_DURATION_SECONDS))


def test_exact_maximum_duration_passes(tmp_path):
    validate_audio(make_wav(tmp_path / "max.wav", av.MAX_DURATION_SECONDS, rate=8000))


# ---------------------------------------------------------------------------
# Missing / empty / corrupt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "", "   "])
def test_no_path(value):
    with pytest.raises(AudioValidationError, match="No voice sample"):
        validate_audio(value)


def test_missing_file(tmp_path):
    with pytest.raises(AudioValidationError, match="could not be found"):
        validate_audio(str(tmp_path / "nope.wav"))


def test_empty_file(tmp_path):
    p = tmp_path / "empty.wav"
    p.write_bytes(b"")
    with pytest.raises(AudioValidationError, match="empty"):
        validate_audio(str(p))


def test_text_file_named_wav_is_unreadable(tmp_path):
    p = tmp_path / "fake.wav"
    p.write_text("this is not audio")
    with pytest.raises(AudioValidationError, match="could not be read"):
        validate_audio(str(p))


def test_truncated_wav_header_is_unreadable(tmp_path):
    good = make_wav(tmp_path / "good.wav", 8)
    p = tmp_path / "cut.wav"
    p.write_bytes(open(good, "rb").read()[:20])
    with pytest.raises(AudioValidationError):
        validate_audio(str(p))


def test_wav_with_no_audio_frames(tmp_path):
    p = tmp_path / "noframes.wav"
    with wave.open(str(p), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
    with pytest.raises(AudioValidationError):
        validate_audio(str(p))


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------

def test_too_short(tmp_path):
    with pytest.raises(AudioValidationError, match="too short"):
        validate_audio(make_wav(tmp_path / "short.wav", 2))


def test_just_under_minimum(tmp_path):
    with pytest.raises(AudioValidationError, match="too short"):
        validate_audio(make_wav(tmp_path / "s.wav", av.MIN_DURATION_SECONDS - 0.5))


def test_too_long(tmp_path):
    with pytest.raises(AudioValidationError, match="too long"):
        validate_audio(make_wav(tmp_path / "long.wav", av.MAX_DURATION_SECONDS + 5, rate=8000))


# ---------------------------------------------------------------------------
# Silence
# ---------------------------------------------------------------------------

def test_digital_silence(tmp_path):
    with pytest.raises(AudioValidationError, match="silent"):
        validate_audio(make_wav(tmp_path / "quiet.wav", 8, amplitude=0))


def test_near_silence(tmp_path):
    # amplitude 0.001 is about -63 dBFS
    with pytest.raises(AudioValidationError, match="silent"):
        validate_audio(make_wav(tmp_path / "hiss.wav", 8, amplitude=0.001))


def test_quiet_but_usable_passes(tmp_path):
    # amplitude 0.02 is about -37 dBFS RMS, a quiet but real recording
    validate_audio(make_wav(tmp_path / "soft.wav", 8, amplitude=0.02))


# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------

def test_oversized_file(tmp_path, monkeypatch):
    p = make_wav(tmp_path / "big.wav", 8)
    monkeypatch.setattr(av, "MAX_FILE_BYTES", 1000)
    with pytest.raises(AudioValidationError, match="too large"):
        validate_audio(p)


# ---------------------------------------------------------------------------
# Other formats (decoded with ffmpeg; skipped when ffmpeg is not installed)
# ---------------------------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def convert(src, dst):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", src, dst], check=True
    )
    return dst


@needs_ffmpeg
@pytest.mark.parametrize("ext", ["mp3", "flac", "ogg", "m4a"])
def test_other_formats_pass(tmp_path, ext):
    src = make_wav(tmp_path / "src.wav", 8)
    try:
        out = convert(src, str(tmp_path / f"clip.{ext}"))
    except subprocess.CalledProcessError:
        pytest.skip(f"this ffmpeg build cannot write {ext}")
    info = validate_audio(out)
    assert info.duration_seconds == pytest.approx(8.0, abs=0.3)


@needs_ffmpeg
def test_short_mp3_rejected(tmp_path):
    src = make_wav(tmp_path / "src.wav", 2)
    try:
        out = convert(src, str(tmp_path / "short.mp3"))
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg build cannot write mp3")
    with pytest.raises(AudioValidationError, match="too short"):
        validate_audio(out)


@needs_ffmpeg
def test_garbage_bytes_named_mp3_unreadable(tmp_path):
    p = tmp_path / "junk.mp3"
    p.write_bytes(os.urandom(5000))
    with pytest.raises(AudioValidationError, match="could not be read"):
        validate_audio(str(p))


def test_error_is_a_value_error():
    assert issubclass(AudioValidationError, ValueError)
