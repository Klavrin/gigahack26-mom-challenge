"""Client for the local nemo-server container (Nemotron ASR + Sortformer diarization).

Both calls stay on the machine / internal network: the URLs point at our own
container (default http://nemo:8001), never at a cloud service.
"""
import io
import wave

import httpx
import numpy as np

from . import config

SR = 16000
_client = httpx.Client(timeout=httpx.Timeout(600, connect=5))


def to_wav(audio: np.ndarray) -> bytes:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def transcribe_chunk(chunk: np.ndarray, language: str = "auto") -> tuple[str, str]:
    """-> (text, 2-letter language code or "")."""
    r = _client.post(f"{config.NEMOTRON_URL}/transcribe",
                     files={"file": ("chunk.wav", to_wav(chunk), "audio/wav")},
                     data={"language": language})
    r.raise_for_status()
    body = r.json()
    return body.get("text", "").strip(), body.get("language", "")


def diarize(audio: np.ndarray) -> list[dict]:
    """-> [{start, end, speaker}] for the whole recording."""
    r = _client.post(f"{config.DIARIZATION_URL}/diarize",
                     files={"file": ("meeting.wav", to_wav(audio), "audio/wav")})
    r.raise_for_status()
    return r.json()["segments"]


def health(url: str) -> bool:
    try:
        return _client.get(f"{url}/health", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False
