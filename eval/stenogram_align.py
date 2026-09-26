"""Parliament stenogram + session audio -> timestamped verbatim transcript and a
Whisper fine-tuning dataset (clips <= 30 s with their exact text).

The stenogram is the reference text; Whisper is only used to find *when* each
stenogram word was spoken. Segments whose words the ASR could not confirm are
dropped, so the kept text is the stenographers' text, not the model's.

  # 1. anywhere (no model): clean the stenogram into speaker turns
  python eval/stenogram_align.py parse stenograma.txt turns.jsonl

  # 2. GPU node, inside the asr container: word timestamps + alignment + clips
  python eval/stenogram_align.py align audio.opus turns.jsonl out/

Outputs in out/:
  asr_words.jsonl   Whisper words with times (cached; delete to recompute)
  aligned.tsv       every stenogram sentence group with start/end, speaker,
                    language, match ratio and kept/dropped - the timed transcript
  dataset/          clips/*.wav (16 kHz mono) + metadata.csv, loadable with
                    datasets.load_dataset("audiofolder", data_dir="out/dataset")
"""
import argparse
import csv
import difflib
import json
import re
import subprocess
import sys
import unicodedata
import wave
from pathlib import Path

import numpy as np

SR = 16000
MAX_SEG_S = 28.0          # Whisper trains on <= 30 s windows; leave room for padding
MIN_SEG_S = 1.0
MIN_MATCH = 0.75          # share of segment words confirmed by the ASR
PAD_START, PAD_END = 0.15, 0.25

# "Domnul Igor Grosu:" / "Doamna Evelina Bubuioc – șefă a Direcției ...:"
NAME = r"[A-ZĂÂÎȘȚŞŢ][\w\-’']+"
SPEAKER = re.compile(rf"(?:Domnul|Doamna) {NAME}(?: {NAME}){{1,3}}(?: – [^:\n]{{3,200}})?:")
STAGE = re.compile(r"\((?:[^()]{0,200})\)")   # (Aplauze.) (Se onorează Drapelul de Stat ...)
PAGE_NO = re.compile(r"^\s*\d{1,3}\s*$", re.M)


# ---------------------------------------------------------------- parse

def parse(txt_path: str, out_path: str) -> None:
    text = Path(txt_path).read_text(encoding="utf-8")
    start = text.find("Ședința începe")
    end = text.find("Ședința s-a încheiat")
    if start < 0 or end < 0:
        sys.exit("could not find 'Ședința începe' / 'Ședința s-a încheiat' markers")
    body = text[start:end]   # text before the first speaker label (opening protocol) is skipped
    body = PAGE_NO.sub(" ", body)
    body = body.replace("ş", "ș").replace("ţ", "ț").replace("Ş", "Ș").replace("Ţ", "Ț")

    turns = []
    marks = list(SPEAKER.finditer(body))
    for i, m in enumerate(marks):
        chunk = body[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(body)]
        chunk = STAGE.sub(" ", chunk)
        chunk = re.sub(r"\s+", " ", chunk).strip()
        if not chunk:
            continue
        speaker = m.group(0).rstrip(":").split(" – ")[0].split(" ", 1)[1]
        turns.append({"turn": len(turns), "speaker": speaker, "lang": lang_of(chunk), "text": chunk})

    with open(out_path, "w", encoding="utf-8") as f:
        for t in turns:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    words = sum(len(t["text"].split()) for t in turns)
    by_lang = {}
    for t in turns:
        by_lang[t["lang"]] = by_lang.get(t["lang"], 0) + 1
    print(f"{len(turns)} turns, {words} words, languages: {by_lang} -> {out_path}")


