# -*- mode: python ; coding: utf-8 -*-
"""What the Windows bundle needs, and why each line of it is here.

A spec file is a measurement of a dependency tree, not a scratch artifact — every entry
below is something the bundle was observed to need, so it is committed and it explains
itself. Built with:

    uv run --with pyinstaller pyinstaller --noconfirm packaging/flow.spec

`--with` rather than a dependency: PyInstaller is a build tool and never enters the venv
Flow runs in, which is the same argument `pyproject.toml` makes for hatchling. R16's
three runtime dependencies are unchanged by anything in this file.

**onedir, never onefile.** A onefile exe unpacks itself into a temp directory on every
launch — a cost paid at every start for a download that is the same size — and it is the
shape antivirus heuristics are most suspicious of, which matters for an unsigned build
that already asks the user past SmartScreen once. A zip of a onedir tree is the same
download with neither cost.

**The models are not in here.** `base.en` (141 MiB) and `small.en` (464 MiB) download to
the Hugging Face cache on first decode, exactly as they do for a dev install, and the
startup line names the path. Bundling them would quadruple the download and freeze two
files that are meant to be swappable with `--model`.
"""

import os
import sys

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

# Measured, not assumed: `collect_all("ctranslate2")` put a second copy of the 57 MB
# `ctranslate2.dll` under `_internal/ctranslate2/` beside the one PyInstaller's own
# dependency scan of `_ext.pyd` already places at `_internal/`. 114 MB for one engine.
# So faster_whisper gets `collect_all` (it has data files to carry) and ctranslate2 is
# left to the scan, which is what actually resolves the DLL at runtime — the launch
# check below the build is what says that is true rather than plausible.

ROOT = os.path.dirname(SPECPATH)  # noqa: F821 — PyInstaller injects SPECPATH
sys.path.insert(0, ROOT)

datas = []
binaries = []
hiddenimports = collect_submodules("flow")

# `faster_whisper` carries data files nothing imports — its tokenizer config, and the
# VAD asset it ships whether or not anything uses it — so an import scan alone leaves
# the package half-built.
fw_datas, fw_binaries, fw_hidden = collect_all("faster_whisper")
datas += fw_datas
binaries += fw_binaries
hiddenimports += fw_hidden

# `sounddevice` is a CFFI wrapper around a PortAudio DLL that ships in a *separate*
# top-level package, `_sounddevice_data`, which nothing imports by name — so it is
# invisible to import analysis and its absence is not an ImportError but a bundle with
# no microphone at all.
datas += collect_data_files("_sounddevice_data")
_sd_datas, _sd_binaries, _sd_hidden = collect_all("sounddevice")
datas += _sd_datas
binaries += _sd_binaries
hiddenimports += _sd_hidden

# PyInstaller collects modules, not distributions, so a frozen bundle carries no
# `.dist-info` unless it is asked for one — and `flow --version` is
# `importlib.metadata.version("flow")` (see `flow/version.py`). Without this the exe
# answers "no package metadata", which is the wrong copy to be unable to identify: the
# zip is what a stranger downloads, the download link always serves the newest one, and
# the exe is the only thing that can tell them which one they got. Resolved at build
# time against the installed project, so a build environment with no `flow` installed
# fails here rather than shipping a bundle that cannot name itself.
datas += copy_metadata("flow")

a = Analysis(  # noqa: F821
    [os.path.join(SPECPATH, "entrypoint.py")],  # noqa: F821
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir: everything else lands beside the exe
    name="flow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX is refused deliberately. It is the single strongest heuristic signal to a
    # Windows AV engine, and this build is already unsigned — buying a smaller download
    # with a higher chance of being quarantined is the wrong trade for the first thing
    # a stranger runs.
    upx=False,
    # A console, because Flow's startup lines *are* its diagnostics: which CLI it found,
    # which models, where the trace is, which hotkeys registered. The README tells people
    # to read them first when something is not working, so they need somewhere to appear.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="flow",
)
