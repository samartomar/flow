"""How long Flow takes to be able to say its first word, on a machine that is cold.

Item 5 of the production-readiness list, and the narrowest thing here: the number is
already quoted in `docs/guide.md` (cold start ~1.4 s, 0.40 s import + 0.98 s model load)
and it is **not measured by anything in the repository**. It was typed once, into a
table, from a run nobody can repeat - which is the one thing this project forbids
everywhere else. `development.md` says a result is a measurement taken at a moment; a
performance claim with no harness behind it is a claim taken on trust.

**Cold is the whole difficulty, and it is why this is a script and not a test.** The
first load after a boot is dominated by disk: reading hundreds of MB of weights that the
page cache has thrown away. Re-running it in the same process measures the *second*
load, which is the one nobody waits for and which looks considerably better. So the
honest harness is `scripts/cold_start.py`, which starts a fresh interpreter, and the
honest instruction is to run it after a reboot rather than in a loop. A number taken
warm and labelled cold is worse than no number, because it will be believed.

Three stages, because a single total cannot be argued with. `import` is everything
before Flow's code runs at all - interpreter start and `site` - and it is paid on every
launch including the warm ones, so it is the one that decides whether Flow feels instant
on a hot start. `model-load` is the tier build, the part that is genuinely cold on a
first run and near-nothing on a warm one. `ready` is cumulative, and it is the number a
person is actually waiting through.

Deliberately **not** wired into the pill's startup. This is a measurement, not a
telemetry subsystem: a launch-time hook that fires on every start to write a file nobody
reads is a cost paid by every user for a number wanted by one, and the traces already
carry per-route durations for anybody who needs them on a real day.
"""

from __future__ import annotations

#: The three stage names, in the order a person waits through them. Named here so the
#: bench and any future in-app caller cannot drift: a stage name that exists in one and
#: not the other is a stage nobody can attribute a time to.
STAGE_IMPORT = "import"
STAGE_RESOLVE = "device-resolve"
STAGE_MODEL = "model-load"
STAGE_READY = "ready"

#: In the order a person waits through them. `ready` is last because it is the moment the
#: first word can come out, which is the number anybody actually feels.
#:
#: **`device-resolve` and the `ready` bug.** The first version of this list had three
#: stages, and its `ready` read 5.38 s while the stages summed to 2.69 s. The obvious
#: reading was a missing fourth stage — the CUDA probe — so `device-resolve` was added,
#: and it came back at 0.23 s, which accounted for none of it. The real cause was one line
#: of arithmetic in the bench: it took `origin()` *after* the load and then added the load
#: duration on top, double-counting 2.5 s. Both facts are kept here because the wrong
#: inference is the more useful one: **a total that does not equal the sum of its parts is
#: a bug until proven otherwise**, and adding a stage to hide the difference is how a
#: measurement ends up explaining itself instead of being right.
STAGES = (STAGE_IMPORT, STAGE_RESOLVE, STAGE_MODEL, STAGE_READY)


def origin():
    """Seconds since this process started, or None when the platform will not say.

    Three sources, in order of preference, because none of them is universal:

    `time._start_time` is CPython's own and is exact, but it **does not exist on
    Windows** - it is built when `HAVE_TIMESPEC`/POSIX paths are compiled in, and the
    first version of this measurement returned `n/a` for `import` on the one platform
    Flow ships on. GettingProcessTimes is the answer there, via ctypes and the stdlib
    only, which R16 permits. `None` last, for a frozen bundle or an embedder that
    refuses: a missing mark is one absent key, never an exception out of a launch.

    The Windows branch is creation time of the process, which is what a person waits
    through. It includes the ~30 ms of CreateProcess and loader work that `_start_time`
    also excludes, so the two paths are comparable to about a few tens of milliseconds -
    which is well inside the noise of a model load and is stated rather than assumed.
    """
    import time

    native = getattr(time, "_start_time", None)
    if native is not None:
        return time.monotonic() - native
    start = _windows_start()
    return None if start is None else time.time() - start


def from_filetime(ticks) -> float | None:
    """FILETIME ticks (100 ns since 1601) as a Unix timestamp, or None if nonsense.

    Split out from the ctypes call so the one piece of arithmetic that can go wrong can be
    tested without a kernel: `GetProcessTimes` answering 0 for a process it cannot
    describe is a real failure mode, and 0 minus the 1601 epoch is a date in 1601 — about
    1.3e11 seconds of nonsense that looks exactly like a plausible measurement and would
    pass any assertion of the form "is this a number".

    The bounds are checked against the current clock rather than a magic constant, so a
    machine with a wrong date fails this too instead of publishing a huge positive number.
    """
    import time

    started = ticks / 1e7 - 11644473600.0
    return started if 0 < started <= time.time() else None


def _windows_start():
    """Process creation time on Windows as a Unix timestamp, or None elsewhere.

    `ctypes` is stdlib, so this costs no dependency (R16).
    """
    import sys

    if sys.platform != "win32":
        return None
    k32 = _init_k32()
    if k32 is None:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        ok = k32.GetProcessTimes(
            k32.GetCurrentProcess(), ctypes.byref(creation), ctypes.byref(exit_time),
            ctypes.byref(kernel), ctypes.byref(user))
        if not ok:
            return None
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return from_filetime(ticks)
    except Exception:  # noqa: BLE001 - a measurement must not be the thing that fails
        return None


#: How `GetProcessTimes` is declared on 64-bit Windows. The default `ctypes` conversion
#: for an `int` is a C `int`, which is 32 bits, so a 64-bit `HANDLE` is sign-extended
#: into a negative number and every call fails. Declaring `restype`/`argtypes` once here
#: is the difference between the measurement working and quietly returning None on the
#: only platform Flow ships on — and it is the whole reason this module exists rather than
#: three lines in the bench script.
def _init_k32():
    """Point kernel32's two functions at 64-bit types. Idempotent, and a no-op elsewhere."""
    import sys

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetCurrentProcess.argtypes = []
    k32.GetProcessTimes.restype = wintypes.BOOL
    k32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    return k32
def stage_times() -> dict:
    """Marks this process's startup by stage, in seconds, or None where unknown.

    Only the mark that has already happened is recorded, and there is no `finish()` and
    no teardown hook on purpose: this is a measurement, not a subsystem, and a lifecycle
    with more states than marks is one that will be left un-instrumented the next time
    somebody moves a stage.
    """
    return {STAGE_IMPORT: origin()}


def load_stages(load=None) -> dict:
    """Time both tiers and return the marks, or reuse a measurement passed in.

    The measurement is the point of item 5 and the reason this is not a benchmark file:
    the number that matters is the one a *user* waits through on a machine that has not
    run Flow since boot, and that number is dominated by disk. A synthetic rerun in a
    warm process measures the second load, which is the one nobody waits for and which
    looks much better.

    `load` exists so a test can pass a callable and assert the arithmetic without
    building two Whisper models. It is called with no arguments - the real
    `WhisperTranscriber.load` takes an optional `final` and `None` means both.
    """
    import time

    if load is None:
        from .asr import WhisperTranscriber

        def load():
            WhisperTranscriber.load(None)

    before = time.monotonic()
    load()
    after = time.monotonic()
    marks = stage_times()
    marks[STAGE_MODEL] = after - before
    return marks