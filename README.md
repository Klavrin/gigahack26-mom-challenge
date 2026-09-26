# On-premise Minutes of Meeting (GigaHack 2026 · Medpark challenge)

Audio of a hospital meeting (Romanian with Russian/English code-switching and medical
vocabulary) → transcript → structured minutes (decisions, action items, owners,
deadlines) → **human review** → emailed to the right distribution list.
**Runs 100% on the hospital LAN — no cloud calls.**

Two roles, like a real hospital: thin clients on staff laptops, one GPU server in the
server room.

```
 LAPTOP (no models)                                   GPU NODE (hospital LAN)
 ┌──────────────────────────────┐   audio  ┌───────────────────────────────┐
 │ Browser: upload / Rec,       │ ───────▶ │ api image as ASR worker       │
 │ review & edit, approve       │ POST     │ faster-whisper: VAD → per-    │
 │ FastAPI api (job queue,      │ /api/asr │ utterance ro/ru/en → prompt   │
 │ render)                      │ ◀─────── ├───────────────────────────────┤
 │ n8n (route by type)          │ ───────▶ │ Ollama · Qwen3 (JSON schema)  │
 │ Mailpit (hospital SMTP)      │ :11434   └───────────────────────────────┘
 └──────────────────────────────┘
```

`MOCK_MODELS=1` (the laptop default) swaps ASR and LLM for canned fixtures, so the web
page, review step and email flow work with no GPU node at all.

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

## Run it

Which machine runs what:

| | Laptop (`docker-compose.yml`) | GPU node (`docker-compose.gpu.yml`) |
|---|---|---|
| Services | api + web page, n8n, Mailpit | Ollama (Qwen3), api image as ASR worker |
| Hardware | any; Docker Desktop | NVIDIA GPU, Docker with NVIDIA runtime |
| Models | none | Whisper + Qwen3 under `./models` |

**Laptop, mock mode** (works alone):

```bash
cp .env.example .env              # MOCK_MODELS=1
docker compose up -d --build
```

- Web app: http://localhost:8000 (header dots show which node does ASR / LLM / n8n)
- Inbox (Mailpit): http://localhost:8025
- n8n editor: http://localhost:5678 (workflow *MoM routing & delivery* is imported and active)

