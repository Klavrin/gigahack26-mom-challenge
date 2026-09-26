# GPU node: CUDA 12.8 + cuDNN 9, needed by CTranslate2 and by Blackwell GPUs (RTX 50xx).
# The laptop builds the same code on a slim base (BASE_IMAGE) since it runs no models.
ARG BASE_IMAGE=nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

# Web app (React). Built here so no machine needs Node and nothing loads from a CDN.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /venv
ENV PATH=/venv/bin:$PATH

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY --from=web /web/dist ./static
COPY fixtures ./fixtures

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
