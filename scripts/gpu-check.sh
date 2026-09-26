#!/bin/sh
# Confirms every model container really runs on the GPU (not a silent CPU fallback).
echo "== host GPU"; nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
echo "== api (faster-whisper / CTranslate2)"
docker compose exec -T api python -c "import ctranslate2 as c; n=c.get_cuda_device_count(); print('CUDA devices:', n); assert n>0"
echo "== ollama (run one prompt, then check where the model sits; want '100% GPU')"
docker compose exec -T ollama ollama run "${LLM_MODEL:-qwen2.5:7b-instruct}" "Spune 'ok'." >/dev/null 2>&1
docker compose exec -T ollama ollama ps
if docker compose ps --services --status running | grep -qx nemo; then
  echo "== nemo (torch)"
  docker compose exec -T nemo python -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
fi