**GPU node** (teammate's machine, same repo checkout):

```bash
cp .env.example .env              # set LLM_MODEL to the Qwen3 tag you use
docker compose -f docker-compose.gpu.yml up -d --build
sh scripts/pull-models.sh         # once, online: Qwen3 + Whisper weights → ./models
```

Then allow ports **8000** (ASR worker) and **11434** (Ollama) from the laptop's IP only:

```powershell
# Windows GPU node (admin PowerShell)
New-NetFirewallRule -DisplayName "MoM GPU node" -Direction Inbound -Protocol TCP -LocalPort 8000,11434 -RemoteAddress <LAPTOP_IP> -Action Allow
```

```bash
# Linux GPU node — Docker-published ports bypass ufw, so filter in DOCKER-USER
sudo iptables -I DOCKER-USER -p tcp -m multiport --dports 8000,11434 ! -s <LAPTOP_IP> -j DROP
```

**Connect the laptop to the GPU node:**

```bash
sh scripts/smoke-gpu-node.sh <GPU_NODE_IP> data/<some-recording>.ogg
# then in .env: MOCK_MODELS=0, ASR_URL=http://<GPU_NODE_IP>:8000, OLLAMA_URL=http://<GPU_NODE_IP>:11434
docker compose up -d
```

**Offline demo:** set `OFFLINE=1` on the GPU node, keep both machines on the same
switch/hotspot with no internet uplink, upload.

## Review before sending

Processing stops at a **draft**. The page shows decisions (with the quote that supports
each), the action items with editable owner and deadline (empty ones highlighted, the
spoken deadline shown next to the resolved date) and the transcript with colour-coded
ro/ru/en tags. Nothing is emailed until someone clicks *Approve & email*
(`POST /api/jobs/{id}/send`). The model's original draft is kept as `mom_draft.json`.

## Privacy / security

- No cloud calls anywhere: ASR, LLM, workflow engine and SMTP run on two machines on the hospital LAN.
- n8n telemetry, version checks and template gallery are disabled.
- On the laptop, n8n and SMTP bind to `127.0.0.1`; only the web app and inbox are exposed.
- On the GPU node, 8000 and 11434 are open to the LAN — firewall them to the laptop's IP (above).
  Traffic between the two is plain HTTP inside the LAN.
- Raw audio is deleted right after transcription on both machines (`KEEP_AUDIO=0`); audio/transcripts are git-ignored.
- With `OFFLINE=1` model files are loaded from disk only.

## Evaluation

```bash
# on the GPU node
docker compose -f docker-compose.gpu.yml exec asr python -m app.cli transcribe /data/dev.wav --mode plain   --out /data/out/plain.txt
docker compose -f docker-compose.gpu.yml exec asr python -m app.cli transcribe /data/dev.wav --mode segment --out /data/out/segment.txt
docker compose -f docker-compose.gpu.yml exec asr python eval/wer.py /data/refs/dev.txt /data/out/plain.txt /data/out/segment.txt
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
api/app/asr.py        hybrid ASR (VAD, per-utterance language ID, prompts, hallucination
                      filter); transcribe_remote() calls the GPU node's /api/asr
api/app/llm.py        Ollama calls: glossary correction, MoM extraction (JSON schema, map-reduce)
api/app/mock.py       MOCK_MODELS=1 stand-ins, served from api/fixtures/ (invented names)
api/app/render.py     email-safe HTML minutes
api/app/pipeline.py   job queue: transcribe → correct → extract → review → send to n8n
api/app/main.py       HTTP API, incl. /api/asr (ASR worker) and /api/health (node status)
api/app/cli.py        transcribe / mom / download from the command line
api/static/index.html upload + Rec, progress, review/edit, approve
n8n/                  routing workflow + SMTP credential (auto-imported)
glossary/             Whisper prompts per language, medical term list
eval/wer.py           WER/CER + most frequent substitutions
scripts/              pull-models.sh (GPU node), smoke-gpu-node.sh (laptop → GPU node)
```

## API

| Endpoint | |
|---|---|
| `POST /api/jobs` | multipart `file`, `meeting_type`, `meeting_date` → job |
| `GET /api/jobs/{id}` | stage (`queued` → `transcribing` → `extracting` → `review` → `sending` → `done`/`failed`), progress, timings |
| `GET /api/jobs/{id}/mom.json`, `segments.json`, `mom.html`, `transcript.txt` | results |
| `POST /api/jobs/{id}/send` | `{"action_items": [{"owner", "deadline"}, …]}` (one per item, in order) → emails via n8n |
| `POST /api/asr` | ASR worker: multipart `file`, `mode` → segment list |
| `GET /api/health` | status + location of ASR, LLM and n8n |

## Configuration (`.env`)

| Variable | Default | |
|---|---|---|
| `MOCK_MODELS` | `1` on the laptop | canned fixtures instead of ASR/LLM calls |
| `ASR_URL` | empty | GPU node ASR worker, e.g. `http://192.168.1.50:8000`; empty = transcribe locally |
| `OLLAMA_URL` | `http://localhost:11434` | GPU node Ollama, e.g. `http://192.168.1.50:11434` |
| `LLM_MODEL` | `qwen3:8b` | any Ollama model; called with `think: false` |
| `WHISPER_MODEL` | `large-v3-turbo` | GPU node |
| `ASR_MODE` | `segment` | `plain` = baseline |
| `CORRECT_TRANSCRIPT` | `0` | LLM glossary correction pass |
| `KEEP_AUDIO` | `0` | keep uploaded audio after transcription |
| `OFFLINE` | `0` | `1` = never download models (GPU node) |
