#!/bin/bash
set -euo pipefail

# Voice Cloner setup for Intel-based macOS Macs (x86_64).
# Place beside manage.py and requirements.txt, then run:
#   bash install_macos_intel.sh
#
# Prerequisites: native x86_64 Python 3.11. This installer uses CPU PyTorch;
# Intel macOS does not use Apple's MPS backend.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
MANAGE_FILE="$PROJECT_DIR/manage.py"
VENV_DIR="$PROJECT_DIR/.venv-macos-intel"

fail() {
    echo "ERROR: $1" >&2
    exit 1
}

[[ "$(uname -s)" == "Darwin" ]] || fail "This installer is for macOS only."
[[ "$(uname -m)" == "x86_64" ]] || fail "This installer requires an Intel Mac running a native x86_64 Terminal session."
[[ -f "$MANAGE_FILE" ]] || fail "manage.py was not found beside this script. Put this script in the Django project root."
[[ -f "$REQUIREMENTS_FILE" ]] || fail "requirements.txt was not found beside this script."

PYTHON_BIN="$(command -v python3.11 || true)"
[[ -n "$PYTHON_BIN" ]] || fail "Python 3.11 was not found. Install the Intel x86_64 Python 3.11 build, then rerun this script."
PYTHON_INFO="$("$PYTHON_BIN" -c 'import platform, sys; print(f"{sys.version_info.major}.{sys.version_info.minor} {platform.machine()}")')"
[[ "$PYTHON_INFO" == "3.11 x86_64" ]] || fail "python3.11 must be native x86_64. Detected: $PYTHON_INFO. Check PATH."

cd "$PROJECT_DIR"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment: $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "Reusing virtual environment: $VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
TEMP_REQUIREMENTS="$(mktemp)"
trap 'rm -f "$TEMP_REQUIREMENTS"' EXIT

# PyTorch 2.2.2 is the Intel macOS x86_64 wheel used by this installer.
# Coqui supports PyTorch 2.2+; TorchCodec is only needed at PyTorch 2.9+.
grep -Ev '^[[:space:]]*(torch|torchaudio|torchvision|torchcodec)([[:space:]]*(===|==|~=|!=|<=|>=|<|>)|[[:space:]]*$)' "$REQUIREMENTS_FILE" > "$TEMP_REQUIREMENTS"

"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel
"$VENV_PYTHON" -m pip install "torch==2.2.2" "torchaudio==2.2.2"
"$VENV_PYTHON" -m pip install -r "$TEMP_REQUIREMENTS"

"$VENV_PYTHON" - <<'PY'
import platform
import shutil
import torch
import torchaudio
import static_ffmpeg
static_ffmpeg.add_paths()
from TTS.api import TTS

print("\nInstallation verification")
print("Python architecture:", platform.machine())
print("PyTorch:", torch.__version__)
print("torchaudio:", torchaudio.__version__)
print("MPS available:", hasattr(torch.backends, "mps") and torch.backends.mps.is_available())
print("CUDA available:", torch.cuda.is_available())
ffmpeg_path = shutil.which("ffmpeg")
print("FFmpeg executable:", ffmpeg_path)
if not ffmpeg_path:
    raise SystemExit("static-ffmpeg did not add an FFmpeg executable to PATH.")
print("This Intel Mac installation uses CPU inference.")
print("Coqui TTS import successful.")
PY

"$VENV_PYTHON" -m pip check
"$VENV_PYTHON" "$MANAGE_FILE" check
"$VENV_PYTHON" "$MANAGE_FILE" migrate --noinput

echo
echo "Intel Mac installation completed. PyTorch, FFmpeg, Coqui, and Django checks passed."
echo "Environment: $VENV_DIR"
echo "Start Django with:"
echo "  \"$VENV_PYTHON\" manage.py runserver"
echo
echo "XTTS model files will be downloaded the first time the model is loaded."
