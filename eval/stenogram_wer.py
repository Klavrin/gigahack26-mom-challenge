"""Approximate WER of a session transcript against the official stenogram.

  python eval/stenogram_wer.py turns.jsonl segments.json            # whole session
  python eval/stenogram_wer.py turns.jsonl segments.json --window   # an excerpt of it

The stenogram is lightly edited (fillers, repetitions and false starts removed), so this
over-counts errors a little; it is a sanity number, not an exact WER.
--window: the audio was only part of the session; the matching stretch of the stenogram
is found automatically (first to last run of >= 8 words shared with the transcript).
Scores are also split by language: stenogram words by their turn's "lang", transcript
words by the language the pipeline decoded them in.
"""
import difflib
import json
import sys

import jiwer

from wer import normalise

MIN_BLOCK = 8   # words in a row that must match to anchor the excerpt


def words_with_lang(items, text_key: str, **norm) -> list[tuple[str, str]]:
    out = []
    for it in items:
        out += [(w, it["lang"]) for w in normalise(it[text_key], **norm).split()]
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    turns = [json.loads(line) for line in open(args[0], encoding="utf-8") if line.strip()]
    segments = json.load(open(args[1], encoding="utf-8"))

    for name, norm in (("raw", {}), ("dialect+no diacr.", {"dialect": True, "diacritics": False})):
        ref = words_with_lang(turns, "text", **norm)
        hyp = words_with_lang(segments, "text", **norm)
        if "--window" in sys.argv:
            sm = difflib.SequenceMatcher(None, [w for w, _ in ref], [w for w, _ in hyp], autojunk=False)
            blocks = [b for b in sm.get_matching_blocks() if b.size >= MIN_BLOCK]
            if not blocks:
                sys.exit("no stretch of the stenogram matches this transcript")
            first, last = blocks[0], blocks[-1]
            # extend by the transcript words before the first / after the last anchor
            start = max(0, first.a - first.b)
            end = min(len(ref), last.a + last.size + (len(hyp) - last.b - last.size))
            ref = ref[start:end]
        for lang in [None] + sorted({l for _, l in ref}):
            r = " ".join(w for w, l in ref if lang in (None, l))
            h = " ".join(w for w, l in hyp if lang in (None, l))
            if r:
                print(f"{lang or 'all':4s} {name:18s} WER {jiwer.wer(r, h):6.1%}  CER {jiwer.cer(r, h):6.1%}  "
                      f"words ref {len(r.split()):6d} / heard {len(h.split()):6d}")


if __name__ == "__main__":
    main()
