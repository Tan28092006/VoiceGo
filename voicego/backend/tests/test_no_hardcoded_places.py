"""Guard: place resolution must not come from a hardcoded place table.

User rule (10/2026): "gazetteer đã kiểm chứng -> bỏ khỏi code, này hardcode". The removed
places_db.py answered first with fixed coordinates and skipped Gemini + Nominatim, so a
generic alias ("bách khoa") silently returned whichever campus was in the table.

Allowed literals: the GPS-less fallback pickup (agent.DEFAULT_PICKUP, geocode.DEFAULT_CENTER)
and db.py's demo seed of accessible gates (looked up by a resolved place's location, never
used to resolve a spoken name).
"""
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
COORD = re.compile(r'"(lat|lng)"\s*:\s*-?\d+\.\d+')


def test_no_gazetteer_module():
    assert not (BACKEND / "places_db.py").exists()
    imp = re.compile(r"^\s*(from\s+places_db\s+import|import\s+places_db)\b", re.MULTILINE)
    for f in BACKEND.glob("*.py"):
        assert not imp.search(f.read_text(encoding="utf-8")), f.name


def test_resolution_modules_have_no_place_table():
    geo = (BACKEND / "geocode.py").read_text(encoding="utf-8")
    assert not COORD.search(geo), "geocode.py contains a literal place coordinate"
    assert '"aliases"' not in geo
    agent = (BACKEND / "agent.py").read_text(encoding="utf-8")
    hits = [m.group(0) for m in COORD.finditer(agent)]
    # DEFAULT_PICKUP is the only literal point allowed (one "lat" + one "lng" on one line).
    assert len(hits) <= 2, hits
    assert '"aliases"' not in agent
