import os
import tempfile

from pydub import AudioSegment
from pydub.effects import normalize

TARGET_SAMPLE_RATE = 22050

def normalize_audio(input_path):
    """
    Convert input audio to normalized WAV:
    - Mono
    - 22050 Hz
    - 16-bit PCM
    - Peak-normalized

    Returns the path to the converted WAV file.
    """
    if not input_path or not os.path.isfile(input_path):
        raise ValueError("Please provide a valid audio file.")

    output_path = None

    try:
        audio = AudioSegment.from_file(input_path)

        # Convert stereo or multichannel audio to mono.
        audio = audio.set_channels(1)

        # Resample to a consistent sample rate.
        audio = audio.set_frame_rate(TARGET_SAMPLE_RATE)

        # Convert to 16-bit PCM before saving.
        audio = audio.set_sample_width(2)

        # Normalize peak volume without changing the duration.
        audio = normalize(audio, headroom=1.0)

        # Create a persistent WAV file for preview and download.
        with tempfile.NamedTemporaryFile(
            suffix="_normalized.wav",
            delete=False
        ) as temp_file:
            output_path = temp_file.name

        audio.export(output_path, format="wav")

        return output_path

    except Exception as exc:
        if output_path and os.path.exists(output_path):
            os.remove(output_path)

        raise ValueError(
            f"Could not convert the audio to WAV: {exc}"
        ) from exc