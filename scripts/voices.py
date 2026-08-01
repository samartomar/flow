"""Which voices this machine has, and what each one sounds like.

Choosing a voice from a list of names is choosing blind, and the whole reason this
exists is that Flow spent its life speaking in whichever voice the engine defaulted to
— on the development machine, the oldest one installed. So this speaks the same
sentence in each, out loud, and prints the exact name to pass to `--voice`.

    uv run python scripts/voices.py                 # list them
    uv run python scripts/voices.py --speak         # say a line in each, in turn
    uv run python scripts/voices.py --speak --wav   # write them to .bench/voices/ instead

If the list is short and they all sound dated, that is the machine and not Flow: Windows
ships better voices than it installs. Settings > Accessibility > Narrator > Add natural
voices, and whatever is added appears here — `System.Speech` reads the same OneCore
store those are registered in, which is checked in the note on `installed_voices`.
"""

from __future__ import annotations

import argparse
import base64
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.speak import Speaker, host, installed_voices  # noqa: E402

#: Long enough to hear prosody rather than just timbre, and it is a real answer of the
#: kind converse mode produces — a voice that handles an acronym and a number badly is
#: worth discovering here rather than mid-conversation.
SAMPLE = (
    "Word Error Rate is the fraction of words a transcriber gets wrong. "
    "Under ten percent is usually considered good."
)

OUT = Path(__file__).resolve().parent.parent / ".bench" / "voices"


def to_wav(name: str, path: Path) -> bool:
    """Speak `SAMPLE` in `name` to a WAV, without touching the speakers."""
    b64 = base64.b64encode(SAMPLE.encode("utf-8")).decode("ascii")
    nb64 = base64.b64encode(name.encode("utf-8")).decode("ascii")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "try{$s.SelectVoice([Text.Encoding]::UTF8.GetString("
        f"[Convert]::FromBase64String('{nb64}')))}}catch{{exit 1}};"
        "$s.Rate=1;"
        f"$s.SetOutputToWaveFile('{path}');"
        "$s.Speak([Text.Encoding]::UTF8.GetString("
        f"[Convert]::FromBase64String('{b64}')));"
        "$s.Dispose();"
    )
    # `host()`, not "powershell". Hardcoding the latter is what the first version did,
    # and every OneCore voice failed to render: 5.1 cannot select them, the `catch`
    # exited 1, and this reported FAIL for exactly the voices worth auditioning.
    done = subprocess.run(
        [host(), "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
    )
    return done.returncode == 0 and path.exists()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speak", action="store_true", help="say a line in each voice")
    ap.add_argument("--wav", action="store_true",
                    help="with --speak, write WAVs to .bench/voices/ instead of playing")
    args = ap.parse_args()

    voices = installed_voices()
    if not voices:
        print("no speech engine found, or no voices installed", flush=True)
        raise SystemExit(1)

    width = max(len(v.name) for v in voices)
    print(f"{len(voices)} installed:\n", flush=True)
    for v in voices:
        print(f"  {v.name:<{width}}  {v.gender:<7} {v.culture}", flush=True)
    print(f"\n  uv run flow --voice {voices[0].name!r}", flush=True)
    print("  ...or part of a name, or just male / female", flush=True)

    if not args.speak:
        return

    if args.wav:
        OUT.mkdir(parents=True, exist_ok=True)
        print(f"\nwriting to {OUT}", flush=True)
        for v in voices:
            path = OUT / (v.name.replace(" ", "-") + ".wav")
            print(f"  {'ok  ' if to_wav(v.name, path) else 'FAIL'} {path.name}",
                  flush=True)
        return

    print("\nspeaking - listen:", flush=True)
    for v in voices:
        print(f"  {v.describe()}", flush=True)
        # A fresh Speaker per voice rather than one that switches: this is the path a
        # user takes on the next launch, and a host that has already spoken in another
        # voice is not that path.
        speaker = Speaker(voice=v.name)
        speaker.say(f"{v.name.replace('Microsoft ', '')}. {SAMPLE}")
        while speaker.speaking:
            time.sleep(0.1)
        speaker.close()
        time.sleep(0.3)


if __name__ == "__main__":
    main()
