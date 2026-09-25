"""Word/char error rate of a hypothesis transcript against a hand-corrected reference.

  python eval/wer.py data/refs/dev.txt data/out/plain.txt data/out/segment.txt

Bracketed prefixes like "[00:01:02 ro S1]" are stripped; case, punctuation and
ş/ș, ţ/ț, ё/е spelling variants are normalised so only real errors count.
"""
import re
import sys
from collections import Counter

import jiwer

VARIANTS = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț", "ё": "е", "Ё": "Е"})


def normalise(text: str) -> str:
    text = re.sub(r"^\[[^\]]*\]\s*", "", text, flags=re.M)
    text = text.translate(VARIANTS).lower()
    text = re.sub(r"[^\w\s]", " ", text)   # "KPI-ul" == "KPI ul"
    return re.sub(r"\s+", " ", text).strip()


def top_errors(ref: str, hyp: str, n: int = 15) -> list[tuple[str, int]]:
    out = jiwer.process_words(ref, hyp)
    subs = Counter()
    for align, r, h in zip(out.alignments, out.references, out.hypotheses):
        for chunk in align:
            if chunk.type == "substitute":
                pair = f"{' '.join(r[chunk.ref_start_idx:chunk.ref_end_idx])} -> " \
                       f"{' '.join(h[chunk.hyp_start_idx:chunk.hyp_end_idx])}"
                subs[pair] += 1
    return subs.most_common(n)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ref = normalise(open(sys.argv[1], encoding="utf-8").read())
    for path in sys.argv[2:]:
        hyp = normalise(open(path, encoding="utf-8").read())
        print(f"\n== {path}")
        print(f"WER {jiwer.wer(ref, hyp):.1%}   CER {jiwer.cer(ref, hyp):.1%}")
        print("most frequent substitutions (reference -> heard):")
        for pair, count in top_errors(ref, hyp):
            print(f"  {count:3d}  {pair}")


if __name__ == "__main__":
    main()
