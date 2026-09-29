# Voice Cloner - ICS 499 Capstone (Group 12)
# Standalone local version of voice_cloner_demo.ipynb.
#
# Setup:  pip install -r requirements.txt
# Run:    python app.py  (GPU strongly recommended for XTTS; first run downloads ~2 GB)
#
# Note: transformers 5.2+ removed isin_mps_friendly, which coqui-tts imports,
# so requirements.txt pins transformers below 5. Do not upgrade it past that pin.

import os
import tempfile

# Running this app means YOU accept the Coqui Public Model License (CPML):
# https://coqui.ai/cpml - this flag records that acceptance so the model loads
# non-interactively.
os.environ['COQUI_TOS_AGREED'] = '1'

import torch
import gradio as gr
from gtts import gTTS
from TTS.api import TTS

MODEL_NAME = 'tts_models/multilingual/multi-dataset/xtts_v2'

device = 'cuda' if torch.cuda.is_available() else 'cpu'
if device == 'cpu':
    print('WARNING: no GPU detected - XTTS will be very slow on CPU.')
print(f'Loading {MODEL_NAME} on {device} (first run downloads about 2 GB)...')
tts = TTS(MODEL_NAME).to(device)
print('Model loaded.')


def clone_voices(text, reference_audio):
    """Generate (standard_voice_audio, cloned_voice_audio) for the given text."""
    if not text or not text.strip():
        raise gr.Error('Type some text first.')
    if reference_audio is None:
        raise gr.Error('Record or upload a voice sample first (6-10 seconds works best).')

    text = text.strip()

    # 1. Standard AI voice: gTTS always sounds the same, no sample needed.
    standard_path = tempfile.mktemp(suffix='_standard.mp3')
    gTTS(text=text, lang='en').save(standard_path)

    # 2. Cloned voice: XTTS v2 copies the voice in the reference sample.
    clone_path = tempfile.mktemp(suffix='_cloned.wav')
    tts.tts_to_file(text=text, speaker_wav=reference_audio, language='en', file_path=clone_path)

    return standard_path, clone_path


demo = gr.Interface(
    fn=clone_voices,
    inputs=[
        gr.Textbox(label='Text to speak', placeholder='Type a sentence or two...', lines=3),
        gr.Audio(label='Voice sample to clone (record or upload, 6-10 seconds)',
                 sources=['microphone', 'upload'], type='filepath'),
    ],
    outputs=[
        gr.Audio(label='Standard AI voice'),
        gr.Audio(label='Cloned voice'),
    ],
    title='Voice Cloner',
    description=('ICS 499 capstone - Group 12 (Mubarek Idris & Mikita Misiulia). '
                 'Type text, record or upload a short voice sample, and compare a standard '
                 'AI voice with a clone of the sample voice.'),
    article=('**Responsible use:** only clone a voice with that person\'s permission. '
             'Cloning someone without consent can be used for fraud and impersonation. '
             'This demo is for coursework and keeps everything on your own machine.'),
)

if __name__ == '__main__':
    # Local demo: open the http://127.0.0.1:7860 link printed on startup.
    # Set share=True for a temporary public gradio.live link instead.
    demo.launch()
