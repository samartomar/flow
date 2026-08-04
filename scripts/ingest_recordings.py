"""Turn a volunteer's phone recording into scored benchmark clips (P3).

One continuous recording arrives per person. This cuts it into one clip per item and
writes the manifest the harnesses already read.

**Boundaries come from the spoken numbers, not from silence.** The recording page also
plays a tone on each advance, and the first real recording showed those do not survive
a phone speaker, a room and a phone mic — the best 880 Hz reading anywhere was barely
above what an injected tone at a third the level scores. The numbers survived
perfectly. So the numbers are the anchor and the tones are decoration.

Retakes are handled by taking the **last** occurrence of a number before the first
occurrence of the next one, which is what "say it again" produces. And the expected
sequence is enforced: a bare "one" inside a sentence cannot open item 1 if item 1 has
already been seen, so ordinary speech containing a number word does not shift every
label after it.

Usage:  uv run python scripts/ingest_recordings.py [--model small.en]
        reads  .bench/recorded/inbox/<group>_<id>.<ext>
        writes .bench/recorded/<group>/<id>_<NN>.wav
               .bench/recorded/manifest-recorded.jsonl
"""

from __future__ import annotations

import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.asr import decode_options  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / ".bench" / "recorded"
INBOX = ROOT / "inbox"
SR = 16000

#: Kept before the first word of a command and after its last. Swept, not guessed: at
#: 0.08 the plosive onset of the verb is lost and the router sees "the bit about the
#: standup" with no "delete" in front of it — 5/11 commands routed correctly. At 0.20
#: it is 9/11 and stays there through 0.50, so 0.20 is the knee.
PAD = 0.35
TAIL_PAD = 0.10

#: What each numbered item is supposed to do, in the order the recording page asks for
#: them. This is the answer key: the audio has no labels, the sequence does.
EXPECTED = [
    (1, "replace_all", "Tuesday -> Wednesday, both"),
    (2, "replace", "sameer -> Samir"),
    (3, "capitalize", "sameer -> Sameer"),
    (4, "lower", "RELEASE NOTES -> release notes"),
    (5, "delete", "remove the standup sentence"),
    (6, "delete_last", "remove the last sentence"),
    (7, "insert_before", "draft before release notes"),
    (8, "undo", "undo the last change"),
    (9, "polish", "make it a proper prompt"),
    (10, "followup", "add to something already sent"),
    (11, "rescue", "that was a command"),
    #: The six shipped trigger words, one item each, said alone (item 70).
    #:
    #: A different kind of item from the eleven above, and deliberately so. Those are
    #: *corrections* aimed at a draft and they measure the router; these are single words
    #: measuring the **decoder**, which is where root 5 lives — the trigger fails every
    #: voice but the owner's, and recognition had been measured at exactly one microphone
    #: (decisions.md 2026-08-03). `edits.SEND_WORD_PRESETS` passed a four-leg corpus gate
    #: that prices *false fires* and structurally cannot price recognition; this is the
    #: other half, and until these clips exist "the six presets decode" is a claim about
    #: one voice.
    (12, "trigger", "boom, said alone"),
    (13, "trigger", "tango, said alone"),
    (14, "trigger", "mango, said alone"),
    (15, "trigger", "falcon, said alone"),
    (16, "trigger", "rocket, said alone"),
    (17, "trigger", "banana, said alone"),
]

#: What each trigger item should have been said, by item number. Kept beside `EXPECTED`
#: rather than derived from `SEND_WORD_PRESETS` at read time, because the manifest is a
#: record of what somebody was *asked* to say: a preset swapped later must not silently
#: relabel a clip recorded against the old list.
TRIGGER_WORDS = {12: "boom", 13: "tango", 14: "mango", 15: "falcon",
                 16: "rocket", 17: "banana"}

#: The free-speech window that closes the session. It is numbered like the rest so it
#: has a boundary: the first recording proved spoken numbers survive a phone speaker,
#: a room and a phone mic intact, while tones, silence and punctuation do not.
#:
#: **It moved from 12 to 18 when the trigger words were added**, and older manifests keep
#: their numbering: nothing re-reads a manifest to renumber it, and `item: 0` is what a
#: free clip carries in every row ever written. A recording made against the old sheet
#: therefore ingests unchanged — the eleven items are still 1..11 — and only the free
#: window needs the newer sheet to be found by number rather than by `free_end`.
FREE_ITEM = 18

WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
}


