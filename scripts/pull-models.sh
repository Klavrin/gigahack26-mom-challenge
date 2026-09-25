#!/bin/sh
# Run ONCE while online. Afterwards everything works with the network off.
set -e
LLM_MODEL=${LLM_MODEL:-qwen2.5:7b-instruct}
docker compose exec ollama ollama pull "$LLM_MODEL"
docker compose exec api python -m app.cli download
echo "Models cached under ./models - you can go offline now (set OFFLINE=1 in .env)."
