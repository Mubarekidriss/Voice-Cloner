import json
from pathlib import Path

import gradio as gr

from config import DEFAULT_SPEAKER, LANGUAGES
from audio_utils import normalize_audio
from audio_validation import validate_audio, AudioValidationError
from tts_engine import TTSEngineError, XTTSService


def _load_verify_results() -> dict:
    """Read smoke-test results written by verify_languages.py, when present.

    Returns {language_code: note} for languages that passed. Missing or
    malformed file means "no verification run recorded" - not an error.
    """
    path = Path(__file__).resolve().parent.parent / "verify_results.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    results = data.get("results", data) if isinstance(data, dict) else {}
    out = {}
    for code, entry in results.items():
        ok = entry.get("ok") if isinstance(entry, dict) else entry in (True, "ok")
        if ok:
            out[code] = "smoke-tested"
    return out


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
            gr.DownloadButton(value=None, interactive=False),  # Clone download
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

    def generate_and_prepare_download(text, original_audio, normalized_audio, language):
        baseline_path, clone_path = generate_from_input(
            text, original_audio, normalized_audio, language
        )
        return (
            baseline_path,
            clone_path,
            gr.DownloadButton(value=clone_path, interactive=bool(clone_path)),
        )

    with gr.Blocks(title="Voice Cloner") as demo:
        lang_total = len(LANGUAGES)
        lang_loaded = len(tts_service.available_languages)
        verified = _load_verify_results()

        gr.HTML(
            f"""
            <div style="background: linear-gradient(135deg, #1e3a8a 0%, #7c3aed 100%);
                        border-radius: 12px; padding: 20px 24px; color: white;
                        margin-bottom: 8px;">
              <div style="font-size: 26px; font-weight: 700;">Voice Cloner</div>
              <div style="opacity: 0.9; margin-top: 4px;">
                Record or upload a voice sample, convert it to a normalized WAV,
                and compare baseline TTS with a clone of the reference voice.
              </div>
              <div style="margin-top: 12px; display: inline-block; background: rgba(255,255,255,0.18);
                          border-radius: 999px; padding: 4px 14px; font-size: 14px;">
                &#9881; XTTS v2 engine &middot; device: <b>{tts_service.device}</b>
                &middot; {lang_loaded}/{lang_total} languages loaded
              </div>
            </div>
            """
        )

        chips = []
        for lang_name, lang_code in LANGUAGES.items():
            ok = lang_code in tts_service.available_languages
            bg = "#16a34a" if ok else "#dc2626"
            mark = "&#10003;" if ok else "&#10007;"
            note = " &middot; smoke-tested" if lang_code in verified else ""
            chips.append(
                f'<span style="background:{bg}; color:white; border-radius:999px;'
                f'padding:5px 12px; font-size:13px; white-space:nowrap;">'
                f'{mark} {lang_name}{note}</span>'
            )
        gr.HTML(
            '<div style="margin: 6px 0 14px 0;">'
            '<div style="font-weight:600; margin-bottom:6px;">Language support '
            f'({lang_total} languages)</div>'
            '<div style="display:flex; flex-wrap:wrap; gap:6px;">'
            + "".join(chips) +
            "</div></div>"
        )

        gr.HTML(
            """
            <div style="display:flex; flex-wrap:wrap; gap:8px; margin: 4px 0 10px 0;">
              <span style="background:#eef2ff; color:#1e3a8a; border-radius:999px; padding:5px 14px; font-size:14px;"><b>Step 1</b> Voice sample</span>
              <span style="background:#eef2ff; color:#1e3a8a; border-radius:999px; padding:5px 14px; font-size:14px;"><b>Step 2</b> Prepare WAV</span>
              <span style="background:#eef2ff; color:#1e3a8a; border-radius:999px; padding:5px 14px; font-size:14px;"><b>Step 3</b> Text &amp; language</span>
              <span style="background:#eef2ff; color:#1e3a8a; border-radius:999px; padding:5px 14px; font-size:14px;"><b>Step 4</b> Generate &amp; download</span>
            </div>
            """
        )

        clear_button = gr.Button("Clear All", variant="secondary")
        normalized_audio_state = gr.State(value=None)

        with gr.Group():
            gr.Markdown("## Step 1: Record or upload your voice sample")
            reference_audio = gr.Audio(
                label="Original voice sample",
                sources=["microphone", "upload"],
                type="filepath",
                format="wav",
            )

        with gr.Group():
            gr.Markdown("## Step 2: Convert to a normalized WAV")
            convert_button = gr.Button("Convert / Normalize to WAV", variant="secondary")
            normalized_preview = gr.Audio(label="Normalized WAV - preview", type="filepath")
            normalized_download = gr.File(label="Download normalized WAV")

        convert_button.click(
            fn=convert_reference,
            inputs=[reference_audio],
            outputs=[normalized_audio_state, normalized_preview, normalized_download],
        )

        with gr.Group():
            gr.Markdown("## Step 3: Enter the text and choose a language")
            text_input = gr.Textbox(
                label="Text to speak",
                placeholder="Type a sentence or two...",
                lines=3,
            )
            language = gr.Dropdown(
                choices=list(LANGUAGES.keys()),
                value="English",
                label="Speech language",
            )

        with gr.Group():
            gr.Markdown("## Step 4: Generate, compare and download")
            generate_button = gr.Button("Generate Speech", variant="primary", size="lg")
            with gr.Row():
                baseline_output = gr.Audio(label=f"Baseline TTS (XTTS - {DEFAULT_SPEAKER})")
                cloned_output = gr.Audio(label="Voice Clone (XTTS v2)")
            clone_download = gr.DownloadButton(
                "Download cloned voice (WAV)",
                value=None,
                interactive=False,
                variant="secondary",
            )

            generate_button.click(
                fn=generate_and_prepare_download,
                inputs=[text_input, reference_audio, normalized_audio_state, language],
                outputs=[baseline_output, cloned_output, clone_download],
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
                clone_download,
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
