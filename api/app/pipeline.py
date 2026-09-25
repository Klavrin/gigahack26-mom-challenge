"""Job runner: audio -> transcript -> MoM -> n8n. One GPU, so one job at a time."""
import datetime as dt
import json
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path

import httpx

from . import asr, config, llm, render

STAGES = ["queued", "transcribing", "correcting", "extracting", "sending", "done"]

_jobs: dict[str, dict] = {}
_queue: "queue.Queue[str]" = queue.Queue()


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
    segments = asr.transcribe(job["audio"], progress=lambda f: job.update(progress=f))
    asr.unload()   # give the GPU to the LLM
    job["timings"]["asr_s"] = round(time.time() - t, 1)
    if not config.KEEP_AUDIO:
        Path(job["audio"]).unlink(missing_ok=True)
    _write(jid, "transcript_raw.txt", asr.to_text(segments))

    if config.CORRECT_TRANSCRIPT:
        t = stage("correcting")
        segments = llm.correct_transcript(segments)
        job["timings"]["correct_s"] = round(time.time() - t, 1)
    transcript = asr.to_text(segments)
    _write(jid, "transcript.txt", transcript)
    _write(jid, "segments.json", json.dumps(segments, ensure_ascii=False, indent=1))

    t = stage("extracting")
    mom = llm.extract_mom(transcript, job["meeting_type"], date)
    job["timings"]["llm_s"] = round(time.time() - t, 1)
    html = render.render_html(mom, job["meeting_type"], date)
    _write(jid, "mom.json", json.dumps(mom, ensure_ascii=False, indent=1))
    _write(jid, "mom.html", html)

    t = stage("sending")
    httpx.post(config.N8N_WEBHOOK_URL, json={
        "job_id": jid,
        "meeting_type": job["meeting_type"],
        "meeting_date": job["meeting_date"],
        "subject": render.subject(mom, job["meeting_type"], date),
        "html": html,
        "mom": mom,
    }, timeout=60).raise_for_status()
    job["timings"]["send_s"] = round(time.time() - t, 1)

    job["timings"]["total_s"] = round(time.time() - t0, 1)
    _write(jid, "timings.json", json.dumps(job["timings"], indent=1))
    job["stage"], job["progress"] = "done", 1.0


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
