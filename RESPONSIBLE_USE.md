# Responsible Use - Voice Cloner (FP8)

This project is ICS 499 coursework. This page covers what the app asks of users and what it does with audio. It describes the current code and marks what is still open.

## Acceptable use

- Clone only your own voice, or a voice whose owner gave you clear permission.
- Do not use the output to impersonate a real person, deceive or defraud anyone, harass, or make content that could harm someone.
- Do not use text you have no right to reproduce.
- The web page shows a consent statement. The Generate button stays disabled until it is checked. This check is in the page only; server-side enforcement is not part of this change.

## Where audio is processed

- The app runs on the machine that starts it (`python manage.py runserver`, or the Colab runtime for the notebook). Audio and text are processed there by the Coqui XTTS v2 model and are not sent to another service by this code.
- In Colab, the runtime is a Google-hosted machine. Treat samples uploaded there as handled by Colab.
- The standard (baseline) voice is the XTTS default speaker, not a separate online service.

## What is stored, and for how long

- Uploads are limited to 25 MB and 6-30 seconds. The app converts them to mono 22.05 kHz 16-bit WAV.
- Temporary conversion and partial files are deleted by the code after use. Generated outputs are written to a temporary folder and removed when the session is cleared ("Clear all") or replaced by a new generation.
- Open item: there is no timed deletion (for example a TTL) for generated files and no delete-after-download behavior yet. Backend retention is tracked as a separate task.

## Security notes

- Forms use Django CSRF protection.
- Open items for the backend: the development `SECRET_KEY` and `DEBUG = True` in `django_site/settings.py` must be replaced for any shared or deployed use, `ALLOWED_HOSTS` must be set, and there is no login or access control. The app is meant for local use only until these are done.

## Risks of voice cloning

- Cloned speech can be mistaken for a real person's voice. Misuse includes fraud, impersonation and misinformation.
- Quality varies by language and sample. Do not treat output as proof that a person said something.
- Keep samples and outputs private, and delete files you no longer need.

## Model license

The XTTS v2 model is covered by the Coqui Public Model License (CPML): https://coqui.ai/cpml. The CPML limits use to non-commercial purposes. The code sets `COQUI_TOS_AGREED=1` so the model loads without a prompt, which means running the app counts as accepting the license.
