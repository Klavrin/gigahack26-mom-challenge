# On-Premise Minutes of Meeting

> GigaHack 2026 · Medpark challenge

Turn a hospital meeting recording into a multilingual transcript and structured minutes
with decisions, action items, owners, and deadlines—then review and deliver the result by
email. The runtime can stay entirely inside the hospital network: no cloud transcription,
cloud LLM, or external workflow service is required.

The solution is designed for Romanian meetings that may switch into Russian or English and
contain medical vocabulary. It combines a React web interface, FastAPI processing pipeline,
local speech recognition, a local LLM, n8n routing, and SMTP delivery.

## What is included

- Browser recording and drag-and-drop upload
- Romanian/Russian/English speech recognition with timestamps
- Optional speaker diarization for up to four speakers
- Structured minutes: summary, topics, decisions, tasks, owners, and deadlines
- Evidence quotes linked back to the corresponding transcript position
- Automatic delivery or an optional human review and approval step
- DOCX generation, optional transcript annex, and optional compressed recording attachment
- Medical, executive, and administrative distribution routes
- Persistent job history and recovery after service restarts
- Mock mode for a complete demo without a GPU or model downloads
- Sealed offline mode with a test that verifies compute containers cannot reach the internet

## Important status and safety note

This repository is a hackathon prototype, not a certified medical device or a production
hospital deployment. Generated transcripts and minutes can contain errors and should be
reviewed before they are used for clinical, legal, or operational decisions.

The web application and webhook do not currently provide user authentication. Keep them on
a trusted, access-controlled network and do not expose their ports to the public internet.
Mailpit is a local email catcher used for the demo; replace it and review the security model
before integrating a real hospital mail system.

## Architecture at a glance

```text
Doctor / secretary
        │ record, upload, review
        ▼
FastAPI + React (:8000)
        ├── audio ──────► Whisper ASR on GPU (:8000)
        ├── transcript ─► Ollama / Qwen on GPU (:11434)
        ├── audio ──────► optional NeMo diarization (:8001 in-container)
        └── approved snapshot + DOCX ─► n8n (:5678) ─► SMTP / Mailpit (:8025)
```

The laptop stack contains the web app, API, job queue, n8n, and Mailpit. The GPU stack
contains Whisper, Ollama, and optional NVIDIA NeMo services. Both stacks may run on one GPU
computer or on two machines connected through a private LAN.

For detailed diagrams and service flows, see [docs/architecture.md](docs/architecture.md).

## Quick start: demo without a GPU

This is the recommended first run. Mock mode exercises upload, progress, review, routing,
DOCX creation, and email delivery using canned transcript and minutes data. It does **not**
transcribe the uploaded audio.

### Requirements

- Git
- Docker Desktop, or Docker Engine with the Compose plugin

### 1. Create the local configuration

macOS, Linux, or Git Bash:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Leave `MOCK_MODELS=1` for this first run. Placeholder GPU URLs in `.env` are ignored in
mock mode.

### 2. Start the laptop stack

```bash
docker compose up -d --build
```

The first startup imports and activates the n8n workflow and its demo SMTP credential.

### 3. Open the application

| Service | URL | Purpose |
|---|---|---|
| Web application | http://localhost:8000 | Upload, record, monitor, review, and send |
| Mailpit | http://localhost:8025 | Inspect locally delivered demo email |
| n8n | http://localhost:5678 | Inspect workflow executions and routing |
| Health endpoint | http://localhost:8000/api/health | Check ASR, LLM, and n8n status |

### 4. Try one meeting

1. Open the web application.
2. For a first test, enable **“Verific procesul-verbal înainte de trimitere”** so the job
   waits for review. If it is left disabled, delivery is automatic.
3. Drop an audio/video file onto the page or use **Record**.
4. Follow the progress through transcription and minutes generation.
5. Review decisions and tasks. Edit owners or deadlines if needed.
6. Enter the reviewer name, choose optional attachments, and select
   **Aprobați și trimiteți**.
7. Open Mailpit and inspect the message and DOCX attachment.

