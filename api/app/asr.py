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
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Union

import numpy as np

from . import config, nemo_client

# faster_whisper is imported lazily: a laptop that sends audio to a remote ASR
# worker (ASR_URL) or runs MOCK_MODELS=1 never loads it.
if TYPE_CHECKING:
    from faster_whisper import WhisperModel

SR = 16000
MIN_DETECT_S = 1.2     # shorter chunks inherit the previous language
MERGE_BELOW_S = 1.5    # glue tiny chunks to their neighbour
MAX_CHUNK_S = 20.0

# Classic Whisper hallucinations on silence/noise (subtitle credits, etc.).
HALLUCINATIONS = (
    "subtitrare", "subtitrarea", "vizionare", "abonați-vă", "субтитры", "продолжение следует",
    "редактор субтитров", "конец", "thanks for watching", "thank you for watching", "subscribe",
)
# Whole-segment hallucinations: fine inside a sentence, fake when they are all there is.
EXACT_HALLUCINATIONS = {
    "mulțumesc", "vă mulțumesc", "vă mulțumesc frumos", "mulțumesc frumos", "спасибо",
    "спасибо за внимание", "thank you", "thank you very much", "amin",
}

_model: Optional["WhisperModel"] = None
_lock = threading.Lock()


def _load() -> "WhisperModel":
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
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
    t = text.lower().strip(" .!?…,")
    if not t or t in EXACT_HALLUCINATIONS:
        return True
    if re.search(r"(\w)\1{5,}", t):                     # same letter 6+ times: "пааааааа"
        return True
    words = t.split()
    if len(words) >= 6 and len(set(words)) / len(words) < 0.35:   # "a declari, a declari, ..."
        return True
    return len(t) < 80 and any(h in t for h in HALLUCINATIONS)


