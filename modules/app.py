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

import os

# ---------------------------------------------------------------------------
# Coqui configuration
# ---------------------------------------------------------------------------

# Running this app means YOU accept the Coqui Public Model License (CPML).
# https://coqui.ai/cpml
#
# This flag allows XTTS to load the model non-interactively.
os.environ["COQUI_TOS_AGREED"] = "1"

from tts_engine import load_tts
from ui import create_interface

def main():
# ---------------------------------------------------------------------------
# Load XTTS
# ---------------------------------------------------------------------------
    tts = load_tts()

# ---------------------------------------------------------------------------
# Gradio interface
# ---------------------------------------------------------------------------
    demo = create_interface(tts)
    result = demo.launch()

# ---------------------------------------------------------------------------
# Start application
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Local demo:
    # http://127.0.0.1:7860
    #
    # Set share=True only if you intentionally want to expose the
    # application through a temporary public Gradio link.
    main()