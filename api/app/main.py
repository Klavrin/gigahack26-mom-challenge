import datetime as dt
import shutil
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import asr, config, mock, pipeline

app = FastAPI(title="MoM - on-premise meeting minutes")
STATIC = Path(__file__).resolve().parent.parent / "static"


@app.on_event("startup")
def _startup() -> None:
    (config.DATA_DIR / "jobs").mkdir(parents=True, exist_ok=True)
    pipeline.start_worker()


@app.post("/api/jobs")
def create_job(
    file: UploadFile = File(...),
    meeting_type: str = Form(...),
    meeting_date: str = Form(""),
):
    if meeting_type not in config.MEETING_TYPES:
        raise HTTPException(400, f"meeting_type must be one of {config.MEETING_TYPES}")
    date = dt.date.fromisoformat(meeting_date) if meeting_date else dt.date.today()
    job_id = pipeline.new_job_id()
    folder = pipeline.job_dir(job_id)
    folder.mkdir(parents=True)
    suffix = Path(file.filename or "audio").suffix or ".webm"
    audio_path = folder / f"audio{suffix}"
    with audio_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return pipeline.submit(audio_path, meeting_type, date, job_id)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = pipeline.get(job_id)
    if not job:
        raise HTTPException(404)
    return job


def _job_file(job_id: str, name: str) -> Path:
    path = pipeline.job_dir(job_id) / name
    if not pipeline.get(job_id) or not path.exists():
        raise HTTPException(404)
    return path


class ActionItemEdit(BaseModel):
    owner: str = ""
    deadline: str = ""   # YYYY-MM-DD or ""


class SendRequest(BaseModel):
    action_items: list[ActionItemEdit] = []


@app.post("/api/jobs/{job_id}/send")
def job_send(job_id: str, body: SendRequest):
    job = pipeline.get(job_id)
    if not job:
        raise HTTPException(404)
    try:
        return pipeline.send(job, [a.model_dump() for a in body.action_items])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"n8n delivery failed: {e}")


@app.get("/api/jobs/{job_id}/mom.json")
def job_mom_json(job_id: str):
    return FileResponse(_job_file(job_id, "mom.json"), media_type="application/json")


@app.get("/api/jobs/{job_id}/segments.json")
def job_segments(job_id: str):
    return FileResponse(_job_file(job_id, "segments.json"), media_type="application/json")


@app.get("/api/jobs/{job_id}/mom.html", response_class=HTMLResponse)
def job_mom(job_id: str):
    return _job_file(job_id, "mom.html").read_text(encoding="utf-8")


@app.get("/api/jobs/{job_id}/transcript.txt", response_class=PlainTextResponse)
def job_transcript(job_id: str):
    return _job_file(job_id, "transcript.txt").read_text(encoding="utf-8")


@app.post("/api/asr")
def asr_worker(file: UploadFile = File(...), mode: str = Form("")):
    """ASR worker: the GPU node serves this, laptops reach it through ASR_URL."""
    if mode and mode not in ("segment", "plain"):
        raise HTTPException(400, "mode must be segment or plain")
    if config.MOCK_MODELS:
        return mock.transcribe(lambda f: None)
    with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as tmp:
        path = Path(tmp) / ("audio" + (Path(file.filename or "").suffix or ".webm"))
        with path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            return asr.transcribe(str(path), mode=mode or None)
        finally:
            asr.unload()   # the LLM may share this GPU


@app.get("/api/asr/health")
def asr_health():
    return {"ok": True, "mock": config.MOCK_MODELS, "model": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE, "compute_type": config.WHISPER_COMPUTE_TYPE,
            "mode": config.ASR_MODE}


@app.get("/api/health")
def health():
    checks = {}
    for name, url in (("ollama", f"{config.OLLAMA_URL}/api/tags"),
                      ("n8n", config.N8N_WEBHOOK_URL.split("/webhook")[0] + "/healthz")):
        try:
            checks[name] = httpx.get(url, timeout=3).status_code == 200
        except httpx.HTTPError:
            checks[name] = False
    return {"ok": all(checks.values()), **checks, "llm": config.LLM_MODEL,
            "asr": config.WHISPER_MODEL, "asr_mode": config.ASR_MODE}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
