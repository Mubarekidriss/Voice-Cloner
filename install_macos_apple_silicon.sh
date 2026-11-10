#!/bin/bash
set -euo pipefail

# Voice Cloner setup for macOS on Apple Silicon (M1/M2/M3/M4).
# Place beside manage.py and requirements.txt, then run:
#   bash install_macos_apple_silicon.sh
#
# Prerequisites: native arm64 Python 3.11 and macOS 12.3 or later for MPS.
# PyTorch 2.8.0 provides the Apple MPS backend. If MPS is unavailable,
# XTTS can still run on CPU, although generation will be slower.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
MANAGE_FILE="$PROJECT_DIR/manage.py"
VENV_DIR="$PROJECT_DIR/.venv-macos-apple-silicon"

fail() {
    echo "ERROR: $1" >&2
    exit 1
}

[[ "$(uname -s)" == "Darwin" ]] || fail "This installer is for macOS only."
[[ "$(uname -m)" == "arm64" ]] || fail "This installer requires an Apple Silicon Mac and a native arm64 Terminal session (not Rosetta)."
[[ -f "$MANAGE_FILE" ]] || fail "manage.py was not found beside this script. Put this script in the Django project root."
[[ -f "$REQUIREMENTS_FILE" ]] || fail "requirements.txt was not found beside this script."

PYTHON_BIN="$(command -v python3.11 || true)"
[[ -n "$PYTHON_BIN" ]] || fail "Python 3.11 was not found. Install the native Apple Silicon Python 3.11 build, then rerun this script."
PYTHON_INFO="$("$PYTHON_BIN" -c 'import platform, sys; print(f"{sys.version_info.major}.{sys.version_info.minor} {platform.machine()}")')"
[[ "$PYTHON_INFO" == "3.11 arm64" ]] || fail "python3.11 must be native arm64. Detected: $PYTHON_INFO. Check PATH and avoid an Intel/Rosetta Python."

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

# The installer owns platform-specific PyTorch. TorchCodec is unnecessary
# here because Coqui requires it only with PyTorch 2.9 and newer.
grep -Ev '^[[:space:]]*(torch|torchaudio|torchvision|torchcodec)([[:space:]]*(===|==|~=|!=|<=|>=|<|>)|[[:space:]]*$)' "$REQUIREMENTS_FILE" > "$TEMP_REQUIREMENTS"

"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel
"$VENV_PYTHON" -m pip install "torch==2.8.0" "torchaudio==2.8.0"
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
print("MPS built:", torch.backends.mps.is_built())
print("MPS available:", torch.backends.mps.is_available())
ffmpeg_path = shutil.which("ffmpeg")
print("FFmpeg executable:", ffmpeg_path)
if not ffmpeg_path:
    raise SystemExit("static-ffmpeg did not add an FFmpeg executable to PATH.")
if torch.backends.mps.is_available():
    print("Apple GPU acceleration is available to PyTorch.")
else:
    print("WARNING: MPS is unavailable; XTTS will need to use CPU.")
print("Coqui TTS import successful.")
PY

"$VENV_PYTHON" -m pip check
"$VENV_PYTHON" "$MANAGE_FILE" check
"$VENV_PYTHON" "$MANAGE_FILE" migrate --noinput

echo
echo "Apple Silicon installation completed. PyTorch, FFmpeg, Coqui, and Django checks passed."
echo "Environment: $VENV_DIR"
echo "Start Django with:"
echo "  \"$VENV_PYTHON\" manage.py runserver"
echo
echo "XTTS model files will be downloaded the first time the model is loaded."
