"""Backend service for loading and using the XTTS-v2 model.

The Gradio layer should call ``load_tts()`` once at application startup and
then use the returned ``XTTSService``. Model-specific code, validation of the
selected language, inference serialization, diagnostics, and generated-file
lifetime are intentionally kept here rather than in the UI.
"""
from __future__ import annotations

import atexit
import logging
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from config import DEFAULT_SPEAKER, LANGUAGES, MODEL_NAME

logger = logging.getLogger(__name__)


class TTSEngineError(RuntimeError):
    """Base error whose message is suitable to show in the UI."""


class ModelLoadError(TTSEngineError):
    """Raised when XTTS cannot be loaded or fails startup validation."""


class LanguageSelectionError(TTSEngineError):
    """Raised when a UI language is unknown or unsupported by the model."""


class GenerationError(TTSEngineError):
    """Raised when XTTS fails to generate a usable WAV file."""


def validate_model(model: Any) -> tuple[set[str], set[str]]:
    """Validate the loaded model's speaker and language metadata.

    Returns ``(available_languages, available_speakers)``. This checks the
    model metadata, not actual speech generation quality; use
    ``verify_languages.py`` for real inference smoke tests.
    """
    available_speakers = set(getattr(model, "speakers", None) or [])
    available_languages = set(getattr(model, "languages", None) or [])

    if DEFAULT_SPEAKER not in available_speakers:
        raise ModelLoadError(
            f"The loaded XTTS model does not contain the configured baseline "
            f"speaker '{DEFAULT_SPEAKER}'. Check DEFAULT_SPEAKER in config.py."
        )

    missing_codes = sorted(set(LANGUAGES.values()) - available_languages)
    if missing_codes:
        raise ModelLoadError(
            "The loaded XTTS model is missing configured language code(s): "
            f"{', '.join(missing_codes)}. Check the installed model and "
            "LANGUAGES in config.py."
        )

    return available_languages, available_speakers


def _is_mps_available(torch_module: Any) -> bool:
    """Return whether this PyTorch build reports an available Apple MPS device."""
    try:
        return bool(torch_module.backends.mps.is_available())
    except (AttributeError, RuntimeError):
        return False


def _resolve_device(torch_module: Any, requested: str) -> str:
    """Resolve ``auto``/CPU/CUDA/MPS, preferring the best-supported default.

    Auto mode deliberately selects CUDA when available, otherwise CPU. XTTS-v2
    has had upstream MPS operator/compatibility problems, so MPS is opt-in via
    VOICE_CLONER_DEVICE=mps rather than being selected automatically.
    """
    requested = (requested or "auto").strip().lower()
    if requested not in {"auto", "cpu", "cuda", "mps"}:
        raise ModelLoadError(
            "Invalid VOICE_CLONER_DEVICE value. Choose 'auto', 'cpu', 'cuda', or 'mps'."
        )

    cuda_available = bool(torch_module.cuda.is_available())
    mps_available = _is_mps_available(torch_module)

    if requested == "auto":
        if cuda_available:
            return "cuda"
        if mps_available:
            logger.warning(
                "Apple MPS is available, but XTTS-v2 has known MPS compatibility "
                "issues. Using CPU by default; set VOICE_CLONER_DEVICE=mps to "
                "try MPS experimentally."
            )
        return "cpu"

    if requested == "cuda" and not cuda_available:
        raise ModelLoadError(
            "CUDA was requested, but PyTorch cannot access a CUDA GPU. "
            "Set VOICE_CLONER_DEVICE=auto or cpu, then restart the app."
        )

    if requested == "mps" and not mps_available:
        raise ModelLoadError(
            "MPS was requested, but this PyTorch/macOS installation does not "
            "report an available MPS device. Use 'auto' or 'cpu' instead."
        )

    if requested == "mps":
        logger.warning(
            "MPS was explicitly enabled. XTTS-v2 may fail or run more slowly "
            "on MPS than on CPU; this mode is experimental."
        )

    return requested


