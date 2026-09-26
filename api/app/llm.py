"""Local LLM (Ollama) - transcript correction and Minutes-of-Meeting extraction."""
import datetime as dt
import json
import re

import httpx

from . import config, deadlines

MOM_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "participants": {"type": "array", "items": {"type": "string"}},
        "speakers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "name": {"type": "string"}},
                "required": ["label", "name"],
            },
        },
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
    "required": ["title", "summary", "participants", "speakers", "topics", "decisions",
                 "action_items", "open_questions"],
}

EXTRACT_RULES = """You are the secretary of a {meeting_type} meeting at Medpark hospital (Chisinau, Moldova).
The transcript is mostly Romanian with abrupt switches to Russian and English, and medical vocabulary.
Each line starts with [hh:mm:ss language speaker]. It comes from speech recognition and may contain errors: infer the intended meaning.
Speaker labels (S1, S2...) are anonymous voices. Map a label to a person only when the transcript makes it clear
(e.g. someone says "Natalia, poți tu?" and S2 answers "Da, mă ocup eu" -> S2 is Natalia). Otherwise keep the owner as the name spoken, or "".
If something is changed later in the meeting (new owner, new deadline, reversed decision), keep ONLY the final version.
Meeting date: {date} ({weekday}).

Write every output field in {language}. Spell drug names, medical terms and people's names correctly.
- summary: 3-6 sentences on what the meeting achieved.
- speakers: for EVERY label (S1, S2...) give the person's name if the transcript reveals it
  (addressed by name and answers, introduces themselves, "Doamna Rusu" + "Natalia" for the same voice -> "Natalia Rusu"), else "".
- participants: people's names (not labels).
- decisions: ONLY things that were actually agreed or decided. Not topics that were merely discussed.
- action_items: concrete tasks someone committed to or was assigned.
  - owner: the person's name (resolve S1/S2 labels via speakers) or role named in the transcript. If nobody was named, use "". NEVER invent a name.
  - deadline: resolve relative expressions ("până vineri", "к понедельнику", "end of month") as YYYY-MM-DD.
    Do NOT calculate dates yourself: look the day up in the CALENDAR below ("vineri"/"Friday" = the first Friday AFTER the meeting date). "" if no deadline was mentioned.
  - deadline_text: the deadline expression exactly as spoken, "" if none.
- evidence: a short verbatim quote (max 20 words) from the transcript that supports the item.
- If something is not in the transcript, leave it out. Empty lists are fine.

CALENDAR (meeting day first):
{calendar}"""

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
WEEKDAYS_RO = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]
WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def calendar(start: dt.date, days: int = 21) -> str:
    """Lookup table so the model never does date arithmetic (7B models get it wrong)."""
    lines = []
    for i in range(days):
        d = start + dt.timedelta(days=i)
        w = d.weekday()
        tag = "  <- meeting" if i == 0 else ""
        lines.append(f"{d.isoformat()} {WEEKDAYS[w]} / {WEEKDAYS_RO[w]} / {WEEKDAYS_RU[w]}{tag}")
    return "\n".join(lines)


def _grounded(name: str, transcript_norm: str) -> bool:
    """A name counts only if one of its words (3+ letters) was actually said."""
    words = re.findall(r"\w{3,}", deadlines.normalize(name))
    return any(w in transcript_norm for w in words)


def _clean(mom: dict, meeting_date: dt.date, transcript: str) -> dict:
    """Deterministic post-checks on the model output."""
    said = deadlines.normalize(transcript)
    label = re.compile(r"^S\d+$")
    names = {sp["label"].strip(): sp["name"].strip()
             for sp in mom.get("speakers", [])
             if sp.get("label") and (sp.get("name") or "").strip()
             and _grounded(sp["name"], said)}          # drops invented names
    mom["speakers"] = [{"label": k, "name": v} for k, v in names.items()]
    people = [p.strip() for p in mom.get("participants", []) if p and p.strip()]
    people = [names.get(p, p) for p in people]
    people = [p for p in people if label.match(p) or _grounded(p, said)]
    mom["participants"] = list(dict.fromkeys(people + list(names.values())))
    for a in mom.get("action_items", []):
        owner = (a.get("owner") or "").strip()
        owner = names.get(owner, owner)
        a["owner"] = owner if not owner or label.match(owner) or _grounded(owner, said) else ""
        # the spoken expression wins over the model's own date arithmetic
        resolved = deadlines.resolve(a.get("deadline_text", ""), meeting_date)
        if resolved:
            a["deadline"] = resolved
        else:
            try:
                dt.date.fromisoformat(a.get("deadline") or "")
            except ValueError:
                a["deadline"] = ""   # never show a malformed date
    return mom


def chat_json(system: str, user: str, schema: dict) -> dict:
    resp = httpx.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={
            "model": config.LLM_MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0, "num_ctx": config.LLM_NUM_CTX},
        },
        timeout=900,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["message"]["content"])


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
        calendar=calendar(meeting_date),
    )
    parts = _chunks(transcript.splitlines(), config.LLM_CHUNK_CHARS)
    partials = [chat_json(system, "TRANSCRIPT:\n" + "\n".join(p), MOM_SCHEMA) for p in parts]
    if len(partials) == 1:
        return _clean(partials[0], meeting_date, transcript)
    reduce_system = system + "\n\n" + REDUCE_RULES.format(language=config.MOM_LANGUAGE)
    return _clean(chat_json(reduce_system, json.dumps(partials, ensure_ascii=False), MOM_SCHEMA),
                  meeting_date, transcript)
