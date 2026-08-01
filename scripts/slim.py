"""Trim ~100 MB of unreachable dependencies out of the venv (R16).

Measured on this machine: a plain `uv sync` venv is **236.8 MB**; after this trim it is
**137.1 MB**, and the full test suite plus a real decode still pass. (The venv has grown
with dependency updates since — it reports its own current size when you run this.)

What it removes and why each is genuinely unreachable:

`onnxruntime` (+`protobuf`) - 33.7 MB
    Used by faster-whisper only for Silero VAD, imported lazily inside `vad.py`. Flow
    always passes `vad_filter=False` because `flow/audio.py` does its own speech gating,
    so the import never executes.

`av` -> replaced by a stub - 66 MB
    faster-whisper imports `av` at package import time, but every use of it sits inside
    `decode_audio()`, which decodes audio *files*. Flow feeds numpy arrays from
    sounddevice and never calls it. The stub satisfies the import and raises loudly if
    anything ever does reach for it.

**This deliberately breaks a dependency contract**, which is why it is opt-in rather than
the default. A future faster-whisper release could start touching `av` at import time or
enable VAD by default. Nothing here is precious: `uv sync` rebuilds the full venv, and
`--undo` reinstalls both packages.

    uv run python scripts/slim.py            # show the plan, change nothing
    uv run python scripts/slim.py --apply
    uv run python scripts/slim.py --undo
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

REMOVE = ("onnxruntime", "protobuf")
STUB_NAME = "av"

STUB = '''"""Stub for PyAV, installed by scripts/slim.py.

faster-whisper imports `av` at package import time but only uses it inside
`decode_audio()`, which decodes audio files. Flow feeds numpy arrays from sounddevice and
never calls it, so the real ~66 MB of FFmpeg binaries is unreachable code.

Reinstall the real package with:  uv pip install av
"""


def __getattr__(name):
    raise RuntimeError(
        f"av.{name} was accessed, but PyAV is stubbed out by scripts/slim.py. "
        "Flow never decodes audio files. Reinstall with: uv pip install av"
    )
'''


def site_packages() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def dir_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def uv(*args: str) -> int:
    cmd = ["uv", "pip", *args, "--python", sys.executable]
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd).returncode


def venv_root() -> Path:
    return Path(sys.prefix)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually perform the trim")
    ap.add_argument("--undo", action="store_true", help="reinstall what was removed")
    args = ap.parse_args()

    if sys.prefix == sys.base_prefix:
        print("refusing to run outside a virtual environment", file=sys.stderr)
        return 2

    sp = site_packages()
    before = dir_mb(venv_root())
    stub = sp / f"{STUB_NAME}.py"

    if args.undo:
        print(f"venv: {venv_root()}  ({before:.1f} MB)")
        if stub.exists():
            stub.unlink()
            print(f"  removed stub {stub.name}")
        uv("install", "av", "onnxruntime")
        print(f"restored: {dir_mb(venv_root()):.1f} MB")
        return 0

    real_av = sp / STUB_NAME
    plan = [f"uninstall {', '.join(REMOVE)}"]
    if real_av.is_dir():
        plan.append(f"uninstall {STUB_NAME} and replace it with a stub")
    elif stub.exists():
        plan.append(f"{STUB_NAME} is already stubbed")

    print(f"venv: {venv_root()}  ({before:.1f} MB)")
    for step in plan:
        print(f"  - {step}")

    if not args.apply:
        print("\nnothing changed. re-run with --apply to perform the trim.")
        return 0

    uv("uninstall", *REMOVE)
    if real_av.is_dir():
        uv("uninstall", STUB_NAME)
    # Written after the uninstall, or uv would remove it again along with the package.
    stub.write_text(STUB, encoding="utf-8")
    print(f"  wrote stub {stub}")
    for leftover in (sp / "av.libs",):
        if leftover.is_dir():
            shutil.rmtree(leftover, ignore_errors=True)
            print(f"  removed leftover {leftover.name}")

    after = dir_mb(venv_root())
    print(f"\n{before:.1f} MB -> {after:.1f} MB  (saved {before - after:.1f} MB)")
    print("verify with: uv run python -m unittest discover -s tests")
    print("undo with:   uv run python scripts/slim.py --undo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
