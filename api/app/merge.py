"""Deterministic ASR + diarization merge: each transcript segment gets the speaker
whose diarization turns overlap it the most. No LLM involved."""

NEAREST_S = 1.0   # no overlap at all: accept the closest turn within this gap


def assign_speakers(segments: list[dict], turns: list[dict]) -> list[dict]:
    if not turns:
        return segments
    for seg in segments:
        overlap: dict[str, float] = {}
        for t in turns:
            o = min(seg["end"], t["end"]) - max(seg["start"], t["start"])
            if o > 0:
                overlap[t["speaker"]] = overlap.get(t["speaker"], 0.0) + o
        if overlap:
            seg["speaker"] = max(overlap, key=overlap.get)
            continue
        gap, speaker = min(
            (max(t["start"] - seg["end"], seg["start"] - t["end"]), t["speaker"]) for t in turns
        )
        seg["speaker"] = speaker if gap <= NEAREST_S else None
    return segments
