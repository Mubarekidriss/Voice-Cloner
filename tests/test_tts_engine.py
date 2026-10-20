"""Unit tests for the XTTS service; no Coqui model download is required."""
from pathlib import Path

import pytest

from config import DEFAULT_SPEAKER, LANGUAGES
from tts_engine import (
    GenerationError,
    LanguageSelectionError,
    ModelLoadError,
    XTTSService,
    validate_model,
    _resolve_device,
)


class FakeModel:
    speakers = [DEFAULT_SPEAKER]
    languages = list(LANGUAGES.values())

    def __init__(self, fail_clone=False):
        self.calls = []
        self.fail_clone = fail_clone

    def tts_to_file(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_clone and "speaker_wav" in kwargs:
            raise RuntimeError("simulated clone failure")
        Path(kwargs["file_path"]).write_bytes(b"fake wav output")


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


class FakeCuda:
    def __init__(self, available):
        self._available = available

    def is_available(self):
        return self._available


class FakeMPS:
    def __init__(self, available):
        self._available = available

    def is_available(self):
        return self._available


class FakeTorch:
    def __init__(self, cuda=False, mps=False):
        self.cuda = FakeCuda(cuda)
        self.backends = type("Backends", (), {"mps": FakeMPS(mps)})()


def test_auto_device_prefers_cuda_when_available():
    assert _resolve_device(FakeTorch(cuda=True, mps=True), "auto") == "cuda"


def test_auto_device_uses_cpu_when_cuda_is_unavailable_even_if_mps_exists():
    assert _resolve_device(FakeTorch(cuda=False, mps=True), "auto") == "cpu"


def test_explicit_cuda_is_rejected_when_unavailable():
    with pytest.raises(ModelLoadError, match="CUDA was requested"):
        _resolve_device(FakeTorch(cuda=False), "cuda")


def test_mps_can_be_selected_explicitly_when_available():
    assert _resolve_device(FakeTorch(mps=True), "mps") == "mps"
