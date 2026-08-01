"""Does biasing the decoder with a personal lexicon actually recover words? (P4)

Three questions, three numbers:

  1. **Recovery.** Take the rare words a clip's reference contains that the model got
     wrong, put exactly those in the lexicon, decode again. How many come back? This
     is an *oracle* — the lexicon is built from the answer key — so it measures the
     ceiling of the mechanism, not what a user's own list will achieve. Stated up
     front because an oracle number quoted as a product number is a lie.

  2. **Harm.** Decode the same clips with a lexicon of plausible but irrelevant terms
     (a developer's tool vocabulary against conversational EdAcc speech). This is the
     realistic case — most of a user's lexicon is irrelevant to most utterances — and
     the question is whether biasing costs accuracy when it does not help.

  3. **Cost.** Decode latency with a full lexicon versus none.

"Rare" is defined from the corpus itself rather than an imported word list: a word in
fewer than `COMMON_MIN` references is rare. Self-contained, and it adapts to whatever
slice is being measured.

Usage:  uv run python scripts/lexicon_bench.py [model] [--clips 100] [--harm]
        default model: small.en (the finals tier — where the pasted text is decided)
        --harm sweeps WER against lexicon size, which is what sets MAX_TERMS
"""

from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from accent_bench import BENCH, load_manifest, load_wav, norm_words, wer_counts  # noqa: E402
from flow.asr import decode_options  # noqa: E402
from flow.clean import normalise  # noqa: E402
from flow.diag import bench_identity  # noqa: E402
from flow.lexicon import MAX_TERMS, parse  # noqa: E402

#: A word in fewer references than this counts as rare — the kind of thing a personal
#: lexicon would carry.
COMMON_MIN = 3

#: A plausible lexicon for this project's user, and irrelevant to EdAcc's chat about
#: holidays and university. Exactly the mismatch a real user hits most of the time.
DISTRACTORS = parse("""
Kubernetes kubectl Grafana Prometheus Terraform Ansible Postgres Redis Kafka
ctranslate2 sounddevice numpy tkinter ctypes idempotent kubelet sidecar envoy
istio helm kustomize argocd loki tempo jaeger opentelemetry datadog sentry
pagerduty pulumi vault consul nomad packer vagrant docker podman containerd
runc systemd journald nginx haproxy traefik caddy linkerd cilium calico
flannel weave webhook middleware goroutine mutex semaphore idempotency
serialization deserialization normalization tokenizer quantization
""".replace(" ", "\n"))


def decode(model, audio, hotwords=None):
    opts = decode_options(final=True)
    if hotwords:
        opts["hotwords"] = hotwords
    t = time.perf_counter()
    segments, _ = model.transcribe(audio, **opts)
    text = normalise(" ".join(s.text.strip() for s in segments))
    return text, time.perf_counter() - t


def harm_sweep(model, entries, sizes) -> None:
    """WER against lexicon size, with terms that are irrelevant to the audio.

    The realistic case. A user's lexicon is their vocabulary, not this utterance's
    vocabulary, so most of it is noise most of the time — and biasing a decoder toward
    words that are not being said is not free. This is what sets MAX_TERMS.

    The last condition mixes the oracle terms into a distractor list, which is the
    actual product question: does a real term still get recovered when it is buried in
    irrelevant ones?
    """
    freq = collections.Counter()
    for e in entries:
        freq.update(set(norm_words(e["ref"])))
    rare = {w for w, c in freq.items() if c < COMMON_MIN}

    print(f"\n{'lexicon':<22}{'WER':>8}{'terms':>7}{'recovered':>11}")
    base_edits = base_n = 0
    per_clip_targets = {}
    for e in entries:
        audio = load_wav(BENCH / e["wav"])
        text, _ = decode(model, audio)
        ed, n = wer_counts(e["ref"], text)
        base_edits += ed
        base_n += n
        heard = set(norm_words(text))
        per_clip_targets[e["wav"]] = [
            w for w in dict.fromkeys(norm_words(e["ref"]))
            if w in rare and w not in heard
        ][:MAX_TERMS]
    print(f"{'none (baseline)':<22}{base_edits / base_n:>8.3f}{0:>7}{'-':>11}")

    for size in sizes:
        edits = 0
        for e in entries:
            audio = load_wav(BENCH / e["wav"])
            text, _ = decode(model, audio, " ".join(DISTRACTORS[:size]))
            edits += wer_counts(e["ref"], text)[0]
        print(f"{'distractors only':<22}{edits / base_n:>8.3f}{size:>7}{'-':>11}")

    # Mixed: the user's real terms buried in irrelevant ones.
    for size in sizes:
        edits = targets = got = 0
        for e in entries:
            audio = load_wav(BENCH / e["wav"])
            mine = per_clip_targets[e["wav"]]
            terms = mine + DISTRACTORS[:size]
            text, _ = decode(model, audio, " ".join(terms[:MAX_TERMS]))
            edits += wer_counts(e["ref"], text)[0]
            back = set(norm_words(text))
            targets += len(mine)
            got += sum(1 for w in mine if w in back)
        print(f"{'mine + distractors':<22}{edits / base_n:>8.3f}{size:>7}"
              f"{f'{got}/{targets}':>11}")


