# Voice Cloner

ICS 499 Software Engineering and Capstone Project - Fall 2026, Group 12
Team: Mubarek Idris & Mikita Misiulia

Type text, record or upload a 6-10 second voice sample, and hear it spoken back two
ways side by side: a standard AI voice (gTTS) and a clone of the sample voice
(Coqui XTTS v2).

## Quick start (Colab, recommended)

Open `voice_cloner_demo.ipynb` in Google Colab (badge at the top of the notebook),
switch the runtime to GPU (Runtime -> Change runtime type -> T4), then Run all.
The first run downloads about 2 GB of model weights (3-5 minutes). Open the
`gradio.live` link the last cell prints.

## Local run

```
pip install -r requirements.txt
python app.py
```

A GPU is strongly recommended; XTTS on CPU is very slow. See DEMO.md for a full walkthrough.

## License and responsible use

Running the notebook or app accepts the Coqui Public Model License (CPML) for the
XTTS v2 model: https://coqui.ai/cpml

Only clone a voice with that person's permission. This project is coursework.
