#!/bin/sh
# GPU node only. Run ONCE while online; afterwards it works with the network off.
set -e
LLM_MODEL=${LLM_MODEL:-qwen3:8b}
docker compose -f docker-compose.gpu.yml exec ollama ollama pull "$LLM_MODEL"
docker compose -f docker-compose.gpu.yml exec asr python -m app.cli download
echo "Models cached under ./models - you can go offline now (set OFFLINE=1 in .env)."
