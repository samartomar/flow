"""Flow Home's API: what each page shows, and the changes it can make.

Every route is a method taking the request's JSON body and returning a dict, so the
whole surface is testable without a socket (`tests/test_home_api.py`). Reads of live
session state and every change go through `Bridge.call`, which runs them on the
session's own thread; reads of files (stats, the model cache, the device list) run here,
on the request's thread, because they touch nothing the session owns.

Settings apply now wherever the session can apply them now, and say "next launch" where
it cannot — the keyboard hook and the registered hotkeys are built once at startup, and
re-registering them from a settings page is the one change here that the OS may refuse
halfway (see `ui.Pill._gesture_menu` for why the gesture, alone, is live).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from .. import stats
from ..edits import SEND_WORD_PRESETS, enter_word
from ..refine import EFFORTS, available, named
from ..session import CONVERSE, DICTATE, REFINE, RECENT_ANSWERED, RECENT_ASKED
from ..version import check_update, version
from .bridge import Busy
from .models import BY_NAME, human

#: Session mode -> the word the pages use. The product has two sides, Dictate and Ask;
#: Refine is Dictate with a polish step, and says so.
MODE_KEYS = {DICTATE: "dictate", REFINE: "refine", CONVERSE: "ask"}

#: What each hotkey action is called on the page, in the order the page lists them.
HOTKEY_LABELS = {
    "toggle": "Start or stop listening",
    "send": "Send the draft",
    "cancel": "Cancel",
    "mode": "Switch mode",
    "quit": "Quit Flow",
}

#: The voice engines, as somebody choosing between them needs to hear it.
VOICE_ENGINES = {
    "sapi": "Windows voices",
    "piper": "Piper - on this PC",
    "edge": "Natural - the text goes to Microsoft",
}

#: The two designs, by the names the page shows. "current" is the stored spelling of
#: the pill Flow shipped first, kept so older profiles still load.
DESIGN_LABELS = {"compact": "Compact", "current": "Classic"}


class ApiError(Exception):
    """A request the page made that cannot be done, said the way the page shows it."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class Api:
    """The routes, over one `Home`."""

    def __init__(self, home) -> None:
        self.home = home
        self.routes = {
            ("GET", "/api/state"): self.state,
            ("GET", "/api/home"): self.home_page,
            ("GET", "/api/models"): self.models,
            ("POST", "/api/models/download"): self.model_download,
            ("POST", "/api/models/cancel"): self.model_cancel,
            ("POST", "/api/models/delete"): self.model_delete,
            ("POST", "/api/models/use"): self.model_use,
            ("POST", "/api/agent"): self.agent,
            ("POST", "/api/replies"): self.replies,
            ("POST", "/api/replies/preview"): self.replies_preview,
            ("GET", "/api/voice"): self.voice_page,
            ("POST", "/api/voice/word"): self.add_word,
            ("POST", "/api/voice/word/remove"): self.remove_word,
            ("POST", "/api/voice/correction"): self.add_correction,
            ("POST", "/api/voice/correction/remove"): self.remove_correction,
            ("POST", "/api/voice/learned"): self.learned,
            ("POST", "/api/voice/tune"): self.tune,
            ("POST", "/api/voice/check"): self.check,
            ("GET", "/api/settings"): self.settings,
            ("POST", "/api/settings/mic"): self.set_mic,
            ("POST", "/api/settings/gesture"): self.set_gesture,
            ("POST", "/api/settings/hotkey"): self.set_hotkey,
            ("POST", "/api/settings/chord"): self.set_chord,
            ("POST", "/api/settings/send"): self.set_send,
            ("POST", "/api/settings/workspace"): self.set_workspace,
            ("POST", "/api/settings/workspace/add"): self.add_workspace,
            ("POST", "/api/settings/workspace/forget"): self.forget_workspace,
            ("POST", "/api/settings/auto_ask"): self.set_auto_ask,
            ("POST", "/api/settings/warm"): self.set_warm,
            ("POST", "/api/settings/design"): self.set_design,
            ("POST", "/api/settings/classic"): self.set_classic,
            ("POST", "/api/settings/apps"): self.set_app,
            ("POST", "/api/update"): self.update,
            ("POST", "/api/open"): self.open_folder,
        }

    def handle(self, method: str, path: str, body: dict) -> tuple[int, dict]:
        route = self.routes.get((method, path))
        if route is None:
            return 404, {"error": "no such page"}
        try:
            return 200, route(body)
        except ApiError as exc:
            return exc.status, {"error": str(exc)}
        except Busy as exc:
            return 503, {"error": str(exc)}
        except Exception as exc:
            traceback.print_exc()
            return 500, {"error": f"that did not work: {exc}"}

    # -- helpers --------------------------------------------------------------

    @property
    def session(self):
        return self.home.session

    @property
    def profile(self):
        return self.home.profile

    def _call(self, fn):
        return self.home.bridge.call(fn)

    def _save(self) -> None:
        """Save the profile on the session's thread, and say so when it cannot."""
        if self.profile is None:
            raise ApiError("Flow was started with --no-profile, so nothing can be saved")
        if not self._call(self.profile.save):
            raise ApiError(f"could not save {self.profile.path}")

    def _need_profile(self):
        if self.profile is None:
            raise ApiError("Flow was started with --no-profile, so nothing can be saved")
        return self.profile

    # -- the live strip every page polls --------------------------------------

    def state(self, _body: dict) -> dict:
        s = self.session

        def read() -> dict:
            asr = getattr(s, "asr", None)
            activity = getattr(s, "activity", None)
            loading = bool(getattr(asr, "loading", False))
            names = getattr(asr, "names", None) if not loading else None
            return {
                "mode": MODE_KEYS.get(getattr(s, "mode", DICTATE), "dictate"),
                "capturing": bool(getattr(s, "capturing", False)),
                "hearing": bool(getattr(s, "hearing", False)),
                "level_db": round(float(getattr(s, "level_db", -90.0) or -90.0), 1),
                "activity": activity.label if activity else "",
                "speaking": bool(getattr(s, "talking", False)),
                "muted": bool(getattr(s, "muted", False)),
                "workspace": getattr(s, "workspace", None),
                "loading": loading,
                "models": list(names) if isinstance(names, tuple) else None,
                "mic": getattr(getattr(s, "mic", None), "device_name", "") or "",
                "cli": getattr(s, "provider", "") or "",
                "lent": getattr(s, "mic_on_loan", "") or "",
            }

        data = self._call(read)
        data["navigate"] = self.home.take_navigate()
        data["version"] = version()
        data["lite"] = bool(self.home.lite)
        return data

    # -- Home -----------------------------------------------------------------

    def home_page(self, _body: dict) -> dict:
        s = self.session
        profile = self.profile

        def read() -> dict:
            asr = getattr(s, "asr", None)
            lexicon = getattr(asr, "lexicon", None)
            try:
                terms = len(lexicon.terms()) if lexicon is not None else 0
            except Exception:
                terms = 0
            names = getattr(asr, "names", None)
            return {
                "recent": [{"kind": role, "text": text}
                           for role, text in list(getattr(s, "recent", []))[:8]],
                "workspace": getattr(s, "workspace", None),
                "cli": getattr(s, "provider", "") or "",
                "mic": getattr(getattr(s, "mic", None), "device_name", "") or "",
                "loaded": bool(getattr(asr, "loaded", False)),
                "loading": bool(getattr(asr, "loading", False)),
                "final": names[1] if isinstance(names, tuple) else "",
                "device": getattr(asr, "device", "") if asr is not None else "",
                "terms": terms,
                "mode": MODE_KEYS.get(getattr(s, "mode", DICTATE), "dictate"),
            }

        live = self._call(read)
        calibrated = bool(profile is not None and profile.calibrated)
        tuned = ""
        if calibrated and profile.calibrated_at:
            tuned = time.strftime("%d %b", time.localtime(profile.calibrated_at))
        setup = [
            {"id": "mic", "title": "Microphone", "done": bool(live["mic"]),
             "detail": live["mic"] or "no microphone found", "page": "settings"},
            {"id": "model", "title": "Speech model", "done": live["loaded"],
             "detail": (f"{live['final']}, on the {'GPU' if live['device'] == 'cuda' else 'CPU'}"
                        if live["loaded"] else "loading" if live["loading"]
                        else "not loaded yet"),
             "page": "models"},
            {"id": "agent", "title": "Ask and Refine", "done": bool(live["cli"]),
             "detail": (f"{live['cli']} found on this PC" if live["cli"]
                        else "install claude or codex to ask questions and refine prompts"),
             "page": "models"},
            {"id": "workspace", "title": "A workspace for Ask", "done": bool(live["workspace"]),
             "detail": live["workspace"] or "the project folder answers are about",
             "page": "settings"},
            {"id": "voice", "title": "Tune Flow to your voice", "done": calibrated,
             "detail": f"tuned {tuned}" if tuned else "60 seconds of reading aloud",
             "page": "voice"},
            {"id": "words", "title": "Add the words you say", "done": live["terms"] > 0,
             "detail": (f"{live['terms']} words and corrections" if live["terms"]
                        else "names, tools, repos"),
             "page": "voice"},
        ]
        # Both paths passed, never defaulted: the files this session actually uses, which
        # under a test or the demo are not the ones in the user's home folder.
        reading = stats.read(trace=self.home.trace_path, profile=profile.path) \
            if profile is not None else stats.Reading()
        today, life = reading.today, reading.life
        saved = max(0, round(today.words / stats.TYPING_WPM - today.ms / 60000))
        recent = []
        for item in live["recent"]:
            side = "ask" if item["kind"] in (RECENT_ASKED, RECENT_ANSWERED) else "dictate"
            recent.append({"side": side, "kind": item["kind"], "text": item["text"]})
        return {
            "stats": {
                "today_words": today.words,
                "today_minutes": round(today.ms / 60000, 1),
                "saved_minutes": saved,
                "typing_wpm": stats.TYPING_WPM,
                "since": (time.strftime("%H:%M", time.localtime(today.since))
                          if today.since else None),
                "all_words": life.words if life.counted else None,
            },
            "setup": setup,
            "recent": recent,
            "mode": live["mode"],
            "workspace": live["workspace"],
            "cli": live["cli"],
            "shortcuts": self._shortcut_names(),
        }

    def _shortcut_names(self) -> dict:
        """The keys the Home page names for each side, as they registered here."""
        hotkeys = self.home.hotkeys
        chord = getattr(hotkeys, "chord", None) if hotkeys is not None else None
        return {
            "dictate": chord.describe() if chord is not None else "",
            "gesture": getattr(chord, "gesture", "") if chord is not None else "",
            "toggle": (getattr(hotkeys, "chosen", {}) or {}).get("toggle", "")
            if hotkeys is not None else "",
            "mode": (getattr(hotkeys, "chosen", {}) or {}).get("mode", "")
            if hotkeys is not None else "",
        }

    # -- Models ---------------------------------------------------------------

    def models(self, _body: dict) -> dict:
        speech = self.home.models.snapshot()
        s = self.session

        def read() -> dict:
            pinned = getattr(s, "cli", None)
            profile = getattr(s, "profile", None)
            speaker = getattr(s, "speaker", None)
            return {
                "pinned": pinned.name if pinned is not None else None,
                "model": getattr(s, "cli_model", "") or "",
                "models": list(getattr(profile, "cli_models", ()) or ()),
                "effort": getattr(s, "cli_effort", "") or "",
                "timeout": float(getattr(s, "cli_timeout", 0) or 0),
                "voice": getattr(speaker, "voice", None) if speaker is not None else None,
                "speaks": speaker is not None,
                "muted": bool(getattr(s, "muted", False)),
            }

        live = self._call(read)
        voices = []
        if live["speaks"]:
            try:
                for v in self.session.voices():
                    voices.append({"name": v.name, "label": v.describe(),
                                   "engine": v.engine,
                                   "group": VOICE_ENGINES.get(v.engine, VOICE_ENGINES["sapi"])})
            except Exception:
                voices = []
        return {
            "speech": speech,
            "agent": {
                "available": [c.name for c in available()],
                "pinned": live["pinned"],
                "model": live["model"],
                "models": live["models"],
                "effort": live["effort"],
                "efforts": list(EFFORTS),
                "timeout": live["timeout"],
            },
            "voice": {
                "available": live["speaks"],
                "current": live["voice"],
                "muted": live["muted"],
                "voices": voices,
            },
        }

    def _spec(self, body: dict):
        name = body.get("name")
        spec = BY_NAME.get(name) if isinstance(name, str) else None
        if spec is None:
            raise ApiError("Flow does not know that model")
        return spec

    def model_download(self, body: dict) -> dict:
        spec = self._spec(body)
        self.home.models.downloads.start(spec)
        return self.models({})

    def model_cancel(self, body: dict) -> dict:
        spec = self._spec(body)
        self.home.models.downloads.cancel(spec.name)
        return self.models({})

    def model_delete(self, body: dict) -> dict:
        spec = self._spec(body)
        if spec.name in self.home.models.in_use():
            raise ApiError(f"{spec.name} is in use - choose another model first")
        job = self.home.models.downloads.jobs().get(spec.name)
        if job is not None and job.state == "running":
            raise ApiError(f"{spec.name} is still downloading - cancel it first")
        from .models import delete

        if not delete(spec.repo):
            raise ApiError(f"{spec.name} is not on this PC")
        self.home.models.forget_scan()
        return self.models({})

    def model_use(self, body: dict) -> dict:
        """Choose the models; a model that is not here yet is downloaded first, then used.

        The body carries both tiers — a name, or null for automatic — so the page states
        the whole choice rather than a change to it. `device` is optional.
        """
        partial, final = body.get("partial"), body.get("final")
        device = body.get("device")
        for value in (partial, final):
            if value is not None and value not in BY_NAME:
                raise ApiError("Flow does not know that model")
        if device is not None and device not in ("auto", "cuda", "cpu"):
            raise ApiError("the device is auto, cuda or cpu")
        from .models import complete

        waiting = []
        for tier, value in (("partial", partial), ("final", final)):
            if value is not None and not complete(BY_NAME[value].repo):
                self.home.models.downloads.start(BY_NAME[value], then_use=tier)
                waiting.append(tier)
        if waiting:
            # Remember the whole choice now, so the download's finish swaps to exactly
            # what was asked for even if the page is closed by then.
            self.home.pending_models = (partial, final, device)
        else:
            self._call(lambda: self.session.set_models(partial, final, device))
        return self.models({})

    def agent(self, body: dict) -> dict:
        s = self.session
        if "cli" in body:
            want = body["cli"]
            if want in (None, "auto"):
                self._call(lambda: s.set_cli(None))
            else:
                cli = named(str(want))
                if cli is None or cli.name not in [c.name for c in available()]:
                    raise ApiError(f"{want} is not installed here")
                self._call(lambda: s.set_cli(cli))
        if "model" in body:
            model = body["model"]
            if not isinstance(model, str) or len(model) > 120:
                raise ApiError("a model name is a short piece of text")
            self._call(lambda: s.set_cli_model(model))
        if "effort" in body:
            if body["effort"] not in EFFORTS:
                raise ApiError(f"effort is one of {', '.join(EFFORTS)}")
            self._call(lambda: s.set_cli_effort(body["effort"]))
        if "timeout" in body:
            try:
                seconds = float(body["timeout"])
            except (TypeError, ValueError):
                raise ApiError("the wait is a number of seconds")
            self._call(lambda: s.set_cli_timeout(seconds))
        return self.models({})

    def replies(self, body: dict) -> dict:
        """The voice that reads answers aloud, and whether it does. On the Models page."""
        s = self.session
        if getattr(s, "speaker", None) is None:
            raise ApiError("spoken replies are not available on this PC")
        if "voice" in body:
            name = body["voice"]
            if name is not None and name not in [v.name for v in s.voices()]:
                raise ApiError("that voice is not installed")
            self._call(lambda: s.set_voice(name))
        if "muted" in body:
            want = bool(body["muted"])
            self._call(lambda: s.toggle_speech() if bool(s.muted) != want else None)
        return self.models({})

    def replies_preview(self, _body: dict) -> dict:
        s = self.session
        speaker = getattr(s, "speaker", None)
        if speaker is None:
            raise ApiError("spoken replies are not available on this PC")
        self._call(lambda: speaker.say("This is how Flow will read its answers to you."))
        return {"ok": True}

    # -- Voice ------------------------------------------------------------------

    def _lexicon_path(self) -> Path | None:
        """The dictionary file this session reads, or None when `--no-lexicon` turned it
        off — in which case nothing on the page may write to one."""
        from ..lexicon import NUL_PATH

        path = self.home.lexicon_path
        if path is None or Path(path) == NUL_PATH:
            return None
        return Path(path)

    def _writable_lexicon(self) -> Path:
        path = self._lexicon_path()
        if path is None:
            raise ApiError("the dictionary is off for this launch (--no-lexicon)")
        return path

    def voice_page(self, _body: dict) -> dict:
        from ..help import COMMANDS
        from ..lexicon import MAX_TERMS, entries

        path = self._lexicon_path()
        terms: list[str] = []
        corrections: list[tuple[str, str]] = []
        exists = False
        if path is not None:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                exists = True
            except OSError:
                text = ""
            terms, corrections = entries(text)
        profile = self.profile
        declared = {w.lower() for w, _r in corrections}

        def read() -> dict:
            if profile is None:
                return {"learned": [], "last": None}
            rows = []
            for wrong, right, times in profile.learned_pairs():
                key = f"{wrong.lower()} -> {right}"
                status = ("fixed" if wrong.lower() in declared
                          else "declined" if key in profile.dismissed else "offer")
                rows.append({"wrong": wrong, "right": right, "times": times, "status": status})
            last = None
            if profile.calibrated:
                last = {"floor_db": profile.floor_db, "speech_db": profile.speech_db,
                        "gap_db": round(profile.speech_db - profile.floor_db, 1),
                        "confidence": profile.confidence,
                        "at": (time.strftime("%d %b %Y", time.localtime(profile.calibrated_at))
                               if profile.calibrated_at else ""),
                        "device": profile.calibrated_device or ""}
            return {"learned": rows, "last": last}

        live = self._call(read)
        s = self.session
        # A name the check offered and the person then added is not offered twice.
        check = self.home.voice.check.public()
        known = {t.lower() for t in terms}
        check["offers"] = [w for w in check["offers"] if w.lower() not in known]
        for score in check["scores"]:
            score["offer"] = [w for w in score["offer"] if w.lower() not in known]
        return {
            "dictionary": {
                "enabled": path is not None,
                "exists": exists,
                "path": str(path) if path is not None else "",
                "terms": terms,
                "corrections": [{"wrong": w, "right": r} for w, r in corrections],
                "used": len(terms) + len(corrections),
                "cap": MAX_TERMS,
                "learned": live["learned"],
            },
            "tune": {**self.home.voice.tune.public(), "last": live["last"],
                     "profile": profile is not None},
            "check": check,
            "commands": [{"say": say, "does": does} for say, does, _route in COMMANDS],
            "send": {"word": s.send_words[0], "enter_word": s.send_words[1],
                     "pastes": bool(getattr(s, "pastes", True))},
        }

    def add_word(self, body: dict) -> dict:
        from ..lexicon import append_term

        term = body.get("term")
        if not isinstance(term, str):
            raise ApiError("type a word first")
        why = append_term(self._writable_lexicon(), term)
        if why:
            raise ApiError(why)
        return self.voice_page({})

    def remove_word(self, body: dict) -> dict:
        from ..lexicon import remove_entry

        term = body.get("term")
        if not isinstance(term, str) or not term.strip():
            raise ApiError("name the word to remove")
        why = remove_entry(self._writable_lexicon(), term=term)
        if why:
            raise ApiError(why)
        return self.voice_page({})

    def add_correction(self, body: dict) -> dict:
        from ..lexicon import append_pair

        wrong, right = body.get("wrong"), body.get("right")
        if not isinstance(wrong, str) or not isinstance(right, str):
            raise ApiError("a correction is what Flow hears, and what to write instead")
        why = append_pair(self._writable_lexicon(), wrong, right)
        if why:
            raise ApiError(why)
        return self.voice_page({})

    def remove_correction(self, body: dict) -> dict:
        from ..lexicon import remove_entry

        wrong = body.get("wrong")
        if not isinstance(wrong, str) or not wrong.strip():
            raise ApiError("name the correction to remove")
        why = remove_entry(self._writable_lexicon(), wrong=wrong)
        if why:
            raise ApiError(why)
        return self.voice_page({})

    def learned(self, body: dict) -> dict:
        """What to do with a pair Flow learned from the person's fixes.

        `fix` declares it — one arrow line appended to the dictionary, the same act as
        the draft menu's offer. `never` stops the offer and keeps the learned spelling
        listened for (`dismiss_pair` — asking is what needed consent, biasing never did).
        `forget` unlearns it: the count goes, and the bias with it.
        """
        from ..lexicon import append_pair

        wrong, right, action = body.get("wrong"), body.get("right"), body.get("action")
        if not isinstance(wrong, str) or not isinstance(right, str):
            raise ApiError("name the pair")
        profile = self._need_profile()
        if action == "fix":
            why = append_pair(self._writable_lexicon(), wrong, right)
            if why:
                raise ApiError(why)
        elif action == "never":
            self._call(lambda: profile.dismiss_pair(wrong, right))
            self._save()
        elif action == "forget":
            if not self._call(lambda: profile.forget_pair(wrong, right)):
                raise ApiError("Flow had not learned that one")
            self._save()
        else:
            raise ApiError("the action is fix, never or forget")
        return self.voice_page({})

    def tune(self, body: dict) -> dict:
        """Tuning Flow to this voice: start, finish ("done reading"), cancel."""
        task = self.home.voice.tune
        action = body.get("action")
        if action == "start":
            busy = self.home.voice.busy()
            if busy:
                raise ApiError(busy)
            why = task.start()
            if why:
                raise ApiError(why)
        elif action == "finish":
            task.finish()
        elif action == "cancel":
            task.cancel()
        else:
            raise ApiError("the action is start, finish or cancel")
        return self.voice_page({})

    def check(self, body: dict) -> dict:
        """The accuracy check: start, record the current sentence, stop it, cancel."""
        task = self.home.voice.check
        action = body.get("action")
        if action == "start":
            busy = self.home.voice.busy()
            if busy:
                raise ApiError(busy)
            why = task.start()
        elif action == "record":
            why = task.record()
        elif action == "stop":
            task.stop()
            why = ""
        elif action == "cancel":
            task.cancel()
            why = ""
        else:
            raise ApiError("the action is start, record, stop or cancel")
        if why:
            raise ApiError(why)
        return self.voice_page({})

    # -- Settings -------------------------------------------------------------

    def settings(self, _body: dict) -> dict:
        from ..audio import input_devices

        s = self.session
        profile = self.profile
        hotkeys = self.home.hotkeys
        chord = getattr(hotkeys, "chord", None) if hotkeys is not None else None

        def read() -> dict:
            mic = getattr(s, "mic", None)
            return {
                "current": getattr(mic, "device_name", "") or "",
                # A device index with no name behind it came from `--device`: the page
                # says so, because that is the one choice this page did not make.
                "flag": (getattr(mic, "pinned", None) is not None
                         and not getattr(mic, "want", None)),
                "workspace": getattr(s, "workspace", None),
                "auto_ask": bool(getattr(s, "auto_ask", True)),
            }

        live = self._call(read)
        chosen = getattr(hotkeys, "chosen", {}) if hotkeys is not None else {}
        overrides = getattr(profile, "hotkeys", {}) if profile is not None else {}
        rows = [{"action": action, "label": label, "combo": chosen.get(action, ""),
                 "override": overrides.get(action, "") if isinstance(overrides.get(action), str)
                 else ""}
                for action, label in HOTKEY_LABELS.items()]
        panels, places = _classic_choices()
        paths = {
            "settings": str(profile.path.parent) if profile is not None else "",
            "trace": str(Path(self.home.trace_path).parent) if self.home.trace_path else "",
            "lexicon": str(self.home.lexicon_path or ""),
        }
        return {
            "mic": {
                "devices": input_devices(),
                "current": live["current"],
                "chosen": getattr(profile, "mic_device", None) if profile is not None else None,
                "flag": live["flag"],
            },
            "shortcuts": {
                "available": hotkeys is not None,
                "lite": bool(self.home.lite),
                "chord": {
                    "keys": getattr(profile, "chord", "") if profile is not None else "",
                    "active": chord is not None,
                    "describe": chord.describe() if chord is not None else "",
                    "gesture": getattr(chord, "gesture", None)
                    or (getattr(profile, "gesture", "hold") if profile is not None else "hold"),
                },
                "hotkeys": rows,
            },
            "send": {
                "word": s.send_words[0],
                "enter_word": s.send_words[1],
                "presets": list(SEND_WORD_PRESETS),
                "pastes": bool(getattr(s, "pastes", True)),
            },
            "workspaces": {
                "current": live["workspace"],
                "recent": list(getattr(profile, "workspaces", []) or []) if profile else [],
            },
            "ask": {"auto_ask": live["auto_ask"]},
            "startup": {"warm": bool(getattr(profile, "warm", True)) if profile else True},
            "design": {
                "current": self.home.design,
                "options": [{"name": n, "label": label} for n, label in DESIGN_LABELS.items()],
            },
            "classic": {
                "panel": getattr(profile, "panel", "") if profile else "",
                "panels": panels,
                "place": getattr(profile, "place", "") if profile else "",
                "places": places,
            },
            "apps": [{"exe": exe, "instruction": text}
                     for exe, text in sorted((getattr(profile, "apps", {}) or {}).items())]
            if profile is not None else [],
            "paths": paths,
            "profile": profile is not None,
            "version": version(),
        }

    def set_mic(self, body: dict) -> dict:
        name = body.get("name")
        if name is not None and not isinstance(name, str):
            raise ApiError("a microphone is named by its name")
        if not self._call(lambda: self.session.set_microphone(name or None)):
            raise ApiError("the microphone did not change - the note on the pill says why")
        return self.settings({})

    def set_gesture(self, body: dict) -> dict:
        gesture = body.get("gesture")
        if gesture not in ("hold", "toggle"):
            raise ApiError("the gesture is hold or toggle")
        chord = getattr(self.home.hotkeys, "chord", None) if self.home.hotkeys else None
        profile = self._need_profile()

        def apply() -> None:
            # The same one-line change `ui.Pill._gesture_menu` makes: the hook reads the
            # attribute on every key event, so assigning it is the whole switch.
            if chord is not None:
                chord.gesture = gesture
            profile.gesture = gesture

        self._call(apply)
        self._save()
        return self.settings({})

    def set_hotkey(self, body: dict) -> dict:
        action = body.get("action")
        combo = body.get("combo", "")
        if action not in HOTKEY_LABELS:
            raise ApiError("there is no shortcut by that name")
        if not isinstance(combo, str):
            raise ApiError("a shortcut is written like ctrl+alt+space")
        combo = combo.strip().lower()
        profile = self._need_profile()
        if combo:
            parse = _hotkey_module("parse")
            if parse is not None:
                binding, why = parse(combo)
                if binding is None:
                    raise ApiError(f"{combo}: {why}")

        def apply() -> None:
            table = dict(profile.hotkeys)
            if combo:
                table[action] = combo
            else:
                table.pop(action, None)
            profile.hotkeys = table

        self._call(apply)
        self._save()
        return self.settings({})

    def set_chord(self, body: dict) -> dict:
        keys = body.get("keys", "")
        if not isinstance(keys, str):
            raise ApiError("the chord is written like ctrl+win")
        keys = keys.strip().lower()
        profile = self._need_profile()
        if keys:
            parse_chord = _hotkey_module("parse_chord")
            if parse_chord is not None:
                mods, why = parse_chord(keys)
                if mods is None:
                    raise ApiError(f"{keys}: {why}")

        def apply() -> None:
            profile.chord = keys

        self._call(apply)
        self._save()
        return self.settings({})

    def set_send(self, body: dict) -> dict:
        word = body.get("word")
        profile = self._need_profile()
        # The presets only, as the menu offers: each passed the 0-of-580 corpus gate that
        # "boom" did (`edits.SEND_WORD_PRESETS`), and a word typed into a box cannot be
        # measured before it is live. A word already set by hand is kept, not refused.
        if word not in SEND_WORD_PRESETS and word != profile.send_word:
            raise ApiError("choose one of the listed words - each was tested so it does not "
                           "fire by accident")

        def apply() -> None:
            profile.send_word = word
            profile.send_enter_word = enter_word(word)

        self._call(apply)
        self._save()
        return self.settings({})

    def set_workspace(self, body: dict) -> dict:
        path = body.get("path")
        if path is not None and not isinstance(path, str):
            raise ApiError("a workspace is a folder path")
        if path and not Path(path).is_dir():
            raise ApiError(f"{path} is not a folder on this PC")
        self._call(lambda: self.session.set_workspace(path or None))
        return self.settings({})

    def add_workspace(self, body: dict) -> dict:
        path = body.get("path")
        if path in (None, ""):
            path = pick_folder()
            if not path:
                return self.settings({})
        if not isinstance(path, str) or not Path(path).is_dir():
            raise ApiError(f"{path} is not a folder on this PC")
        self._call(lambda: self.session.set_workspace(path))
        return self.settings({})

    def forget_workspace(self, body: dict) -> dict:
        path = body.get("path")
        profile = self._need_profile()
        from ..profile import path_key

        def apply() -> None:
            profile.workspaces = [w for w in profile.workspaces if path_key(w) != path_key(path)]

        self._call(apply)
        self._save()
        return self.settings({})

    def set_auto_ask(self, body: dict) -> dict:
        want = bool(body.get("on"))
        s = self.session
        self._call(lambda: s.toggle_auto_ask() if bool(s.auto_ask) != want else None)
        return self.settings({})

    def set_warm(self, body: dict) -> dict:
        profile = self._need_profile()
        want = bool(body.get("on"))

        def apply() -> None:
            profile.warm = want

        self._call(apply)
        self._save()
        return self.settings({})

    def set_design(self, body: dict) -> dict:
        name = body.get("name")
        if name not in DESIGN_LABELS:
            raise ApiError("there is no design by that name")
        surface = self.home.surface
        if surface is None:
            raise ApiError("the pill is not on screen")
        if name == self.home.design:
            return self.settings({})

        def apply() -> None:
            # A Tk callback of its own rather than inline: this runs inside the pill's
            # frame, and a switch takes that window down — the menu row it replaces ran
            # as its own callback for the same reason.
            surface.after(0, lambda: surface.switch_design(name))

        self._call(apply)
        return self.settings({})

    def set_classic(self, body: dict) -> dict:
        profile = self._need_profile()
        panels, places = _classic_choices()
        panel, place = body.get("panel"), body.get("place")
        if panel is not None and panel not in panels:
            raise ApiError("that panel size is not one of the drawn ones")
        if place is not None and place not in places:
            raise ApiError("that is not a place the pill can sit")

        def apply() -> None:
            if panel is not None:
                profile.panel = panel
            if place is not None:
                profile.place = place

        self._call(apply)
        self._save()
        return self.settings({})

    def set_app(self, body: dict) -> dict:
        profile = self._need_profile()
        exe = str(body.get("exe") or "").strip().lower()
        text = body.get("instruction")
        if not exe.endswith(".exe") or len(exe) > 80 or "\\" in exe or "/" in exe:
            raise ApiError("name the program as its file is called, like code.exe")
        if text is not None and (not isinstance(text, str) or len(text) > 400):
            raise ApiError("keep the instruction to a sentence or two")

        def apply() -> None:
            table = dict(profile.apps)
            if text and text.strip():
                table[exe] = text.strip()
            else:
                table.pop(exe, None)
            profile.apps = table

        self._call(apply)
        self._save()
        return self.settings({})

    def update(self, _body: dict) -> dict:
        line, ran = check_update()
        return {"line": line, "ran": ran}

    def open_folder(self, body: dict) -> dict:
        """Open one of Flow's own folders in the file manager. Only these, never a path
        the page sends: the page names *which* folder, and this decides where that is."""
        what = body.get("what")
        from .models import cache_dir

        folders = {
            "settings": self.profile.path.parent if self.profile is not None else None,
            "trace": Path(self.home.trace_path).parent if self.home.trace_path else None,
            "lexicon": Path(self.home.lexicon_path).parent if self.home.lexicon_path else None,
            "models": Path(cache_dir()) if cache_dir() else None,
        }
        folder = folders.get(what) if isinstance(what, str) else None
        if folder is None:
            raise ApiError("there is no folder by that name")
        folder.mkdir(parents=True, exist_ok=True)
        reveal(folder)
        return {"ok": True}


