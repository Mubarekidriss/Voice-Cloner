# Voice Cloner - ICS 499 Capstone (Group 12)
#
# Standalone local version of the voice cloner application.
#
# Setup:
#   pip install -r requirements.txt
#
# Run:
#   python app.py
#
# GPU is strongly recommended for XTTS.
# CPU mode works but is significantly slower.
#
# The application uses XTTS v2 for both generated outputs:
#   1. Baseline TTS - a predefined XTTS speaker
#   2. Voice Clone  - the user's reference voice
#
# The same XTTS model and selected language are used for both outputs.
#
# Audio input:
#   Users can record from a microphone or upload an audio file.
#   Gradio converts the input to WAV before passing the filepath
#   to the application.
#
# The input audio component also provides the original recording's
# playback controls, allowing the user to verify the recording
# before starting conversion.
#
# FFmpeg / ffprobe:
#   static-ffmpeg supplies platform-appropriate binaries so users
#   do not need to install FFmpeg manually on Windows or macOS.


import os
import tempfile

# ---------------------------------------------------------------------------
# Provide FFmpeg and ffprobe through the Python environment.
#
# This must happen before importing Gradio because Gradio's audio
# processing may use pydub, which requires ffprobe for non-WAV files.
# ---------------------------------------------------------------------------

import static_ffmpeg

static_ffmpeg.add_paths()


# ---------------------------------------------------------------------------
# Remaining imports
# ---------------------------------------------------------------------------

import torch
import gradio as gr

from TTS.api import TTS


# ---------------------------------------------------------------------------
# Coqui configuration
# ---------------------------------------------------------------------------

# Running this app means YOU accept the Coqui Public Model License (CPML).
# https://coqui.ai/cpml
#
# This flag allows XTTS to load the model non-interactively.
os.environ["COQUI_TOS_AGREED"] = "1"


MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

# Predefined XTTS speaker used for the baseline TTS output.
#
# "Ana Florence" is one of the Coqui speakers listed for XTTS-v2.
DEFAULT_SPEAKER = "Ana Florence"


# ---------------------------------------------------------------------------
# Supported XTTS languages
# ---------------------------------------------------------------------------

LANGUAGES = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Portuguese": "pt",
    "Polish": "pl",
    "Turkish": "tr",
    "Russian": "ru",
    "Dutch": "nl",
    "Czech": "cs",
    "Arabic": "ar",
    "Chinese (Mandarin)": "zh-cn",
    "Hungarian": "hu",
    "Korean": "ko",
    "Japanese": "ja",
    "Hindi": "hi",
}


# ---------------------------------------------------------------------------
# Load XTTS
# ---------------------------------------------------------------------------

device = "cuda" if torch.cuda.is_available() else "cpu"

if device == "cpu":
    print("WARNING: no GPU detected - XTTS will be very slow on CPU.")

print(
    f"Loading {MODEL_NAME} on {device} "
    "(first run downloads about 2 GB)..."
)

tts = TTS(MODEL_NAME).to(device)

print("Model loaded.")


# ---------------------------------------------------------------------------
# Validate model configuration
# ---------------------------------------------------------------------------

# Make sure the expected baseline speaker exists in the installed model.
available_speakers = tts.speakers or []

if DEFAULT_SPEAKER not in available_speakers:
    raise RuntimeError(
        f"Default XTTS speaker '{DEFAULT_SPEAKER}' was not found. "
        f"Available speakers: {available_speakers}"
    )

# Verify that the language codes defined above are supported by the
# loaded model rather than assuming the model configuration matches.
available_languages = set(tts.languages or [])

unsupported_languages = {
    code
    for code in LANGUAGES.values()
    if code not in available_languages
}

if unsupported_languages:
    raise RuntimeError(
        "The installed XTTS model does not support these configured "
        f"languages: {sorted(unsupported_languages)}"
    )


print(f"Default speaker: {DEFAULT_SPEAKER}")
print(f"Supported languages: {sorted(available_languages)}")


# ---------------------------------------------------------------------------
# Voice conversion
# ---------------------------------------------------------------------------

def clone_voices(text, reference_audio, language):
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

        standard_file = tempfile.NamedTemporaryFile(
            suffix="_standard.wav",
            delete=False
        )

        standard_path = standard_file.name
        standard_file.close()

        tts.tts_to_file(
            text=text,
            speaker=DEFAULT_SPEAKER,
            language=language_code,
            file_path=standard_path
        )

        # ---------------------------------------------------------------
        # 2. Voice cloning using the user's reference recording
        # ---------------------------------------------------------------

        clone_file = tempfile.NamedTemporaryFile(
            suffix="_cloned.wav",
            delete=False
        )

        clone_path = clone_file.name
        clone_file.close()

        tts.tts_to_file(
            text=text,
            speaker_wav=reference_audio,
            language=language_code,
            file_path=clone_path
        )

        return standard_path, clone_path

    except Exception as e:
        # Clean up files if conversion fails.
        for path in (standard_path, clone_path):
            if path and os.path.exists(path):
                os.remove(path)

        raise gr.Error(f"Voice conversion failed: {e}")


# ---------------------------------------------------------------------------
# Gradio interface
# ---------------------------------------------------------------------------

demo = gr.Interface(
    fn=clone_voices,

    inputs=[
        # ---------------------------------------------------------------
        # Text
        # ---------------------------------------------------------------

        gr.Textbox(
            label="Text to speak",
            placeholder="Type a sentence or two...",
            lines=3
        ),

        # ---------------------------------------------------------------
        # Voice sample
        #
        # This is the ORIGINAL recording/player.
        # The user can listen to it before pressing Convert.
        # Gradio normalizes the input to WAV for backend processing.
        # ---------------------------------------------------------------

        gr.Audio(
            label="Voice sample to clone",
            sources=["microphone", "upload"],
            type="filepath",
            format="wav"
        ),

        # ---------------------------------------------------------------
        # Language
        # ---------------------------------------------------------------

        gr.Dropdown(
            choices=list(LANGUAGES.keys()),
            value="English",
            label="Speech language"
        ),
    ],

    outputs=[
        # ---------------------------------------------------------------
        # Baseline XTTS output
        # ---------------------------------------------------------------

        gr.Audio(
            label=f"Baseline TTS (XTTS - {DEFAULT_SPEAKER})"
        ),

        # ---------------------------------------------------------------
        # Cloned XTTS output
        # ---------------------------------------------------------------

        gr.Audio(
            label="Voice Clone (XTTS v2)"
        ),
    ],

    title="Voice Cloner",

    description=(
        "ICS 499 capstone - Group 12 (Mubarek Idris & Mikita Misiulia). "
        "Record or upload a voice sample, listen to it before conversion, "
        "select a language, and compare a predefined XTTS voice with "
        "a clone of the reference voice."
    ),

    article=(
        "**Responsible use:** only clone a voice with that person's permission. "
        "Cloning someone without consent can be used for fraud or impersonation. "
        "This demonstration runs locally on your own machine."
    ),
)


# ---------------------------------------------------------------------------
# Start application
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Local demo:
    # http://127.0.0.1:7860
    #
    # Set share=True only if you intentionally want to expose the
    # application through a temporary public Gradio link.
    demo.launch()