The page can be closed while a job runs. Completed and interrupted jobs are restored from
`data/jobs/` and appear under **Recente** after a restart.

## Delivery behavior

There are two supported paths:

| Mode | How to select it | Result |
|---|---|---|
| Automatic | Leave the review checkbox disabled | Minutes are sent when processing finishes and marked as not human-reviewed. |
| Human review | Enable the review checkbox before upload | Processing stops at a draft until a reviewer edits, approves, and sends it. |

If no meeting type is selected, the LLM infers `medical`, `executive`, or
`administrative` from the content. The selected type controls the n8n distribution route.
The local demo uses synthetic `@medpark.local` recipients defined in the workflow.

## Real local-AI deployment

### Hardware and software

- Laptop/coordinator: any machine capable of running the laptop Docker stack
- GPU node: NVIDIA GPU, NVIDIA driver, Docker, and NVIDIA Container Toolkit
- Private LAN connection between the two machines
- Approximately 10 GB or more of free space for model weights, depending on enabled models

The current defaults are Whisper `large-v3` and Ollama model `qwen3:8b`. Model names and
measured demo configurations may differ; the value in `.env` must match the model actually
downloaded into Ollama.

### A. Start the GPU node

Clone this repository on the GPU machine and create `.env`. Keep `OFFLINE=1`; the download
script temporarily enables network access only for model acquisition.

```bash
docker compose -f docker-compose.gpu.yml up -d --build
sh scripts/pull-models.sh
```

The helper scripts require a POSIX shell. On Windows, run them from Git Bash or WSL.

The GPU stack exposes:

- `8000`: FastAPI ASR worker
- `11434`: Ollama
- `8002`: optional NeMo service when the `nemo` profile is enabled

Restrict these ports to the coordinator's IP. For example, on the Windows GPU node, run in
an elevated PowerShell:

```powershell
New-NetFirewallRule -DisplayName "MoM GPU node" -Direction Inbound -Protocol TCP `
  -LocalPort 8000,11434 -RemoteAddress <LAPTOP_IP> -Action Allow
```

### B. Verify the GPU node from the laptop

From Git Bash, WSL, macOS, or Linux:

```bash
sh scripts/smoke-gpu-node.sh <GPU_NODE_IP> data/<recording>.ogg
```

The audio argument is optional. Without it, the script still verifies the ASR health route,
the installed Ollama models, and a small JSON LLM response.

### C. Point the laptop stack at the GPU node

Edit the laptop's `.env`:

```dotenv
MOCK_MODELS=0
ASR_URL=http://<GPU_NODE_IP>:8000
OLLAMA_URL=http://<GPU_NODE_IP>:11434
LLM_MODEL=qwen3:8b
```

Then recreate the laptop services:

```bash
docker compose up -d --build
```

Open `/api/health` or the settings panel. ASR, LLM, and n8n should all report `up` before
processing real recordings.

## One-computer GPU demo

Both Compose stacks can run as one project on a single NVIDIA GPU computer. In `.env`, set:

```dotenv
COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml
COMPOSE_PATH_SEPARATOR=:
MOCK_MODELS=0
ASR_URL=http://asr:8000
OLLAMA_URL=http://ollama:11434
ASR_PORT=8001
LLM_MODEL=qwen3:8b
```

Start, download models once, and verify GPU access:

```bash
docker compose up -d --build
sh scripts/pull-models.sh
sh scripts/gpu-check.sh
```

For the exact configuration used by the live demonstration, including optional speaker
diarization, follow [docs/demo-runbook.md](docs/demo-runbook.md).

## Optional NeMo services

The `nemo` Compose profile provides:

- NVIDIA Nemotron 3.5 ASR as an alternative backend
- Streaming Sortformer speaker diarization with up to four speaker labels

Enable the profile and configure the relevant URLs:

```dotenv
COMPOSE_PROFILES=nemo
DIARIZATION_URL=http://nemo:8001
NEMO_LOAD=diar
```

For Nemotron ASR, also set:

```dotenv
ASR_BACKEND=nemotron
NEMOTRON_URL=http://nemo:8001
NEMO_LOAD=asr,diar
```

On a split deployment, use the GPU node's reachable address and published NeMo port
instead of the internal hostname. See [docs/contracts.md](docs/contracts.md) for request and
response formats.

## Sealed offline mode

Download all models before enabling sealed mode. The offline overlay places the API, ASR,
LLM, NeMo, n8n, and Mailpit containers on an internal Docker network with no internet route.
An nginx gateway exposes only the local browser interfaces.

For the one-computer stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml \
  -f docker-compose.offline.yml --profile nemo up -d
sh scripts/egress-check.sh
```

