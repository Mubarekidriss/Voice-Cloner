"""Django views for the local XTTS Voice Cloner UI.

The reusable XTTS/audio modules (config.py, audio_utils.py, audio_validation.py,
tts_engine.py) are expected to live in the project root next to manage.py.
"""

import json
import logging
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from threading import Lock

from django.core.exceptions import ValidationError

import time
from .security import consent_required
from django.contrib.auth.decorators import login_required

# Supports either the project-root layout or the existing `modules/` layout.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = PROJECT_ROOT / "modules"
if MODULES_DIR.is_dir() and str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))

# Set the Coqui consent flag before importing/initializing the model, matching
# the existing local Gradio application's behavior.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

# Makes a bundled FFmpeg/ffprobe available to pydub and audio conversion code.
# Keep this if static-ffmpeg is already part of the project's requirements.
import static_ffmpeg

static_ffmpeg.add_paths()

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from audio_utils import normalize_audio
from audio_validation import AudioValidationError, validate_audio
from config import DEFAULT_SPEAKER, LANGUAGES
from tts_engine import TTSEngineError, XTTSService, load_tts

logger = logging.getLogger(__name__)

ALLOWED_AUDIO_SUFFIX = re.compile(
    r"^\.[a-zA-Z0-9]{1,8}$"
)

_workspace_cleanup_lock = Lock()

# Load XTTS once per Django process. A separate generation lock prevents two
# simultaneous requests from using the same model instance at the same time.
_tts_service = None
_tts_service_lock = Lock()
_generation_lock = Lock()


def _get_tts_service() -> XTTSService:
    """Create the service on first use and reuse it for later requests.

    This assumes XTTSService() loads/validates its model in its constructor.
    If your implementation has an explicit load() call, call it here once.
    """
    global _tts_service
    if _tts_service is None:
        with _tts_service_lock:
            if _tts_service is None:
                _tts_service = load_tts()
    return _tts_service

def _private_sessions_root() -> Path:
    """Return the private session storage directory."""

    root = Path(settings.PRIVATE_AUDIO_ROOT).resolve()

    media_root = Path(settings.MEDIA_ROOT).resolve()

    # Prevent accidentally placing private files inside MEDIA_ROOT.
    if root == media_root or media_root in root.parents:
        raise RuntimeError(
            "PRIVATE_AUDIO_ROOT must be outside MEDIA_ROOT."
        )

    root.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700
    )

    sessions_root = root / "sessions"

    sessions_root.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700
    )

    if os.name != "nt":
        os.chmod(root, 0o700)
        os.chmod(sessions_root, 0o700)

    return sessions_root.resolve()


def _workspace_dir(request, create: bool = True) -> Path:
    """
    Return a private working directory for the current
    authenticated user and browser session.
    """

    if not request.user.is_authenticated:
        raise Http404("Authentication required.")

    current_user_id = str(request.user.pk)

    workspace_owner = request.session.get(
        "voice_cloner_workspace_owner"
    )

    workspace_id = request.session.get(
        "voice_cloner_workspace"
    )

    # If a different account is using this browser session,
    # discard the previous account's session references.
    if workspace_owner != current_user_id:

        for key in (
            "voice_cloner_workspace",
            "voice_cloner_reference_name",
            "voice_cloner_text",
            "voice_cloner_language",
        ):
            request.session.pop(key, None)

        workspace_id = None

        request.session["voice_cloner_workspace_owner"] = (
            current_user_id
        )

    # Create a new workspace if none exists or its ID is invalid.
    if not workspace_id or not re.fullmatch(
        r"[a-f0-9]{32}", workspace_id
    ):

        request.session.pop(
            "voice_cloner_reference_name", None
        )

        if not create:
            raise Http404("No audio workspace exists.")

        workspace_id = uuid.uuid4().hex

        request.session["voice_cloner_workspace"] = (
            workspace_id
        )

        request.session["voice_cloner_workspace_owner"] = (
            current_user_id
        )

    root = _private_sessions_root()

    workspace = root / workspace_id

    if workspace.is_symlink():
        raise Http404("Invalid audio workspace.")

    if create:

        workspace.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700
        )

    elif not workspace.is_dir():

        raise Http404("Audio workspace not found.")

    workspace = workspace.resolve()

    if workspace.parent != root:
        raise Http404("Invalid audio workspace.")

    if os.name != "nt":
        os.chmod(workspace, 0o700)

    # Refresh activity time for automatic audio retention.
    os.utime(workspace, None)

    return workspace


