"""Windows session-wide ownership of the Flow desktop and its reopen requests."""

import ctypes
from ctypes import wintypes


class DesktopLaunch:
    def __init__(self, name: str = r"Local\SamarTomar.Flow.OpenHome") -> None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateEventW
        create.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
        create.restype = wintypes.HANDLE
        self._signal = kernel.SetEvent
        self._signal.argtypes = (wintypes.HANDLE,)
        self._wait = kernel.WaitForSingleObject
        self._wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self._wait.restype = wintypes.DWORD
        self._close = kernel.CloseHandle
        self._close.argtypes = (wintypes.HANDLE,)

        # The first creator keeps this auto-reset event open for the lifetime of
        # its desktop. Later launches signal the same event, even during startup.
        self._event = create(None, False, False, name)
        error = ctypes.get_last_error()
        if not self._event:
            raise ctypes.WinError(error)
        self.primary = error != 183  # ERROR_ALREADY_EXISTS

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._close(self._event)

    def reopen(self) -> None:
        if not self._signal(self._event):
            raise ctypes.WinError(ctypes.get_last_error())

    def requested(self) -> bool:
        # WAIT_OBJECT_0 means a request arrived. Reading it resets the event.
        return self._wait(self._event, 0) == 0