class XTTSService:
    """Own an XTTS model and expose validated synthesis operations.

    Generated WAVs are stored in a dedicated temporary directory. Successful
    files remain available to Gradio for playback/download during the app
    session and are removed when ``close()`` runs (also registered at exit).
    Failed/partial outputs are removed immediately.
    """

    def __init__(self, model: Any, device: str = "cpu") -> None:
        self._model = model
        self.device = device
        self.available_languages, self.available_speakers = validate_model(model)
        self._lock = threading.Lock()
        self._closed = False
        self._output_dir = Path(tempfile.mkdtemp(prefix="voice_cloner_xtts_"))
        atexit.register(self.close)

    @property
    def output_dir(self) -> Path:
        """Directory containing this service's temporary generated audio."""
        return self._output_dir

    def _ensure_open(self) -> None:
        if self._closed:
            raise TTSEngineError("The speech engine has been shut down. Restart the app to use it again.")

    @staticmethod
    def _validate_text(text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise TTSEngineError("Type some text first.")
        return text.strip()

    def _language_code(self, language: str) -> str:
        if language not in LANGUAGES:
            raise LanguageSelectionError("Please select a supported language from the list.")

        code = LANGUAGES[language]
        if code not in self.available_languages:
            # This should normally be caught during startup. Keep the check at
            # the request boundary in case the configuration/model is changed.
            raise LanguageSelectionError(
                f"The loaded XTTS model does not support {language} ({code})."
            )
        return code

    @staticmethod
    def _validate_reference(reference_audio: str | os.PathLike[str]) -> str:
        if not reference_audio:
            raise TTSEngineError("Please record or upload a voice sample first.")
        path = os.fspath(reference_audio)
        if not os.path.isfile(path):
            raise TTSEngineError("The reference audio file could not be found. Please upload or record it again.")
        try:
            if os.path.getsize(path) <= 0:
                raise TTSEngineError("The reference audio file is empty. Please upload or record it again.")
        except OSError as exc:
            raise TTSEngineError("The reference audio file could not be accessed.") from exc
        return path

    def _new_output_path(self, kind: str) -> str:
        return str(self._output_dir / f"{kind}_{uuid.uuid4().hex}.wav")

    @staticmethod
    def _remove_files(*paths: str | None) -> None:
        for path in paths:
            if not path:
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("Could not remove temporary audio file: %s", path, exc_info=True)

    @staticmethod
    def _check_output(path: str) -> None:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise RuntimeError("XTTS returned without writing a non-empty output file.")

    def _synthesize_locked(
        self,
        *,
        text: str,
        language_code: str,
        output_path: str,
        reference_audio: str | None = None,
    ) -> None:
        """Run one model call. Caller must hold ``self._lock``."""
        args: dict[str, Any] = {
            "text": text,
            "language": language_code,
            "file_path": output_path,
        }
        if reference_audio is None:
            args["speaker"] = DEFAULT_SPEAKER
        else:
            args["speaker_wav"] = reference_audio

        self._model.tts_to_file(**args)
        self._check_output(output_path)

    def _user_generation_error(self, exc: Exception) -> GenerationError:
        message = str(exc).lower()
        if "out of memory" in message or "cuda error: out of memory" in message:
            user_message = (
                "XTTS ran out of memory on the selected device. Try shorter text, "
                "close other GPU-heavy applications, or restart the app in CPU mode."
            )
        else:
            user_message = (
                f"XTTS could not generate the audio on {self.device}. Check the "
                "reference audio and selected language, then try again. See the "
                "terminal/console output for diagnostic details."
            )
        logger.exception("XTTS generation failed on device %s", self.device, exc_info=exc)
        return GenerationError(user_message)

    def generate_baseline(self, text: str, language: str) -> str:
        """Generate audio with the configured predefined XTTS speaker."""
        text = self._validate_text(text)
        language_code = self._language_code(language)
        output_path = self._new_output_path("baseline")

        with self._lock:
            self._ensure_open()
            try:
                self._synthesize_locked(
                    text=text,
                    language_code=language_code,
                    output_path=output_path,
                )
            except Exception as exc:
                self._remove_files(output_path)
                raise self._user_generation_error(exc) from exc

        return output_path

    def generate_clone(self, text: str, reference_audio: str | os.PathLike[str], language: str) -> str:
        """Generate audio conditioned on a reference voice sample."""
        text = self._validate_text(text)
        language_code = self._language_code(language)
        reference_path = self._validate_reference(reference_audio)
        output_path = self._new_output_path("clone")

        with self._lock:
            self._ensure_open()
            try:
                self._synthesize_locked(
                    text=text,
                    language_code=language_code,
                    output_path=output_path,
                    reference_audio=reference_path,
                )
            except Exception as exc:
                self._remove_files(output_path)
                raise self._user_generation_error(exc) from exc

        return output_path

    def generate_voices(
        self,
        text: str,
        reference_audio: str | os.PathLike[str],
        language: str,
    ) -> tuple[str, str]:
        """Generate both baseline and cloned audio as one serialized operation."""
        text = self._validate_text(text)
        language_code = self._language_code(language)
        reference_path = self._validate_reference(reference_audio)
        baseline_path = self._new_output_path("baseline")
        clone_path = self._new_output_path("clone")

        # XTTS model instances should not be used for concurrent inference.
        # Keep the pair together so requests cannot interleave between outputs.
        with self._lock:
            self._ensure_open()
            try:
                self._synthesize_locked(
                    text=text,
                    language_code=language_code,
                    output_path=baseline_path,
                )
                self._synthesize_locked(
                    text=text,
                    language_code=language_code,
                    output_path=clone_path,
                    reference_audio=reference_path,
                )
            except Exception as exc:
                self._remove_files(baseline_path, clone_path)
                raise self._user_generation_error(exc) from exc

        return baseline_path, clone_path

    def close(self) -> None:
        """Remove generated temporary audio; safe to call more than once."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            shutil.rmtree(self._output_dir, ignore_errors=True)


def load_tts(device: str | None = None) -> XTTSService:
    """Load XTTS once and return a validated service instance.

    ``device`` overrides ``VOICE_CLONER_DEVICE``. Defaults to CUDA when
    available, otherwise CPU. If automatic CUDA loading fails, initialization
    is retried on CPU. Set VOICE_CLONER_DEVICE=cpu|cuda|mps to force a device.
    """
    requested = device or os.environ.get("VOICE_CLONER_DEVICE", "auto")

    try:
        import torch
    except Exception as exc:
        logger.exception("PyTorch import failed")
        raise ModelLoadError(
            "PyTorch could not be imported. Reinstall the dependencies in the "
            "project's virtual environment, then restart the app."
        ) from exc

    resolved = _resolve_device(torch, requested)

    try:
        from TTS.api import TTS
    except Exception as exc:
        logger.exception("Coqui TTS import failed")
        raise ModelLoadError(
            "Coqui TTS could not be imported. Check the installed coqui-tts and "
            "transformers versions, then restart the app."
        ) from exc

    attempts = [resolved]
    if requested.strip().lower() == "auto" and resolved == "cuda":
        attempts.append("cpu")

    model = None
    actual_device = resolved
    last_error: Exception | None = None

    for index, candidate in enumerate(attempts):
        logger.info("Loading %s on %s (first run downloads the model files).", MODEL_NAME, candidate)
        print(f"Loading {MODEL_NAME} on {candidate} (first run downloads the model files)...")
        try:
            model = TTS(MODEL_NAME).to(candidate)
            actual_device = candidate
            break
        except Exception as exc:
            last_error = exc
            logger.exception("XTTS model load failed on %s", candidate)
            if index + 1 < len(attempts):
                logger.warning("CUDA initialization failed; retrying XTTS on CPU.")
                print("WARNING: XTTS failed to initialize on CUDA; retrying on CPU.")

    if model is None:
        logger.error("XTTS could not be loaded", exc_info=last_error)
        raise ModelLoadError(
            "XTTS could not be loaded. Check the installed dependencies, available "
            "memory, and model download/cache, then review the terminal output."
        ) from last_error

    # Perform metadata checks outside the device fallback loop: a missing
    # speaker/language is a model/configuration mismatch, not a GPU failure.
    try:
        service = XTTSService(model=model, device=actual_device)
    except ModelLoadError:
        logger.exception("Loaded XTTS model failed startup validation")
        raise
    except Exception as exc:
        logger.exception("XTTS service initialization failed")
        raise ModelLoadError("XTTS loaded, but the backend service could not initialize.") from exc

    if actual_device == "cpu":
        print("WARNING: XTTS is running on CPU and will be significantly slower than a supported CUDA GPU.")
    print(f"XTTS model loaded on {actual_device}.")
    print(f"Verified baseline speaker: {DEFAULT_SPEAKER}")
    print(f"Verified configured languages: {len(LANGUAGES)}")
    logger.info("XTTS model loaded on %s; verified %d configured languages.", actual_device, len(LANGUAGES))
    return service
