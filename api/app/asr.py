"""Hybrid RO/RU/EN speech recognition.

Stock Whisper detects the language once per 30 s window, so a Romanian meeting
with Russian interjections gets the Russian parts "translated" into Romanian or
garbled. "segment" mode instead:
  1. splits the audio at pauses with Silero VAD (utterance-sized chunks),
  2. detects the language of each chunk, restricted to ro/ru/en,
  3. transcribes each chunk with that language forced and a domain prompt.

ASR_BACKEND picks the recogniser for step 3: faster-whisper here, or Nemotron
3.5 ASR in the local nemo-server container. Both share the same VAD chunks, so
their WER can be compared like for like.
"""
import gc
import json
import threading
from typing import Callable, Optional, Union

import numpy as np
from faster_whisper import WhisperModel, decode_audio
from faster_whisper.vad import VadOptions, get_speech_timestamps

from . import config, nemo_client

SR = 16000
MIN_DETECT_S = 1.2     # shorter chunks inherit the previous language
MERGE_BELOW_S = 1.5    # glue tiny chunks to their neighbour
MAX_CHUNK_S = 20.0

# Classic Whisper hallucinations on silence/noise (subtitle credits, etc.).
HALLUCINATIONS = (
    "subtitrare", "subtitrarea", "mulțumesc pentru vizionare", "vă mulțumim pentru vizionare",
    "abonați-vă", "субтитры", "продолжение следует", "редактор субтитров",
    "thanks for watching", "thank you for watching", "subscribe",
)

_model: Optional[WhisperModel] = None
_lock = threading.Lock()


def _load() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
            download_root=str(config.WHISPER_DIR),
            local_files_only=config.OFFLINE,
        )
    return _model


def unload() -> None:
    """Free VRAM so the LLM has the whole GPU (8 GB laptops)."""
    global _model
    _model = None
    gc.collect()


def load_prompts() -> dict:
    path = config.GLOSSARY_DIR / "whisper_prompts.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _is_hallucination(text: str) -> bool:
    t = text.lower().strip(" .!?…")
    return not t or (len(t) < 80 and any(h in t for h in HALLUCINATIONS))


def _speech_chunks(audio: np.ndarray) -> list[tuple[int, int]]:
    opts = VadOptions(
        threshold=0.5,
        min_speech_duration_ms=250,
        min_silence_duration_ms=400,
        speech_pad_ms=200,
        max_speech_duration_s=MAX_CHUNK_S,
    )
    raw = [(c["start"], c["end"]) for c in get_speech_timestamps(audio, opts, sampling_rate=SR)]
    merged: list[tuple[int, int]] = []
    for start, end in raw:
        if merged:
            p_start, p_end = merged[-1]
            short = (end - start) < MERGE_BELOW_S * SR or (p_end - p_start) < MERGE_BELOW_S * SR
            close = (start - p_end) < 1.0 * SR
            fits = (end - p_start) <= MAX_CHUNK_S * SR
            if short and close and fits:
                merged[-1] = (p_start, end)
                continue
        merged.append((start, end))
    return merged


def _pick_language(model: WhisperModel, chunk: np.ndarray, previous: str) -> tuple[str, float]:
    if len(chunk) < MIN_DETECT_S * SR:
        return previous, 0.0
    _, _, all_probs = model.detect_language(audio=chunk)
    allowed = [(lang, p) for lang, p in all_probs if lang in config.ASR_LANGUAGES]
    lang, prob = max(allowed, key=lambda x: x[1])
    # Low-confidence switches are usually noise; stay with the running language.
    if prob < 0.4 and previous:
        return previous, prob
    return lang, prob


def load_audio(path: str) -> np.ndarray:
    return decode_audio(path, sampling_rate=SR)


def transcribe(
    audio: Union[str, np.ndarray],
    mode: Optional[str] = None,
    backend: Optional[str] = None,
    progress: Callable[[float], None] = lambda f: None,
) -> list[dict]:
    """Return [{start, end, lang, text, speaker}] for an audio file or 16 kHz array."""
    mode = mode or config.ASR_MODE
    backend = backend or config.ASR_BACKEND
    if isinstance(audio, str):
        audio = load_audio(audio)
    if backend == "nemotron":
        return _transcribe_nemotron(audio, progress)
    with _lock:
        model = _load()
        if mode == "plain":
            return _transcribe_plain(model, audio, progress)
        return _transcribe_segmented(model, audio, progress)


def _transcribe_nemotron(audio, progress) -> list[dict]:
    """Same VAD chunks as the Whisper path; each chunk goes to the local Nemotron
    container in auto-language mode. If it picks a language outside ro/ru/en
    (e.g. Moldovan Romanian heard as another locale), retry with the running one."""
    chunks = _speech_chunks(audio)
    out: list[dict] = []
    lang = config.ASR_LANGUAGES[0]
    for i, (start, end) in enumerate(chunks):
        chunk = audio[start:end]
        text, detected = nemo_client.transcribe_chunk(chunk, "auto")
        if detected in config.ASR_LANGUAGES:
            lang = detected
        elif text:
            text, _ = nemo_client.transcribe_chunk(chunk, config.NEMOTRON_LOCALES[lang])
        if not _is_hallucination(text):
            out.append({"start": round(start / SR, 2), "end": round(end / SR, 2),
                        "lang": lang, "text": text, "speaker": None})
        progress((i + 1) / len(chunks))
    return out


def _transcribe_plain(model, audio, progress) -> list[dict]:
    segments, info = model.transcribe(audio, beam_size=5, vad_filter=True)
    total = len(audio) / SR
    out = []
    for s in segments:
        progress(min(s.end / total, 1.0))
        if not _is_hallucination(s.text):
            out.append({"start": s.start, "end": s.end, "lang": info.language,
                        "text": s.text.strip(), "speaker": None})
    return out


def _transcribe_segmented(model, audio, progress) -> list[dict]:
    prompts = load_prompts()
    chunks = _speech_chunks(audio)
    out: list[dict] = []
    lang = config.ASR_LANGUAGES[0]
    for i, (start, end) in enumerate(chunks):
        chunk = audio[start:end]
        lang, prob = _pick_language(model, chunk, lang)
        segments, _ = model.transcribe(
            chunk,
            language=lang,
            beam_size=5,
            initial_prompt=prompts.get(lang),
            condition_on_previous_text=False,   # stops repetition loops
            vad_filter=False,                   # already split
            without_timestamps=True,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if not _is_hallucination(text):
            out.append({"start": round(start / SR, 2), "end": round(end / SR, 2),
                        "lang": lang, "lang_prob": round(prob, 2),
                        "text": text, "speaker": None})
        progress((i + 1) / len(chunks))
    return out


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def to_text(segments: list[dict], with_meta: bool = True) -> str:
    lines = []
    for s in segments:
        if with_meta:
            who = f" {s['speaker']}" if s.get("speaker") else ""
            lines.append(f"[{fmt_ts(s['start'])} {s['lang']}{who}] {s['text']}")
        else:
            lines.append(s["text"])
    return "\n".join(lines)