def main() -> None:
    from faster_whisper import WhisperModel

    argv = sys.argv[1:]
    n_clips = 100
    if "--clips" in argv:
        i = argv.index("--clips")
        n_clips = int(argv[i + 1])
        del argv[i:i + 2]
    sweep = "--harm" in argv
    argv = [a for a in argv if not a.startswith("--")]
    name = argv[0] if argv else "small.en"

    entries = load_manifest()[:n_clips]
    freq = collections.Counter()
    for e in entries:
        freq.update(set(norm_words(e["ref"])))
    rare = {w for w, c in freq.items() if c < COMMON_MIN}
    print(f"{len(entries)} clips, {len(freq)} distinct reference words, "
          f"{len(rare)} rare (in < {COMMON_MIN} references)")
    print(f"distractor lexicon: {len(DISTRACTORS)} terms")

    model = WhisperModel(name, device="cpu", compute_type="int8")
    print(f"MODEL={name}\n")

    if sweep:
        harm_sweep(model, entries, (8, 32))
        return

    stats = {
        "base": [0, 0, 0.0], "oracle": [0, 0, 0.0], "distract": [0, 0, 0.0],
    }  # edits, ref_words, seconds
    targets = recovered = 0
    clips_with_targets = 0
    detail = []

    for i, e in enumerate(entries):
        audio = load_wav(BENCH / e["wav"])
        ref_words = norm_words(e["ref"])

        base_text, dt = decode(model, audio)
        ed, n = wer_counts(e["ref"], base_text)
        stats["base"][0] += ed
        stats["base"][1] += n
        stats["base"][2] += dt

        # The oracle lexicon: rare reference words this decode missed.
        heard = set(norm_words(base_text))
        missing = [w for w in dict.fromkeys(ref_words) if w in rare and w not in heard]
        missing = missing[:MAX_TERMS]

        dis_text, dt = decode(model, audio, " ".join(DISTRACTORS))
        ed, _ = wer_counts(e["ref"], dis_text)
        stats["distract"][0] += ed
        stats["distract"][1] += n
        stats["distract"][2] += dt

        if missing:
            clips_with_targets += 1
            targets += len(missing)
            orc_text, dt = decode(model, audio, " ".join(missing))
            ed, _ = wer_counts(e["ref"], orc_text)
            stats["oracle"][2] += dt
            back = set(norm_words(orc_text))
            got = [w for w in missing if w in back]
            recovered += len(got)
            detail.append({"wav": e["wav"], "group": e["group"], "targets": missing,
                           "recovered": got, "base": base_text, "oracle": orc_text})
        else:
            # Nothing to bias toward, so the oracle condition *is* the baseline here.
            # Scoring it as such keeps all three columns over the same clips; scoring
            # only the clips with targets would flatter the oracle column by dropping
            # every clip the model already got right.
            ed = wer_counts(e["ref"], base_text)[0]
        stats["oracle"][0] += ed
        stats["oracle"][1] += n

        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(entries)} clips...")

    print(f"\n{'condition':<12}{'WER':>8}{'ref words':>11}{'decode s':>10}")
    for key in ("base", "oracle", "distract"):
        ed, n, secs = stats[key]
        print(f"{key:<12}{ed / max(1, n):>8.3f}{n:>11}{secs:>10.1f}")

    print(f"\nrecovery: {recovered}/{targets} rare words returned "
          f"({recovered / max(1, targets):.1%}), over {clips_with_targets} clips "
          f"that had any missing rare word")
    out = BENCH / f"lexicon-{name.replace('/', '_')}.json"
    out.write_text(json.dumps({"identity": bench_identity(models=(name,)),
                               "model": name, "stats": stats, "targets": targets,
                               "recovered": recovered, "detail": detail}, indent=1),
                   encoding="utf-8")
    print(f"detail -> {out}")


if __name__ == "__main__":
    main()
