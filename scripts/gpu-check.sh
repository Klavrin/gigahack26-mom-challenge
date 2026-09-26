#!/bin/sh
# Confirms every model container really runs on the GPU (not a silent CPU fallback).
# Run it BEFORE processing a meeting: it loads the LLM for a moment (8 GB GPUs).
echo "== host GPU"; nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
echo "== asr worker (faster-whisper / CTranslate2)"
docker compose exec -T asr python -c "import os, ctranslate2 as c; n=c.get_cuda_device_count(); print('CUDA devices:', n, '| model:', os.environ.get('WHISPER_MODEL'), os.environ.get('WHISPER_COMPUTE_TYPE')); assert n>0"
echo "== ollama (run one prompt, then check where the model sits; want '100% GPU')"
docker compose exec -T ollama ollama run "${LLM_MODEL:-qwen2.5:7b-instruct}" "Spune 'ok'." >/dev/null 2>&1
docker compose exec -T ollama ollama ps
docker compose exec -T ollama ollama stop "${LLM_MODEL:-qwen2.5:7b-instruct}" >/dev/null 2>&1   # give the VRAM back
if docker compose ps --services --status running | grep -qx nemo; then
  echo "== nemo (torch)"
  docker compose exec -T nemo python -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
fi
