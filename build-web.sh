#!/usr/bin/env bash
set -euo pipefail
export VOICE_INFERENCE_MODE=remote
python -m pip install -r requirements-web.txt
python manage.py check
python manage.py collectstatic --noinput
python manage.py migrate --noinput
