"""Google Search grounding must never make a free key slower or park it (offline, fake client).

Measured 10/2026: every grounded request on the free keys returned 429 while plain calls
worked. Before the fix, GEMINI_GROUNDING=true cost ~1.5 s per key per lookup and parked the
keys (escalating) for plain calls too.
"""
import types as pytypes

import geocode as g


class FakeModels:
    def __init__(self, log):
        self.log = log

    def generate_content(self, model, contents, config):
        grounded = bool(getattr(config, "tools", None))
        self.log.append("grounded" if grounded else "plain")
        if grounded:
            raise RuntimeError("429 RESOURCE_EXHAUSTED. You exceeded your current quota")
        return pytypes.SimpleNamespace(text='{"query_type":"poi","locations":[]}')


def _setup(monkeypatch, keys=("k1", "k2")):
    log = []
    monkeypatch.setattr(g, "GEMINI_API_KEYS", list(keys))
    monkeypatch.setattr(g, "_GEMINI_CLIENTS", {k: pytypes.SimpleNamespace(models=FakeModels(log)) for k in keys})
    monkeypatch.setattr(g, "_GEMINI_PARKED", {})
    monkeypatch.setattr(g, "_GEMINI_STRIKES", {})
    monkeypatch.setattr(g, "_GROUNDING_OFF_UNTIL", 0.0)
    monkeypatch.setattr(g, "GEMINI_GROUNDING", True)
    return log


def test_grounding_429_on_every_key_turns_grounding_off_without_parking(monkeypatch):
    log = _setup(monkeypatch)
    assert g._gemini_call("x", grounded=True, retries=0) is not None     # fell back to plain
    assert log == ["grounded", "grounded", "plain"]
    assert g._GEMINI_PARKED == {}                                        # keys still usable
    assert not g.grounding_active()                                      # off for a while


def test_after_grounding_off_lookups_skip_grounded_attempts(monkeypatch):
    log = _setup(monkeypatch)
    g._gemini_call("x", grounded=True, retries=0)
    log.clear()
    g._gemini_locations("Bách Khoa", 10.77, 106.70)
    assert log == ["plain"]


def test_plain_429_still_parks_the_key(monkeypatch):
    log = _setup(monkeypatch, keys=("k1",))

    class Exhausted(FakeModels):
        def generate_content(self, model, contents, config):
            self.log.append("plain")
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
    monkeypatch.setattr(g, "_GEMINI_CLIENTS", {"k1": pytypes.SimpleNamespace(models=Exhausted(log))})
    assert g._gemini_call("x", grounded=False, retries=0) is None
    assert "k1" in g._GEMINI_PARKED
