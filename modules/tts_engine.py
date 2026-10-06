import torch
from TTS.api import TTS

from config import MODEL_NAME, DEFAULT_SPEAKER, LANGUAGES

def load_tts():
    device = "cuda" if torch.cuda.is_available() else "cpu"

    if device == "cpu":
        print("WARNING: no GPU detected - XTTS will be very slow on CPU.")

    print(
        f"Loading {MODEL_NAME} on {device} "
        "(first run downloads about 2 GB)..."
    )

    tts = TTS(MODEL_NAME).to(device)

    print("Model loaded.")

    validate_model(tts)

    return tts


# ---------------------------------------------------------------------------
# Validate model configuration
# ---------------------------------------------------------------------------

# Make sure the expected baseline speaker exists in the installed model.
def validate_model(tts):
    available_speakers = tts.speakers or []

    if DEFAULT_SPEAKER not in available_speakers:
        raise RuntimeError(
            f"Default XTTS speaker '{DEFAULT_SPEAKER}' was not found. "
            f"Available speakers: {available_speakers}"
        )

    # Verify that the language codes defined above are supported by the
    # loaded model rather than assuming the model configuration matches.
    available_languages = set(tts.languages or [])

    unsupported_languages = {
        code
        for code in LANGUAGES.values()
        if code not in available_languages
    }

    if unsupported_languages:
        raise RuntimeError(
            "The installed XTTS model does not support these configured "
            f"languages: {sorted(unsupported_languages)}"
        )


    print(f"Default speaker: {DEFAULT_SPEAKER}")
    print(f"Supported languages: {sorted(available_languages)}")