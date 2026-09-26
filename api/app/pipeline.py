"""Job runner: audio -> transcript -> MoM draft -> human review -> n8n.
One GPU, so one job at a time."""
import datetime as dt
import json
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path

import httpx

from . import asr, config, llm, mock, render

STAGES = ["queued", "transcribing", "correcting", "extracting", "review", "sending", "done"]

_jobs: dict[str, dict] = {}
_queue: "queue.Queue[str]" = queue.Queue()
_send_lock = threading.Lock()


def job_dir(job_id: str) -> Path:
    return config.DATA_DIR / "jobs" / job_id


def get(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def submit(audio_path: Path, meeting_type: str, meeting_date: dt.date, job_id: str) -> dict:
    job = {
        "id": job_id,
        "meeting_type": meeting_type,
        "meeting_date": meeting_date.isoformat(),
        "stage": "queued",
        "progress": 0.0,
        "error": None,
        "created": time.time(),
        "timings": {},
        "audio": str(audio_path),
    }
    _jobs[job_id] = job
    _queue.put(job_id)
    return job


def new_job_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _write(job_id: str, name: str, content: str) -> None:
    (job_dir(job_id) / name).write_text(content, encoding="utf-8")


def run(job: dict) -> None:
    jid = job["id"]
    date = dt.date.fromisoformat(job["meeting_date"])
    t0 = time.time()

    def stage(name: str) -> float:
        job["stage"], job["progress"] = name, 0.0
        return time.time()

    t = stage("transcribing")
    segments = _transcribe(job)
    job["audio_s"] = round(segments[-1]["end"], 1) if segments else 0.0
    job["timings"]["asr_s"] = round(time.time() - t, 1)
    if not config.KEEP_AUDIO:
        Path(job["audio"]).unlink(missing_ok=True)
    _write(jid, "transcript_raw.txt", asr.to_text(segments))

    if config.CORRECT_TRANSCRIPT:
        t = stage("correcting")
        segments = (mock if config.MOCK_MODELS else llm).correct_transcript(segments)
        job["timings"]["correct_s"] = round(time.time() - t, 1)
    transcript = asr.to_text(segments)
    _write(jid, "transcript.txt", transcript)
    _write(jid, "segments.json", json.dumps(segments, ensure_ascii=False, indent=1))

    t = stage("extracting")
    mom = (mock if config.MOCK_MODELS else llm).extract_mom(transcript, job["meeting_type"], date)
    job["timings"]["llm_s"] = round(time.time() - t, 1)
    job["title"] = mom.get("title") or None
    _write(jid, "mom_draft.json", json.dumps(mom, ensure_ascii=False, indent=1))
    _write(jid, "mom.json", json.dumps(mom, ensure_ascii=False, indent=1))
    _write(jid, "mom.html", render.render_html(mom, job["meeting_type"], date))

    # Nothing is emailed until a person has checked owners and deadlines (send()).
    job["timings"]["total_s"] = round(time.time() - t0, 1)
    job["review_since"] = time.time()
    job["stage"], job["progress"] = "review", 1.0


def recent(limit: int = 10) -> list[dict]:
    jobs = sorted(_jobs.values(), key=lambda j: j["created"], reverse=True)[:limit]
    keys = ("id", "stage", "meeting_type", "meeting_date", "title", "created")
    return [{k: j.get(k) for k in keys} for j in jobs]


def send(job: dict, action_items: list[dict], meeting_type: str | None = None) -> dict:
    """Apply the reviewer's edits (owners, deadlines, distribution list), re-render,
    deliver through n8n."""
    jid = job["id"]
    date = dt.date.fromisoformat(job["meeting_date"])
    with _send_lock:
        if job["stage"] != "review":
            raise ValueError(f"job is {job['stage']}, not waiting for review")
        if meeting_type and meeting_type not in config.MEETING_TYPES:
            raise ValueError(f"meeting_type must be one of {config.MEETING_TYPES}")
        mom = json.loads((job_dir(jid) / "mom.json").read_text(encoding="utf-8"))
        items = mom.get("action_items", [])
        if len(action_items) != len(items):
            raise ValueError(f"expected {len(items)} action items, got {len(action_items)}")
        for item, edit in zip(items, action_items):
            deadline = edit["deadline"].strip()
            if deadline:
                dt.date.fromisoformat(deadline)   # ValueError -> 400
            item["owner"], item["deadline"] = edit["owner"].strip(), deadline
        if meeting_type:
            job["meeting_type"] = meeting_type   # the reviewer picks who receives it
        job["stage"], job["error"] = "sending", None

    html = render.render_html(mom, job["meeting_type"], date)
    _write(jid, "mom.json", json.dumps(mom, ensure_ascii=False, indent=1))
    _write(jid, "mom.html", html)
    t = time.time()
    try:
        httpx.post(config.N8N_WEBHOOK_URL, json={
            "job_id": jid,
            "meeting_type": job["meeting_type"],
            "meeting_date": job["meeting_date"],
            "subject": render.subject(mom, job["meeting_type"], date),
            "html": html,
            "mom": mom,
        }, timeout=60).raise_for_status()
    except httpx.HTTPError as e:
        job["stage"], job["error"] = "review", f"Sending failed: {e}"   # let the user retry
        raise
    job["timings"]["send_s"] = round(time.time() - t, 1)
    job["timings"]["review_s"] = round(t - job["review_since"], 1)
    _write(jid, "timings.json", json.dumps(job["timings"], indent=1))
    job["stage"] = "done"
    return job


def _transcribe(job: dict) -> list[dict]:
    progress = lambda f: job.update(progress=f)
    if config.MOCK_MODELS:
        return mock.transcribe(progress)
    if config.ASR_URL:
        return asr.transcribe_remote(job["audio"])
    segments = asr.transcribe(job["audio"], progress=progress)
    asr.unload()   # give the GPU to the LLM
    return segments


def _worker() -> None:
    while True:
        job = _jobs[_queue.get()]
        try:
            run(job)
        except Exception as e:  # surface to the UI, keep the worker alive
            traceback.print_exc()
            job["error"] = f"{type(e).__name__}: {e}"
            job["stage"] = "failed"
        finally:
            asr.unload()


def start_worker() -> None:
    threading.Thread(target=_worker, daemon=True, name="mom-worker").start()
