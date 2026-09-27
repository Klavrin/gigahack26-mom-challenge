"""Job runner: audio -> transcript -> MoM draft -> (human review) -> n8n.
One GPU, so one job at a time. Each job's state is kept in its folder (job.json): after a
restart finished meetings are still there and interrupted ones are processed again."""
import datetime as dt
import json
import os
import queue
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import asr, config, delivery, llm, merge, mock, nemo_client, render

STAGES = ["queued", "transcribing", "correcting", "extracting", "review", "sending", "done"]
WORKING = ("queued", "transcribing", "correcting", "extracting")
RECORDING = "recording.ogg"   # compressed copy of the audio for the email

_jobs: dict[str, dict] = {}
_queue: "queue.Queue[str]" = queue.Queue()
_send_lock = threading.Lock()


def job_dir(job_id: str) -> Path:
    return config.DATA_DIR / "jobs" / job_id


def get(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def _save(job: dict) -> None:
    """Keep the job's state next to its files (atomic, so a crash never leaves half a file)."""
    path = job_dir(job["id"]) / "job.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def submit(audio_path: Path, meeting_type: str | None, meeting_date: dt.date, job_id: str,
           auto_send: bool = True) -> dict:
    job = {
        "id": job_id,
        "meeting_type": meeting_type,   # None: the LLM infers it from the content
        "meeting_type_source": "chosen" if meeting_type else "inferred",
        "auto_send": auto_send,         # False: waits on the review page for a person
        "meeting_date": meeting_date.isoformat(),
        "stage": "queued",
        "progress": 0.0,
        "error": None,
        "created": time.time(),
        "timings": {},
        "audio": str(audio_path),
    }
    _jobs[job_id] = job
    _save(job)
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
        _save(job)
        return time.time()

    t = stage("transcribing")
    recording = _start_recording(job)   # CPU work, done while the GPU transcribes
    segments, turns = _transcribe(job)
    job["audio_s"] = round(segments[-1]["end"], 1) if segments else 0.0
    job["timings"]["asr_s"] = round(time.time() - t, 1)
    _finish_recording(job, recording)
    if not config.KEEP_AUDIO:
        Path(job["audio"]).unlink(missing_ok=True)
    _write(jid, "diarization.json", json.dumps(turns, indent=1))
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
    if not config.MOCK_MODELS:
        llm.unload()   # the next job's Whisper needs this VRAM (8 GB GPUs)
    job["timings"]["llm_s"] = round(time.time() - t, 1)
    if not job["meeting_type"]:   # what the meeting was about picks the distribution list
        inferred = mom.get("meeting_type")
        job["meeting_type"] = inferred if inferred in config.MEETING_TYPES else "medical"
    job["title"] = mom.get("title") or None
    _write(jid, "mom_draft.json", json.dumps(mom, ensure_ascii=False, indent=1))
    _write(jid, "mom.json", json.dumps(mom, ensure_ascii=False, indent=1))
    _write(jid, "mom.html", render.render_html(mom, job["meeting_type"], date))

    job["timings"]["total_s"] = round(time.time() - t0, 1)
    job["review_since"] = time.time()
    if job.get("auto_send"):
        job["stage"], job["progress"] = "sending", 1.0
        _save(job)
        _auto_send(job, mom, date)
        return
    # Nothing is emailed until a person has checked owners and deadlines (send()).
    job["stage"], job["progress"] = "review", 1.0
    _save(job)


def recent(limit: int = 10) -> list[dict]:
    jobs = sorted(_jobs.values(), key=lambda j: j["created"], reverse=True)[:limit]
    keys = ("id", "stage", "meeting_type", "meeting_date", "title", "created")
    return [{k: j.get(k) for k in keys} for j in jobs]


