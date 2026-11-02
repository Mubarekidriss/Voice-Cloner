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
- Each browser session gets a working folder on the machine running the app (`voice_cloner_sessions/<id>` under Django's `MEDIA_ROOT`). The uploaded sample, the normalized WAV and the generated baseline and cloned WAVs live there.
- These files are kept until the user selects "Clear all", which deletes the whole folder. Normalizing a new sample deletes the old generated outputs. Generating again replaces them.
- Temporary files created during conversion and generation are removed after they are copied into the session folder.
- Not done yet: there is no automatic expiry (TTL), no delete-after-download, and no cleanup of abandoned session folders. Backend retention is a separate task.

## Security notes

- Forms use Django CSRF protection.
- Open items for the backend: the development `SECRET_KEY` and `DEBUG = True` in `django_site/settings.py` must be replaced for any shared or deployed use, `ALLOWED_HOSTS` must be set, and there is no login or access control. The app is meant for local use only until these are done.

## Risks of voice cloning

- Cloned speech can be mistaken for a real person's voice. Misuse includes fraud, impersonation and misinformation.
- Quality varies by language and sample. Do not treat output as proof that a person said something.
- Keep samples and outputs private, and delete files you no longer need.

## Model license

The XTTS v2 model is covered by the Coqui Public Model License (CPML): https://coqui.ai/cpml. The CPML limits use to non-commercial purposes. The code sets `COQUI_TOS_AGREED=1` so the model loads without a prompt, which means running the app counts as accepting the license.