Every running compute/data service printed by `egress-check.sh` should report `BLOCKED`.
The gateway is intentionally excluded because it is the LAN entry point.

## Configuration reference

Values below are the Compose defaults unless noted otherwise.

| Variable | Default | Meaning |
|---|---:|---|
| `MOCK_MODELS` | `1` | Use canned ASR and minutes; no model calls |
| `ASR_URL` | empty | Remote ASR worker base URL; empty uses ASR in the API process |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API base URL |
| `LLM_MODEL` | `qwen3:8b` | Ollama model tag used for minutes extraction |
| `LLM_NUM_CTX` | `16384` | LLM context size |
| `ASR_MODE` | `longform` | `longform`, `segment`, or `plain` |
| `ASR_BACKEND` | `whisper` | `whisper` or `nemotron` |
| `WHISPER_MODEL` | `large-v3` | faster-whisper model cached under `models/whisper` |
| `WHISPER_COMPUTE_TYPE` | `float16` | GPU inference precision |
| `DIARIZATION_URL` | empty | NeMo diarization endpoint; empty disables diarization |
| `CORRECT_TRANSCRIPT` | `0` | Run an additional LLM glossary-correction pass |
| `KEEP_AUDIO` | `0` | Retain source audio after transcription |
| `OFFLINE` | `1` | Load model files from disk without runtime downloads |
| `MAX_UPLOAD_MB` | `2048` | Maximum accepted upload size |
| `APP_BIND_ADDRESS` | `127.0.0.1` | Web app bind address; `0.0.0.0` opens it to the LAN |
| `N8N_BIND_ADDRESS` | `127.0.0.1` | n8n editor bind address |
| `MAILPIT_BIND_ADDRESS` | `127.0.0.1` | Mailpit web interface bind address |
| `N8N_WEBHOOK_URL` | `http://n8n:5678/webhook/mom` | Delivery webhook used inside the laptop Compose network |
| `N8N_ENCRYPTION_KEY` | demo value | Key protecting n8n credentials; replace before first non-demo startup and never rotate it without migrating data |

Additional ASR tuning variables are documented directly in
[`api/app/config.py`](api/app/config.py). Each machine may use its own `.env`.

## Data lifecycle and privacy

| Data | Location | Default behavior |
|---|---|---|
| Uploaded recording | `data/jobs/<id>/audio.*` | Deleted after transcription when `KEEP_AUDIO=0` |
| Compressed email recording | `data/jobs/<id>/recording.ogg` | Optional attachment; deleted after successful delivery |
| Transcript and segments | `data/jobs/<id>/` | Retained locally; not emailed unless the reviewer requests a transcript annex |
| Draft minutes | `data/jobs/<id>/mom_draft.json` | Retained as the original model result |
| Final minutes | `data/jobs/<id>/mom.json` and `mom.html` | Retained locally |
| Model weights | `models/` | Downloaded once and loaded locally |
| n8n state | Docker volume `n8n_data` | Includes credentials and execution history; executions are configured for 24-hour pruning |

Recordings without an audio track and uploads larger than the configured limit are rejected.
If processing fails, source audio is removed unless retention was explicitly enabled.

## API summary