def send(job: dict, action_items: list[dict], meeting_type: str | None = None,
         approved_by: str = "", attach_transcript: bool = False, attach_audio: bool = False,
         automatic: bool = False) -> dict:
    """Apply the reviewer's edits (owners, deadlines, distribution list), re-render,
    deliver through n8n. automatic: the uploader chose not to review; sent as drafted."""
    jid = job["id"]
    date = dt.date.fromisoformat(job["meeting_date"])
    with _send_lock:
        if job["stage"] not in (("review", "sending") if automatic else ("review",)):
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
                d = dt.date.fromisoformat(deadline)   # ValueError -> 400
                if not date <= d <= (date + dt.timedelta(days=366)):
                    raise ValueError(f"Termenul {d.strftime('%d.%m.%Y')} trebuie să fie între data ședinței "
                                     f"și un an după ({date.strftime('%d.%m.%Y')} - "
                                     f"{(date + dt.timedelta(days=366)).strftime('%d.%m.%Y')}).")
            item["owner"], item["deadline"] = edit["owner"].strip(), deadline
        if meeting_type:
            job["meeting_type"] = meeting_type   # the reviewer picks who receives it
        job["stage"], job["error"] = "sending", None
        _save(job)

    html = render.render_html(mom, job["meeting_type"], date)
    _write(jid, "mom.json", json.dumps(mom, ensure_ascii=False, indent=1))
    _write(jid, "mom.html", html)
    t = time.time()
    try:
        job["attempts"] = job.get("attempts", 0) + 1
        transcript = recording = None
        if attach_transcript:
            transcript = json.loads((job_dir(jid) / "segments.json").read_text(encoding="utf-8"))
        if attach_audio and job.get("recording"):
            recording = (job_dir(jid) / RECORDING).read_bytes()
        body = delivery.payload(job, mom, approved_by, job["attempts"], transcript, recording,
                                automatic)   # n8n contract v2
        httpx.post(config.N8N_WEBHOOK_URL, json=body, timeout=60).raise_for_status()
    except httpx.HTTPError as e:
        job["stage"], job["error"] = "review", f"Trimiterea nu a reușit: {e}"   # let the user retry
        _save(job)
        raise
    job["timings"]["send_s"] = round(time.time() - t, 1)
    job["sent_with"] = {"recording": recording is not None, "transcript": transcript is not None,
                        "automatic": automatic}
    job["timings"]["review_s"] = round(t - job["review_since"], 1)
    _write(jid, "timings.json", json.dumps(job["timings"], indent=1))
    if not config.KEEP_AUDIO:
        (job_dir(jid) / RECORDING).unlink(missing_ok=True)   # it only existed for this email
        job.pop("recording", None)
    job["stage"] = "done"
    _save(job)
    return job


def _auto_send(job: dict, mom: dict, date: dt.date) -> None:
    """The uploader chose not to review: send the draft as it is, with the recording, marked
    as not reviewed. If delivery fails the meeting waits on the review page instead."""
    try:
        send(job, _drafted(mom, date), attach_audio=True, automatic=True)
    except (ValueError, httpx.HTTPError) as e:
        job["stage"] = "review"
        job["error"] = f"Trimiterea automată nu a reușit ({e}). Verificați și trimiteți manual."
        _save(job)


def _drafted(mom: dict, date: dt.date) -> list[dict]:
    """Owners and deadlines as the LLM drafted them, minus what the review page would refuse:
    voice labels (S1, S2...) as owners, deadlines outside meeting date .. one year after."""
    last = date + dt.timedelta(days=366)
    items = []
    for a in mom.get("action_items", []):
        owner = (a.get("owner") or "").strip()
        deadline = (a.get("deadline") or "").strip()
        try:
            ok = date <= dt.date.fromisoformat(deadline) <= last
        except ValueError:
            ok = False
        items.append({"owner": "" if delivery.VOICE_LABEL.match(owner) else owner,
                      "deadline": deadline if ok else ""})
    return items


def _transcribe(job: dict) -> tuple[list[dict], list[dict]]:
    """-> (segments with speakers, diarization turns). Diarization runs alongside
    ASR; if it fails the meeting still goes out, just without speaker labels."""
    progress = lambda f: job.update(progress=f)
    if config.MOCK_MODELS:
        return mock.transcribe(progress), []
    diarize = bool(config.DIARIZATION_URL)
    if diarize and asr.duration_s(job["audio"]) > config.DIARIZATION_MAX_S:
        diarize = False
        job["warning"] = "recording longer than DIARIZATION_MAX_S: no speaker labels"
    need_audio = diarize or not config.ASR_URL
    audio = asr.load_audio(job["audio"]) if need_audio else None
    turns: list[dict] = []
    with ThreadPoolExecutor(1) as pool:
        diar = pool.submit(nemo_client.diarize, audio) if diarize else None
        if config.ASR_URL:
            segments = asr.transcribe_remote(job["audio"], progress=progress)
        else:
            segments = asr.transcribe(audio, progress=progress)
            asr.unload()   # give the GPU to the LLM
        if diar:
            try:
                turns = diar.result()
            except Exception as e:
                job["warning"] = f"diarization failed: {e}"
    return merge.assign_speakers(segments, turns), turns


def _kbps(seconds: float) -> int | None:
    """Bitrate that keeps the recording under the attachment limit: 24 kbps up to
    ~1 h 20 min, lower for longer meetings, None past ~5 h 30 min."""
    kbps = min(24, int(config.RECORDING_MAX_MB * 8 * 1024 * 1024 * 0.95 / seconds / 1000))
    return kbps if kbps >= 6 else None


