# Secure MoM · GigaHack 2026

The revised physical-meeting architecture is:

```text
Capture → preserve raw audio + Silero VAD → chunks
  → Nemotron ASR + NeMo diarization/identification (NVIDIA workers)
  → timestamp merge and structured meeting state (MacBook backend)
  → Qwen3 live extraction + final reconciliation (AMD/Ollama)
  → human review → backend DOCX/PDF generation
  → n8n approved-state validation → meeting-type routing → Mailpit
```

The backend owns the meeting state. Unknown owners/deadlines remain `null`.
Transcripts and speaker embeddings stay in the backend; n8n receives an approved
snapshot and document bytes. See [the workflow guide](n8n/README.md) for the
contract, responsibilities, network addresses, and backend handoff.

## Run the portable automation stack

```sh
cp .env.example .env
# For non-demo use, choose a persistent N8N_ENCRYPTION_KEY before first startup.
# Keep it unchanged while reusing the n8n_data volume.
docker compose up -d
node n8n/test-contract.cjs
node n8n/smoke-test.cjs
```

Windows PowerShell: `Copy-Item .env.example .env`. Docker Desktop uses Linux
containers. No GPU is required for this stack. Open [n8n](http://localhost:5678)
and [Mailpit](http://localhost:8025). Tests send only synthetic minutes.

## Implementation boundaries

The v2 n8n workflow includes approval/schema validation, nullable assignments,
important notes, portable PDF/DOCX attachments, and three distribution routes.
It rejects the old unapproved HTML contract.

The checked-in `api/` is still the legacy upload/Whisper/Qwen2.5 implementation.
Live capture, remote Nemotron/NeMo clients, Qwen3 state updates, transcript merging,
human review, and document generation remain backend/model-team work. Updating the
workflow does not implement those services. The schema freezes the delivery
boundary for those teammates.

The old NVIDIA containers are opt-in under `--profile legacy-nvidia`. They are
kept for reference; their automatic delivery payload is incompatible with the new
approval gate. The AMD Qwen host should run its separately configured Ollama, not
this legacy NVIDIA service. `QWEN_URL`, `NEMOTRON_URL`, and `NEMO_URL` in the example
environment document the coordinator handoff; the legacy API only maps QWEN_URL to
its existing Ollama client.

Model accuracy, multilingual performance, live recovery, and physical ARM/Windows
machine compatibility still require team integration testing. Repeated delivery
requests send repeated emails; inspect ambiguous timeouts before retrying.
