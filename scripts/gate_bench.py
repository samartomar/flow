"""How much speech does the gate eat, and does pre-roll get it back? (defect 5)

A gate can only open after it has heard something loud enough, so the quiet head of
the word that opened it is already gone by then. That head is not silence — it is the
unaspirated stop, the soft fricative, the approximant carrying the consonant — and
losing it is worse in an accent, where the onset is often exactly the part a listener
needs most.

This measures the whole path rather than the gate alone: every clip is fed through the
real `SpeechGate` block by block, the audio the gate would have *kept* is reassembled,
and that is what gets decoded. WER against the reference is then the honest answer to
"what does gating cost", and the difference between pre-roll settings is what the ring
buffer buys.

Reported per setting:
  kept audio  - how much of the clip survived the gate
  WER         - on the gated audio, versus the same clips decoded whole

Decoding is pinned to a single temperature here. The app's finals ladder samples, and
that noise is the same size as the effect, so it would drown it.

Usage:  uv run python scripts/gate_bench.py [model] [--clips 80]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from accent_bench import BENCH, load_manifest, load_wav, wer_counts  # noqa: E402
from flow.asr import decode_options  # noqa: E402
from flow.audio import BLOCK, SpeechGate  # noqa: E402
from flow.clean import normalise  # noqa: E402
from flow.diag import bench_identity  # noqa: E402

SR = 16000


def gated_audio(audio: np.ndarray, preroll: int) -> np.ndarray:
    """What the session would have captured, reassembled.

    Runs the production `SpeechGate` and the production `_pump_audio` logic, so a
    change to either shows up here rather than in a copy that has quietly drifted.
    """
    gate = SpeechGate(preroll_blocks=preroll)
    kept: list[np.ndarray] = []
    for i in range(len(audio) // BLOCK):
        block = audio[i * BLOCK:(i + 1) * BLOCK]
        started, _stopped = gate.push(block)
        if gate.speaking:
            if started:
                kept.extend(gate.take_preroll())
            kept.append(block)
    return np.concatenate(kept) if kept else np.zeros(0, dtype=np.float32)


def main() -> None:
    from faster_whisper import WhisperModel

    argv = sys.argv[1:]
    n_clips = 80
    if "--clips" in argv:
        i = argv.index("--clips")
        n_clips = int(argv[i + 1])
        del argv[i:i + 2]
    name = argv[0] if argv else "base.en"

    entries = load_manifest()[:n_clips]
    model = WhisperModel(name, device="cpu", compute_type="int8")
    print(f"{len(entries)} clips, MODEL={name}\n")

    def decode(audio):
        # Temperature pinned to a single step, which the app does not do: the finals
        # ladder samples, and sampling noise on 80 clips is the same size as the
        # effect being measured. The variable under test is the audio, so everything
        # else has to be deterministic.
        opts = decode_options(final=True) | {"temperature": (0.0,)}
        segments, _ = model.transcribe(audio, **opts)
        return normalise(" ".join(s.text.strip() for s in segments))

    rows = {}
    ungated_edits = ref_words = 0
    for e in entries:
        audio = load_wav(BENCH / e["wav"])
        ed, n = wer_counts(e["ref"], decode(audio))
        ungated_edits += ed
        ref_words += n
    print(f"{'condition':<22}{'WER':>8}{'kept audio':>12}")
    print(f"{'ungated (whole clip)':<22}{ungated_edits / ref_words:>8.3f}{'100%':>12}")

    total_audio = sum(len(load_wav(BENCH / e["wav"])) for e in entries)
    for preroll in (0, 2, 4, 8):
        edits = kept_samples = 0
        for e in entries:
            audio = load_wav(BENCH / e["wav"])
            gated = gated_audio(audio, preroll)
            kept_samples += len(gated)
            edits += wer_counts(e["ref"], decode(gated))[0]
        label = f"gated, preroll {preroll * BLOCK * 1000 // SR} ms"
        print(f"{label:<22}{edits / ref_words:>8.3f}"
              f"{kept_samples / total_audio:>11.1%}")
        rows[preroll] = {"wer": edits / ref_words, "kept": kept_samples / total_audio}

    out = BENCH / f"gate-{name}.json"
    out.write_text(json.dumps({"identity": bench_identity(models=(name,)),
                               "model": name, "n": len(entries),
                               "ungated_wer": ungated_edits / ref_words,
                               "rows": rows}, indent=1), encoding="utf-8")
    print(f"\ndetail -> {out}")


if __name__ == "__main__":
    main()
