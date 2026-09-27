#!/bin/sh
# GPU node only. Run ONCE while online. The stack runs with OFFLINE=1 by default (models from
# disk only); this script is the one place where the containers download weights.
set -e
# Same model the app uses: shell variable, else .env, else the compose default.
LLM_MODEL=${LLM_MODEL:-$(grep -s '^LLM_MODEL=' .env | tail -1 | cut -d= -f2)}
LLM_MODEL=${LLM_MODEL:-qwen3:8b}
docker compose -f docker-compose.gpu.yml exec ollama ollama pull "$LLM_MODEL"
docker compose -f docker-compose.gpu.yml exec -e OFFLINE=0 -e HF_HUB_OFFLINE=0 asr python -m app.cli download
echo "$LLM_MODEL + Whisper cached under ./models."

# NVIDIA speech models: the nemo container downloads them when it starts online.
if docker compose config --services 2>/dev/null | grep -qx nemo; then
  echo "Starting nemo online once to download its weights (Sortformer, Nemotron per NEMO_LOAD)..."
  OFFLINE=0 docker compose up -d --force-recreate nemo
  until docker compose exec nemo python -c "import urllib.request;urllib.request.urlopen('http://localhost:8001/health')" 2>/dev/null; do sleep 10; done
  docker compose up -d --force-recreate nemo   # back to OFFLINE=1: loads from disk only
  echo "nemo weights cached; nemo restarted offline."
fi
echo "Done: the stack now runs without reaching any model hub."
