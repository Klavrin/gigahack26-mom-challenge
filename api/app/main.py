import datetime as dt
import shutil
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config, pipeline

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


@app.get("/api/jobs/{job_id}/mom.html", response_class=HTMLResponse)
def job_mom(job_id: str):
    return _job_file(job_id, "mom.html").read_text(encoding="utf-8")


@app.get("/api/jobs/{job_id}/transcript.txt", response_class=PlainTextResponse)
def job_transcript(job_id: str):
    return _job_file(job_id, "transcript.txt").read_text(encoding="utf-8")


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