def _speech_chunks(audio: np.ndarray) -> list[tuple[int, int]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

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


def load_audio(path: str) -> np.ndarray:
    from faster_whisper import decode_audio
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
        if mode == "segment":
            return _transcribe_segmented(model, audio, progress)
        return _transcribe_longform(model, audio, progress)


def _language_runs(model, audio) -> list[tuple[int, int, str]]:
    """VAD regions (<= 30 s) -> language per region -> consecutive same-language regions
    merged into runs. The language must be chosen BEFORE decoding: Whisper forced to
    Romanian on a Russian speech writes "Să vă mulțumim pentru vizionare" instead."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    primary = config.ASR_LANGUAGES[0]
    opts = VadOptions(min_silence_duration_ms=500, speech_pad_ms=300, max_speech_duration_s=30)
    regions = [(c["start"], c["end"]) for c in get_speech_timestamps(audio, opts, sampling_rate=SR)]
    runs: list[list] = []
    lang = primary
    for start, end in regions:
        if end - start >= 2 * SR:                  # too short to judge: keep the running language
            _, _, all_probs = model.detect_language(audio=audio[start:end])
            probs = {l: p for l, p in all_probs if l in config.ASR_LANGUAGES and l != primary}
            rival = max(probs, key=probs.get, default=None)
            lang = rival if rival and probs[rival] >= config.LONGFORM_SWITCH_PROB else primary
        if runs and runs[-1][2] == lang:
            runs[-1][1] = end
        else:
            runs.append([start, end, lang])
    return [tuple(r) for r in runs]


def _transcribe_longform(model, audio, progress) -> list[dict]:
    """Language runs, each decoded with Whisper's 30 s windows and the previous text
    as context. On a hand-corrected Moldovan lecture this beat short-chunk decoding
    by ~30 WER points; on the Parliament session it keeps whole Russian speeches."""
    total = len(audio) / SR
    out: list[dict] = []
    for start, end, lang in _language_runs(model, audio):
        offset = start / SR
        run = audio[start:end]
        segments, _ = model.transcribe(run, language=lang, beam_size=5, vad_filter=True)
        for s in segments:
            progress(min((offset + s.end) / total, 1.0))
            chunk = run[int(s.start * SR):int(s.end * SR)]
            text, seg_lang, logp = _rescue(model, chunk, s.text.strip(), lang, s.avg_logprob)
            if not _is_hallucination(text):
                out.append({"start": round(offset + s.start, 2), "end": round(offset + s.end, 2),
                            "lang": seg_lang, "logprob": round(logp, 2), "text": text,
                            "speaker": None})
    return out


def _rescue(model, chunk, text: str, lang: str, logp: float) -> tuple[str, str, float]:
    """A doubtful segment (low confidence, or a hallucination such as Whisper writing
    "Să vă mulțumim pentru vizionare" over Russian speech) is decoded again in the
    other languages; the best alternative replaces it only if it is clearly better."""
    hallucinated = _is_hallucination(text)
    if not config.LONGFORM_RESCUE or len(chunk) < SR or \
            not (hallucinated or logp < config.RESCUE_BELOW_LOGPROB):
        return text, lang, logp
    best = (text, lang, logp)
    for other in config.ASR_LANGUAGES:
        if other == lang:
            continue
        r_text, r_logp = _decode(model, chunk, other, None)
        if _is_hallucination(r_text):
            continue
        good_enough = r_logp >= config.RESCUE_MIN_LOGPROB if hallucinated else \
            r_logp > logp + config.RESCUE_MARGIN
        if good_enough and (best[1] == lang or r_logp > best[2]):
            best = (r_text, other, r_logp)
    return best

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


def _decode(model, chunk, lang: str, prompt: Optional[str]) -> tuple[str, float]:
    """-> (text, token-weighted average log-prob)."""
    segments, _ = model.transcribe(
        chunk,
        language=lang,
        beam_size=5,
        initial_prompt=prompt,
        condition_on_previous_text=False,   # stops repetition loops
        vad_filter=False,                   # already split
        without_timestamps=True,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
    )
    segments = list(segments)
    n = sum(max(len(s.tokens), 1) for s in segments) or 1
    logp = sum(s.avg_logprob * max(len(s.tokens), 1) for s in segments) / n if segments else -9.0
    return " ".join(s.text.strip() for s in segments).strip(), logp


def _transcribe_segmented(model, audio, progress) -> list[dict]:
    """Primary language (ro) by default. Another language wins a chunk only when
    detection is fairly sure AND its transcription is clearly more likely: forcing
    Russian on Moldovan-accented Romanian produces fluent-looking Cyrillic nonsense."""
    prompts = load_prompts() if config.WHISPER_PROMPTS else {}
    primary = config.ASR_LANGUAGES[0]
    chunks = _speech_chunks(audio)
    out: list[dict] = []
    for i, (start, end) in enumerate(chunks):
        chunk = audio[start:end]
        probs = {primary: 1.0}
        if len(chunk) >= MIN_DETECT_S * SR:
            _, _, all_probs = model.detect_language(audio=chunk)
            probs = {l: p for l, p in all_probs if l in config.ASR_LANGUAGES}
        rival = max((l for l in probs if l != primary), key=lambda l: probs[l], default=None)
        text, logp = _decode(model, chunk, primary, prompts.get(primary))
        lang = primary
        if rival and probs[rival] >= config.SWITCH_MIN_PROB:
            r_text, r_logp = _decode(model, chunk, rival, prompts.get(rival))
            if r_logp > logp + config.RESCUE_MARGIN:
                text, logp, lang = r_text, r_logp, rival
        if logp >= config.MIN_AVG_LOGPROB and not _is_hallucination(text):
            out.append({"start": round(start / SR, 2), "end": round(end / SR, 2),
                        "lang": lang, "lang_prob": round(probs.get(lang, 0.0), 2),
                        "logprob": round(logp, 2), "text": text, "speaker": None})
        progress((i + 1) / len(chunks))
    return out


def transcribe_remote(path: str, mode: Optional[str] = None,
                      progress: Callable[[float], None] = lambda f: None) -> list[dict]:
    """Send the audio to the ASR worker at ASR_URL; returns the same list as transcribe().
    While the worker runs, its per-chunk progress is polled so the UI bar moves."""
    import uuid

    import httpx

    progress_id = uuid.uuid4().hex
    done = threading.Event()

    def poll() -> None:
        with httpx.Client(timeout=5) as client:
            while not done.wait(1.0):
                try:
                    r = client.get(f"{config.ASR_URL}/api/asr/progress/{progress_id}")
                    if r.status_code == 200:
                        progress(float(r.json().get("progress", 0.0)))
                except (httpx.HTTPError, ValueError):
                    pass   # an older worker without progress: the bar just waits

    threading.Thread(target=poll, daemon=True, name="asr-progress").start()
    try:
        with open(path, "rb") as f:
            resp = httpx.post(
                f"{config.ASR_URL}/api/asr",
                files={"file": (Path(path).name, f)},
                data={"mode": mode or config.ASR_MODE, "progress_id": progress_id},
                timeout=3600,
            )
    finally:
        done.set()
    resp.raise_for_status()
    progress(1.0)
    return resp.json()


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
