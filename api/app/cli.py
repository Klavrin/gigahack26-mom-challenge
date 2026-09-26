"""Command line tools (run inside the api container):

  python -m app.cli download                       # fetch Whisper weights once (online)
  python -m app.cli transcribe clip.wav --mode plain --out /data/out/plain.txt
  python -m app.cli transcribe clip.wav --backend nemotron --out /data/out/nemotron.txt
  python -m app.cli mom /data/out/segment.txt --type medical --date 2026-09-25
"""
import argparse
import datetime as dt
import json
import time
from pathlib import Path

from . import asr, config, llm, render


def main() -> None:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("download")

    t = sub.add_parser("transcribe")
    t.add_argument("audio")
    t.add_argument("--mode", choices=["segment", "plain"], default=config.ASR_MODE)
    t.add_argument("--backend", choices=["whisper", "nemotron"], default=config.ASR_BACKEND)
    t.add_argument("--out", help="write transcript here (default: stdout)")
    t.add_argument("--correct", action="store_true", help="run the LLM glossary correction")

    m = sub.add_parser("mom")
    m.add_argument("transcript")
    m.add_argument("--type", default="medical", choices=config.MEETING_TYPES)
    m.add_argument("--date", default=dt.date.today().isoformat())
    m.add_argument("--out", default="mom.html")

    args = p.parse_args()

    if args.cmd == "download":
        asr._load()
        print("Whisper model ready in", config.WHISPER_DIR)

    elif args.cmd == "transcribe":
        start = time.time()
        segments = asr.transcribe(args.audio, mode=args.mode, backend=args.backend)
        if args.correct:
            asr.unload()
            segments = llm.correct_transcript(segments)
        text = asr.to_text(segments)
        took = time.time() - start
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
            Path(args.out).with_suffix(".json").write_text(
                json.dumps(segments, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            print(text)
        audio_s = segments[-1]["end"] if segments else 0
        print(f"\n[{args.backend}/{args.mode}] {len(segments)} segments, {audio_s / 60:.1f} min audio "
              f"in {took:.0f}s")

    elif args.cmd == "mom":
        date = dt.date.fromisoformat(args.date)
        start = time.time()
        mom = llm.extract_mom(Path(args.transcript).read_text(encoding="utf-8"), args.type, date)
        Path(args.out).write_text(render.render_html(mom, args.type, date), encoding="utf-8")
        print(json.dumps(mom, ensure_ascii=False, indent=1))
        print(f"\nLLM took {time.time() - start:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()