def lang_of(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "ro"
    cyr = sum("Ѐ" <= c <= "ӿ" for c in letters) / len(letters)
    return "ru" if cyr > 0.7 else "mixed" if cyr > 0.1 else "ro"


# ---------------------------------------------------------------- align

def norm(word: str) -> str:
    w = unicodedata.normalize("NFC", word.lower())
    w = w.replace("ş", "ș").replace("ţ", "ț").replace("ё", "е")
    return re.sub(r"[^\w]", "", w)


def asr_words(audio: str, cache: Path) -> list[dict]:
    if cache.exists():
        return [json.loads(l) for l in cache.open(encoding="utf-8")]
    here = Path(__file__).resolve().parent.parent
    sys.path[:0] = [str(here), str(here / "api")]   # /app in the container, repo/api outside it
    from app import asr   # loads the configured Whisper model (GPU node)

    model = asr._load()
    segments, info = model.transcribe(
        audio, beam_size=5, word_timestamps=True, vad_filter=True,
        multilingual=True,                 # per-segment language: keeps Russian replies Russian
        condition_on_previous_text=False,
        initial_prompt=asr.load_prompts().get("ro"),
    )
    words = []
    with cache.open("w", encoding="utf-8") as f:
        for seg in segments:
            for w in seg.words or []:
                item = {"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
                words.append(item)
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            print(f"\r  ASR {seg.end / 60:6.1f} / {info.duration / 60:.1f} min", end="", flush=True)
    print()
    return words


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZĂÂÎȘȚА-ЯЁ„\"«])", text)
    out = []
    for p in parts:   # very long sentences: also allow a split after commas/semicolons
        out.extend(re.split(r"(?<=[,;:])\s+", p) if len(p.split()) > 60 else [p])
    return [p for p in out if p.strip()]


def align(audio: str, turns_path: str, out_dir: str, holdout_every: int = 10) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    turns = [json.loads(l) for l in open(turns_path, encoding="utf-8")]
    asr = asr_words(audio, out / "asr_words.jsonl")
    print(f"{len(asr)} ASR words")

    # Flatten the stenogram into words, remembering turn and sentence.
    ref, units = [], []                  # ref: normalized words; units: (turn, sent, first, last)
    for t in turns:
        for s in sentences(t["text"]):
            first = len(ref)
            for w in s.split():
                ref.append(norm(w))
            units.append((t, s, first, len(ref) - 1))

    hyp = [norm(w["w"]) for w in asr]
    # autojunk drops very frequent words ("de", "și") as anchors, which keeps this
    # fast on hours of speech; content words still anchor the alignment.
    match = [-1] * len(ref)
    for a, b, n in difflib.SequenceMatcher(None, ref, hyp, autojunk=True).get_matching_blocks():
        for k in range(n):
            if ref[a + k]:
                match[a + k] = b + k
    matched = sum(m >= 0 for m in match)
    print(f"stenogram words confirmed by ASR: {matched}/{len(ref)} ({matched / max(1, len(ref)):.0%})")

    # Group consecutive sentences of one turn into segments of <= MAX_SEG_S.
    segs, cur = [], None
    for t, s, first, last in units:
        ts = [match[i] for i in range(first, last + 1) if match[i] >= 0]
        if cur and cur["turn"] == t["turn"] and ts and cur["times"]:
            span = asr[max(ts)]["e"] - asr[min(cur["times"])]["s"]
            if span <= MAX_SEG_S:
                cur["text"] += " " + s
                cur["last"] = last
                cur["times"] += ts
                continue
        if cur:
            segs.append(cur)
        cur = {"turn": t["turn"], "speaker": t["speaker"], "lang": t["lang"], "text": s,
               "first": first, "last": last, "times": ts}
    if cur:
        segs.append(cur)

    audio_pcm = load_pcm(audio, out / "audio16k.raw")
    total_s = len(audio_pcm) / SR
    rows, kept_s = [], 0.0
    clips = out / "dataset" / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    meta = open(out / "dataset" / "metadata.csv", "w", newline="", encoding="utf-8")
    writer = csv.writer(meta)
    writer.writerow(["file_name", "text", "speaker", "lang", "start", "end", "match", "split"])

    for n, seg in enumerate(segs):
        idx = range(seg["first"], seg["last"] + 1)
        ratio = sum(match[i] >= 0 for i in idx) / len(idx)
        # Boundaries must be confirmed within 1 word, or the clip may cut speech off.
        edge_ok = (max(match[seg["first"]], match[min(seg["first"] + 1, seg["last"])]) >= 0 and
                   max(match[seg["last"]], match[max(seg["last"] - 1, seg["first"])]) >= 0)
        if seg["times"]:
            start = max(0.0, asr[min(seg["times"])]["s"] - PAD_START)
            end = min(total_s, asr[max(seg["times"])]["e"] + PAD_END)
        else:
            start = end = 0.0
        dur = end - start
        cps = len(seg["text"]) / dur if dur > 0 else 0
        keep = (ratio >= MIN_MATCH and edge_ok and MIN_SEG_S <= dur <= 30.0 and 4 <= cps <= 30)
        rows.append([f"{start:.2f}", f"{end:.2f}", seg["speaker"], seg["lang"], f"{ratio:.2f}",
                     "kept" if keep else "dropped", seg["text"]])
        if not keep:
            continue
        name = f"clips/{n:05d}.wav"
        write_wav(clips.parent / name, audio_pcm[int(start * SR):int(end * SR)])
        # whole speaker turns are held out, so validation never shares a turn with training
        split = "validation" if holdout_every and seg["turn"] % holdout_every == 0 else "train"
        writer.writerow([name, seg["text"], seg["speaker"], seg["lang"],
                         f"{start:.2f}", f"{end:.2f}", f"{ratio:.2f}", split])
        kept_s += dur
    meta.close()

    with open(out / "aligned.tsv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["start", "end", "speaker", "lang", "match", "status", "text"])
        w.writerows(rows)
    del audio_pcm   # release the memmap so the temp file can be deleted (Windows)
    (out / "audio16k.raw").unlink(missing_ok=True)
    kept = sum(r[5] == "kept" for r in rows)
    print(f"{len(rows)} segments, kept {kept} ({kept_s / 3600:.2f} h of {total_s / 3600:.2f} h audio)"
          f" -> {out / 'dataset'}")


def load_pcm(audio: str, raw: Path) -> np.ndarray:
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", audio,
                    "-ac", "1", "-ar", str(SR), "-f", "s16le", str(raw)], check=True)
    return np.memmap(raw, dtype=np.int16, mode="r")


def write_wav(path: Path, pcm: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.asarray(pcm).tobytes())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("parse"); a.add_argument("txt"); a.add_argument("out")
    b = sub.add_parser("align"); b.add_argument("audio"); b.add_argument("turns"); b.add_argument("out")
    b.add_argument("--holdout-every", type=int, default=10,
                   help="put every Nth speaker turn in validation; 0 = everything is train")
    args = p.parse_args()
    if args.cmd == "parse":
        parse(args.txt, args.out)
    else:
        align(args.audio, args.turns, args.out, args.holdout_every)


if __name__ == "__main__":
    main()