def _cleanup_expired_workspaces():
    """
    Delete inactive audio workspaces.

    Removes original uploads, normalized audio, and generated
    baseline/cloned recordings together.
    """

    root = _private_sessions_root()

    retention = settings.AUDIO_RETENTION_SECONDS

    if retention <= 0:
        return

    expiration_time = time.time() - retention

    with _workspace_cleanup_lock:

        for workspace in root.iterdir():

            if workspace.is_symlink():
                continue

            if not workspace.is_dir():
                continue

            try:

                last_activity = workspace.stat().st_mtime

                if last_activity < expiration_time:

                    shutil.rmtree(workspace)

            except OSError:

                logger.warning(
                    "Could not remove expired audio workspace: %s",
                    workspace,
                    exc_info=True
                )


def _reference_path(request) -> Path | None:
    name = request.session.get("voice_cloner_reference_name")
    if not name:
        return None
    # The name is created by _save_uploaded_reference; disallow paths anyway.
    if Path(name).name != name or not name.startswith("reference_original"):
        return None
    try:
        path = _workspace_dir(request, create=False) / name
    except Http404:
        return None
    return path if path.is_file() else None


def _delete_named_files(workspace: Path, *names: str) -> None:
    for name in names:
        path = workspace / name
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
        except OSError:
            logger.warning("Could not remove old Voice Cloner file: %s", path, exc_info=True)


def _save_uploaded_reference(request, uploaded_file) -> Path:
    """Save and validate an uploaded or recorded audio sample."""

    max_upload_size = settings.MAX_AUDIO_UPLOAD_BYTES

    if uploaded_file.size > max_upload_size:
        raise ValueError("The audio file exceeds the 25 MB limit.")

    if uploaded_file.size == 0:
        raise ValueError("The uploaded audio file is empty.")

    suffix = Path(uploaded_file.name).suffix.lower()

    if not ALLOWED_AUDIO_SUFFIX.fullmatch(suffix):
        raise ValueError("The uploaded audio file has an invalid extension.")

    workspace = _workspace_dir(request)

    old_name = request.session.get(
        "voice_cloner_reference_name"
    )

    new_name = f"reference_original{suffix}"

    destination = workspace / new_name

    # Unique temporary filename, retaining the real audio extension
    # so the existing audio validator can identify the format.
    partial = workspace / (
        f".{uuid.uuid4().hex}.uploading{suffix}"
    )

    copied_size = 0

    try:

        with partial.open("xb") as target:

            for chunk in uploaded_file.chunks():

                copied_size += len(chunk)

                if copied_size > max_upload_size:
                    raise ValueError(
                        "The audio file exceeds the 25 MB limit."
                    )

                target.write(chunk)

            target.flush()
            os.fsync(target.fileno())

        if copied_size != uploaded_file.size:
            raise ValueError(
                "The uploaded audio file was not saved completely."
            )

        if os.name != "nt":
            os.chmod(partial, 0o600)

        # Use the project's existing audio validation module.
        validate_audio(str(partial))

        # Only replace the previous reference after validation succeeds.
        partial.replace(destination)

    except Exception:

        partial.unlink(missing_ok=True)

        raise

    if old_name and old_name != new_name:
        _delete_named_files(workspace, old_name)

    request.session["voice_cloner_reference_name"] = new_name

    # A new reference invalidates all existing derived audio.
    _delete_named_files(
        workspace,
        "normalized.wav",
        "baseline.wav",
        "cloned.wav"
    )

    return destination


def _copy_and_remove_temp(source_path, destination_path: Path, workspace: Path) -> None:
    """Copy a generated temporary file to a stable session path, then clean it."""
    source = Path(source_path)
    if not source.is_file():
        raise RuntimeError(f"The audio engine did not create the expected output: {source.name}")
    shutil.copy2(source, destination_path)

    if os.name != "nt":
        os.chmod(destination_path, 0o600)

    try:
        resolved_source = source.resolve()
        resolved_workspace = workspace.resolve()
        # Do not remove files owned by the session workspace.
        if resolved_source != destination_path.resolve() and resolved_workspace not in resolved_source.parents:
            source.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove temporary audio file %s", source, exc_info=True)


