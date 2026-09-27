# Architecture

Everything runs on the hospital network. No component calls a cloud service at runtime.
Model weights are downloaded once during setup and then load from disk (`OFFLINE=1`).

## 1. The stack at a glance

```mermaid
flowchart LR
    user(["Doctor / secretary<br/>browser"])

    subgraph laptop["Laptop stack · docker-compose.yml"]
        api["<b>api</b> :8000<br/>FastAPI + React web app<br/>job queue, pipeline"]
        n8n["<b>n8n</b> :5678<br/>validate approved minutes<br/>route by meeting type"]
        mail["<b>mailpit</b> :8025 / SMTP :1025<br/>stands in for the<br/>hospital mail server"]
    end

    subgraph gpu["GPU node · docker-compose.gpu.yml"]
        asr["<b>asr</b> :8000<br/>Whisper large-v3<br/>longform, RO / RU / EN"]
        nemo["<b>nemo</b> :8001<br/>Sortformer diarization<br/>who spoke when (S1-S4)"]
        llm["<b>ollama</b> :11434<br/>Qwen 2.5 7B<br/>minutes as JSON"]
    end

    user -- "upload / Rec<br/>review, approve" --> api
    api -- "audio" --> asr
    api -- "audio (≤ 2 h)" --> nemo
    api -- "transcript" --> llm
    api -- "approved snapshot<br/>+ DOCX + audio (contract v2)" --> n8n
    n8n -- "SMTP" --> mail
    mail -. "email to the<br/>distribution list" .-> user
```

For the demo, both compose files run on **one laptop** as one project. In a hospital, the
GPU node would be the server-room machine and the laptop stack would run anywhere on the LAN.

## 2. One meeting, start to finish

```mermaid
sequenceDiagram
    autonumber
    actor U as Doctor
    participant A as api
    participant S as asr (Whisper)
    participant D as nemo (Sortformer)
    participant L as ollama (Qwen)
    participant N as n8n
    participant M as mailpit

    U->>A: upload recording + meeting type + date
    A->>A: save to data/jobs/<id>/, queue (one job at a time)
    par transcription
        A->>S: POST /api/asr (+ progress id)
        loop every second
            A->>S: GET /api/asr/progress/<id>
            S-->>A: 0.0 … 1.0 (the web page's progress bar)
        end
        S-->>A: segments [start, end, lang, text]
    and diarization (recordings ≤ 2 h)
        A->>D: POST /diarize
        D-->>A: turns [start, end, S1…S4]
    end
    A->>A: attach speakers by time overlap, delete the audio (keep a compressed copy for the email)
    A->>L: transcript + rules + JSON schema
    L-->>A: title, summary, decisions, action items, open questions
    A->>A: deadlines by code, drop invented names, unload the LLM
    A-->>U: draft minutes: review page with quotes
    U->>A: fix owners / deadlines, "Aprobat de", Approve
    A->>N: POST /webhook/mom (schema v2 + DOCX + .ogg)
    N->>N: validate, switch on medical / executive / administrative
    N->>M: email to that distribution list
```

## 3. Inside the ASR: longform with language runs

```mermaid
flowchart TD
    a["audio file"] --> dec["ffmpeg → 16 kHz mono<br/>(bounded memory, 5 h 44 min OK)"]
    dec --> vad["Silero VAD<br/>speech regions ≤ 30 s"]
    vad --> lid{"language per region<br/>Russian ≥ 95 % sure?"}
    lid -- "yes" --> ru["ru"]
    lid -- "no" --> ro["ro (primary)"]
    ru --> runs["merge neighbours with the same language<br/>into runs (≤ 10 min)"]
    ro --> runs
    runs --> wh["Whisper large-v3 per run<br/>30 s windows + previous text as context<br/>language forced to the run's"]
    wh --> flt["filters: hallucinations ('КОНЕЦ', 'vizionare'…),<br/>repeats, foreign scripts (Korean, Chinese)"]
    flt --> seg["segments: start, end, lang, text"]
```

Why this design, measured on a hand-corrected Moldovan lecture and the Parliament session:

| Choice | Instead of | Result |
|---|---|---|
| 30 s windows with context | short chunks (5-20 s) | WER 53 % vs 78-85 % |
| language chosen **before** decoding | re-checking after | whole Russian speeches kept (Whisper forced to Romanian writes "Să vă mulțumim pentru vizionare" instead) |
| Russian only at ≥ 95 % | 80 % | no fake Russian on noisy Romanian (66.5 % → 53 % WER) |
| Whisper large-v3 | large-v3-turbo / Nemotron 3.5 | 53 % vs 57-71 % (turbo); 5/5 vs 2/5 phrases (Nemotron) |

## 4. From transcript to minutes

```mermaid
flowchart LR
    t["transcript<br/>[00:02:14 ro S2] …"] --> q["Qwen 2.5 7B<br/>JSON schema, long meetings<br/>in chunks + merge"]
    q --> c1["deadlines by code<br/>'până joi', 'к пятнице', '15.10'<br/>→ YYYY-MM-DD"]
    q --> c2["grounding: every name must<br/>appear in the transcript"]
    q --> c3["speaker map<br/>S2 → Natalia Rusu"]
    c1 --> mom["mom.json + mom.html"]
    c2 --> mom
    c3 --> mom
    mom --> rev["review page<br/>(a person approves)"]
    rev --> docx["DOCX + audio + v2 payload → n8n"]
```

The LLM only reads and summarises. Dates, names and the delivery format are checked by
plain code, so a 7B model can't invent an owner or miscount a weekday.

## 5. Deployment modes

```mermaid
flowchart TB
    subgraph one["One machine (demo laptop, RTX 5060 8 GB)"]
        direction LR
        o1["docker-compose.yml<br/>+ docker-compose.gpu.yml<br/>+ --profile nemo"]
    end
    subgraph split["Hospital: laptop + GPU server on the LAN"]
        direction LR
        s1["laptop: docker-compose.yml<br/>ASR_URL / OLLAMA_URL → server"] --- s2["server: docker-compose.gpu.yml"]
    end
    subgraph sealed["Sealed demo: + docker-compose.offline.yml"]
        direction LR
        g["nginx gateway<br/>:8000 :8025 :5678<br/>(config only, no code)"] --- net["internal network, no route out:<br/>api, asr, nemo, ollama, n8n, mailpit"]
    end
```

`scripts/egress-check.sh` opens a connection to the internet from inside every container;
in sealed mode each one must print **BLOCKED**. `scripts/gpu-check.sh` confirms the models
run on the GPU.

## 6. Where things live

| What | Where | Kept? |
|---|---|---|
| uploaded audio | `data/jobs/<id>/audio.*` | deleted right after transcription (`KEEP_AUDIO=0`) |
| transcript, speakers | `data/jobs/<id>/segments.json`, `transcript.txt` | on the server only, never emailed |
| draft / approved minutes | `data/jobs/<id>/mom_draft.json`, `mom.json`, `mom.html` | on the server |
| model weights | `models/whisper`, `models/ollama`, `models/hf` | local disk |
| routing workflow + SMTP credential | `n8n/workflows`, `n8n/credentials` | imported by `n8n-init` at start |

`data/` and `models/` are git-ignored. Interfaces between the services: [contracts.md](contracts.md).
