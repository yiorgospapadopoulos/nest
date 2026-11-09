"""The recordings voice input takes (B154): WAV, 16-bit PCM, one channel at 16 kHz, what
Whisper hears. Clients make it themselves, so the daemon needs no audio decoder.
"""

import io
import wave

from nestd.errors import InvalidInputError

SAMPLE_RATE = 16_000
SAMPLE_BYTES = 2
# A message's worth; clients stop recording here.
MAX_SECONDS = 300
_HEADER_ROOM = 1024
_WAV_HEADER = 44
# Shorter than this is a tap, not speech: nothing is heard.
SHORTEST_SECONDS = 0.2
MAX_BYTES = MAX_SECONDS * SAMPLE_RATE * SAMPLE_BYTES + _HEADER_ROOM


def recording_seconds(data: bytes) -> float:
    """How long the recording is; InvalidInputError when it is not one voice input takes."""
    if len(data) > MAX_BYTES:
        msg = f"recordings are at most {MAX_SECONDS // 60} minutes"
        raise InvalidInputError(msg)
    try:
        with wave.open(io.BytesIO(data), "rb") as recording:
            shape = (
                recording.getnchannels(),
                recording.getsampwidth(),
                recording.getframerate(),
                recording.getcomptype(),
            )
            frames = recording.getnframes()
    except (wave.Error, EOFError) as error:
        msg = f"not a WAV recording: {error}"
        raise InvalidInputError(msg) from error
    if shape != (1, SAMPLE_BYTES, SAMPLE_RATE, "NONE"):
        msg = "recordings are 16-bit PCM, one channel, 16 kHz"
        raise InvalidInputError(msg)
    # The header's count can claim more than the body holds; the body decides.
    return min(frames, (len(data) - _WAV_HEADER) // SAMPLE_BYTES) / SAMPLE_RATE
