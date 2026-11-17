# Local inference helper

Run voice generation on the computer executing this command, not on Render.
This is a standalone command-line entry point around the team's existing
`modules/tts_engine.py`, audio validation and normalization. It does not change
the website's Generate button, start a server, or connect a browser to a local
computer. Compatibility with future scripts has not been tested.

## Before running

- Use the project files from this branch and the Python environment created by
  the existing installer for your platform. If you already installed the project,
  use that environment rather than installing everything again.
- New installations need Python and the project's packages, including PyTorch
  and Coqui TTS. The existing Windows CPU installer expects 64-bit Python 3.11;
  macOS has separate Apple Silicon and Intel installers. Follow the main README
  for the installer command. The installers also run Django setup; the helper
  itself does not need a Django login, database or running web server.
- The first model load may download XTTS files and ask you to review its license.
  An existing model cache can avoid another model download. Review and accept
  terms yourself if eligible; the helper does not set `COQUI_TOS_AGREED` for you.
  The `--consent` flag is voice permission, not acceptance of the model license.
- Use your own voice or a voice you have permission to clone. Provide a clear
  6-30 second recording, under 25 MB. A PCM WAV is the simplest input. Other
  supported audio formats may require the project's bundled FFmpeg download.
- The computer needs enough memory for XTTS. CPU mode can be slow. No minimum
  RAM figure or inference speed has been verified for this helper.

## Run

From the repository root, with the project's Python environment activated:

```bash
python local_inference.py --reference "path/to/reference.wav" --text "This is a local voice generation test." --language English --device auto --consent
```

If the environment is not activated, replace `python` with its interpreter.
For the existing Windows CPU environment, PowerShell uses:

```powershell
.\.venv-cpu\Scripts\python.exe local_inference.py --reference "C:\path\reference.wav" --text "This is a local voice generation test." --device cpu --consent
```

For the existing Apple Silicon environment:

```bash
./.venv-macos-apple-silicon/bin/python local_inference.py --reference "/path/reference.wav" --text "This is a local voice generation test." --device auto --consent
```

Use `python local_inference.py --help` for supported languages and devices.
Device selection and accelerator-to-CPU fallback reuse the existing engine.
`--device cpu` explicitly chooses CPU. `--output-dir "my-results"` changes the
parent output directory. No arguments are sent to Render by this helper.

## Results and cleanup

A successful run prints the full paths to `baseline.wav` and `clone.wav` in a
new `local_outputs/run_.../` folder. Each run gets a separate folder, so it does
not overwrite previous results. Files remain after the engine shuts down.
Listen to both files before claiming the voice-cloning demo works.

The helper validates the sample before loading the model, normalizes it using
the existing audio module, then asks the existing engine to generate both
outputs. It checks that each output is a readable, non-empty WAV before
reporting success. This check does not judge pronunciation or voice similarity.

The original sample is not changed. Temporary normalized audio and temporary
engine outputs are cleaned up on success, failure or Ctrl+C. A partially copied
result folder is removed on failure. A forced process kill or power loss may
prevent cleanup. Saved results remain until you delete them; don't commit
private samples or generated voices. The default results folder is gitignored.

Exit codes: `0` means both WAVs were saved, `1` means a dependency or runtime
failure, `2` means invalid command arguments, and `130` means interrupted.

## Verification status - November 17, 2026

The local helper tests and the existing repository tests passed together:
78 tests. The helper tests use simulated inference, not the XTTS model. They
cover argument/consent checks, audio validation, options passed to the engine,
saved outputs surviving cleanup, separate result folders, and failure cleanup.
The help command also ran without ML packages installed.

Actual XTTS inference, model downloads, listening quality and operation on
Mikita's intended computer have **not** been verified. The test environment
had no PyTorch/Coqui installation or cached model. This is not a claim that a
successful real generation or classroom demo has already happened.

To run tests without downloading the model, install the project's development
requirements in the project environment, then run:

```bash
python -m pytest -q
```

## Suggested teammate demo check

1. Use the updated branch in an already working project environment if possible.
2. Run the short command above with a permitted reference sample.
3. Wait for both output paths and exit code 0. Open and listen to both WAVs.
4. If generation fails, report the error and machine/device details. Do not call
   a mocked test, a help command, or the existing hosted upload flow a successful
   local inference demo.

The earlier hosted tests verified signup/login, upload and WAV conversion.
The hosted generation attempt produced no usable result. This helper has not
been connected to that hosted flow and does not establish the cause of its
failure.
