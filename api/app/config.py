import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _flag(name: str, default: str = "0") -> bool:
    return _env(name, default).lower() in ("1", "true", "yes")


WHISPER_MODEL = _env("WHISPER_MODEL", "large-v3-turbo")
WHISPER_DEVICE = _env("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = _env("WHISPER_COMPUTE_TYPE", "int8_float16")
WHISPER_DIR = Path(_env("WHISPER_DIR", "/models/whisper"))
# "longform" = 30 s windows with context, primary language forced, Russian re-checked
#              per segment (default: best WER on a hand-corrected Moldovan lecture)
# "segment"  = short VAD chunks transcribed one by one, no context (much worse WER)
# "plain"    = stock Whisper, language auto-detected (baseline for WER)
ASR_MODE = _env("ASR_MODE", "longform")
ASR_MODES = ("longform", "segment", "plain")
# longform: a segment switches to another language only above this detection probability.
# 0.8 let noisy Romanian regions of the lecture through as Russian (WER 66.5% vs 53.0%).
LONGFORM_SWITCH_PROB = float(_env("LONGFORM_SWITCH_PROB", "0.95"))
# Off by default: +10 WER on the Moldovan lecture (hard Romanian flipped to Russian).
LONGFORM_RESCUE = _flag("LONGFORM_RESCUE")
# longform rescue: segments below this confidence (or flagged as hallucinations) are
# decoded again in the other languages; the best version replaces them if clearly better.
RESCUE_BELOW_LOGPROB = float(_env("RESCUE_BELOW_LOGPROB", "-0.7"))
# ...a replacement for a hallucinated segment must reach at least this confidence.
RESCUE_MIN_LOGPROB = float(_env("RESCUE_MIN_LOGPROB", "-0.6"))
# ...and a replacement for a low-confidence segment must beat it by this much (names are
# low-confidence in every language, so a small margin flips them to the wrong one).
RESCUE_MARGIN = float(_env("RESCUE_MARGIN", "0.3"))
ASR_LANGUAGES = tuple(_env("ASR_LANGUAGES", "ro,ru,en").split(","))   # first = primary language
# Glossary prompt for Whisper. Off by default: on noisy audio Whisper copies the
# prompt into the transcript (tested on a 96-min recording).
WHISPER_PROMPTS = _flag("WHISPER_PROMPTS")
# Another language only replaces the primary one if detection is at least this sure...
SWITCH_MIN_PROB = float(_env("SWITCH_MIN_PROB", "0.5"))
# ...and its transcription is this much more likely (avg log-prob per token).
SWITCH_MARGIN = float(_env("SWITCH_MARGIN", "0.1"))
# Chunks whose best transcription is below this are unintelligible noise: dropped.
MIN_AVG_LOGPROB = float(_env("MIN_AVG_LOGPROB", "-0.95"))
# Which recogniser transcribes each VAD chunk:
# "whisper"  = faster-whisper in this container
# "nemotron" = Nemotron 3.5 ASR in the local nemo-server container
ASR_BACKEND = _env("ASR_BACKEND", "whisper")
NEMOTRON_URL = _env("NEMOTRON_URL", "http://nemo:8001")
NEMOTRON_LOCALES = {"ro": "ro-RO", "ru": "ru-RU", "en": "en-US"}
# Speaker diarization (Sortformer in nemo-server). Empty = off.
DIARIZATION_URL = _env("DIARIZATION_URL", "")
# Base URL of a remote ASR worker (the same api image on the GPU node).
# Empty = transcribe in this process.
ASR_URL = _env("ASR_URL", "").rstrip("/")

OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = _env("LLM_MODEL", "qwen3:8b")
LLM_NUM_CTX = int(_env("LLM_NUM_CTX", "16384"))
# Characters of transcript per LLM call; longer meetings are map-reduced.
LLM_CHUNK_CHARS = int(_env("LLM_CHUNK_CHARS", "14000"))
MOM_LANGUAGE = _env("MOM_LANGUAGE", "Romanian")
CORRECT_TRANSCRIPT = _flag("CORRECT_TRANSCRIPT")

N8N_WEBHOOK_URL = _env("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/mom")

DATA_DIR = Path(_env("DATA_DIR", "/data"))
GLOSSARY_DIR = Path(_env("GLOSSARY_DIR", "/glossary"))
# Privacy default: raw audio is deleted as soon as it has been transcribed.
KEEP_AUDIO = _flag("KEEP_AUDIO")
# 1 = never touch the network for model files (demo / hospital mode).
OFFLINE = _flag("OFFLINE")
# 1 = no ASR/LLM calls at all; serve canned fixtures (frontend/backend dev without a GPU).
MOCK_MODELS = _flag("MOCK_MODELS")
FIXTURES_DIR = Path(_env("FIXTURES_DIR", str(Path(__file__).resolve().parent.parent / "fixtures")))

MEETING_TYPES = ("medical", "executive", "administrative")

# Built React app (api/web -> npm run build). The Docker image copies it here.
STATIC_DIR = Path(_env("STATIC_DIR", str(Path(__file__).resolve().parent.parent / "static")))
