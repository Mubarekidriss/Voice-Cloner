import os
import tempfile

import gradio as gr

from config import DEFAULT_SPEAKER, LANGUAGES


# ---------------------------------------------------------------------------
# Voice conversion
# ---------------------------------------------------------------------------
def clone_voices(tts, text, reference_audio, language):
    """
    Generate two outputs using XTTS v2:

        1. Baseline TTS using a predefined XTTS speaker
        2. Voice-cloned speech using the user's reference recording

    Both outputs use:
        - the same text
        - the same XTTS model
        - the same selected language

    Only the speaker source differs.
    """
    print("text:", repr(text))
    print("reference_audio:", repr(reference_audio))
    print("language:", repr(language))

    if not text or not text.strip():
        raise gr.Error("Type some text first.")

    if reference_audio is None:
        raise gr.Error("Record or upload a voice sample first.")

    if language not in LANGUAGES:
        raise gr.Error("Please select a supported language.")

    text = text.strip()
    language_code = LANGUAGES[language]

    standard_path = None
    clone_path = None

    try:
        # ---------------------------------------------------------------
        # 1. Baseline TTS using a predefined XTTS speaker
        # ---------------------------------------------------------------

        standard_path = _create_temp_path("_standard.wav")

        tts.tts_to_file(
            text=text,
            speaker=DEFAULT_SPEAKER,
            language=language_code,
            file_path=standard_path
        )

        # ---------------------------------------------------------------
        # 2. Voice cloning using the user's reference recording
        # ---------------------------------------------------------------

        clone_path = _create_temp_path("cloned.wav")
        tts.tts_to_file(
            text=text,
            speaker_wav=reference_audio,
            language=language_code,
            file_path=clone_path
        )

        return standard_path, clone_path

    except Exception as e:
        # Clean up files if conversion fails.
        _cleanup(standard_path, clone_path)
        raise gr.Error(f"Voice conversion failed: {e}")


def _create_temp_path(suffix):
    file = tempfile.NamedTemporaryFile(
                suffix=suffix,
                delete=False
            )
    path = file.name
    file.close()
    return path

def _cleanup(*paths):
    for path in paths:
        if path and os.path.exists(path):
            os.remove(path)