import os
import tempfile

import gradio as gr

from config import DEFAULT_SPEAKER, LANGUAGES


def generate_voices(tts, text, reference_audio, language):
    """
    Generate baseline and cloned speech using the same text,
    language, and XTTS model.
    """

    if not text or not text.strip():
        raise gr.Error("Type some text first.")

    if not reference_audio or not os.path.isfile(reference_audio):
        raise gr.Error(
            "Convert or upload a reference audio file first."
        )

    if language not in LANGUAGES:
        raise gr.Error("Please select a supported language.")

    text = text.strip()
    language_code = LANGUAGES[language]

    standard_path = None
    clone_path = None

    try:
        standard_path = _create_temp_path("_standard.wav")
        clone_path = _create_temp_path("_cloned.wav")

        # Baseline TTS: predefined speaker.
        tts.tts_to_file(
            text=text,
            speaker=DEFAULT_SPEAKER,
            language=language_code,
            file_path=standard_path,
        )

        # Voice clone: normalized reference WAV.
        tts.tts_to_file(
            text=text,
            speaker_wav=reference_audio,
            language=language_code,
            file_path=clone_path,
        )

        return standard_path, clone_path

    except Exception as exc:
        _cleanup(standard_path, clone_path)
        raise gr.Error(f"Voice generation failed: {exc}") from exc


def _create_temp_path(suffix):
    with tempfile.NamedTemporaryFile(
        suffix=suffix,
        delete=False,
    ) as temp_file:
        return temp_file.name


def _cleanup(*paths):
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass