import gradio as gr

from config import DEFAULT_SPEAKER, LANGUAGES
from audio_utils import normalize_audio
from audio_validation import validate_audio, AudioValidationError
from tts_engine import TTSEngineError, XTTSService


def create_interface(tts_service: XTTSService):
    """Create the Gradio UI around an already-loaded XTTS backend service."""

    def convert_reference(reference_audio):
        if not reference_audio:
            raise gr.Error("Record or upload a voice sample first.")

        try:
            validate_audio(reference_audio)
        except AudioValidationError as exc:
            raise gr.Error(str(exc)) from exc

        try:
            wav_path = normalize_audio(reference_audio)
            return wav_path, wav_path, wav_path
        except Exception as exc:
            raise gr.Error(f"Audio conversion failed: {exc}") from exc

    def clear_all():
        return (
            "",       # Text input
            None,     # Original audio
            "English",# Language reset
            None,     # Normalized audio state
            None,     # Normalized audio preview
            None,     # WAV download
            None,     # Baseline output
            None,     # Cloned output
        )

    def generate_from_input(text, original_audio, normalized_audio, language):
        reference = normalized_audio or original_audio
        if not reference:
            raise gr.Error("Please record or upload a voice sample.")

        # Validate the original even if a normalized copy exists, so a stale
        # normalized path cannot hide a missing/invalid current recording.
        try:
            validate_audio(original_audio)
        except AudioValidationError as exc:
            raise gr.Error(str(exc)) from exc

        try:
            return tts_service.generate_voices(text, reference, language)
        except TTSEngineError as exc:
            raise gr.Error(str(exc)) from exc

    with gr.Blocks(title="Voice Cloner") as demo:
        gr.Markdown("# Voice Cloner")
        gr.Markdown(
            "Record or upload a voice sample, convert it to a normalized WAV "
            "file, and compare baseline TTS with a clone of the reference voice."
        )

        clear_button = gr.Button("Clear All", variant="secondary")
        normalized_audio_state = gr.State(value=None)

        with gr.Group():
            gr.Markdown("## 1. Input")
            text_input = gr.Textbox(
                label="Text to speak",
                placeholder="Type a sentence or two...",
                lines=3,
            )
            reference_audio = gr.Audio(
                label="Original voice sample",
                sources=["microphone", "upload"],
                type="filepath",
                format="wav",
            )
            language = gr.Dropdown(
                choices=list(LANGUAGES.keys()),
                value="English",
                label="Speech language",
            )
            convert_button = gr.Button("Convert / Normalize to WAV", variant="secondary")

        with gr.Group():
            gr.Markdown("## 2. Converted reference audio")
            normalized_preview = gr.Audio(label="Normalized WAV — preview", type="filepath")
            normalized_download = gr.File(label="Download normalized WAV")

        convert_button.click(
            fn=convert_reference,
            inputs=[reference_audio],
            outputs=[normalized_audio_state, normalized_preview, normalized_download],
        )

        with gr.Group():
            gr.Markdown("## 3. Generate and compare")
            generate_button = gr.Button("Generate Speech", variant="primary")
            baseline_output = gr.Audio(label=f"Baseline TTS (XTTS - {DEFAULT_SPEAKER})")
            cloned_output = gr.Audio(label="Voice Clone (XTTS v2)")

            generate_button.click(
                fn=generate_from_input,
                inputs=[text_input, reference_audio, normalized_audio_state, language],
                outputs=[baseline_output, cloned_output],
            )

        clear_button.click(
            fn=clear_all,
            inputs=[],
            outputs=[
                text_input,
                reference_audio,
                language,
                normalized_audio_state,
                normalized_preview,
                normalized_download,
                baseline_output,
                cloned_output,
            ],
        )

        reference_audio.change(
            fn=lambda: (None, None, None),
            inputs=[],
            outputs=[normalized_audio_state, normalized_preview, normalized_download],
        )

        gr.Markdown(
            "**Responsible use:** Only clone a voice with the speaker's permission. "
            "This demonstration runs locally on your machine."
        )

    return demo
