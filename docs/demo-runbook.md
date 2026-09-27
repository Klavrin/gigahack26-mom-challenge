# Demo runbook (one laptop with an NVIDIA GPU)

All commands run from the repo folder. PowerShell works for `docker compose`. The `sh
scripts/...` helpers need **Git Bash**, because PowerShell has no `sh`.

## A. Once, the day before (online)

1. Update to the latest `main`:
   ```bash
   git checkout main && git pull
   ```
2. Create `.env`:
   ```bash
   cp .env.example .env
   ```
   Then set the one-machine block. These are the values tested on the RTX 5060 Laptop:
   ```
   COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml
   COMPOSE_PATH_SEPARATOR=:
   COMPOSE_PROFILES=nemo
   MOCK_MODELS=0
   ASR_URL=http://asr:8000
   OLLAMA_URL=http://ollama:11434
   ASR_PORT=8001
   DIARIZATION_URL=http://nemo:8001
   NEMO_LOAD=diar
   WHISPER_MODEL=large-v3
   WHISPER_COMPUTE_TYPE=float16
   ASR_MODE=longform
   LLM_MODEL=qwen2.5:7b-instruct
   N8N_ENCRYPTION_KEY=local-demo-key-change-me
   ```
3. Build and start everything:
   ```bash
   docker compose up -d --build
   ```
4. Download the models (about 10 GB, once):
   ```bash
   sh scripts/pull-models.sh
   ```
5. Check the GPU. Every model must be on CUDA and Qwen at `100% GPU`:
   ```bash
   sh scripts/gpu-check.sh
   ```
6. **Process the demo recording once** at http://localhost:8000. The finished job stays under
   "Recente" and is the fallback if anything fails on stage.

## B. Switch to offline mode (before going on stage)

1. In `.env`, set `OFFLINE=1` and append `:docker-compose.offline.yml` to `COMPOSE_FILE`.
2. Restart:
   ```bash
   docker compose up -d
   ```
3. Prove nothing can reach the internet. **Every line must say `BLOCKED`**:
   ```bash
   sh scripts/egress-check.sh
   ```
4. Quit Tailscale and turn Wi-Fi off.

## C. On stage (~3 min)

Follow the flow in [demo-script.md](demo-script.md#demo-flow-on-stage-3-min):
1. security check
2. upload (type **Medical**)
3. numbers slide while it runs
4. review with quotes and the changed owner
5. "Aprobat de"
6. Approve
7. the email in Mailpit: the final decisions, with the DOCX and the recording attached

| Open in the browser | What it shows |
|---|---|
| http://localhost:8000 | the app (upload, review, approve) |
| http://localhost:8025 | Mailpit, where the email arrives |
| http://localhost:5678 | n8n: the routing workflow by meeting type |

## If something goes wrong

| Symptom | Fix |
|---|---|
| Progress stays at 0 % for long | Normal for the first ~20 s (model loading) and during the language pre-pass on long files |
| Job fails with an out-of-memory error | Another model is holding VRAM. Run `docker compose exec ollama ollama stop qwen2.5:7b-instruct`, or `docker compose restart nemo`, then retry |
| `egress-check.sh` prints nothing | The stack is not running under the same `COMPOSE_FILE`: check `.env` |
| n8n "credentials could not be decrypted" | `N8N_ENCRYPTION_KEY` changed after the first start. Put the old value back |
| Anything else live | Open the job processed in step A.6 from "Recente" |

Speeds measured on the RTX 5060 Laptop (8 GB):
- about 13 min of transcription per 60 min of dense speech,
- 11.7 min recording → review in 3.5 min.