# -- the machine -----------------------------------------------------------------------


def _hotkey_module(name: str):
    """A function from `flow.hotkey`, or None off Windows — that module binds user32 at
    import, and the checks it offers only mean anything where the hotkeys exist."""
    if sys.platform != "win32":
        return None
    try:
        from .. import hotkey

        return getattr(hotkey, name)
    except Exception:
        return None


def _classic_choices() -> tuple[list[str], list[str]]:
    """The panel widths and places the Classic pill draws. Read off `flow.ui` when it
    loads, and its spelled defaults otherwise, so this page cannot offer one it lacks."""
    try:
        from ..ui import PANEL_WIDTHS, PLACES

        return list(PANEL_WIDTHS), list(PLACES)
    except Exception:
        return ["regular", "large", "larger"], ["bottom", "corner"]


def reveal(folder: Path) -> None:
    """Show a folder in the platform's file manager."""
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))  # noqa: S606 - a folder of Flow's own
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except OSError:
        pass


def pick_folder() -> str:
    """Ask for a folder with the platform's own dialog. "" when cancelled or unavailable.

    A process of its own rather than a dialog in Flow's window: this runs on a request
    thread, and a modal dialog on the pill's thread would freeze the pill while it is
    open. PowerShell's folder browser on Windows, AppleScript's chooser on a Mac.
    """
    try:
        if sys.platform == "win32":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "$d.Description = 'Choose the project folder Ask should answer about';"
                "$d.UseDescriptionForTitle = $true;"
                "if ($d.ShowDialog() -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }"
            )
            out = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", script],
                capture_output=True, text=True, timeout=600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return out.stdout.strip()
        if sys.platform == "darwin":
            out = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt '
                                    '"Choose the project folder Ask should answer about")'],
                capture_output=True, text=True, timeout=600,
            )
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


__all__ = ["Api", "ApiError", "human"]
