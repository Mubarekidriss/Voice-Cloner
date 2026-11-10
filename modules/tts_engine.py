"""Backend service for loading and using the XTTS-v2 model.

The service prefers a supported local accelerator (NVIDIA CUDA, AMD ROCm,
Intel XPU, or Apple MPS) and falls back to CPU if accelerator initialization
or the first inference attempt fails.
"""
from __future__ import annotations

import atexit
import gc
import logging
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence

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
    """Validate the loaded model's speaker and language metadata."""
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


def _is_cuda_available(torch_module: Any) -> bool:
    """Detect CUDA-compatible PyTorch devices, including AMD ROCm."""
    try:
        return bool(torch_module.cuda.is_available())
    except Exception:
        logger.debug("CUDA/ROCm detection failed.", exc_info=True)
        return False


def _is_rocm(torch_module: Any) -> bool:
    """Detect a ROCm build or an AMD Radeon device behind PyTorch's CUDA API."""
    hip_version = getattr(getattr(torch_module, "version", None), "hip", None)
    if hip_version:
        return True

    # Some vendor builds do not expose torch.version.hip consistently.
    try:
        if torch_module.cuda.is_available():
            name = str(torch_module.cuda.get_device_name(0)).lower()
            return "amd" in name or "radeon" in name
    except Exception:
        pass

    return False


def _is_xpu_available(torch_module: Any) -> bool:
    """Detect Intel GPU acceleration through PyTorch XPU."""
    try:
        xpu = getattr(torch_module, "xpu", None)
        return bool(xpu and xpu.is_available())
    except Exception:
        logger.debug("Intel XPU detection failed.", exc_info=True)
        return False


def _is_mps_available(torch_module: Any) -> bool:
    """Detect Apple GPU acceleration through Metal Performance Shaders."""
    try:
        return bool(torch_module.backends.mps.is_available())
    except Exception:
        logger.debug("Apple MPS detection failed.", exc_info=True)
        return False


def _resolve_device(torch_module: Any, requested: str) -> list[str]:
    """Return devices to try, in priority order, with CPU as final fallback."""
    requested = (requested or "auto").strip().lower()
    valid_devices = {"auto", "cpu", "cuda", "rocm", "xpu", "mps"}

    if requested not in valid_devices:
        raise ModelLoadError(
            "Invalid VOICE_CLONER_DEVICE setting. "
            "Choose auto, cpu, cuda, rocm, xpu, or mps."
        )

    cuda_available = _is_cuda_available(torch_module)
    rocm_available = _is_rocm(torch_module)
    xpu_available = _is_xpu_available(torch_module)
    mps_available = _is_mps_available(torch_module)

    if requested == "auto":
        candidates: list[str] = []
        if cuda_available:
            # AMD ROCm is intentionally selected as "cuda" by PyTorch.
            candidates.append("cuda")
        if xpu_available:
            candidates.append("xpu")
        if mps_available:
            candidates.append("mps")
        candidates.append("cpu")
        return candidates

    if requested == "cpu":
        return ["cpu"]

    if requested == "rocm":
        if not rocm_available or not cuda_available:
            raise ModelLoadError(
                "ROCm was requested, but an AMD ROCm-enabled PyTorch "
                "installation and compatible GPU were not detected."
            )
        return ["cuda"]

    if requested == "cuda":
        if not cuda_available:
            raise ModelLoadError(
                "CUDA/ROCm was requested, but PyTorch cannot access "
                "a compatible GPU. Check your PyTorch installation and drivers."
            )
        return ["cuda"]

    if requested == "xpu":
        if not xpu_available:
            raise ModelLoadError(
                "Intel XPU was requested, but PyTorch cannot access "
                "a compatible Intel GPU."
            )
        return ["xpu"]

    if requested == "mps":
        if not mps_available:
            raise ModelLoadError(
                "Apple MPS was requested, but it is not available "
                "in this PyTorch/macOS installation."
            )
        return ["mps"]

    return ["cpu"]


def _device_description(torch_module: Any, device: str) -> str:
    """Return a readable description of the selected execution device."""
    if device == "cuda":
        try:
            gpu_name = torch_module.cuda.get_device_name(0)
        except Exception:
            gpu_name = "GPU"
        backend = "AMD ROCm" if _is_rocm(torch_module) else "NVIDIA CUDA"
        return f"{backend} - {gpu_name}"

    if device == "xpu":
        try:
            gpu_name = torch_module.xpu.get_device_name(0)
        except Exception:
            gpu_name = "Intel GPU"
        return f"Intel XPU - {gpu_name}"

    if device == "mps":
        return "Apple Metal Performance Shaders"

    return "CPU"