Interactive OpenAPI documentation is available at http://localhost:8000/docs while the API
is running.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/jobs` | Upload a recording and create a processing job |
| `GET` | `/api/jobs` | List recent jobs |
| `GET` | `/api/jobs/{id}` | Read job status and progress |
| `POST` | `/api/jobs/{id}/send` | Apply review edits, approve, and deliver |
| `GET` | `/api/jobs/{id}/mom.json` | Download structured minutes |
| `GET` | `/api/jobs/{id}/segments.json` | Download timestamped transcript segments |
| `GET` | `/api/jobs/{id}/transcript.txt` | Download the plain-text transcript |
| `GET` | `/api/jobs/{id}/mom.html` | View rendered minutes |
| `POST` | `/api/asr` | Remote ASR worker endpoint |
| `GET` | `/api/asr/health` | ASR worker status |
| `GET` | `/api/health` | Combined ASR, LLM, and n8n status |

The n8n delivery payload is validated against
[`schemas/meeting-delivery-v2.schema.json`](schemas/meeting-delivery-v2.schema.json). Full
contract details are in [n8n/README.md](n8n/README.md).

## Validation and maintenance

Validate the n8n contract with Node.js 18 or newer:

```bash
node n8n/test-contract.cjs
```

With the laptop stack running, exercise all routes and check actual Mailpit delivery:

```bash
node n8n/smoke-test.cjs
```

Frontend development requires Node.js 20.19 or newer:

```bash
cd api/web
npm install
npm run dev
```

The Vite development server runs at http://localhost:5173 and proxies the backend on port
8000. Normal Docker builds compile the frontend automatically; Node.js is not required on
deployment machines.

Useful operational commands:

```bash
docker compose ps
docker compose logs --tail=100
docker compose restart api
docker compose down
```

`docker compose down` preserves the named `n8n_data` volume unless `--volumes` is added.

## Troubleshooting

| Symptom | Check |
|---|---|
| Web application does not open | Run `docker compose ps` and inspect `docker compose logs api`. |
| Health page reports ASR down | Verify `ASR_URL`, the GPU firewall, and `/api/asr/health` on the GPU node. |
| Health page reports LLM down | Verify `OLLAMA_URL` and that `LLM_MODEL` exactly matches a pulled Ollama tag. |
| Uploaded real audio returns sample minutes | `MOCK_MODELS` is still `1`; change it to `0` and recreate the API container. |
| Processing appears idle at first | Model loading and the language pre-pass can take time before visible progress changes. |
| GPU out-of-memory error | Stop an idle Ollama model or restart the NeMo service, then retry one job at a time. |
| n8n cannot decrypt credentials | Restore the `N8N_ENCRYPTION_KEY` used when `n8n_data` was created. |
| No email appears in Mailpit | Inspect the job error, n8n execution history, and `docker compose logs n8n mailpit`. |
| `egress-check.sh` prints nothing | Confirm the running stack uses the same Compose files/profile as the shell invoking the script. |

## Repository map

```text
api/app/                 FastAPI routes, ASR/LLM pipeline, review, rendering, delivery
api/web/                 React/Vite user interface
services/nemo-server/    Optional Nemotron ASR and Sortformer diarization service
n8n/                     Routing workflow, SMTP credential, contract and smoke tests
schemas/                 Versioned delivery JSON schema
scripts/                 Model download, GPU, connectivity, and offline checks
docs/                    Architecture, contracts, demo runbook, and demo script
eval/                    WER/CER and stenogram evaluation tools
glossary/                Medical terms and optional Whisper prompts
data/                    Local job data and evaluation references
```

## Further reading

- [How to use the solution](HOW_TO_USE.md)
- [Architecture](docs/architecture.md)
- [Service contracts](docs/contracts.md)
- [Demo runbook](docs/demo-runbook.md)
- [Demo script](docs/demo-script.md)
- [n8n delivery documentation](n8n/README.md)
- [Welcome to the project](WELCOME.md)
- [Thank you](THANK_YOU.md)

## Project purpose

This is our GigaHack 2026 response to the Medpark challenge: practical AI that helps teams
turn multilingual conversations into accountable follow-up while keeping sensitive data
under local control. Feedback, validation, and responsible testing are welcome.
