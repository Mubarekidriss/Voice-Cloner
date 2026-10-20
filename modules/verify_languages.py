"""Smoke-test real XTTS generation for every configured language.

Run from the project root:
    python verify_languages.py
    python verify_languages.py --reference path/to/voice_sample.wav

Without --reference, this tests the predefined baseline speaker in all 17
configured languages. Supplying --reference also smoke-tests voice cloning for
every language. Supported reference formats are validated and normalized to WAV
before XTTS receives them, matching the app's audio-input processing.
The script reports whether XTTS produced a non-empty WAV; it does not assess
pronunciation, naturalness, or translation quality.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from config import LANGUAGES
from tts_engine import TTSEngineError, load_tts

# Short, language-appropriate prompts exercise each language's character set
# and tokenizer rather than synthesizing the same English sentence 17 times.
TEST_TEXT = {
    "English": "This is a short speech synthesis test.",
    "Spanish": "Esta es una prueba breve de síntesis de voz.",
    "French": "Ceci est un court test de synthèse vocale.",
    "German": "Dies ist ein kurzer Test der Sprachsynthese.",
    "Italian": "Questo è un breve test di sintesi vocale.",
    "Portuguese": "Este é um breve teste de síntese de fala.",
    "Polish": "To jest krótki test syntezy mowy.",
    "Turkish": "Bu, kısa bir konuşma sentezi testidir.",
    "Russian": "Это короткий тест синтеза речи.",
    "Dutch": "Dit is een korte test van spraaksynthese.",
    "Czech": "Toto je krátký test syntézy řeči.",
    "Arabic": "هذا اختبار قصير لتوليد الكلام.",
    "Chinese (Mandarin)": "这是一段简短的语音合成测试。",
    "Hungarian": "Ez egy rövid beszédszintézis-teszt.",
    "Korean": "이것은 짧은 음성 합성 테스트입니다.",
    "Japanese": "これは短い音声合成テストです。",
    "Hindi": "यह वाक् संश्लेषण का एक छोटा परीक्षण है。",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        help="Optional voice-reference audio path; also test cloned synthesis.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default=None,
        help="Override VOICE_CLONER_DEVICE for this run.",
    )
    args = parser.parse_args()

    reference_path = None
    normalized_reference_path = None
    if args.reference:
        original_reference_path = os.path.abspath(args.reference)
        if not os.path.isfile(original_reference_path) or os.path.getsize(original_reference_path) == 0:
            print(
                f"ERROR: reference file does not exist or is empty: {original_reference_path}",
                file=sys.stderr,
            )
            return 2
        try:
            # Initialize FFmpeg before importing pydub-backed audio helpers.
            import static_ffmpeg
            static_ffmpeg.add_paths()
            from audio_validation import validate_audio
            from audio_utils import normalize_audio

            validate_audio(original_reference_path)
            # Do not pass MP3/M4A/other original uploads straight to XTTS:
            # its torchaudio/SoundFile path may not decode those formats.
            # Convert once to mono 22050 Hz PCM WAV and reuse it in every test.
            normalized_reference_path = normalize_audio(original_reference_path)
            validate_audio(normalized_reference_path)
            reference_path = normalized_reference_path
        except Exception as exc:
            if normalized_reference_path:
                try:
                    Path(normalized_reference_path).unlink(missing_ok=True)
                except OSError:
                    pass
            print(f"ERROR: reference audio could not be prepared for XTTS: {exc}", file=sys.stderr)
            return 2

    service = None
    failures: list[str] = []
    try:
        service = load_tts(device=args.device)
        print("\nRunning XTTS language smoke tests...")
        for language in LANGUAGES:
            print(f"[{language}] ", end="", flush=True)
            outputs: list[str] = []
            try:
                outputs.append(service.generate_baseline(TEST_TEXT[language], language))
                if reference_path:
                    outputs.append(service.generate_clone(TEST_TEXT[language], reference_path, language))
                for output in outputs:
                    if not os.path.isfile(output) or os.path.getsize(output) <= 0:
                        raise RuntimeError("generation did not produce a non-empty WAV")
                print("PASS" + (" (baseline + clone)" if reference_path else " (baseline)"))
            except Exception as exc:
                failures.append(language)
                print(f"FAIL — {exc}")
            finally:
                for output in outputs:
                    try:
                        Path(output).unlink(missing_ok=True)
                    except OSError:
                        pass
    except TTSEngineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if service is not None:
            service.close()
        if normalized_reference_path:
            try:
                Path(normalized_reference_path).unlink(missing_ok=True)
            except OSError:
                pass

    print(f"\nResult: {len(LANGUAGES) - len(failures)}/{len(LANGUAGES)} languages passed.")
    if failures:
        print("Failed languages: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
