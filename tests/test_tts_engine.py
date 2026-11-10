"""Unit tests for the XTTS service; no Coqui model download is required.

Run from the repo root with `pytest`, or this file on its own with
`pytest tests/test_tts_engine.py`.
"""
import os
import sys
from pathlib import Path

import pytest

# Make the repo root (config.py) and modules/ importable no matter which
# test file pytest collects first.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "modules"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import DEFAULT_SPEAKER, LANGUAGES
from tts_engine import (
    GenerationError,
    LanguageSelectionError,
    ModelLoadError,
    XTTSService,
    validate_model,
    _device_description,
    _install_rocm_windows_audio_loader,
    _probe_device,
    _resolve_device,
)


class FakeModel:
    speakers = [DEFAULT_SPEAKER]
    languages = list(LANGUAGES.values())

    def __init__(self, fail_clone=False):
        self.calls = []
        self.fail_clone = fail_clone
        self.to_calls = []

    def to(self, device):
        self.to_calls.append(device)
        return self

    def tts_to_file(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_clone and "speaker_wav" in kwargs:
            raise RuntimeError("simulated clone failure")
        Path(kwargs["file_path"]).write_bytes(b"fake wav output")


# ---------------------------------------------------------------------------
# Model metadata validation
# ---------------------------------------------------------------------------

def test_validate_model_accepts_all_configured_languages():
    languages, speakers = validate_model(FakeModel())
    assert set(LANGUAGES.values()).issubset(languages)
    assert DEFAULT_SPEAKER in speakers
    assert len(LANGUAGES) == 17


def test_validate_model_rejects_missing_language():
    model = FakeModel()
    model.languages = [code for code in model.languages if code != LANGUAGES["Hindi"]]
    with pytest.raises(ModelLoadError, match="hi"):
        validate_model(model)


def test_validate_model_rejects_missing_baseline_speaker():
    model = FakeModel()
    model.speakers = []
    with pytest.raises(ModelLoadError, match="baseline speaker"):
        validate_model(model)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def test_generate_pair_writes_baseline_and_clone(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference audio")
    model = FakeModel()
    service = XTTSService(model=model, device="cpu")
    try:
        baseline, clone = service.generate_voices("  Hello there.  ", str(reference), "English")
        assert Path(baseline).is_file()
        assert Path(clone).is_file()
        assert model.calls[0]["text"] == "Hello there."
        assert model.calls[1]["text"] == "Hello there."
        assert model.calls[0]["language"] == "en"
        assert model.calls[1]["language"] == "en"
        assert model.calls[0]["speaker"] == DEFAULT_SPEAKER
        assert model.calls[1]["speaker_wav"] == str(reference)
    finally:
        service.close()
    assert not Path(baseline).exists()
    assert not Path(clone).exists()


def test_unknown_language_is_rejected_before_model_call(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference audio")
    model = FakeModel()
    service = XTTSService(model=model, device="cpu")
    try:
        with pytest.raises(LanguageSelectionError, match="supported language"):
            service.generate_voices("Hello", str(reference), "Klingon")
        assert model.calls == []
    finally:
        service.close()


def test_partial_outputs_are_removed_when_clone_fails(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference audio")
    model = FakeModel(fail_clone=True)
    service = XTTSService(model=model, device="cpu")
    try:
        with pytest.raises(GenerationError, match="could not generate"):
            service.generate_voices("Hello", str(reference), "English")
        assert list(service.output_dir.glob("*.wav")) == []
    finally:
        service.close()


def test_empty_text_is_rejected_before_model_call():
    model = FakeModel()
    service = XTTSService(model=model, device="cpu")
    try:
        with pytest.raises(Exception, match="Type some text"):
            service.generate_baseline("  ", "English")
        assert model.calls == []
    finally:
        service.close()


def test_empty_text_is_rejected_for_clone_before_model_call(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference audio")
    model = FakeModel()
    service = XTTSService(model=model, device="cpu")
    try:
        with pytest.raises(Exception, match="Type some text"):
            service.generate_clone("  ", str(reference), "English")
        assert model.calls == []
    finally:
        service.close()


def test_missing_reference_is_rejected_before_model_call():
    model = FakeModel()
    service = XTTSService(model=model, device="cpu")
    try:
        with pytest.raises(Exception, match="voice sample"):
            service.generate_clone("Hello", "", "English")
        assert model.calls == []
    finally:
        service.close()


# ---------------------------------------------------------------------------
# Device detection fakes
# ---------------------------------------------------------------------------

class FakeCuda:
    def __init__(self, available, name="NVIDIA GeForce RTX 3060"):
        self._available = available
        self._name = name
        self.synced = False
        self.cache_cleared = False

    def is_available(self):
        return self._available

    def get_device_name(self, index):
        return self._name

    def synchronize(self):
        self.synced = True

    def empty_cache(self):
        self.cache_cleared = True


class FakeXPU:
    def __init__(self, available, name="Intel Arc A750"):
        self._available = available
        self._name = name

    def is_available(self):
        return self._available

    def get_device_name(self, index):
        return self._name


class FakeMPS:
    def __init__(self, available):
        self._available = available

    def is_available(self):
        return self._available


class FakeTorch:
    """Minimal stand-in for the torch module's device-detection surface."""

    def __init__(self, cuda=False, mps=False, xpu=False,
                 gpu_name="NVIDIA GeForce RTX 3060", hip=None):
        self.cuda = FakeCuda(cuda, gpu_name)
        self.xpu = FakeXPU(xpu)
        self.backends = type("Backends", (), {"mps": FakeMPS(mps)})()
        self.version = type("Version", (), {"hip": hip})()


# ---------------------------------------------------------------------------
# Device resolution (returns a fallback list; CPU is always the last resort)
# ---------------------------------------------------------------------------

def test_auto_device_prefers_cuda_then_falls_back_to_cpu():
    assert _resolve_device(FakeTorch(cuda=True), "auto") == ["cuda", "cpu"]


def test_auto_device_orders_cuda_xpu_mps_then_cpu():
    assert _resolve_device(FakeTorch(cuda=True, xpu=True, mps=True), "auto") == [
        "cuda", "xpu", "mps", "cpu",
    ]


def test_auto_device_uses_mps_before_cpu_when_no_cuda_or_xpu():
    assert _resolve_device(FakeTorch(mps=True), "auto") == ["mps", "cpu"]


def test_auto_device_is_cpu_only_without_accelerators():
    assert _resolve_device(FakeTorch(), "auto") == ["cpu"]


def test_blank_device_setting_is_treated_as_auto():
    assert _resolve_device(FakeTorch(), None) == ["cpu"]
    assert _resolve_device(FakeTorch(), "") == ["cpu"]
    assert _resolve_device(FakeTorch(cuda=True), "  AUTO  ") == ["cuda", "cpu"]


def test_invalid_device_setting_is_rejected():
    with pytest.raises(ModelLoadError, match="Invalid VOICE_CLONER_DEVICE"):
        _resolve_device(FakeTorch(), "tpu")


def test_explicit_cpu_returns_only_cpu():
    assert _resolve_device(FakeTorch(cuda=True, mps=True), "cpu") == ["cpu"]


def test_explicit_cuda_is_rejected_when_unavailable():
    with pytest.raises(ModelLoadError, match="CUDA/ROCm was requested"):
        _resolve_device(FakeTorch(), "cuda")


def test_rocm_maps_to_the_cuda_device_when_amd_gpu_present():
    torch = FakeTorch(cuda=True, gpu_name="AMD Radeon RX 7900 XTX")
    assert _resolve_device(torch, "rocm") == ["cuda"]


def test_rocm_detected_through_hip_version_without_device_name():
    torch = FakeTorch(cuda=True, gpu_name="Graphics Device", hip="6.1")
    assert _resolve_device(torch, "rocm") == ["cuda"]


def test_rocm_is_rejected_when_the_gpu_is_not_amd():
    torch = FakeTorch(cuda=True, gpu_name="NVIDIA GeForce RTX 3060")
    with pytest.raises(ModelLoadError, match="ROCm was requested"):
        _resolve_device(torch, "rocm")


def test_explicit_xpu_is_returned_when_available():
    assert _resolve_device(FakeTorch(xpu=True), "xpu") == ["xpu"]


def test_explicit_xpu_is_rejected_when_unavailable():
    with pytest.raises(ModelLoadError, match="Intel XPU was requested"):
        _resolve_device(FakeTorch(), "xpu")


def test_mps_can_be_selected_explicitly_when_available():
    assert _resolve_device(FakeTorch(mps=True), "mps") == ["mps"]


def test_explicit_mps_is_rejected_when_unavailable():
    with pytest.raises(ModelLoadError, match="Apple MPS was requested"):
        _resolve_device(FakeTorch(), "mps")


# ---------------------------------------------------------------------------
# Device descriptions shown while loading
# ---------------------------------------------------------------------------

def test_device_description_for_cpu():
    assert _device_description(FakeTorch(), "cpu") == "CPU"


def test_device_description_for_mps():
    assert _device_description(FakeTorch(mps=True), "mps") == (
        "Apple Metal Performance Shaders"
    )


def test_device_description_distinguishes_nvidia_from_amd_rocm():
    nvidia = FakeTorch(cuda=True, gpu_name="NVIDIA GeForce RTX 3060")
    assert _device_description(nvidia, "cuda") == "NVIDIA CUDA - NVIDIA GeForce RTX 3060"

    amd = FakeTorch(cuda=True, gpu_name="AMD Radeon RX 7900 XTX")
    assert _device_description(amd, "cuda") == "AMD ROCm - AMD Radeon RX 7900 XTX"


def test_device_description_for_xpu():
    torch = FakeTorch(xpu=True)
    assert _device_description(torch, "xpu") == "Intel XPU - Intel Arc A750"


# ---------------------------------------------------------------------------
# Startup probe: a tiny tensor operation, not just an allocation
# ---------------------------------------------------------------------------

class FakeScalar:
    def __init__(self, value):
        self._value = value

    def __mul__(self, other):
        return FakeScalar(self._value * other)

    def __add__(self, other):
        return FakeScalar(self._value + other)

    def item(self):
        return self._value


class ProbeTorch(FakeTorch):
    """Fake torch that can run (or botch) the probe's tiny tensor operation."""

    def __init__(self, start_value=1.0, **kwargs):
        super().__init__(**kwargs)
        self._start_value = start_value
        self.tensor_calls = []

    def tensor(self, values, device=None):
        self.tensor_calls.append((list(values), device))
        return FakeScalar(self._start_value)


def test_probe_device_runs_an_operation_on_the_requested_device():
    torch = ProbeTorch(cuda=True)
    _probe_device(torch, "cuda")
    assert torch.tensor_calls == [([1.0], "cuda")]
    assert torch.cuda.synced


def test_probe_device_raises_when_the_operation_returns_wrong_result():
    torch = ProbeTorch(start_value=0.0, cuda=True)
    with pytest.raises(RuntimeError, match="Basic tensor operation failed"):
        _probe_device(torch, "cuda")


# ---------------------------------------------------------------------------
# Windows ROCm audio loader: no-op on other platforms
# ---------------------------------------------------------------------------

def test_rocm_windows_audio_loader_is_a_noop_off_windows():
    if __import__("os").name == "nt":
        pytest.skip("the no-op branch only exists off Windows")
    torch = FakeTorch(cuda=True, gpu_name="AMD Radeon RX 7900 XTX")
    _install_rocm_windows_audio_loader(torch)  # must not raise or patch anything


# ---------------------------------------------------------------------------
# GPU-to-CPU fallback after an accelerator inference failure
# ---------------------------------------------------------------------------

class FlakyModel(FakeModel):
    """Fails a fixed number of times, then behaves like a healthy model."""

    def __init__(self, failures, **kwargs):
        super().__init__(**kwargs)
        self.failures = failures

    def tts_to_file(self, **kwargs):
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("simulated accelerator failure")
        super().tts_to_file(**kwargs)


class UnmovableModel(FakeModel):
    """Cannot be moved between devices (`.to` raises)."""

    def to(self, device):
        raise RuntimeError("model cannot move devices")


def test_accelerator_failure_retries_on_cpu_and_succeeds(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference audio")
    torch = FakeTorch(cuda=True)
    model = FlakyModel(failures=1)
    service = XTTSService(model=model, device="cuda", torch_module=torch)
    try:
        baseline, clone = service.generate_voices("Hello", str(reference), "English")
        assert Path(baseline).is_file()
        assert Path(clone).is_file()
        assert service.device == "cpu"
        assert model.to_calls == ["cpu"]
        assert torch.cuda.cache_cleared
    finally:
        service.close()


def test_failed_accelerator_outputs_are_removed_before_cpu_retry(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference audio")
    model = FlakyModel(failures=1)
    service = XTTSService(model=model, device="cuda", torch_module=FakeTorch(cuda=True))
    try:
        service.generate_voices("Hello", str(reference), "English")
        outputs = list(service.output_dir.glob("*.wav"))
        assert len(outputs) == 2  # only the CPU retry's pair remains
    finally:
        service.close()


def test_unmovable_model_without_factory_raises_user_error(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference audio")
    model = UnmovableModel(fail_clone=True)
    service = XTTSService(model=model, device="cuda", torch_module=FakeTorch(cuda=True))
    try:
        with pytest.raises(GenerationError, match="could not generate the audio"):
            service.generate_voices("Hello", str(reference), "English")
        assert service.device == "cuda"
    finally:
        service.close()


def test_unmovable_model_is_reloaded_on_cpu_through_the_factory(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference audio")
    broken = UnmovableModel(fail_clone=True)
    fresh = FakeModel()
    service = XTTSService(
        model=broken,
        device="cuda",
        torch_module=FakeTorch(cuda=True),
        model_factory=lambda: fresh,
    )
    try:
        baseline, clone = service.generate_voices("Hello", str(reference), "English")
        assert Path(baseline).is_file()
        assert Path(clone).is_file()
        assert service.device == "cpu"
        assert fresh.to_calls == ["cpu"]
        assert fresh.calls  # the reloaded CPU model produced the audio
    finally:
        service.close()


def test_out_of_memory_failure_gets_a_specific_user_message(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference audio")

    class OomModel(FakeModel):
        def tts_to_file(self, **kwargs):
            raise RuntimeError("CUDA out of memory")

    service = XTTSService(model=OomModel(), device="cpu")
    try:
        with pytest.raises(GenerationError, match="ran out of memory"):
            service.generate_voices("Hello", str(reference), "English")
        assert list(service.output_dir.glob("*.wav")) == []
    finally:
        service.close()
