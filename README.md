# On-premise Minutes of Meeting (GigaHack 2026 · Medpark challenge)

Audio of a hospital meeting (Romanian with Russian/English code-switching and medical
vocabulary) → transcript → structured minutes (decisions, action items, owners,
deadlines) → emailed to the right distribution list. **Runs 100% offline on one machine.**

```
 Browser (upload / Rec)                              all containers on one host, no egress
        │
        ▼
 ┌─────────────┐   ┌──────────────────────────┐   ┌──────────────┐   ┌────────┐   ┌─────────┐
 │ FastAPI api │──▶│ faster-whisper (GPU)     │──▶│ Ollama LLM   │──▶│  n8n   │──▶│ Mailpit │
 │ + web page  │   │ VAD → per-utterance lang │   │ JSON-schema  │   │ Switch │   │ (SMTP)  │
 └─────────────┘   │ ID (ro/ru/en) → prompt   │   │ MoM extract  │   │ by type│   └─────────┘
                   └──────────────────────────┘   └──────────────┘   └────────┘
```

## Why this handles code-switching

Stock Whisper picks **one language per 30 s window**, so Russian inside a Romanian
meeting gets translated or garbled. We:

1. split audio at pauses with **Silero VAD** into utterance-sized chunks (≤20 s),
2. detect the language **per chunk**, restricted to `ro/ru/en` (short or low-confidence chunks keep the running language),
3. transcribe each chunk with that language forced, a **medical glossary prompt** in that language,
   `condition_on_previous_text=False` (no repetition loops) and a filter for known
   Whisper hallucinations ("Subtitrare…", "Продолжение следует").
4. optional: a local-LLM **glossary correction pass** that fixes only medical-term spelling and
   rejects any line it rewrote too much (`CORRECT_TRANSCRIPT=1`).

`ASR_MODE=plain` runs stock Whisper so we can measure the difference (see *Evaluation*).

## ASR backends & speaker diarization

Both recognisers get the **same VAD chunks**, so WER comparisons are like for like.

| `.env` | What runs |
|---|---|
| `ASR_BACKEND=whisper` (default) | faster-whisper `large-v3-turbo` inside `api` |
| `ASR_BACKEND=nemotron` | [Nemotron 3.5 ASR](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) in the local `nemo` container (auto language per chunk, retried in ro/ru/en if it guesses another locale) |
| `DIARIZATION_URL=http://nemo:8001` | [Streaming Sortformer](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1) speaker turns (max 4 speakers), merged onto the transcript by time overlap |

```bash
docker compose --profile nemo up -d --build     # adds the nemo container
docker compose exec api python -m app.cli transcribe /data/dev.wav --backend nemotron --out /data/out/nemotron.txt
```

If diarization fails the minutes are still sent, just without speaker labels.
Interfaces between services: [docs/contracts.md](docs/contracts.md).

## Run it

Requirements: Docker Desktop (WSL2 backend) with an NVIDIA GPU (8 GB is enough).

```bash
cp .env.example .env
docker compose up -d --build
sh scripts/pull-models.sh        # once, online: LLM + Whisper weights → ./models
```

- Web app: http://localhost:8000
- Inbox (Mailpit): http://localhost:8025
- n8n editor: http://localhost:5678 (workflow *MoM routing & delivery* is imported and active)

**Offline demo (sealed mode):** every compute container is put on a Docker network with
no route to the internet; only an nginx gateway (config only, no code) publishes ports.

```bash
docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d
sh scripts/egress-check.sh   # every container must print BLOCKED
sh scripts/gpu-check.sh      # Whisper, Ollama (and NeMo) must be on the GPU
```

Then turn Wi-Fi off (and quit Tailscale) and run a meeting end to end.

## Privacy / security

- No cloud calls anywhere: ASR, LLM, workflow engine and SMTP are local containers.
- n8n telemetry, version checks and template gallery are disabled.
- Internal tools (Ollama, n8n, SMTP) bind to `127.0.0.1`; only the web app and inbox are exposed.
- Raw audio is deleted right after transcription (`KEEP_AUDIO=0`); audio/transcripts are git-ignored.
- With `OFFLINE=1` model files are loaded from disk only.

## Evaluation

```bash
# inside the api container
docker compose exec api python -m app.cli transcribe /data/dev.wav --mode plain   --out /data/out/plain.txt
docker compose exec api python -m app.cli transcribe /data/dev.wav --mode segment --out /data/out/segment.txt
docker compose exec api python eval/wer.py /data/refs/dev.txt /data/out/plain.txt /data/out/segment.txt
```

The 11-min sample is split: **0–6 min = dev** (tune on it), **6–11 min = held-out test**
(only measured at the end). Cut with
`ffmpeg -i sample.mp3 -t 360 dev.wav` / `ffmpeg -i sample.mp3 -ss 360 test.wav`.

| Setup | WER dev | WER test | CER test |
|---|---|---|---|
| Whisper large-v3-turbo, plain | – | – | – |
| + VAD / per-utterance language | – | – | – |
| + glossary prompt | – | – | – |
| + LLM correction | – | – | – |

**Speed** (60-min recording, `scripts/make-60min.sh`), RTX 5060 Laptop 8 GB:

| Stage | Time |
|---|---|
| ASR | – |
| LLM extraction | – |
| n8n + email | – |
| **Upload → email** | – |

## Layout

```
api/app/asr.py        hybrid ASR (VAD, per-utterance language ID, prompts, hallucination filter)
api/app/llm.py        Ollama calls: glossary correction, MoM extraction (JSON schema, map-reduce)
api/app/render.py     email-safe HTML minutes
api/app/pipeline.py   job queue: transcribe → correct → extract → n8n
api/app/cli.py        transcribe / mom / download from the command line
api/static/index.html upload + Rec web page
n8n/                  routing workflow + SMTP credential (auto-imported)
glossary/             Whisper prompts per language, medical term list
eval/wer.py           WER/CER + most frequent substitutions
```

## Configuration (`.env`)

| Variable | Default | |
|---|---|---|
| `LLM_MODEL` | `qwen2.5:7b-instruct` | any Ollama model; 7–8B Q4 fits 8 GB |
| `WHISPER_MODEL` | `large-v3-turbo` | |
| `ASR_MODE` | `segment` | `plain` = baseline |
| `CORRECT_TRANSCRIPT` | `0` | LLM glossary correction pass |
| `KEEP_AUDIO` | `0` | keep uploaded audio after transcription |
| `OFFLINE` | `0` | `1` = never download models |
