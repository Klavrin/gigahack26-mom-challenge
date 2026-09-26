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
# "segment" = VAD split + per-utterance language ID (our pipeline)
# "plain"   = stock Whisper, one language per 30 s window (baseline for WER)
ASR_MODE = _env("ASR_MODE", "segment")
ASR_LANGUAGES = tuple(_env("ASR_LANGUAGES", "ro,ru,en").split(","))
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
