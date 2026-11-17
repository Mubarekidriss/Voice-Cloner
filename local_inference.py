"""Run the existing XTTS engine locally, without Django or a web server."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import shutil
import sys
import tempfile
import wave

from config import LANGUAGES


class LocalInferenceError(RuntimeError):
    """A failure that can be reported without a Python traceback."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True,
                        help="6-30 second voice sample, at most 25 MB")
    parser.add_argument("--text", required=True, help="Text to synthesize")
    parser.add_argument("--language", choices=sorted(LANGUAGES), default="English")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda", "rocm", "xpu", "mps"),
                        default="auto")
    parser.add_argument("--output-dir", type=Path, default=Path("local_outputs"),
                        help="Parent directory for a new, unique result folder")
    parser.add_argument("--consent", action="store_true", required=True,
                        help="Confirm you have permission to clone the reference voice")
    return parser


def _check_wav(path: Path) -> None:
    """Reject missing, empty or invalid PCM output before reporting success."""
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getnframes() <= 0 or not audio.readframes(1):
                raise ValueError("no audio frames")
    except (OSError, EOFError, wave.Error, ValueError) as exc:
        raise LocalInferenceError("The engine did not produce a readable, non-empty WAV.") from exc


def run(args: argparse.Namespace) -> Path:
    """Generate and preserve both WAVs; always remove temporary reference audio."""
    if not args.text.strip():
        raise LocalInferenceError("Provide non-empty --text.")
    reference = args.reference.expanduser().resolve()
    if not reference.is_file() or reference.stat().st_size == 0:
        raise LocalInferenceError("The reference must be an existing, non-empty audio file.")
    output_parent = args.output_dir.expanduser().resolve()
    if output_parent.exists() and not output_parent.is_dir():
        raise LocalInferenceError("--output-dir must be a directory, not a file.")

    # Lazy imports keep --help and argument validation independent of ML packages.
    from modules.audio_validation import validate_audio
    from modules.audio_utils import normalize_audio
    from modules.tts_engine import load_tts

    validate_audio(str(reference))
    # WAV input needs no FFmpeg download. Other formats use the project's bundle.
    try:
        with wave.open(str(reference), "rb") as audio:
            audio.getparams()
    except (wave.Error, EOFError):
        import static_ffmpeg
        static_ffmpeg.add_paths()

    normalized = None
    service = None
    result_dir = None
    complete = False
    try:
        normalized = Path(normalize_audio(str(reference)))
        print("Loading the local model. First use may download model files; CPU inference can be slow.",
              flush=True)
        # Do not silently accept model-license terms or set COQUI_TOS_AGREED.
        service = load_tts(device=args.device)
        print(f"Generating on {service.device}...", flush=True)
        baseline, clone = service.generate_voices(args.text.strip(), str(normalized), args.language)
        _check_wav(Path(baseline))
        _check_wav(Path(clone))
        output_parent.mkdir(parents=True, exist_ok=True)
        result_dir = Path(tempfile.mkdtemp(prefix="run_", dir=output_parent))
        for source, name in ((baseline, "baseline.wav"), (clone, "clone.wav")):
            shutil.copyfile(source, result_dir / name)
        complete = True
        return result_dir
    finally:
        if service is not None:
            service.close()
        if normalized is not None:
            normalized.unlink(missing_ok=True)
        if result_dir is not None and not complete:
            shutil.rmtree(result_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result_dir = run(args)
    except KeyboardInterrupt:
        print("Cancelled. No complete result was saved.", file=sys.stderr)
        return 130
    except ImportError as exc:
        print(f"Missing dependency: {exc}. Activate the project's installed Python environment.",
              file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Local inference failed: {exc}", file=sys.stderr)
        return 1
    print(f"Baseline: {result_dir / 'baseline.wav'}")
    print(f"Clone: {result_dir / 'clone.wav'}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