def _probe_device(torch_module: Any, device: str) -> None:
    """Run a tiny operation, not just an allocation, on the selected device."""
    sample = torch_module.tensor([1.0], device=device)
    result = sample * 2.0 + 1.0

    if device == "cuda":
        torch_module.cuda.synchronize()
    elif device == "xpu":
        synchronize = getattr(torch_module.xpu, "synchronize", None)
        if callable(synchronize):
            synchronize()

    if float(result.item()) != 3.0:
        raise RuntimeError(f"Basic tensor operation failed on {device}.")


def _install_rocm_windows_audio_loader(torch_module: Any) -> None:
    """Avoid TorchCodec for XTTS reference-audio loading on Windows ROCm.

    PyTorch 2.9's torchaudio.load delegates decoding to TorchCodec. The
    Windows ROCm distribution does not currently provide the same TorchCodec
    support as the standard CPU/CUDA distributions. XTTS only needs a decoded
    waveform here, so use SoundFile to read the already-normalized WAV input.
    """
    if os.name != "nt" or not _is_rocm(torch_module):
        return

    try:
        import numpy as np
        import soundfile as sf
        import torchaudio
    except Exception as exc:
        logger.exception("Could not prepare the Windows ROCm audio loader.")
        raise ModelLoadError(
            "AMD GPU mode on Windows requires the soundfile and torchaudio "
            "packages. Reinstall the project's audio dependencies."
        ) from exc

    def _soundfile_load(
        uri: Any,
        frame_offset: int = 0,
        num_frames: int = -1,
        normalize: bool = True,
        channels_first: bool = True,
        format: str | None = None,
        backend: str | None = None,
        **kwargs: Any,
    ) -> tuple[Any, int]:
        # Coqui's XTTS reference loader calls torchaudio.load(path) with its
        # defaults. SoundFile returns float32 samples in [-1, 1], matching
        # torchaudio's default normalize=True behavior for PCM input.
        try:
            waveform, sample_rate = sf.read(
                uri,
                dtype="float32",
                always_2d=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not decode reference audio with SoundFile: {uri}"
            ) from exc

        start = max(0, int(frame_offset or 0))
        stop = None
        if num_frames is not None and int(num_frames) >= 0:
            stop = start + int(num_frames)
        waveform = waveform[start:stop]

        if channels_first:
            waveform = waveform.T

        waveform = np.ascontiguousarray(waveform, dtype=np.float32)
        return torch_module.from_numpy(waveform), int(sample_rate)

    torchaudio.load = _soundfile_load
    logger.info(
        "Windows AMD ROCm detected; using SoundFile for torchaudio.load "
        "to avoid the TorchCodec dependency."
    )


def _clear_device_cache(torch_module: Any | None, device: str) -> None:
    """Release cached accelerator memory after a failed initialization/inference."""
    if torch_module is None:
        return

    backend_name = {"cuda": "cuda", "xpu": "xpu", "mps": "mps"}.get(device)
    if not backend_name:
        return

    try:
        backend = getattr(torch_module, backend_name, None)
        empty_cache = getattr(backend, "empty_cache", None)
        if callable(empty_cache):
            empty_cache()
    except Exception:
        logger.debug("Could not clear %s memory cache.", device, exc_info=True)


