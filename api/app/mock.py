"""MOCK_MODELS=1: canned ASR/LLM output so the UI, review step and n8n delivery
can be developed on a machine without a GPU. Fixtures use invented names only."""
import copy
import datetime as dt
import json
import time
from typing import Callable

from . import config


def _fixture(name: str):
    return json.loads((config.FIXTURES_DIR / name).read_text(encoding="utf-8"))


def transcribe(progress: Callable[[float], None]) -> list[dict]:
    steps = 20
    for i in range(steps):
        time.sleep(0.2)
        progress((i + 1) / steps)
    return _fixture("segments.json")


def correct_transcript(segments: list[dict]) -> list[dict]:
    time.sleep(1)
    return segments


def extract_mom(transcript: str, meeting_type: str, meeting_date: dt.date) -> dict:
    time.sleep(2)
    return copy.deepcopy(_fixture("mom.json"))
