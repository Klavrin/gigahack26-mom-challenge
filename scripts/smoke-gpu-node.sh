#!/bin/sh
# From the laptop: check the GPU node answers before switching MOCK_MODELS off.
# Usage: sh scripts/smoke-gpu-node.sh <GPU_NODE_IP> [audio file to transcribe 30 s of]
set -e
NODE=${1:?usage: smoke-gpu-node.sh <GPU_NODE_IP> [audio]}
AUDIO=$2
MODEL=${LLM_MODEL:-qwen3:8b}

echo "== ASR worker  http://$NODE:8000"
curl -fsS "http://$NODE:8000/api/asr/health"
echo

echo "== Ollama      http://$NODE:11434 (models pulled)"
curl -fsS "http://$NODE:11434/api/tags" | grep -o '"name":"[^"]*"'

echo "== LLM JSON reply from $MODEL"
cat > /tmp/mom-smoke.json <<EOF
{"model": "$MODEL", "stream": false, "think": false, "format": "json",
 "messages": [{"role": "user", "content": "Reply with the JSON object {\"ok\": true} and nothing else."}]}
EOF
curl -fsS "http://$NODE:11434/api/chat" -d @/tmp/mom-smoke.json -w '\n%{time_total}s\n' \
  | grep -o '"content":"[^"]*"\|^[0-9.]*s$'

if [ -n "$AUDIO" ]; then
  CLIP=/tmp/mom-smoke.wav
  ffmpeg -loglevel error -y -i "$AUDIO" -t 30 -ac 1 -ar 16000 "$CLIP"
  echo "== ASR on the first 30 s of $AUDIO"
  curl -fsS "http://$NODE:8000/api/asr" -F "file=@$CLIP" -F mode=segment -w '\n%{time_total}s\n'
fi
rm -f /tmp/mom-smoke.json /tmp/mom-smoke.wav
echo "OK - now set MOCK_MODELS=0, ASR_URL=http://$NODE:8000, OLLAMA_URL=http://$NODE:11434 in .env"
