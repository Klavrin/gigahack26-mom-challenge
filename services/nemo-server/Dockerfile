# NVIDIA speech models (Nemotron ASR + Sortformer diarization) behind a tiny HTTP API.
# Runs on the same machine as the rest of the stack; only the backend talks to it.
FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends libsndfile1 ffmpeg git build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install Cython packaging && pip install -r requirements.txt
COPY server.py .

EXPOSE 8001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
