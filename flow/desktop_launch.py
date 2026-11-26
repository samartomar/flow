"""Windows session-wide ownership of the Flow desktop and its reopen requests."""

import ctypes
import mmap
import os
import struct
from contextlib import ExitStack
from ctypes import wintypes


class DesktopLaunch:
    def __init__(self, name: str = r"Local\SamarTomar.Flow") -> None:
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

        mutex = kernel.CreateMutexW
        mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        mutex.restype = wintypes.HANDLE
        self._release = kernel.ReleaseMutex
        self._release.argtypes = (wintypes.HANDLE,)
        # Open the signal before the mutex so a repeat launch can queue a
        # reopen even if the first launch has yet to build its window.
        with ExitStack() as resources:
            self._event = create(None, False, False, name + ".OpenHome")
            if not self._event:
                raise ctypes.WinError(ctypes.get_last_error())
            resources.callback(self._close, self._event)
            self._owner = resources.enter_context(mmap.mmap(-1, 4, tagname=name + ".Owner"))
            running = mutex(None, True, name + ".Running")
            error = ctypes.get_last_error()
            if not running:
                raise ctypes.WinError(error)
            resources.callback(self._close, running)
            self._running = running
            self.primary = error != 183  # ERROR_ALREADY_EXISTS
            if self.primary:
                struct.pack_into("I", self._owner, 0, os.getpid())
            self._resources = resources.pop_all()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        if self.primary:
            self._release(self._running)
        self._resources.close()

    def _take_over_if_idle(self) -> bool:
        # WAIT_OBJECT_0 or WAIT_ABANDONED means the previous owner has quit.
        if self._wait(self._running, 0) not in (0, 0x80):
            return False
        self.primary = True
        struct.pack_into("I", self._owner, 0, os.getpid())
        return True

    def reopen(self) -> bool:
        """True if sent to the running app, False if this launch took over."""
        if self._take_over_if_idle():
            return False
        # The launch from Explorer can give the existing Flow process its
        # foreground permission. If Windows denies it, the request still runs.
        owner, = struct.unpack_from("I", self._owner)
        if owner:
            allow = ctypes.WinDLL("user32").AllowSetForegroundWindow
            allow.argtypes = (wintypes.DWORD,)
            allow(owner)
        if not self._signal(self._event):
            raise ctypes.WinError(ctypes.get_last_error())
        return not self._take_over_if_idle()

    def requested(self) -> bool:
        # WAIT_OBJECT_0 means a request arrived. Reading it resets the event.
        return self._wait(self._event, 0) == 0
