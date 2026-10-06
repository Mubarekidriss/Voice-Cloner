import gradio as gr

from config import DEFAULT_SPEAKER, LANGUAGES
from voice_cloner import clone_voices


def create_interface(tts):
    return gr.Interface(
        fn=lambda text, reference_audio, language:
            clone_voices(tts, text, reference_audio, language),

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