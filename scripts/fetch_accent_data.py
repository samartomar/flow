"""Fetch per-accent evaluation slices into .bench/accent/ (roadmap Phase 0).

Pulls utterance-level clips + references from the EdAcc corpus (Edinburgh
International Accents of English, CC BY-SA) via the Hugging Face datasets-server
REST API — no `datasets` dependency, no multi-GB shard downloads; only the
selected clips are fetched. Pure stdlib + numpy, mirroring asr_bench.py's rule
that the bench path should not grow the dependency tree.

Groups fetched (EdAcc `l1` labels -> group slug):

    Spanish               -> spanish       (295 utterances available)
    Russian               -> russian       (287)
    Japanese              -> japanese      (137)
    Indian English        -> indian        (373)
    Mainstream US English -> us-control    (357)  <- the control: the speaker
                                                     population every other tool
                                                     already serves

`us-control` exists so the accent gap is measured here, not quoted from papers.

Output layout (consumed by scripts/accent_bench.py):

    .bench/accent/edacc/<group>/<row_idx>.wav      16 kHz mono 16-bit PCM
    .bench/accent/manifest-edacc.jsonl             one JSON object per clip:
        {wav, ref, group, dataset, speaker, row_idx, duration}

EdAcc is *conversational* speech — expect WER well above dictation register.
That is fine: it is the stress test, and model-vs-model deltas are the signal.

Usage:  uv run python scripts/fetch_accent_data.py [--per-group 60]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np

API = "https://datasets-server.huggingface.co"
DATASET = "edinburghcstr/edacc"
SPLIT = "validation"
SR = 16000

GROUPS = {
    "Spanish": "spanish",
    "Russian": "russian",
    "Japanese": "japanese",
    "Indian English": "indian",
    "Mainstream US English": "us-control",
}

#: Rows that are scoring directives or annotation noise, not speech references.
_BAD_TEXT = ("IGNORE_TIME_SEGMENT_IN_SCORING",)

BENCH = Path(__file__).resolve().parent.parent / ".bench" / "accent"


def _get(url: str, *, binary: bool = False, tries: int = 6):
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "flow-accent-bench"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            return data if binary else json.loads(data)
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                # The datasets-server rate-limits bursts; honour Retry-After and
                # back off hard — a stalled fetch beats a dead one.
                wait = int(e.headers.get("Retry-After") or 0) or 20 * (attempt + 1)
                print(f"  429 rate-limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                time.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001 - retry then surface
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed after {tries} tries: {url[:120]}... ({last})")


def _rows_page(offset: int, length: int = 100) -> dict:
    q = urllib.parse.urlencode(
        {"dataset": DATASET, "config": "default", "split": SPLIT,
         "offset": offset, "length": length}
    )
    return _get(f"{API}/rows?{q}")


def _usable(text: str) -> bool:
    if any(marker in text for marker in _BAD_TEXT):
        return False
    words = [w for w in text.split() if w.isalpha() or w.replace("'", "").isalpha()]
    return len(words) >= 2


def _to_16k_mono(data: bytes) -> tuple[np.ndarray, float]:
    """Decode a WAV asset to float32 mono 16 kHz. Returns (audio, duration_s)."""
    with wave.open(io.BytesIO(data), "rb") as w:
        sr, nch, width, nframes = (
            w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        )
        raw = w.readframes(nframes)
    if width != 2:
        raise ValueError(f"expected 16-bit PCM, got {width * 8}-bit")
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nch > 1:
        a = a.reshape(-1, nch).mean(axis=1)
    if sr != SR:
        n_out = int(len(a) * SR / sr)
        a = np.interp(
            np.linspace(0, len(a) - 1, n_out), np.arange(len(a)), a
        ).astype(np.float32)
    return a, len(a) / SR


def _write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((audio * 32767.0).astype(np.int16).tobytes())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-group", type=int, default=60)
    ap.add_argument("--min-sec", type=float, default=1.5)
    ap.add_argument("--max-sec", type=float, default=20.0)
    args = ap.parse_args()

    first = _rows_page(0, 1)
    total = first["num_rows_total"]
    print(f"{DATASET} {SPLIT}: {total} rows; "
          f"selecting up to {args.per_group}/group, {args.min_sec}-{args.max_sec}s")

    manifest = BENCH / "manifest-edacc.jsonl"
    BENCH.mkdir(parents=True, exist_ok=True)

    # Resumable: prior manifest lines and already-downloaded WAVs are reused, so
    # a rate-limit crash mid-run costs nothing but the re-paging time.
    counts = {slug: 0 for slug in GROUPS.values()}
    have: set[int] = set()
    if manifest.exists():
        with manifest.open(encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                have.add(e["row_idx"])
                counts[e["group"]] += 1
        print(f"resuming: {len(have)} clips already in manifest")

    written = len(have)
    rejected_dur = rejected_dl = 0
    mf = manifest.open("a", encoding="utf-8")

    for offset in range(0, total, 100):
        if all(n >= args.per_group for n in counts.values()):
            break
        page = _rows_page(offset)
        time.sleep(1.0)  # pace the metadata pages; bursts trip the rate limit
        for item in page["rows"]:
            row = item["row"]
            slug = GROUPS.get(row.get("l1", ""))
            if slug is None or counts[slug] >= args.per_group:
                continue
            if item["row_idx"] in have or not _usable(row.get("text", "")):
                continue
            audio_refs = row.get("audio") or []
            if not audio_refs or "src" not in audio_refs[0]:
                continue
            wav = BENCH / "edacc" / slug / f"{item['row_idx']:05d}.wav"
            try:
                if wav.exists():  # downloaded by a crashed run; trust and reuse
                    audio = None
                    with wave.open(str(wav), "rb") as w:
                        dur = w.getnframes() / SR
                else:
                    # Asset URLs are signed with a short expiry, so download
                    # immediately rather than collecting URLs to fetch later.
                    audio, dur = _to_16k_mono(_get(audio_refs[0]["src"], binary=True))
            except Exception as e:  # noqa: BLE001 - skip the clip, keep the run
                rejected_dl += 1
                print(f"  skip row {item['row_idx']}: {e}", file=sys.stderr)
                continue
            if not (args.min_sec <= dur <= args.max_sec):
                rejected_dur += 1
                continue
            if audio is not None:
                _write_wav(wav, audio)
            mf.write(json.dumps({
                "wav": str(wav.relative_to(BENCH)).replace("\\", "/"),
                "ref": row["text"],
                "group": slug,
                "dataset": "edacc",
                "speaker": row.get("speaker", ""),
                "row_idx": item["row_idx"],
                "duration": round(dur, 2),
            }) + "\n")
            mf.flush()
            counts[slug] += 1
            written += 1
        done = ", ".join(f"{s}={n}" for s, n in counts.items())
        print(f"  rows 0-{min(offset + 100, total)}: {done}")

    mf.close()
    print(f"\nmanifest has {written} clips -> {manifest}")
    print(f"rejected: {rejected_dur} duration, {rejected_dl} download/decode")
    for slug, n in counts.items():
        if n < args.per_group:
            print(f"  note: {slug} capped at {n} (corpus exhausted or filtered)")


if __name__ == "__main__":
    main()
