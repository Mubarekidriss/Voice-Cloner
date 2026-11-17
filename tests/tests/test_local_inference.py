"""Local helper tests use fake inference, never download the XTTS model."""
import array
from pathlib import Path
import sys
import wave

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_inference as cli
from modules import tts_engine


def write_wav(path, seconds=7, level=2000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(array.array("h", [level, -level] * (22050 * seconds // 2)).tobytes())


@pytest.fixture
def setup_run(tmp_path, monkeypatch):
    reference = tmp_path / "reference.wav"
    write_wav(reference)
    services = []

    class FakeService:
        device = "cpu"

        def __init__(self):
            self.temp = tmp_path / f"engine_{len(services)}"
            self.temp.mkdir()
            self.closed = False
            self.calls = []
            services.append(self)

        def generate_voices(self, text, reference_audio, language):
            self.calls.append((text, reference_audio, language))
            assert Path(reference_audio).exists()
            paths = [self.temp / "baseline.wav", self.temp / "clone.wav"]
            for path in paths:
                write_wav(path, seconds=1)
            return tuple(map(str, paths))

        def close(self):
            import shutil
            self.closed = True
            shutil.rmtree(self.temp)

    devices = []

    def load(device):
        devices.append(device)
        return FakeService()

    monkeypatch.setattr(tts_engine, "load_tts", load)
    argv = ["--reference", str(reference), "--text", "  Hello.  ", "--consent",
            "--device", "cpu", "--output-dir", str(tmp_path / "results")]
    return argv, services, devices, reference


def test_help_needs_no_ml_dependencies(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])
    assert error.value.code == 0
    assert "--reference" in capsys.readouterr().out


def test_success_keeps_results_after_engine_cleanup(setup_run, capsys):
    argv, services, devices, reference = setup_run
    assert cli.main(argv) == 0
    service = services[0]
    assert devices == ["cpu"]
    text, normalized, language = service.calls[0]
    assert (text, language) == ("Hello.", "English")
    assert not Path(normalized).exists()
    assert reference.exists()
    assert service.closed
    outputs = list((reference.parent / "results").glob("run_*/*.wav"))
    assert len(outputs) == 2
    for path in outputs:
        cli._check_wav(path)
    assert "Clone:" in capsys.readouterr().out


def test_repeated_runs_do_not_overwrite(setup_run):
    argv, services, _, reference = setup_run
    assert cli.main(argv) == cli.main(argv) == 0
    assert len(list((reference.parent / "results").glob("run_*"))) == 2


@pytest.mark.parametrize("replacement", ["", "   "])
def test_empty_text_never_loads_model(setup_run, replacement):
    argv, services, _, _ = setup_run
    argv[3] = replacement
    assert cli.main(argv) == 1
    assert not services


def test_missing_reference_never_loads_model(setup_run):
    argv, services, _, reference = setup_run
    reference.unlink()
    assert cli.main(argv) == 1
    assert not services


@pytest.mark.parametrize("seconds,level", [(1, 2000), (31, 2000), (7, 0)])
def test_invalid_audio_never_loads_model(setup_run, seconds, level):
    argv, services, _, reference = setup_run
    write_wav(reference, seconds=seconds, level=level)
    assert cli.main(argv) == 1
    assert not services


def test_consent_is_required(setup_run):
    argv, services, _, _ = setup_run
    argv.remove("--consent")
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2
    assert not services


def test_invalid_language_rejected(setup_run):
    argv, services, _, _ = setup_run
    with pytest.raises(SystemExit) as error:
        cli.main(argv + ["--language", "Klingon"])
    assert error.value.code == 2
    assert not services


def test_generation_failure_cleans_up(setup_run, monkeypatch):
    argv, services, _, reference = setup_run
    original_load = tts_engine.load_tts

    def load(device):
        service = original_load(device)

        def fail(*args):
            service.calls.append(args)
            raise RuntimeError("simulated inference failure")

        service.generate_voices = fail
        return service

    monkeypatch.setattr(tts_engine, "load_tts", load)
    assert cli.main(argv) == 1
    assert services[0].closed
    assert not Path(services[0].calls[0][1]).exists()
    assert not list(reference.parent.glob("results/run_*"))


def test_model_load_failure_cleans_reference(setup_run, monkeypatch):
    argv, _, _, _ = setup_run
    from modules import audio_utils
    normalized_paths = []
    original_normalize = audio_utils.normalize_audio

    def normalize(path):
        result = original_normalize(path)
        normalized_paths.append(Path(result))
        return result

    def fail(device):
        raise RuntimeError("simulated model load failure")

    monkeypatch.setattr(audio_utils, "normalize_audio", normalize)
    monkeypatch.setattr(tts_engine, "load_tts", fail)
    assert cli.main(argv) == 1
    assert normalized_paths and not normalized_paths[0].exists()


def test_invalid_generated_wav_is_not_success(setup_run, monkeypatch):
    argv, services, _, reference = setup_run
    original_check = cli._check_wav

    def corrupt(path):
        path.write_bytes(b"not a wav")
        original_check(path)

    monkeypatch.setattr(cli, "_check_wav", corrupt)
    assert cli.main(argv) == 1
    assert services[0].closed
    assert not list(reference.parent.glob("results/run_*"))


def test_output_file_rejected_before_load(setup_run):
    argv, services, _, reference = setup_run
    argv[-1] = str(reference)
    assert cli.main(argv) == 1
    assert not services


def test_copy_failure_removes_partial_result(setup_run, monkeypatch):
    argv, services, _, reference = setup_run
    original_copy = cli.shutil.copyfile
    calls = []

    def fail_second(source, destination):
        calls.append(destination)
        if len(calls) == 2:
            raise OSError("simulated disk full")
        return original_copy(source, destination)

    monkeypatch.setattr(cli.shutil, "copyfile", fail_second)
    assert cli.main(argv) == 1
    assert services[0].closed
    assert not list(reference.parent.glob("results/run_*"))
