"""http_get_json retry/back-off behavior (the Spellbook 429 fix)."""

from __future__ import annotations

import pytest
import requests

import weaver.ingest.base as base


class FakeResp:
    def __init__(self, status, json_data=None, headers=None):
        self.status_code = status
        self._json = json_data or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._json


def test_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return FakeResp(429, headers={"Retry-After": "0"})
        return FakeResp(200, {"ok": True})

    monkeypatch.setattr(base.requests, "get", fake_get)
    monkeypatch.setattr(base, "_sleep", lambda s: None)  # no real waiting
    assert base.http_get_json("http://x") == {"ok": True}
    assert calls["n"] == 3  # two 429s, then success


def test_retries_on_500(monkeypatch):
    seq = [FakeResp(503), FakeResp(200, {"ok": 1})]
    monkeypatch.setattr(base.requests, "get", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(base, "_sleep", lambda s: None)
    assert base.http_get_json("http://x") == {"ok": 1}


def test_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(base.requests, "get", lambda *a, **k: FakeResp(429))
    monkeypatch.setattr(base, "_sleep", lambda s: None)
    with pytest.raises(requests.HTTPError):
        base.http_get_json("http://x", retries=2)


def test_success_first_try_does_not_sleep(monkeypatch):
    slept = {"n": 0}
    monkeypatch.setattr(base.requests, "get", lambda *a, **k: FakeResp(200, {"a": 1}))
    monkeypatch.setattr(base, "_sleep", lambda s: slept.__setitem__("n", slept["n"] + 1))
    assert base.http_get_json("http://x") == {"a": 1}
    assert slept["n"] == 0
