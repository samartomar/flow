"""Flow Home: one window for everything that isn't talking (decisions.md 2026-09-22).

The pill is where somebody talks, and it never grows a setting. Everything else a
product has to offer — which speech model, which microphone, which shortcut, which
project Ask answers about, what Flow has heard and learned — lives here, in a window of
its own, instead of in command-line flags and files nobody should have to edit.

The window is HTML, served from this process on 127.0.0.1 (`server.py`) and shown in an
Edge app window (`window.py`); the page talks to `api.py`, and `api.py` talks to the
session only through `bridge.py`, on the session's own thread. The server does not start
until somebody opens the window, so a session that never does never listens on a port.
"""

from __future__ import annotations

import threading

from . import window
from .api import Api
from .bridge import Bridge
from .models import ModelManager
from .server import HomeServer

#: The pages the window has, by the name the URL and the rail use.
PAGES = ("home", "history", "voice", "ask", "models", "settings")


class Home:
    """Flow Home for one session: the window, its server, and what it can change."""

    def __init__(self, session, *, profile=None, hotkeys=None, lite: bool = False,
                 lexicon_path=None, trace_path=None) -> None:
        self.session = session
        self.profile = profile
        self.hotkeys = hotkeys
        self.lite = lite
        self.lexicon_path = lexicon_path
        self.trace_path = trace_path
        #: The pill on screen, and which design it is. Set by `__main__.build` every
        #: time a surface is built, because a design switch replaces both.
        self.surface = None
        self.design: str | None = None
        #: A model choice waiting on a download: (partial, final, device). Applied by
        #: `_downloaded` when the model it needs lands. See `Api.model_use`.
        self.pending_models: tuple | None = None
        self.bridge = Bridge(session.post)
        self.models = ModelManager(session, on_downloaded=self._downloaded)
        #: What the Voice page's listening tasks open instead of a real microphone, or
        #: None for the real one. The demo and the suite set it.
        self.mic_factory = None
        from .voice import VoiceTasks

        self.voice = VoiceTasks(self)
        self.api = Api(self)
        self._server: HomeServer | None = None
        self._lock = threading.Lock()
        self._navigate: str | None = None

    # -- the window ------------------------------------------------------------

    def server(self) -> HomeServer:
        """The server, started the first time it is needed."""
        with self._lock:
            if self._server is None:
                server = HomeServer(self.api.handle)
                server.start()
                self._server = server
            return self._server

    def url(self, page: str = "home") -> str:
        server = self.server()
        page = page if page in PAGES else "home"
        return f"{server.origin}/#token={server.token}&page={page}"

    def open(self, page: str = "home") -> str:
        """Open the window at `page`, or bring the open one forward there.

        Returns "" when a window is on its way, or a sentence saying why not — which the
        pill shows, because a menu row that silently does nothing is the failure this
        product is being rebuilt to stop.
        """
        page = page if page in PAGES else "home"
        try:
            server = self.server()
        except OSError as exc:
            return f"Flow Home could not start: {exc}"
        if server.connected():
            # A window is open and polling: it will go to `page` at its next poll, and
            # this brings it forward. If it was closed a moment ago, `focus` finds
            # nothing and a new one opens below.
            self._navigate = page
            if window.focus():
                return ""
        url = self.url(page)
        if window.launch(url):
            return ""
        # The whole address, token and all, on the console — the one place long enough
        # for it — so a machine with no browser Flow can start is not a dead end.
        print(f"Flow Home: {url}", flush=True)
        return f"could not open a window - Flow Home's address is on the console ({server.origin})"

    def take_navigate(self) -> str | None:
        """The page an open window should move to, once. Read by the page's poll."""
        page, self._navigate = self._navigate, None
        return page

    def close(self) -> None:
        # A tuning or a check still listening gives the microphone back first; the
        # process is going, but a stream left open is a stream Windows shows as in use.
        self.voice.tune.cancel()
        self.voice.check.cancel()
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass

    # -- downloads that finish after the page asked -------------------------------

    def _downloaded(self, job) -> None:
        """A model somebody chose before it was here has arrived: use it now.

        Runs on the download's thread, so the swap is posted rather than waited on — the
        session applies it at its next frame, and the page sees it at its next poll.
        """
        self.models.forget_scan()
        pending = self.pending_models
        if not job.then_use or pending is None:
            return
        partial, final, device = pending
        wanted = {"partial": partial, "final": final}
        if wanted.get(job.then_use) != job.name:
            return
        from .models import BY_NAME, complete

        # Both tiers may have been waiting; swap only once everything asked for is here.
        for name in (partial, final):
            if name is not None and not complete(BY_NAME[name].repo):
                return
        self.pending_models = None
        self.session.post(lambda: self.session.set_models(partial, final, device))


__all__ = ["Home", "PAGES"]
