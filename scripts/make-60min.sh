#!/bin/sh
# Build a 60-minute test file for the speed benchmark by looping a recording.
# Usage: scripts/make-60min.sh data/sample.mp3 data/bench-60min.wav
set -e
ffmpeg -y -stream_loop -1 -i "$1" -t 3600 -ac 1 -ar 16000 "$2"
