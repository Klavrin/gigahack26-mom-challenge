# Approved meeting delivery (v2)

n8n handles the last step only: approved JSON + generated DOCX/PDF → validation →
medical/executive/administrative distribution list → Mailpit SMTP. It does not call
Qwen, Nemotron or NeMo. The same workflow runs on ARM64 Mac, Linux (including AMD
hosts), and Windows Docker Desktop using Linux containers. Real hardware testing
is still needed on the teammates' machines.

## Start

```sh
cp .env.example .env
# For anything beyond the local demo, replace N8N_ENCRYPTION_KEY before the
# first startup. Never change it while reusing the same n8n_data volume.
docker compose up -d
node n8n/test-contract.cjs
node n8n/smoke-test.cjs
```

On Windows PowerShell use `Copy-Item .env.example .env`. The encryption key must
remain stable because n8n uses it to protect credentials in `n8n_data`. If a key
is lost, restore it from the team's secret store or initialize a new empty volume;
another key cannot decrypt the existing data. Node 18+ is required only
for developer scripts, not for running the containers. The default Compose stack
starts n8n, its importer, and Mailpit; no GPU or model downloads are involved.
Editor: http://localhost:5678; inbox: http://localhost:8025.
Smoke tests send synthetic emails to the local Mailpit catcher.

If already initialized, export editor changes first, then reimport:

```sh
docker compose stop n8n
docker compose run --rm n8n-init
docker compose up -d --no-deps n8n
```

The importer replaces the workflow and demo SMTP credential. Do not use it to
manage an independently customized SMTP setup without saving that setup first.

## Backend contract

POST JSON to `/webhook/mom` after final reconciliation, human review, and document
generation. `schemas/meeting-delivery-v2.schema.json` is the transport contract;
`examples/approved-meeting.json` is a complete synthetic example with small PDF/DOCX fixtures.

- `schema_version`: `"2"`.
- `delivery_id`: caller-generated attempt identifier (1–128 ASCII letters, digits,
  underscores or hyphens). Keep it in the backend delivery log.
- `state.meeting`: `id`, `title`, `type`, `started_at`, `ended_at`. Timestamps include
  timezone; only ended meetings may be distributed.
- `state`: `participants` (display-name strings), `topics`, `decisions`,
  `open_questions`, `important_notes` (string arrays), and `action_items`.
- Actions: `description`, `owner`, `deadline`, `status`. Unknown owners/deadlines
  are JSON `null`. Deadlines may be natural language; n8n never invents dates.
  Status is `open`, `in_progress`, `done`, or `cancelled`.
- `approval`: `status: "approved"`, nonblank `approved_by`, `approved_at`.
  Approval must follow meeting end. Backend owns authenticating the reviewer and
  ensuring documents and state are the exact approved snapshot.
- `documents`: one or two `{filename, mime_type, data_base64}` objects, DOCX/PDF
  only, maximum **5 MiB total decoded**. Use plain canonical base64, no data URL.
  No filesystem paths, download URLs, credentials or recipients are accepted.

The full backend state may retain `transcript`, richer participant identities,
revision history, and speaker embeddings. Project only the approved display fields
above into the delivery snapshot. These list shapes formalize details left open
in the planning documents. n8n checks file signatures, not full document validity
or whether document text matches state. The backend must generate valid files.

Example encoding in the backend:

```python
import base64
from pathlib import Path
pdf = Path("meeting-001-minutes.pdf")
document = {
    "filename": pdf.name,
    "mime_type": "application/pdf",
    "data_base64": base64.b64encode(pdf.read_bytes()).decode("ascii"),
}
```

HTTP 200 is returned only after SMTP accepts the message:

```json
{"status":"delivered","delivery_id":"demo-medical-001","meeting_id":"meeting-001","meeting_type":"medical"}
```

Backend must verify status and both IDs. HTTP 400 means invalid payload; HTTP 502
means SMTP failure. There is no retry/deduplication: an ambiguous timeout requires
checking delivery before resending. `delivery_id` is correlation, not an idempotency
key. Version 1 and legacy HTML are deliberately rejected because they bypassed
human approval. The old backend cannot yet send through this workflow.

## Device placement and networking

| Device | Responsibilities |
|---|---|
| MacBook coordinator | FastAPI, capture/VAD/chunking, timestamp merge, state, finalization/review, document generation, n8n/Mailpit |
| AMD machine | Qwen3 through native Ollama; live extraction and final reconciliation |
| NVIDIA workers | Nemotron ASR and NeMo diarization/speaker identification |

The coordinator's new clients should use `QWEN_URL`, `NEMOTRON_URL`, `NEMO_URL`
with the corresponding Tailscale addresses. These client implementations are a
backend handoff, not part of n8n. Qwen model tag/quantization belongs in the model
client; changing GPU or model does not change this webhook.

If backend shares the Compose network: `N8N_WEBHOOK_URL=http://n8n:5678/webhook/mom`.
If backend runs natively on the coordinator: use `http://localhost:5678/webhook/mom`.
For a backend on another device, set `N8N_BIND_ADDRESS` to the **n8n host's Tailscale
IPv4**, then use `http://<that-ip>:5678/webhook/mom`. Recreate n8n after changing
bindings. `localhost` inside a container refers to that container, not the host.
Mac/Windows Docker Desktop provides `host.docker.internal`; on Linux prefer the
host's Tailscale address for native Ollama. Do not send files by a local path from
another device. Base64 attachments require no shared mounts or callback endpoint.

`N8N_TEST_URL` and `MAILPIT_TEST_URL` override smoke-test endpoints. To inspect the
inbox remotely, explicitly set `MAILPIT_BIND_ADDRESS` to its host's Tailscale IPv4.
The webhook trusts the private network; approval metadata is not authentication.
Restrict access with your tailnet policy. No public deployment is configured.

## Routes and maintenance

Recipient lists are fixed configuration in the three Email nodes:

| Type | Addresses at medpark.local |
|---|---|
| medical | consiliul-medical, director.medical, sef.sectie |
| executive | board, ceo, cfo |
| administrative | administratie, hr, achizitii |

Edit `prepare-mom.js` or the JSON schema, run `node n8n/sync-workflow.cjs`, then
`node n8n/test-contract.cjs`. Tests fail when embedded code/schema is stale.
`node n8n/smoke-test.cjs` checks all routes, actual Mailpit recipients and attachment
bytes, and rejection responses. It leaves its synthetic messages in Mailpit.

Attachments use n8n binary item properties and the Email node's attachment names,
per the [n8n Send Email documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.sendemail/).
Execution history contains meeting contents; Compose sets a 24-hour pruning age.
This is a local demo with no verified hospital deployment controls.

`examples/qwen-mom.json` is the retained historical v1 example; it is rejected
by v2 and must not be used for delivery.
