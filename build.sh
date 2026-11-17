
#!/usr/bin/env bash

set -euo pipefail

echo "Installing Python build tools..."

python -m pip install --upgrade pip setuptools wheel


# ---------------------------------------------------------
# INSTALL LINUX CPU-ONLY PYTORCH
# ---------------------------------------------------------

echo "Installing CPU-only PyTorch 2.8.0..."

python -m pip install \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.8.0 \
    torchaudio==2.8.0


# ---------------------------------------------------------
# INSTALL REMAINING PROJECT REQUIREMENTS
# ---------------------------------------------------------

echo "Installing remaining project requirements..."

TEMP_REQUIREMENTS="$(mktemp)"

trap 'rm -f "$TEMP_REQUIREMENTS"' EXIT

# Exclude hardware-specific packages.
# PyTorch was installed separately above.

grep -Ev \
'^[[:space:]]*(torch|torchaudio|torchvision|torchcodec)([[:space:]]*(===|==|~=|!=|<=|>=|<|>)|[[:space:]]*$)' \
requirements.txt > "$TEMP_REQUIREMENTS"

python -m pip install -r "$TEMP_REQUIREMENTS"


# ---------------------------------------------------------
# DJANGO DEPLOYMENT PREPARATION
# ---------------------------------------------------------

echo "Checking Django configuration..."

python manage.py check


echo "Collecting static files for WhiteNoise..."

python manage.py collectstatic --noinput


echo "Applying database migrations..."

python manage.py migrate --noinput


echo "Render build completed successfully."
