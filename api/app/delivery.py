"""Approved minutes -> n8n delivery contract v2 (schemas/meeting-delivery-v2.schema.json):
approved state snapshot + a DOCX of the minutes, and the recording when the reviewer
leaves it ticked. The transcript leaves the backend only if the reviewer attaches it."""
import base64
import datetime as dt
import io
import re

from docx import Document
from docx.shared import Pt

from . import render

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


VOICE_LABEL = re.compile(r"^S\d+$")   # diarization labels, not people


def _person(value) -> str | None:
    value = (value or "").strip()
    return value if value and not VOICE_LABEL.match(value) else None


def _strings(items) -> list[str]:
    return [s.strip() for s in items if isinstance(s, str) and s.strip()]


def to_state(job: dict, mom: dict, ended_at: dt.datetime) -> dict:
    started_at = ended_at - dt.timedelta(seconds=float(job.get("audio_s") or 0))
    return {
        "meeting": {
            "id": job["id"],
            "title": ((mom.get("title") or "").strip() or "Proces-verbal")[:240],
            "type": job["meeting_type"],
            "started_at": started_at.isoformat(timespec="seconds"),
            "ended_at": ended_at.isoformat(timespec="seconds"),
        },
        "summary": (mom.get("summary") or "").strip(),
        "participants": [p for p in _strings(mom.get("participants", [])) if _person(p)],
        "topics": _strings(f"{t.get('topic', '').strip()}: {t.get('discussion', '').strip()}".strip(": ")
                           for t in mom.get("topics", [])),
        "decisions": _strings(d.get("decision", "") for d in mom.get("decisions", [])),
        "action_items": [
            {
                "description": a["task"].strip(),
                "owner": _person(a.get("owner")),
                "deadline": (a.get("deadline") or a.get("deadline_text") or "").strip() or None,
                "status": "open",
            }
            for a in mom.get("action_items", []) if (a.get("task") or "").strip()
        ],
        "open_questions": _strings(mom.get("open_questions", [])),
        "important_notes": [],
    }


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def minutes_docx(mom: dict, meeting_type: str, date: dt.date,
                 transcript: list[dict] | None = None, approval: str = "") -> bytes:
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    label = render.TYPE_LABELS.get(meeting_type, (meeting_type, ""))[0]
    doc.add_heading(mom.get("title") or "Proces-verbal", level=0)
    doc.add_paragraph(f"{label} · {date.isoformat()}")
    if approval:
        doc.add_paragraph().add_run(approval).italic = True

    doc.add_heading("Rezumat", level=1)
    doc.add_paragraph(mom.get("summary") or "")
    if mom.get("participants"):
        doc.add_paragraph("Participanți: " + ", ".join(mom["participants"]))

    doc.add_heading("Decizii", level=1)
    for d in mom.get("decisions", []) or [{"decision": "Nicio decizie înregistrată."}]:
        doc.add_paragraph(d.get("decision", ""), style="List Number")

    doc.add_heading("Sarcini", level=1)
    items = mom.get("action_items", [])
    if items:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Light Grid Accent 1"
        for cell, text in zip(table.rows[0].cells, ("Sarcină", "Responsabil", "Termen")):
            cell.text = text
        for a in items:
            row = table.add_row().cells
            row[0].text = a.get("task", "")
            row[1].text = a.get("owner") or "Nespecificat"
            row[2].text = a.get("deadline") or a.get("deadline_text") or "—"
    else:
        doc.add_paragraph("Nicio sarcină înregistrată.")

    if mom.get("topics"):
        doc.add_heading("Subiecte discutate", level=1)
        for t in mom["topics"]:
            p = doc.add_paragraph()
            p.add_run(f"{t.get('topic', '')}. ").bold = True
            p.add_run(t.get("discussion", ""))
    if mom.get("open_questions"):
        doc.add_heading("Întrebări deschise", level=1)
        for q in mom["open_questions"]:
            doc.add_paragraph(q, style="List Bullet")

    if transcript:
        # Opt-in at review time only: the transcript holds everything that was said,
        # patient details included.
        doc.add_page_break()
        doc.add_heading("Anexă: Transcriere", level=1)
        doc.add_paragraph().add_run("Transcriere automată (poate conține erori de recunoaștere). "
                                    "Format: [ora · limba · vorbitor] text.").italic = True
        for seg in transcript:
            p = doc.add_paragraph()
            who = f" · {seg['speaker']}" if seg.get("speaker") else ""
            meta = p.add_run(f"[{_clock(seg.get('start', 0))} · {seg.get('lang', '')}{who}] ")
            meta.font.size = Pt(9)
            p.add_run(seg.get("text", ""))
            p.paragraph_format.space_after = Pt(2)

    footer = doc.sections[0].footer.paragraphs[0]
    footer.text = "Generat de Synaps, on-premise. Înregistrarea și transcrierea nu au părăsit rețeaua internă."
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def payload(job: dict, mom: dict, approved_by: str, attempt: int,
            transcript: list[dict] | None = None, recording: bytes | None = None,
            automatic: bool = False) -> dict:
    date = dt.date.fromisoformat(job["meeting_date"])
    now = dt.datetime.now().astimezone()
    ended_at = dt.datetime.fromtimestamp(job["created"]).astimezone()   # upload = meeting over
    approver = approved_by.strip() or "Reviewer (web app)"
    docx = minutes_docx(mom, job["meeting_type"], date, transcript,
                        "Trimis automat, fără verificare umană." if automatic else f"Aprobat de {approver}.")
    state = to_state(job, mom, min(ended_at, now))
    if transcript:
        state["important_notes"].append(
            "Transcrierea completă este anexată la procesul-verbal (DOCX), la cererea celui care a aprobat.")
    body = {
        "schema_version": "2",
        "delivery_id": f"{job['id']}-{attempt}",
        "state": state,
        "approval": {
            "status": "automatic" if automatic else "approved",   # automatic: the uploader chose no review
            "approved_by": "Trimitere automată" if automatic else approver,
            "approved_at": now.isoformat(timespec="seconds"),
        },
        "documents": [{
            "filename": f"{job['id']}-minutes.docx",
            "mime_type": DOCX_MIME,
            "data_base64": base64.b64encode(docx).decode("ascii"),
        }],
    }
    if recording:
        body["recording"] = {
            "filename": f"{job['id']}-recording.ogg",
            "mime_type": "audio/ogg",
            "duration_s": job["recording"]["duration_s"],
            "data_base64": base64.b64encode(recording).decode("ascii"),
        }
    return body
