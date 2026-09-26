"""Local LLM (Ollama) - transcript correction and Minutes-of-Meeting extraction."""
import datetime as dt
import json
import re

import httpx

from . import config

MOM_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "participants": {"type": "array", "items": {"type": "string"}},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"topic": {"type": "string"}, "discussion": {"type": "string"}},
                "required": ["topic", "discussion"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"decision": {"type": "string"}, "evidence": {"type": "string"}},
                "required": ["decision", "evidence"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "owner": {"type": "string"},
                    "deadline": {"type": "string"},
                    "deadline_text": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["task", "owner", "deadline", "deadline_text", "evidence"],
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "participants", "topics", "decisions",
                 "action_items", "open_questions"],
}

EXTRACT_RULES = """You are the secretary of a {meeting_type} meeting at Medpark hospital (Chisinau, Moldova).
The transcript is mostly Romanian with abrupt switches to Russian and English, and medical vocabulary.
Each line starts with [hh:mm:ss language speaker]. It comes from speech recognition and may contain errors: infer the intended meaning.
Meeting date: {date} ({weekday}).

Write every output field in {language}. Spell drug names, medical terms and people's names correctly.
- summary: 3-6 sentences on what the meeting achieved.
- decisions: ONLY things that were actually agreed or decided. Not topics that were merely discussed.
- action_items: concrete tasks someone committed to or was assigned.
  - owner: the person or role named in the transcript. If nobody was named, use "". NEVER invent a name.
  - deadline: resolve relative expressions ("până vineri", "к понедельнику", "end of month") against the meeting date, as YYYY-MM-DD. "" if no deadline was mentioned.
  - deadline_text: the deadline expression exactly as spoken, "" if none.
- evidence: a short verbatim quote (max 20 words) from the transcript that supports the item.
- If something is not in the transcript, leave it out. Empty lists are fine."""

REDUCE_RULES = """Below are partial minutes extracted from consecutive parts of ONE meeting, as JSON.
Merge them into a single set of minutes: one title, one summary covering the whole meeting,
deduplicated participants/decisions/action items (keep every distinct one, keep their evidence),
and merged topics. Do not add anything that is not in the parts. Write in {language}."""

CORRECT_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        }
    },
    "required": ["lines"],
}

CORRECT_RULES = """You fix speech-recognition errors in a hospital meeting transcript (Romanian/Russian/English code-switching).
Fix ONLY clearly misrecognised medical terms, drug names, department names and the glossary terms below.
Do NOT translate. Do NOT rephrase. Keep each line's language and script (Latin/Cyrillic) as is.
Return every line with its id, unchanged if there is nothing to fix.

Glossary:
{glossary}"""

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def chat_json(system: str, user: str, schema: dict) -> dict:
    resp = httpx.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={
            "model": config.LLM_MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "format": schema,
            "think": False,   # Qwen3: skip the reasoning trace, answer with JSON only
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0, "num_ctx": config.LLM_NUM_CTX},
        },
        timeout=900,
    )
    resp.raise_for_status()
    content = re.sub(r"<think>.*?</think>", "", resp.json()["message"]["content"], flags=re.S)
    return json.loads(content)


def _chunks(lines: list[str], max_chars: int) -> list[list[str]]:
    out, cur, size = [], [], 0
    for line in lines:
        if cur and size + len(line) > max_chars:
            out.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        out.append(cur)
    return out


def load_glossary() -> str:
    path = config.GLOSSARY_DIR / "medical_terms.txt"
    if not path.exists():
        return ""
    terms = [t.strip() for t in path.read_text(encoding="utf-8").splitlines()
             if t.strip() and not t.startswith("#")]
    return ", ".join(terms)


def correct_transcript(segments: list[dict]) -> list[dict]:
    """Glossary-guided spelling fix. Rejects any line the model rewrote too much."""
    system = CORRECT_RULES.format(glossary=load_glossary())
    for batch_start in range(0, len(segments), 40):
        batch = segments[batch_start:batch_start + 40]
        user = "\n".join(f"{batch_start + i}\t{s['text']}" for i, s in enumerate(batch))
        try:
            fixed = chat_json(system, user, CORRECT_SCHEMA)["lines"]
        except (httpx.HTTPError, KeyError, json.JSONDecodeError):
            continue
        for item in fixed:
            idx = item.get("id")
            if not isinstance(idx, int) or not batch_start <= idx < batch_start + len(batch):
                continue
            old, new = segments[idx]["text"], (item.get("text") or "").strip()
            if new and abs(len(new) - len(old)) <= max(8, 0.2 * len(old)):
                segments[idx]["text"] = new
    return segments


def extract_mom(transcript: str, meeting_type: str, meeting_date: dt.date) -> dict:
    system = EXTRACT_RULES.format(
        meeting_type=meeting_type,
        date=meeting_date.isoformat(),
        weekday=WEEKDAYS[meeting_date.weekday()],
        language=config.MOM_LANGUAGE,
    )
    parts = _chunks(transcript.splitlines(), config.LLM_CHUNK_CHARS)
    partials = [chat_json(system, "TRANSCRIPT:\n" + "\n".join(p), MOM_SCHEMA) for p in parts]
    if len(partials) == 1:
        return partials[0]
    reduce_system = system + "\n\n" + REDUCE_RULES.format(language=config.MOM_LANGUAGE)
    return chat_json(reduce_system, json.dumps(partials, ensure_ascii=False), MOM_SCHEMA)
