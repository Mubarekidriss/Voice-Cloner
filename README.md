# Voice Cloner

ICS 499 Software Engineering and Capstone Project - Fall 2026, Group 12
Team: Mubarek Idris & Mikita Misiulia

Type text, record or upload a 6-10 second voice sample, and hear it spoken back two
ways side by side: a standard AI voice (gTTS) and a clone of the sample voice
(Coqui XTTS v2).

## Local run

```
pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py runserver
```

A GPU is strongly recommended; XTTS on CPU is very slow. See DEMO.md for a full walkthrough.

## Verify the languages

Run a metadata check and actual baseline inference for all configured languages:

```bash
python verify_languages.py
```

To smoke-test voice cloning in every configured language too, provide a valid reference recording accepted by the app's `audio_validation.py` (6–30 seconds under the current settings):

```bash
python verify_languages.py --reference path/to/reference.wav
```

The script prints a `PASS`/`FAIL` per language and exits nonzero if any fails. This is a generation smoke test, not a pronunciation-quality review; listen to representative outputs as a separate QA step.

## Tests

From the project root, run:

```bash
python -m pytest -q tests/test_tts_engine.py
```

These tests expect the project's existing `config.py` to be importable from the project root. They verify metadata validation, language rejection, correct use of the default speaker/reference audio, generation error handling, and cleanup of partial/successful test outputs.

## License and responsible use

Running the notebook or app accepts the Coqui Public Model License (CPML) for the
XTTS v2 model: https://coqui.ai/cpml

Only clone a voice with that person's permission. This project is coursework.
