#!/bin/sh
# GPU node only. Run ONCE while online; afterwards it works with the network off.
set -e
LLM_MODEL=${LLM_MODEL:-qwen3:8b}
docker compose -f docker-compose.gpu.yml exec ollama ollama pull "$LLM_MODEL"
docker compose -f docker-compose.gpu.yml exec asr python -m app.cli download
echo "Models cached under ./models - you can go offline now (set OFFLINE=1 in .env)."

# NVIDIA speech models: the nemo container downloads them on first start.
if docker compose ps --services --status running | grep -q '^nemo$'; then
  echo "Waiting for nemo-server to load Nemotron + Sortformer (first start downloads weights)..."
  until docker compose exec nemo python -c "import urllib.request;urllib.request.urlopen('http://localhost:8001/health')" 2>/dev/null; do sleep 10; done
  echo "nemo-server ready."
fi
