"""Word/char error rate of a hypothesis transcript against a hand-corrected reference.

  python eval/wer.py data/refs/dev.txt data/out/plain.txt data/out/segment.txt

Bracketed prefixes like "[00:01:02 ro S1]" are stripped; case, punctuation and
ş/ș, ţ/ț, ё/е spelling variants are normalised so only real errors count.

Three scores per file:
  raw         the above only
  dialect     + spoken Moldovan forms mapped to standard Romanian on BOTH sides
                ("așa-i" = "așa e", "omogene-s" = "omogene sunt", "îs" = "sunt",
                "pân'" = "până", "ș-a" = "și a"): same words, different spelling
  +no diacr.  + ă â î ș ț folded to a a i s t (shows how much is only diacritics)
"""
import re
import sys
from collections import Counter

import jiwer

VARIANTS = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț", "ё": "е", "Ё": "Е"})
NO_DIACRITICS = str.maketrans("ăâîșț", "aaist")

# Spoken Moldovan/colloquial Romanian -> standard spelling. Applied to reference and
# hypothesis alike, so it never favours either side.
DIALECT = [
    (r"\bîs\b", "sunt"),
    (r"\bpân'", "până"),
    (r"\bș-(?=\w)", "și "),
    (r"(\w)-s\b", r"\1 sunt"),
    (r"(\w)-i\b", r"\1 e"),
]


def normalise(text: str, dialect: bool = False, diacritics: bool = True) -> str:
    text = re.sub(r"^\[[^\]]*\]\s*", "", text, flags=re.M)
    text = text.translate(VARIANTS).lower()
    if dialect:
        for pattern, repl in DIALECT:
            text = re.sub(pattern, repl, text)
    if not diacritics:
        text = text.translate(NO_DIACRITICS)
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


def scores(ref_text: str, hyp_text: str) -> dict[str, tuple[float, float]]:
    out = {}
    for name, kw in (("raw", {}), ("dialect", {"dialect": True}),
                     ("+no diacr.", {"dialect": True, "diacritics": False})):
        ref, hyp = normalise(ref_text, **kw), normalise(hyp_text, **kw)
        out[name] = (jiwer.wer(ref, hyp), jiwer.cer(ref, hyp))
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ref_text = open(sys.argv[1], encoding="utf-8").read()
    for path in sys.argv[2:]:
        hyp_text = open(path, encoding="utf-8").read()
        print(f"\n== {path}")
        for name, (wer, cer) in scores(ref_text, hyp_text).items():
            print(f"{name:11s} WER {wer:6.1%}   CER {cer:6.1%}")
        print("most frequent substitutions after dialect normalisation (reference -> heard):")
        for pair, count in top_errors(normalise(ref_text, dialect=True), normalise(hyp_text, dialect=True)):
            print(f"  {count:3d}  {pair}")


if __name__ == "__main__":
    main()