def _load_verify_results() -> dict:
    """Read optional smoke-test results written by verify_languages.py."""
    path = Path(__file__).resolve().parent.parent / "verify_results.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    results = data.get("results", data) if isinstance(data, dict) else {}
    verified = {}
    for code, entry in results.items():
        ok = entry.get("ok") if isinstance(entry, dict) else entry in (True, "ok")
        if ok:
            verified[code] = "smoke-tested"
    return verified


def _file_exists(workspace: Path | None, name: str | None) -> bool:
    return bool(workspace and name and (workspace / name).is_file())


def _render_home(request, *, service=None, service_error=None, status_message=None):
    workspace = None
    try:
        workspace = _workspace_dir(request, create=False)
    except Http404:
        pass

    available_languages = set(getattr(service, "available_languages", []) or [])
    verified = _load_verify_results()
    reference_name = request.session.get("voice_cloner_reference_name")
    has_original = _file_exists(workspace, reference_name)
    has_normalized = _file_exists(workspace, "normalized.wav")
    has_baseline = _file_exists(workspace, "baseline.wav")
    has_cloned = _file_exists(workspace, "cloned.wav")

    selected_language = request.session.get("voice_cloner_language", "English")
    if selected_language not in LANGUAGES:
        selected_language = "English"

    context = {
        "default_speaker": DEFAULT_SPEAKER,
        "languages": LANGUAGES,
        "lang_total": len(LANGUAGES),
        "available_languages": available_languages,
        "lang_loaded": sum(1 for code in LANGUAGES.values() if code in available_languages),
        "verified": verified,
        "device": getattr(service, "device", "unavailable"),
        "service_error": service_error,
        "status_message": status_message,
        "text_input": request.session.get("voice_cloner_text", ""),
        "selected_language": selected_language,
        "has_original": has_original,
        "has_normalized": has_normalized,
        "has_baseline": has_baseline,
        "has_cloned": has_cloned,
        "original_name": reference_name,
        "model_loaded": service is not None,
        "configured_languages": set(LANGUAGES.values()),
        "device": getattr(service, "device", "not loaded yet"),
        "consent_acknowledged": (
            request.session.get("voice_cloner_consent_acknowledged")
            is True
        ),
    }
    return render(request, "index.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@consent_required
def index(request):
    """Render the UI and handle upload, normalize, generate, and clear actions."""
    _cleanup_expired_workspaces()

    if request.method == "GET":
        return _render_home(request, service=_tts_service)

    action = request.POST.get("action", "")
    if action == "clear":
        try:
            workspace = _workspace_dir(request, create=False)
            shutil.rmtree(workspace, ignore_errors=True)
        except Http404:
            pass
        for key in (
            "voice_cloner_workspace",
            "voice_cloner_workspace_owner",
            "voice_cloner_reference_name",
            "voice_cloner_text",
            "voice_cloner_language",
            "voice_cloner_consent_acknowledged",
        ):
            request.session.pop(key, None)
        return redirect("voice_cloner_home")

    text = request.POST.get("text_input", "")
    language = request.POST.get("language", "English")

    try:
        # Bind the current session to the authenticated user
        # before saving any new session-specific information.
        if action in {"upload", "normalize", "generate"}:
            _workspace_dir(request, create=True)

        request.session["voice_cloner_text"] = text

        request.session["voice_cloner_language"] = (
            language if language in LANGUAGES else "English"
        )
        # This also supports choosing a new file and clicking Normalize or
        # Generate directly, without requiring a separate upload-button click.
        uploaded = request.FILES.get("reference_audio")
        if uploaded:
            _save_uploaded_reference(request, uploaded)

        if action == "upload":
            if not _reference_path(request):
                messages.error(request, "Choose an audio file or record a sample first.")
            else:
                messages.success(request, "Voice sample saved. Next, normalize it to WAV.")

        elif action == "normalize":
            original_path = _reference_path(request)
            if not original_path:
                raise ValueError("Record or upload a voice sample first.")

            validate_audio(str(original_path))
            try:
                temporary_wav = Path(normalize_audio(str(original_path)))
            except Exception as exc:
                raise ValueError(f"Audio conversion failed: {exc}") from exc
            workspace = _workspace_dir(request)
            normalized_path = workspace / "normalized.wav"
            try:
                shutil.copy2(temporary_wav, normalized_path)

                if os.name != "nt":
                    os.chmod(normalized_path, 0o600)
            finally:
                try:
                    if temporary_wav.resolve() != normalized_path.resolve():
                        temporary_wav.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove temporary normalized WAV", exc_info=True)

            _delete_named_files(workspace, "baseline.wav", "cloned.wav")
            messages.success(request, "Audio normalized successfully. You can preview or download the WAV.")

        elif action == "generate":
            original_path = _reference_path(request)
            if not original_path:
                raise ValueError("Please record or upload a voice sample.")
            if not text.strip():
                raise ValueError("Enter the text you want the model to speak.")
            if len(text) > 10000:
                raise ValueError("Text must be 10,000 characters or fewer.")
            if language not in LANGUAGES:
                raise ValueError("Choose a valid speech language.")

            # Validate the current original even when a normalized copy exists,
            # matching the behavior of the Gradio version.
            validate_audio(str(original_path))
            workspace = _workspace_dir(request)
            normalized_path = workspace / "normalized.wav"
            reference_path = normalized_path if normalized_path.is_file() else original_path

            service = _get_tts_service()
            language_code = LANGUAGES[language]
            if language_code not in service.available_languages:
                raise ValueError(f"{language} is not available in the loaded XTTS model.")

            # Remove older outputs first so a failed retry cannot leave stale
            # audio visible as if it came from the newest text/reference.
            _delete_named_files(workspace, "baseline.wav", "cloned.wav")
            baseline_temp = clone_temp = None
            try:
                with _generation_lock:
                    baseline_temp, clone_temp = service.generate_voices(
                        text.strip(), str(reference_path), language
                    )
                    _copy_and_remove_temp(baseline_temp, workspace / "baseline.wav", workspace)
                    _copy_and_remove_temp(clone_temp, workspace / "cloned.wav", workspace)
            finally:
                for candidate in (baseline_temp, clone_temp):
                    if candidate:
                        path = Path(candidate)
                        try:
                            if path.is_file() and workspace.resolve() not in path.resolve().parents:
                                path.unlink(missing_ok=True)
                        except OSError:
                            logger.warning("Could not remove generated temporary output", exc_info=True)

            messages.success(request, "Speech generated. Play both versions and compare them below.")

        else:
            messages.error(request, "Unknown action. Please try again.")

    except AudioValidationError as exc:
        messages.error(
            request,
            f"The audio sample could not be used: {exc}"
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    except TTSEngineError:
        logger.exception("XTTS speech generation failed")
        messages.error(
            request,
            "Speech generation failed. Try a shorter text or a clearer "
            "voice sample. Technical details are available in the terminal."
        )
    except Exception:
        logger.exception("Voice Cloner request failed")
        messages.error(
            request,
            "Something went wrong while processing your request. "
            "Check the terminal for technical details."
        )

    return redirect("voice_cloner_home")


@login_required
@require_http_methods(["GET"])
def audio_file(request, kind: str):
    """Stream private audio belonging to the current browser session."""

    _cleanup_expired_workspaces()

    allowed_names = {
        "original": request.session.get(
            "voice_cloner_reference_name"
        ),
        "normalized": "normalized.wav",
        "baseline": "baseline.wav",
        "cloned": "cloned.wav",
    }

    if kind not in allowed_names:
        raise Http404("Unknown audio file.")

    name = allowed_names[kind]

    if not name or Path(name).name != name:
        raise Http404("Audio file not found.")

    try:
        workspace = _workspace_dir(
            request,
            create=False
        ).resolve()

        candidate = workspace / name

        if candidate.is_symlink():
            raise Http404("Audio file not found.")

        path = candidate.resolve(strict=True)

    except (OSError, RuntimeError):
        raise Http404("Audio file not found.")

    if path.parent != workspace or not path.is_file():
        raise Http404("Audio file not found.")

    download = request.GET.get("download") == "1"

    content_type = (
        "audio/wav"
        if path.suffix.lower() == ".wav"
        else None
    )

    response = FileResponse(
        path.open("rb"),
        as_attachment=download,
        filename=path.name,
        content_type=content_type,
    )

    # Prevent browsers and intermediaries from caching sensitive recordings.
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    response["Pragma"] = "no-cache"

    return response