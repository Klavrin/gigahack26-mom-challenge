"""Local speech service: Nemotron 3.5 ASR + Streaming Sortformer diarization.

Contract: docs/contracts.md
  GET  /health
  POST /transcribe   multipart file=<16 kHz mono wav>, language=auto|ro-RO|ru-RU|en-US
                     -> {"text": "...", "language": "ro"}
  POST /diarize      multipart file=<16 kHz mono wav>
                     -> {"segments": [{"start": 1.2, "end": 4.8, "speaker": "S1"}, ...]}

NEMO_LOAD=asr,diar picks which models this instance loads, so the two can run on
separate machines during development and together on one box for the demo.
Set HF_HUB_OFFLINE=1 once the weights are cached: models then load from disk only.
"""
import os
import re
import tempfile
import threading

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

ASR_MODEL = os.environ.get("NEMOTRON_MODEL", "nvidia/nemotron-3.5-asr-streaming-0.6b")
DIAR_MODEL = os.environ.get("DIAR_MODEL", "nvidia/diar_streaming_sortformer_4spk-v2.1")
LOAD = {x.strip() for x in os.environ.get("NEMO_LOAD", "asr,diar").split(",") if x.strip()}
SR = 16000
LANG_TAG = re.compile(r"<([a-z]{2})-[A-Z]{2}>")
SPECIAL = re.compile(r"<[^>]*>")

app = FastAPI(title="nemo-server")
_asr = _processor = _diar = None
_gpu = threading.Lock()   # one request on the GPU at a time


@app.on_event("startup")
def _load() -> None:
    global _asr, _processor, _diar
    if "asr" in LOAD:
        from transformers import AutoModelForRNNT, AutoProcessor
        _processor = AutoProcessor.from_pretrained(ASR_MODEL)
        _asr = AutoModelForRNNT.from_pretrained(ASR_MODEL)
        _asr = (_asr.cuda() if torch.cuda.is_available() else _asr).eval()
    if "diar" in LOAD:
        from nemo.collections.asr.models import SortformerEncLabelModel
        _diar = SortformerEncLabelModel.from_pretrained(DIAR_MODEL)
        _diar.eval()
        if torch.cuda.is_available():
            _diar = _diar.cuda()


def _read_wav(upload: UploadFile) -> np.ndarray:
    audio, sr = sf.read(upload.file, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if sr != SR:
        raise HTTPException(400, f"expected {SR} Hz mono wav, got {sr} Hz")
    return audio


@app.get("/health")
def health():
    return {"status": "ok", "asr": _asr is not None, "diar": _diar is not None,
            "cuda": torch.cuda.is_available()}


@app.post("/transcribe")
def transcribe(file: UploadFile = File(...), language: str = Form("auto")):
    if _asr is None:
        raise HTTPException(503, "ASR not loaded on this instance (NEMO_LOAD)")
    audio = _read_wav(file)
    with _gpu, torch.inference_mode():
        inputs = _processor(audio, sampling_rate=SR, language=language)
        inputs.to(_asr.device, dtype=_asr.dtype)
        out = _asr.generate(**inputs, return_dict_in_generate=True)
        raw = _processor.decode(out.sequences[0], skip_special_tokens=False)
    tags = LANG_TAG.findall(raw)
    detected = tags[-1] if tags else (language.split("-")[0] if language != "auto" else "")
    text = SPECIAL.sub("", raw).strip()
    return {"text": text, "language": detected}


def _parse_segment(line) -> tuple[float, float, str]:
    start, end, spk = str(line).split()[:3]
    idx = int(re.sub(r"\D", "", spk) or 0)
    return float(start), float(end), f"S{idx + 1}"


@app.post("/diarize")
def diarize(file: UploadFile = File(...)):
    if _diar is None:
        raise HTTPException(503, "diarization not loaded on this instance (NEMO_LOAD)")
    audio = _read_wav(file)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, audio, SR)
    try:
        with _gpu, torch.inference_mode():
            result = _diar.diarize(audio=tmp.name, batch_size=1)
    finally:
        os.unlink(tmp.name)
    lines = result[0] if result and isinstance(result[0], (list, tuple)) else result
    segments = []
    for line in lines:
        start, end, speaker = _parse_segment(line)
        segments.append({"start": round(start, 2), "end": round(end, 2), "speaker": speaker})
    return {"segments": sorted(segments, key=lambda s: s["start"])}