def decode_audio(path: Path) -> np.ndarray:
    """Any phone format to 16 kHz mono, through the PyAV that faster-whisper ships.

    No ffmpeg on this machine and none needed — but `scripts/slim.py --apply` stubs
    `av` out to save ~100 MB, so ingestion must run on a non-slimmed install.
    """
    import av

    container = av.open(str(path))
    resampler = av.audio.resampler.AudioResampler(
        format="s16", layout="mono", rate=SR
    )
    chunks = []
    bad = 0
    # Demux and decode packet by packet rather than `container.decode()`, so one bad
    # packet costs a few milliseconds instead of the whole recording. The first real
    # phone recordings — raw MP3 streams named `.mpeg` — threw InvalidDataError partway
    # in, and the all-or-nothing loop discarded five minutes of a volunteer's time for
    # it. A recording is expensive and unrepeatable; a decoder that gives up on it is
    # the wrong trade.
    for packet in container.demux(container.streams.audio[0]):
        try:
            frames = packet.decode()
        except av.error.InvalidDataError:
            bad += 1
            continue
        for frame in frames:
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        raise ValueError("no audio decoded")
    if bad:
        # Never silent: a dropped packet is missing audio, and the person reading the
        # scores has to know the recording was not whole.
        print(f"  {path.name}: skipped {bad} undecodable packet(s)", file=sys.stderr)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def number_at(word: str) -> int | None:
    """The item number this word announces, or None. Punctuation is Whisper's."""
    w = word.strip().strip(".,:;!?-–—").lower()
    if w.isdigit():
        return int(w)
    return WORDS.get(w)


def find_boundaries(words: list[dict], n_items: int) -> dict[int, tuple[float, float]]:
    """(number start, speech start) for each item, keyed by item number.

    Sequential: item n is only looked for after item n-1 has been found, so a number
    word inside ordinary speech cannot capture a slot. Within that window the *last*
    occurrence wins, because saying a number twice is what a retake sounds like.

    Two times, not one, because the announced number is scaffolding and must not reach
    the router — a clip that opens with "two" is not a command, it is a sentence
    beginning with a number, and the first scoring run routed ten of eleven to
    dictation for exactly that reason. The number's start bounds the *previous* item;
    the following word's start opens this one.
    """
    starts: dict[int, tuple[float, float]] = {}
    expect = 1
    i = 0
    while expect <= n_items and i < len(words):
        hit = None
        j = i
        while j < len(words):
            n = number_at(words[j]["word"])
            if n == expect + 1 and hit is not None:
                break  # the next item has begun; stop looking for retakes of this one
            if n == expect:
                hit = j
            j += 1
        if hit is None:
            expect += 1
            continue
        # Not clamped to the number word's end: Whisper reports word ends late and
        # contiguous with the next start, so clamping silently zeroed the pad.
        speech = words[hit + 1]["start"] if hit + 1 < len(words) else words[hit]["end"]
        starts[expect] = (words[hit]["start"],
                          max(words[hit]["start"], speech - PAD))
        i = hit + 1
        expect += 1
    return starts


def free_end(words: list[dict], last_start: float, phrase: str) -> float | None:
    """Where the last prompted command stops and the free-speech window begins.

    Only used for recordings made before the sheet announced the free window as item
    12. Nothing else separates them: in the first real recording the largest silence
    anywhere after item 11 was 0.68 s, and Whisper punctuated the entire 17 s tail as
    one run-on, so neither pause nor full stop marks the seam. What is known is the
    prompted wording, so the end of *that* is the boundary; matching is phonetic
    because the whole point of these recordings is that the wording arrives accented.
    """
    from flow.phonetic import similarity

    want = phrase.lower().split()
    after = [w for w in words if w["start"] >= last_start][1:]  # skip the number
    best, best_score = None, 0.75
    for i in range(len(after) - len(want) + 1):
        window = after[i:i + len(want)]
        score = sum(
            similarity(w["word"].strip().strip(".,:;!?").lower(), t)
            for w, t in zip(window, want)
        ) / len(want)
        if score > best_score:
            best, best_score = window[-1]["end"], score
    return best


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((audio * 32767.0).astype(np.int16).tobytes())


