import datetime as dt
import shutil
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import asr, config, mock, nemo_client, pipeline

app = FastAPI(title="MoM - on-premise meeting minutes")
STATIC = config.STATIC_DIR


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


@app.get("/api/jobs")
def recent_jobs():
    return pipeline.recent()


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
    meeting_type: str | None = None   # distribution list, chosen at review time
    approved_by: str = ""             # reviewer name for the approval record


@app.post("/api/jobs/{job_id}/send")
def job_send(job_id: str, body: SendRequest):
    job = pipeline.get(job_id)
    if not job:
        raise HTTPException(404)
    try:
        return pipeline.send(job, [a.model_dump() for a in body.action_items], body.meeting_type,
                             body.approved_by)
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


_asr_progress: dict[str, float] = {}   # progress_id -> 0..1, only while a request runs


@app.post("/api/asr")
def asr_worker(file: UploadFile = File(...), mode: str = Form(""), progress_id: str = Form("")):
    """ASR worker: the GPU node serves this, laptops reach it through ASR_URL."""
    if mode and mode not in ("segment", "plain"):
        raise HTTPException(400, "mode must be segment or plain")
    pid = progress_id[:64]
    report = (lambda f: _asr_progress.__setitem__(pid, round(f, 3))) if pid else (lambda f: None)
    try:
        if config.MOCK_MODELS:
            return mock.transcribe(report)
        with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as tmp:
            path = Path(tmp) / ("audio" + (Path(file.filename or "").suffix or ".webm"))
            with path.open("wb") as f:
                shutil.copyfileobj(file.file, f)
            try:
                return asr.transcribe(str(path), mode=mode or None, progress=report)
            finally:
                asr.unload()   # the LLM may share this GPU
    finally:
        _asr_progress.pop(pid, None)


@app.get("/api/asr/progress/{progress_id}")
def asr_progress(progress_id: str):
    """Polled by the laptop while /api/asr runs (FastAPI serves it from another thread)."""
    return {"progress": _asr_progress.get(progress_id, 0.0)}


@app.get("/api/asr/health")
def asr_health():
    return {"ok": True, "mock": config.MOCK_MODELS, "model": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE, "compute_type": config.WHISPER_COMPUTE_TYPE,
            "mode": config.ASR_MODE}


def _get(url: str) -> httpx.Response | None:
    try:
        return httpx.get(url, timeout=3)
    except httpx.HTTPError:
        return None


def _llm_status() -> dict:
    node = {"where": config.OLLAMA_URL, "model": config.LLM_MODEL}
    if config.MOCK_MODELS:
        return {**node, "status": "mock"}
    r = _get(f"{config.OLLAMA_URL}/api/tags")
    if not r or r.status_code != 200:
        return {**node, "status": "down", "detail": "Ollama unreachable"}
    names = {m["name"] for m in r.json().get("models", [])}
    if config.LLM_MODEL not in names and f"{config.LLM_MODEL}:latest" not in names:
        return {**node, "status": "down", "detail": f"{config.LLM_MODEL} not pulled"}
    return {**node, "status": "up"}


def _asr_status() -> dict:
    if config.MOCK_MODELS:
        return {"where": "fixtures", "model": config.WHISPER_MODEL, "status": "mock"}
    if not config.ASR_URL:
        return {"where": "local", "model": config.WHISPER_MODEL,
                "device": config.WHISPER_DEVICE, "status": "up"}
    r = _get(f"{config.ASR_URL}/api/asr/health")
    if not r or r.status_code != 200:
        return {"where": config.ASR_URL, "model": config.WHISPER_MODEL, "status": "down",
                "detail": "ASR worker unreachable"}
    info = r.json()
    return {"where": config.ASR_URL, "model": info.get("model"), "device": info.get("device"),
            "status": "mock" if info.get("mock") else "up"}


@app.get("/api/health")
def health():
    """Which node does what, and is it reachable. Shown in the web page header."""
    n8n_base = config.N8N_WEBHOOK_URL.split("/webhook")[0]
    r = _get(f"{n8n_base}/healthz")
    nodes = {
        "asr": _asr_status(),
        "llm": _llm_status(),
        "n8n": {"where": n8n_base, "status": "up" if r and r.status_code == 200 else "down"},
    }
    if config.ASR_BACKEND == "nemotron" and not config.MOCK_MODELS:
        up = nemo_client.health(config.NEMOTRON_URL)
        nodes["asr"] = {"where": config.NEMOTRON_URL, "model": "nemotron-3.5-asr",
                        "status": "up" if up else "down"}
    if config.DIARIZATION_URL and not config.MOCK_MODELS:
        up = nemo_client.health(config.DIARIZATION_URL)
        nodes["diarization"] = {"where": config.DIARIZATION_URL, "model": "sortformer-4spk",
                                "status": "up" if up else "down"}
    return {"ok": all(n["status"] != "down" for n in nodes.values()),
            "mock": config.MOCK_MODELS, "asr_mode": config.ASR_MODE, "nodes": nodes}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
