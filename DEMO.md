# Demo Guide - Voice Cloner (FP iteration checkpoint)

## What the demo shows

1. Record (or upload) a 6-30 second voice sample of your own voice and convert it to WAV.
2. Type a sentence or two into the text box and pick a language.
3. Tick the consent box, then Generate speech - the app returns two audio players side by side:
   - Baseline voice (XTTS default speaker, no sample needed)
   - Cloned voice (XTTS v2, copies the sample voice)

## Running it (Colab)

1. Open the notebook from the repo: `voice_cloner_demo.ipynb` (Colab badge at top).
2. Runtime -> Change runtime type -> GPU (T4).
3. Runtime -> Run all. First run downloads ~2 GB, allow 3-5 minutes.
4. Colab: the notebook may still start the old Gradio app. For the Django app, run the local steps below on your own machine instead.

## Running it locally

```
pip install -r requirements.txt
python manage.py createsuperuser
python manage.py migrate
```
**Follow console prompts**
```
python manage.py runserver
```

Open http://127.0.0.1:8000 and follow the four steps on the page.
Use a GPU machine; CPU works but is slow.

## Known fixes baked in

- `transformers` is pinned `>=4.57,<5`: 5.2+ removed `isin_mps_friendly`,
  which `coqui-tts` imports at load time.
- `COQUI_TOS_AGREED=1` is set in code so the CPML acceptance is recorded and the
  model loads without an interactive prompt.

## Troubleshooting

- `cpu - WARNING` cell output: switch the Colab runtime to GPU and re-run.
- Model download stalls: re-run the cell; the download resumes.
- Generate is greyed out: tick the consent statement first.
- Microphone recording only works on localhost or HTTPS.
