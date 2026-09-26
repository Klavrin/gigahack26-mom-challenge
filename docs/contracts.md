# Service contracts

Every service runs on the same machine (or the hospital's internal network).
No component calls a cloud service at runtime.

```
browser ──▶ api :8000 ──▶ nemo :8001      (Nemotron ASR, Sortformer diarization)   optional
                     ├──▶ ollama :11434   (Qwen / LLM)
                     └──▶ n8n :5678 ──▶ mailpit :1025 (SMTP)
```

Audio sent between services is always **16 kHz mono 16-bit WAV**.

## nemo-server (`services/nemo-server`)

### `GET /health`
```json
{"status": "ok", "asr": true, "diar": true, "cuda": true}
```

### `POST /transcribe`
multipart: `file` = one VAD chunk (≤20 s), `language` = `auto` | `ro-RO` | `ru-RU` | `en-US`
```json
{"text": "Natalia va contacta furnizorul până joi.", "language": "ro"}
```
`language` is the 2-letter code from Nemotron's `<xx-XX>` tag in auto mode ("" if none).
The backend retries with the running language when auto mode returns something outside ro/ru/en.

### `POST /diarize`
multipart: `file` = the whole meeting
```json
{"segments": [{"start": 10.1, "end": 15.9, "speaker": "S2"}]}
```
Speakers are `S1`…`S4` (Sortformer 4spk limit).

## Merged transcript segment (api, `segments.json`)
```json
{"start": 10.2, "end": 15.8, "lang": "ro", "speaker": "S2",
 "text": "Natalia va contacta furnizorul până joi."}
```
Speaker = diarization turn with the largest time overlap (`api/app/merge.py`, no LLM).
Text form fed to the LLM: `[00:00:10 ro S2] Natalia va contacta furnizorul până joi.`

## Minutes (`mom.json`, LLM output, enforced by JSON schema in `api/app/llm.py`)
```json
{
  "title": "...", "summary": "...", "participants": ["..."],
  "topics": [{"topic": "...", "discussion": "..."}],
  "decisions": [{"decision": "...", "evidence": "verbatim quote"}],
  "action_items": [{"task": "...", "owner": "Natalia Rusu", "deadline": "2026-10-01",
                    "deadline_text": "până joi", "evidence": "verbatim quote"}],
  "open_questions": ["..."]
}
```
Missing owner / deadline = `""`. Later changes in the meeting override earlier ones.

## n8n webhook (`POST http://n8n:5678/webhook/mom`)
```json
{"job_id": "...", "meeting_type": "medical|executive|administrative",
 "meeting_date": "2026-09-26", "subject": "...", "html": "<email body>", "mom": {}}
```
