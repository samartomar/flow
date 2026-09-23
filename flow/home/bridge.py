"""The one way Flow Home's threads touch the session: posted to its thread, and waited on.

The session is driven from one thread by the pull contract both surfaces follow, and it
is not thread-safe. Flow Home's requests arrive on the HTTP server's threads, so every
read of live state and every change goes through `Session.post` and is run by the next
frame's `pump_results`. The request thread waits on the answer here.
"""

from __future__ import annotations

import threading

#: How long a request waits for the pill's next frame. Frames are 30 ms apart, so this
#: is dozens of frames of slack; past it the pill is not pumping at all — a native menu's
#: modal loop, a design switch rebuilding the window — and the page is told to try again
#: rather than left hanging on a socket.
CALL_TIMEOUT_SEC = 2.0


class Busy(Exception):
    """The session did not run the call in time."""


class Bridge:
    """Run a function on the session's thread and hand its answer back.

    `post` is `Session.post`, or anything with its shape — the tests and the demo pass a
    queue they drain by hand, which is the whole reason this takes a function rather
    than a session.
    """

    def __init__(self, post) -> None:
        self._post = post

    def call(self, fn, timeout: float = CALL_TIMEOUT_SEC):
        """`fn()`, run on the session's thread. Its exception is re-raised here.

        A call that times out may still run later, when the pill pumps again. That is
        accepted rather than cancelled: every call Home makes is a setting somebody
        asked for, and the page re-reads the state after an error, so the change shows
        up where they are looking as soon as it lands.
        """
        done = threading.Event()
        box: dict = {}

        def run() -> None:
            try:
                box["value"] = fn()
            except BaseException as exc:  # handed back to the caller, not swallowed
                box["error"] = exc
            finally:
                done.set()

        self._post(run)
        if not done.wait(timeout):
            raise Busy("Flow did not answer in time - it may be showing a menu")
        if "error" in box:
            raise box["error"]
        return box.get("value")
