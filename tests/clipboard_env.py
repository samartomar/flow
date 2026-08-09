"""Make the clipboard a fact the test declares, not one the machine happens to hold.

The same lesson as `cli_env.py`, one seam along, and found the same way — by a suite
that went red for a reason that had nothing to do with the change under it. 28 tests in
`test_inject_target` failed together, having passed an hour earlier on the same commit,
because a screenshot had been copied in between. Every one of them mocks the clipboard:
`get_clipboard_text`, `set_clipboard_text`, `clipboard_sequence`. They mock every door
but one. `paste()` also calls `clipboard_formats()`, which enumerates the **real**
Windows clipboard, so an image on it added

    your clipboard held an image - it will not be restored after this paste

to a warning list the tests then compared against `[]`. The code was right, the warning
was right, and the tests were reading the developer's desktop as a premise.

Sealed for the module rather than at the 28 call sites, and that is the point: the next
test to call `paste()` is sealed without its author having to know this happened. The
handful that *are* about what the clipboard holds patch the same name themselves, and an
inner patch wins and unwinds back to this one.

What the seal declares is an ordinary text clipboard rather than an empty one. Both are
silent, so nothing here turns on the choice — but `unrestorable()` is silent about them
for different reasons, and "text, which comes back" is the state a real machine is
almost always in, where "nothing at all" is the one it almost never is.
"""

import sys
from unittest import mock


class _Unsealed:
    """Off Windows there is no clipboard to seal.

    `flow.inject` binds `ctypes.WinDLL` at import, which is why the two modules that
    reach for `paste()` from behind a `skipUnless` never import it at module scope. A
    seal that imported it to install itself would be exactly the import those guards
    exist to avoid — so on the non-Windows legs this is a pair of no-ops, and the tests
    it would have protected are skipped anyway.
    """

    def start(self):
        pass

    def stop(self):
        pass


def sealed_clipboard():
    """A patcher for a test module to `start()` in setUp and `stop()` in tearDown.

        _CLIPBOARD = sealed_clipboard()

        def setUpModule():
            _CLIPBOARD.start()

        def tearDownModule():
            _CLIPBOARD.stop()
    """
    if sys.platform != "win32":  # pragma: no cover - the CI legs that are not Windows
        return _Unsealed()

    from flow.inject import CF_UNICODETEXT

    return mock.patch("flow.inject.clipboard_formats", return_value=[CF_UNICODETEXT])
