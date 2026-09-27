# How to Use Our Meeting Minutes Solution

This guide explains how to launch the solution, process a meeting, review the generated
minutes, and send the final result. If this is your first visit, you can try the complete
experience in mock mode without a GPU or downloaded AI models.

## What the solution does

The application turns a hospital meeting recording into structured minutes through one
simple workflow:

1. A user records a meeting or uploads an audio file.
2. The system transcribes Romanian, Russian, and English speech.
3. A local language model identifies decisions, action items, owners, and deadlines.
4. The user can review and edit the draft before approval.
5. The approved minutes are routed to the appropriate distribution list and emailed.

The processing stack can run entirely on the hospital network, keeping sensitive meeting
content away from external cloud services.

## Option 1: Try the interface in mock mode

Mock mode is the fastest way to explore the user experience. It uses prepared sample data,
so it works on an ordinary laptop without an NVIDIA GPU.

### Requirements

- Git
- Docker Desktop or Docker Engine with Compose

### Start the solution

From the repository folder, run:

```bash
cp .env.example .env
docker compose up -d --build
```

The default `.env.example` configuration enables `MOCK_MODELS=1` on the laptop.

Open these pages in your browser:

| Page | Address | Purpose |
|---|---|---|
| Main application | http://localhost:8000 | Record, upload, monitor, review, and send |
| Mailpit inbox | http://localhost:8025 | View the email produced by the workflow |
| n8n editor | http://localhost:5678 | Inspect the routing and delivery workflow |

## Process a meeting

### 1. Open the application

Visit http://localhost:8000. The home screen is intentionally simple: it provides an
upload area and a **Record** button. Technical options are available behind the settings
icon.

### 2. Choose automatic or reviewed delivery

By default, the application sends the minutes automatically when processing finishes.
Enable **“Verific procesul-verbal înainte de trimitere”** if you want the workflow to stop
at a draft so that a person can verify it first.

For a first test, we recommend enabling review. It lets you see the extracted decisions,
tasks, owners, deadlines, and supporting transcript quotes before anything is sent.

### 3. Add a recording

Use either method:

- drag and drop an existing audio file anywhere on the page; or
- select **Record** to capture a meeting directly in the browser.

When uploading a file, its modified date is used as the meeting date. While recording,
the interface provides an audio-level meter and pause control.

### 4. Follow the processing status

The application shows the current stage in plain language:

- **Transcriem** — the audio is being transcribed;
- **Redactăm** — the structured minutes are being created; and
- **Gata de verificat** — the draft is ready for review.

You may close the page during processing. The meeting can be reopened later from
**Recente**.

### 5. Review and improve the draft

On the review page:

- check the meeting summary, decisions, and action items;
- edit owners or deadlines when necessary;
- inspect highlighted missing information;
- select a supporting quote to open the transcript at the relevant moment; and
- confirm that the selected distribution list is appropriate.

The original model output remains available as `mom_draft.json`, while approved minutes
are stored separately.

### 6. Approve and send

Select **Aprobați și trimiteți** when the minutes are correct. The application sends the
approved snapshot and generated attachments through the n8n workflow. In the local demo,
open http://localhost:8025 to see the delivered message in Mailpit.

## Option 2: Run with real local AI models

Real transcription and extraction require an NVIDIA GPU machine with Docker and the
NVIDIA container runtime. The laptop runs the web application and workflow services; the
GPU node runs Whisper and Ollama.

On the GPU node:

```bash
cp .env.example .env
docker compose -f docker-compose.gpu.yml up -d --build
sh scripts/pull-models.sh
```

The model-download script is required once while online. Restrict ports **8000** and
**11434** so they are reachable only from the laptop running the application.

Test the connection from the laptop:

```bash
sh scripts/smoke-gpu-node.sh <GPU_NODE_IP> data/<some-recording>.ogg
```

Then update the laptop's `.env`:

```dotenv
MOCK_MODELS=0
ASR_URL=http://<GPU_NODE_IP>:8000
OLLAMA_URL=http://<GPU_NODE_IP>:11434
```

Apply the configuration:

```bash
docker compose up -d
```

The user workflow remains the same: upload or record, wait for processing, review if
requested, and send.

## Run everything on one GPU computer

For a single-machine setup, configure `.env` with the local service addresses and run:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile nemo up -d --build
```

See the [main README](README.md) for the exact environment values and optional speaker
diarization settings.

## Stop or restart the solution

Stop the running containers:

```bash
docker compose down
```

Start them again:

```bash
docker compose up -d
```

View container status and logs:

```bash
docker compose ps
docker compose logs --tail=100
```

## Quick troubleshooting

| Problem | What to check |
|---|---|
| The web page does not open | Run `docker compose ps` and confirm the API container is healthy. |
| Processing does not progress | Open settings and verify the ASR, LLM, and n8n status indicators. |
| The GPU node cannot be reached | Confirm its IP, firewall rules, and ports 8000 and 11434. |
| No email appears | Check Mailpit at http://localhost:8025 and inspect the n8n workflow. |
| Real audio returns sample content | Confirm that `MOCK_MODELS=0` is set and restart the stack. |
| A draft has missing details | Edit highlighted owners or deadlines before approving it. |

## Privacy reminders

- Keep the deployment on a trusted, closed network.
- Limit access to the GPU ports and browser services.
- Leave `KEEP_AUDIO=0` unless retaining source audio is explicitly required.
- Download models before switching to sealed offline operation.
- Review generated minutes before delivery when accuracy is critical.

## Learn more

- [README](README.md) — complete setup, configuration, and evaluation details
- [Architecture](docs/architecture.md) — how data moves through the system
- [Demo runbook](docs/demo-runbook.md) — preparation and on-stage demo steps
- [Demo script](docs/demo-script.md) — a sample meeting and expected output
- [Thank you](THANK_YOU.md) — how feedback and support help the project grow

You are ready to turn a meeting recording into clear, private, and actionable minutes. 🚀