class XTTSService:
    """Own an XTTS model and expose validated, serialized synthesis operations."""

    def __init__(
        self,
        model: Any,
        device: str = "cpu",
        *,
        torch_module: Any | None = None,
        model_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._model = model
        self.device = device
        self._torch = torch_module
        self._model_factory = model_factory
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
        if self._closed or self._model is None:
            raise TTSEngineError(
                "The speech engine is unavailable. Restart the application to use it again."
            )

    @staticmethod
    def _validate_text(text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise TTSEngineError("Type some text first.")
        return text.strip()

    def _language_code(self, language: str) -> str:
        if language not in LANGUAGES:
            raise LanguageSelectionError(
                "Please select a supported language from the list."
            )

        code = LANGUAGES[language]
        if code not in self.available_languages:
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
            raise TTSEngineError(
                "The reference audio file could not be found. Please upload or record it again."
            )

        try:
            if os.path.getsize(path) <= 0:
                raise TTSEngineError(
                    "The reference audio file is empty. Please upload or record it again."
                )
        except OSError as exc:
            raise TTSEngineError(
                "The reference audio file could not be accessed."
            ) from exc

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
                logger.warning(
                    "Could not remove temporary audio file: %s", path, exc_info=True
                )

    @staticmethod
    def _check_output(path: str) -> None:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise RuntimeError(
                "XTTS returned without writing a non-empty output file."
            )

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

    def _switch_to_cpu_locked(self, cause: Exception) -> bool:
        """Move/reload the model on CPU after an accelerator inference failure."""
        if self.device == "cpu":
            return False

        failed_device = self.device
        logger.warning(
            "XTTS inference failed on %s; attempting CPU fallback.",
            failed_device,
            exc_info=(type(cause), cause, cause.__traceback__),
        )

        # First try moving the already-loaded model. This avoids downloading or
        # loading the model a second time when the move is supported.
        try:
            moved_model = self._model.to("cpu")
            if moved_model is not None:
                self._model = moved_model
            validate_model(self._model)
        except Exception:
            logger.exception("Could not move the existing XTTS model to CPU.")

            # If the accelerator model cannot be moved safely, load a fresh
            # CPU copy. The factory is supplied by load_tts().
            if self._model_factory is None:
                return False

            try:
                self._model = None
                gc.collect()
                _clear_device_cache(self._torch, failed_device)

                cpu_model = self._model_factory()
                moved_model = cpu_model.to("cpu")
                self._model = moved_model if moved_model is not None else cpu_model
                validate_model(self._model)
            except Exception:
                logger.exception("Could not reload XTTS on CPU after GPU failure.")
                self._model = None
                return False

        self.device = "cpu"
        _clear_device_cache(self._torch, failed_device)
        gc.collect()
        logger.warning(
            "XTTS switched to CPU after an accelerator inference failure. "
            "Subsequent generations will remain on CPU until the app restarts."
        )
        return True

    def _run_with_fallback_locked(
        self,
        operation: Callable[[], None],
        output_paths: Sequence[str],
    ) -> None:
        """Run inference; retry once on CPU if an accelerator call fails."""
        try:
            operation()
            return
        except Exception as first_error:
            self._remove_files(*output_paths)

            if not self._switch_to_cpu_locked(first_error):
                raise self._user_generation_error(first_error) from first_error

            try:
                operation()
            except Exception as retry_error:
                self._remove_files(*output_paths)
                raise self._user_generation_error(retry_error) from retry_error

    def _user_generation_error(self, exc: Exception) -> GenerationError:
        message = str(exc).lower()
        if "out of memory" in message:
            user_message = (
                f"XTTS ran out of memory on {self.device}. Try shorter text, "
                "close other GPU-heavy applications, or restart the app."
            )
        else:
            user_message = (
                f"XTTS could not generate the audio on {self.device}. Check the "
                "reference audio and selected language, then try again. See the "
                "terminal/console output for diagnostic details."
            )
        logger.exception(
            "XTTS generation failed on device %s.", self.device, exc_info=exc
        )
        return GenerationError(user_message)

    def generate_baseline(self, text: str, language: str) -> str:
        """Generate audio with the configured predefined XTTS speaker."""
        text = self._validate_text(text)
        language_code = self._language_code(language)
        output_path = self._new_output_path("baseline")

        with self._lock:
            self._ensure_open()
            self._run_with_fallback_locked(
                lambda: self._synthesize_locked(
                    text=text,
                    language_code=language_code,
                    output_path=output_path,
                ),
                [output_path],
            )

        return output_path

    def generate_clone(
        self,
        text: str,
        reference_audio: str | os.PathLike[str],
        language: str,
    ) -> str:
        """Generate audio conditioned on a reference voice sample."""
        text = self._validate_text(text)
        language_code = self._language_code(language)
        reference_path = self._validate_reference(reference_audio)
        output_path = self._new_output_path("clone")

        with self._lock:
            self._ensure_open()
            self._run_with_fallback_locked(
                lambda: self._synthesize_locked(
                    text=text,
                    language_code=language_code,
                    output_path=output_path,
                    reference_audio=reference_path,
                ),
                [output_path],
            )

        return output_path

    def generate_voices(
        self,
        text: str,
        reference_audio: str | os.PathLike[str],
        language: str,
    ) -> tuple[str, str]:
        """Generate baseline and cloned audio as one serialized operation."""
        text = self._validate_text(text)
        language_code = self._language_code(language)
        reference_path = self._validate_reference(reference_audio)
        baseline_path = self._new_output_path("baseline")
        clone_path = self._new_output_path("clone")

        def generate_pair() -> None:
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

        with self._lock:
            self._ensure_open()
            self._run_with_fallback_locked(
                generate_pair,
                [baseline_path, clone_path],
            )

        return baseline_path, clone_path

    def close(self) -> None:
        """Remove generated temporary audio; safe to call more than once."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._model = None
            shutil.rmtree(self._output_dir, ignore_errors=True)


def load_tts(device: str | None = None) -> XTTSService:
    """Load XTTS on the best available device, with CPU fallback.

    Set VOICE_CLONER_DEVICE=auto|cpu|cuda|rocm|xpu|mps to override selection.
    AMD ROCm uses PyTorch's ``cuda`` device interface, so the selected device
    name is ``cuda`` while the diagnostic description identifies ROCm.
    """
    requested = device or os.environ.get("VOICE_CLONER_DEVICE", "auto")

    try:
        import torch
    except Exception as exc:
        logger.exception("PyTorch import failed")
        raise ModelLoadError(
            "PyTorch could not be imported. Reinstall the application's dependencies and restart it."
        ) from exc

    # Install before importing Coqui so XTTS's reference-audio loader uses the
    # SoundFile path on Windows ROCm instead of torchaudio's TorchCodec path.
    _install_rocm_windows_audio_loader(torch)

    attempts = _resolve_device(torch, requested)

    try:
        from TTS.api import TTS
    except Exception as exc:
        logger.exception("Coqui TTS import failed")
        raise ModelLoadError(
            "Coqui TTS could not be imported. Check the installed coqui-tts and transformers versions."
        ) from exc

    model = None
    actual_device = None
    last_error: Exception | None = None

    for candidate in attempts:
        candidate_model = None
        description = _device_description(torch, candidate)

        logger.info("Attempting to load %s on %s.", MODEL_NAME, description)
        print(f"Loading {MODEL_NAME} on {candidate} ({description})...")

        try:
            _probe_device(torch, candidate)
            candidate_model = TTS(MODEL_NAME)
            moved_model = candidate_model.to(candidate)
            model = moved_model if moved_model is not None else candidate_model
            actual_device = candidate
            break
        except Exception as exc:
            last_error = exc
            logger.exception("XTTS initialization failed on %s.", candidate)
            candidate_model = None
            model = None
            gc.collect()
            _clear_device_cache(torch, candidate)

            if candidate != attempts[-1]:
                next_device = attempts[attempts.index(candidate) + 1]
                logger.warning(
                    "Could not initialize XTTS on %s. Trying %s instead.",
                    candidate,
                    next_device,
                )
                print(
                    f"WARNING: {candidate} initialization failed. "
                    f"Trying {next_device}..."
                )

    if model is None or actual_device is None:
        logger.error("XTTS could not be loaded.")
        raise ModelLoadError(
            "XTTS could not be initialized on any available device. Check the "
            "installed dependencies, drivers, available memory, and model cache. "
            "Review the terminal output for diagnostic details."
        ) from last_error

    try:
        service = XTTSService(
            model=model,
            device=actual_device,
            torch_module=torch,
            model_factory=lambda: TTS(MODEL_NAME),
        )
    except ModelLoadError:
        logger.exception("XTTS model failed startup validation")
        raise
    except Exception as exc:
        logger.exception("XTTS service initialization failed")
        raise ModelLoadError(
            "XTTS loaded, but the backend service could not initialize."
        ) from exc

    device_info = _device_description(torch, actual_device)
    if actual_device == "cpu":
        logger.warning(
            "XTTS is running on CPU. Generation will be slower than on a supported GPU."
        )
        print("WARNING: No supported GPU backend was initialized. XTTS is running on CPU.")

    print(f"XTTS model loaded on {actual_device}.")
    print(f"Execution backend: {device_info}")
    print(f"Verified baseline speaker: {DEFAULT_SPEAKER}")
    print(f"Verified configured languages: {len(LANGUAGES)}")

    logger.info(
        "XTTS model loaded on %s (%s); verified %d configured languages.",
        actual_device,
        device_info,
        len(LANGUAGES),
    )

    return service
