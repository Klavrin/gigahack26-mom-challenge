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

## Sealed offline demo

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
