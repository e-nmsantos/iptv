"""Shared HTTP test doubles for the parser suites (no network access)."""

import json

import requests
from PySide6.QtCore import QObject, Signal


class FakeResponse:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(self, payload=None, status_code=200, text=None, invalid_json=False):
        self.payload = payload
        self.status_code = status_code
        self.invalid_json = invalid_json
        if text is not None:
            self.text = text
        else:
            self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self.invalid_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeCookies:
    """Cookie jar stub that only records assignments."""

    def __init__(self):
        self.values = {}

    def set(self, name, value):
        self.values[name] = value


class FakeSession:
    """Scripted queue of responses, recording every request made."""
    def __init__(self):
        self.headers = {}
        self.cookies = FakeCookies()
        self.get_calls = []
        self.post_calls = []
        self.responses = []
        self.closed = False

    def queue(self, *responses):
        self.responses.extend(responses)
        return self

    def _next(self):
        if not self.responses:
            raise AssertionError("unexpected HTTP call: no response queued")
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, "kwargs": kwargs})
        response = self._next()
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        self.post_calls.append({"url": url, "kwargs": kwargs})
        response = self._next()
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


class FakeMediaPlayer(QObject):
    """MediaPlayer stand-in: records calls and exposes the real signals."""

    position_changed = Signal(float)
    time_changed = Signal(int)
    length_changed = Signal(int)
    state_changed = Signal(str)
    error_occurred = Signal(str)
    media_ended = Signal()
    recording_state_changed = Signal(bool, str)
    stats_changed = Signal(dict)
    timeshift_limit_reached = Signal()

    _RETURNS = {
        "get_volume": lambda self: self.volume,
        "get_length": lambda self: 0,
        "get_time": lambda self: 0,
        "get_subtitle_track": lambda self: -1,
        "get_subtitle_delay": lambda self: 0,
        "is_playing": lambda self: self.playing,
        "is_recording": lambda self: False,
        "get_audio_tracks": lambda self: [],
        "get_subtitle_tracks": lambda self: [],
        "toggle_mute": lambda self: self._toggle_mute(),
    }

    def __init__(self, **kwargs):
        super().__init__()
        self.volume = 70
        self.playing = False
        self.calls = []
        self.last_play = None

    def _toggle_mute(self):
        self.volume = 0 if self.volume else 70
        self.calls.append("toggle_mute")
        return self.volume == 0

    def play(self, url=None, headers=None, is_live=True, **kwargs):
        self.last_play = {"url": url, "headers": headers, "is_live": is_live}
        self.playing = True
        self.calls.append("play")

    def stop(self):
        self.playing = False
        self.calls.append("stop")

    def pause(self):
        self.playing = False
        self.calls.append("pause")

    def set_volume(self, value):
        self.volume = int(value)
        self.calls.append(("set_volume", self.volume))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in FakeMediaPlayer._RETURNS:
            return lambda *args, **kwargs: FakeMediaPlayer._RETURNS[name](self)
        if name.startswith("get_") or name.startswith("is_"):
            return lambda *args, **kwargs: None

        def noop(*args, **kwargs):
            self.calls.append(name)
            return None

        return noop