def _start_recording(job: dict):
    """Ogg/Opus copy of the recording for the email. Browser recordings (WebM) carry no
    length, so those start at 24 kbps and _finish_recording shrinks them if needed."""
    seconds = asr.duration_s(job["audio"])
    kbps = _kbps(seconds) if seconds else 24
    if not kbps:
        return None
    try:
        return asr.compress(job["audio"], str(job_dir(job["id"]) / RECORDING), kbps)
    except OSError:   # no ffmpeg: the email simply goes out without the recording
        return None


def _finish_recording(job: dict, proc) -> None:
    if not proc:
        return
    _, err = proc.communicate()
    path = job_dir(job["id"]) / RECORDING
    limit = config.RECORDING_MAX_MB * 1024 * 1024
    seconds = 0.0 if proc.returncode else asr.duration_s(str(path))   # an Ogg always knows its length
    if seconds and path.stat().st_size > limit and (kbps := _kbps(seconds)):
        proc = asr.compress(job["audio"], str(path), kbps)   # long browser recording: once more, smaller
        _, err = proc.communicate()
    size = path.stat().st_size if path.exists() else 0
    if proc.returncode or not seconds or not size or size > limit:
        print(f"no recording for the email (ffmpeg {proc.returncode}, {size} bytes): {err.strip()[:300]}")
        path.unlink(missing_ok=True)
        return
    job["recording"] = {"duration_s": round(seconds, 1), "bytes": size}


def _discard_audio(job: dict) -> None:
    """Raw audio and the email copy never outlive a meeting that failed."""
    if not config.KEEP_AUDIO:
        Path(job["audio"]).unlink(missing_ok=True)
        (job_dir(job["id"]) / RECORDING).unlink(missing_ok=True)


def restore() -> None:
    """Load the jobs kept on disk, oldest first. Finished ones come back as they were; ones
    a restart interrupted are queued again while their audio is still there."""
    root = config.DATA_DIR / "jobs"
    for folder in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        path = folder / "job.json"
        try:
            job = json.loads(path.read_text(encoding="utf-8")) if path.exists() else _legacy(folder)
        except (OSError, ValueError, KeyError, IndexError):
            continue
        if not job:
            continue
        if job["stage"] in WORKING:
            if Path(job["audio"]).exists():
                job.update(stage="queued", progress=0.0)
                _queue.put(job["id"])
            else:
                job.update(stage="failed", error="Procesarea a fost întreruptă de o repornire. "
                                                 "Încărcați înregistrarea din nou.")
        elif job["stage"] == "sending":
            job.update(stage="review", error="Trimiterea a fost întreruptă de o repornire. "
                                             "Verificați în Mailpit înainte de a trimite din nou.")
        if job["stage"] not in WORKING and not config.KEEP_AUDIO:
            Path(job["audio"]).unlink(missing_ok=True)   # e.g. left behind by a crash
            if job["stage"] != "review":
                (folder / RECORDING).unlink(missing_ok=True)
        _jobs[job["id"]] = job
        _save(job)


def _legacy(folder: Path) -> dict | None:
    """Meetings processed before job.json existed: rebuild what the pages need from the files."""
    day = folder.name[:8]
    if not day.isdigit() or not (folder / "mom.json").exists():
        return None
    read = lambda name, empty: (json.loads((folder / name).read_text(encoding="utf-8"))
                                if (folder / name).exists() else empty)
    mom, timings, segments = read("mom.json", {}), read("timings.json", {}), read("segments.json", [])
    return {
        "id": folder.name, "meeting_type": mom.get("meeting_type") or "medical",
        "meeting_type_source": "chosen", "auto_send": False,
        "meeting_date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
        "stage": "done" if "send_s" in timings else "review", "progress": 1.0, "error": None,
        "created": folder.stat().st_mtime, "review_since": folder.stat().st_mtime,
        "timings": timings, "audio": str(folder / "audio"),
        "audio_s": round(segments[-1]["end"], 1) if segments else 0.0, "title": mom.get("title") or None,
    }


def _worker() -> None:
    while True:
        job = _jobs[_queue.get()]
        try:
            run(job)
        except Exception as e:  # surface to the UI, keep the worker alive
            traceback.print_exc()
            job["error"] = f"{type(e).__name__}: {e}"
            job["stage"] = "failed"
            _save(job)
            _discard_audio(job)
        finally:
            asr.unload()


def start_worker() -> None:
    threading.Thread(target=_worker, daemon=True, name="mom-worker").start()
