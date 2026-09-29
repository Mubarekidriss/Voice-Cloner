# Demo Guide - Voice Cloner (FP iteration checkpoint)

## What the demo shows

1. Type a sentence or two into the text box.
2. Record (or upload) a 6-10 second voice sample.
3. Submit - the app returns two audio players side by side:
   - Standard AI voice (gTTS, no sample needed)
   - Cloned voice (XTTS v2, copies the sample voice)

## Running it (Colab)

1. Open the notebook from the repo: `voice_cloner_demo.ipynb` (Colab badge at top).
2. Runtime -> Change runtime type -> GPU (T4).
3. Runtime -> Run all. First run downloads ~2 GB, allow 3-5 minutes.
4. Open the `gradio.live` link printed by the last cell.
5. Run the three steps above with a short sample recorded live.

## Running it locally

```
pip install -r requirements.txt
python app.py
```

Open the printed local URL (default http://127.0.0.1:7860). Same three steps.
Use a GPU machine; CPU works but is slow.

## Known fixes baked in

- `transformers` is pinned `>=4.57,<5`: 5.2+ removed `isin_mps_friendly`,
  which `coqui-tts` imports at load time.
- `COQUI_TOS_AGREED=1` is set in code so the CPML acceptance is recorded and the
  model loads without an interactive prompt.

## Troubleshooting

- `cpu - WARNING` cell output: switch the Colab runtime to GPU and re-run.
- Model download stalls: re-run the cell; the download resumes.
- Gradio link expired: links live only as long as the session; re-run the last cell.