def main() -> None:
    from faster_whisper import WhisperModel

    argv = sys.argv[1:]
    model_name = "small.en"
    if "--model" in argv:
        model_name = argv[argv.index("--model") + 1]

    # `.mpeg`/`.mpg` are here because a real phone produced them: the first Indian-accent
    # recordings arrived as MP3 in an .mpeg container. The decoder never cared — ffmpeg
    # reads the codec, not the extension — so an allow-list that omitted them silently
    # ingested nothing and said nothing about why.
    files = sorted(
        p for p in INBOX.glob("*")
        if p.suffix.lower() in {".m4a", ".mp3", ".mpeg", ".mpg", ".mp4", ".wav",
                                ".opus", ".aac", ".ogg", ".amr"}
    )
    # The id may be a name, not just a number. Volunteers are people, the files arrive
    # named after them, and `us-control_02` and `indian_vijaya01` are both useful — the
    # second more so, because the speaker travels with the clip into the manifest.
    # Still one underscore before the id, since the group is taken by rsplit.
    named = [p for p in files if re.match(r"^[a-z-]+_[a-z0-9-]+$", p.stem)]
    skipped = [p for p in files if p not in named]
    for p in skipped:
        print(f"  skipping {p.name}: not named <group>_<id> "
              f"(lower case, one underscore, e.g. indian_vijaya01)", file=sys.stderr)
    if not named:
        print(f"nothing to ingest in {INBOX}")
        return

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    manifest = ROOT / "manifest-recorded.jsonl"
    rows = []

    for path in named:
        group, ident = path.stem.rsplit("_", 1)
        audio = decode_audio(path)
        segments, _ = model.transcribe(
            audio, word_timestamps=True,
            **(decode_options(final=True) | {"temperature": (0.0,)}),
        )
        words, texts = [], []
        for seg in segments:
            texts.append(seg.text.strip())
            for w in (seg.words or []):
                words.append({"word": w.word, "start": w.start, "end": w.end})

        starts = find_boundaries(words, FREE_ITEM)
        free = starts.pop(FREE_ITEM, None)
        free_start = free[1] if free else None
        print(f"\n{path.name}: {len(audio) / SR:.0f}s, "
              f"{len(starts)}/{len(EXPECTED)} items located")

        ordered = sorted(starts.items())
        if free_start is None and ordered:
            free_start = free_end(words, ordered[-1][1][0], EXPECTED[-1][2])

        for idx, (num, (_, start)) in enumerate(ordered):
            # Ends where the *next* number is announced, not where its speech begins —
            # then pulled back to this item's own last word, because the announced
            # number is a whole syllable early in Whisper's own timing and otherwise
            # lands inside the clip ("undo that" came back as "Undo that. Nice.").
            bound = ordered[idx + 1][1][0] if idx + 1 < len(ordered) else (
                free_start if free_start else len(audio) / SR
            )
            mine = [w for w in words if start <= w["start"] < bound]
            end = min(bound, mine[-1]["end"] + TAIL_PAD) if mine else bound
            clip = audio[int(start * SR):int(end * SR)]
            if len(clip) < int(0.3 * SR):
                print(f"  item {num}: too short ({len(clip) / SR:.1f}s), skipped")
                continue
            # Whisper word tokens carry their own leading space; joining on " " too
            # doubles every gap.
            said = re.sub(
                r"\s+", " ",
                "".join(w["word"] for w in words if start <= w["start"] < end),
            ).strip()
            _, op, note = EXPECTED[num - 1]
            word = TRIGGER_WORDS.get(num)
            wav = ROOT / group / f"{ident}_{num:02d}.wav"
            write_wav(wav, clip)
            rows.append({
                "wav": str(wav.relative_to(ROOT)).replace(chr(92), "/"),
                "group": group,
                "speaker": f"{group}_{ident}",
                "item": num,
                "op": op,
                "intent": note,
                "said": said,
                "duration": round(len(clip) / SR, 2),
                "dataset": "recorded",
                # Only on a trigger row: the word the speaker was asked for, so a scorer
                # can compare it against `said` without re-deriving the sheet.
                **({"word": word} if word else {}),
            })
            print(f"  {num:2d} {start:6.1f}s +{len(clip) / SR:4.1f}s  "
                  f"[{op:<13}] {said[:52]}")

        if free_start is not None and len(audio) / SR - free_start > 3.0:
            clip = audio[int(free_start * SR):]
            said = re.sub(
                r"\s+", " ",
                "".join(w["word"] for w in words if w["start"] >= free_start),
            ).strip()
            wav = ROOT / group / f"{ident}_free.wav"
            write_wav(wav, clip)
            rows.append({
                "wav": str(wav.relative_to(ROOT)).replace(chr(92), "/"),
                "group": group, "speaker": f"{group}_{ident}", "item": 0,
                "op": "free", "intent": "unprompted", "said": said,
                "duration": round(len(clip) / SR, 2), "dataset": "recorded",
            })
            print(f"  free {free_start:6.1f}s +{len(clip) / SR:4.1f}s  "
                  f"[free         ] {said[:52]}")

    manifest.write_text(
        chr(10).join(json.dumps(r) for r in rows) + chr(10), encoding="utf-8"
    )
    print(f"\n{len(rows)} clips -> {manifest}")


if __name__ == "__main__":
    main()
