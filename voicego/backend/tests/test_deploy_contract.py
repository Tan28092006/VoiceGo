"""Deploy contract tests: offline, no API keys, no MongoDB, no network.

Two invariants a Render deploy depends on (see f3c11fe):
  1. /api/health is a pure liveness check: answers fast (GET and HEAD) even when MongoDB
     is unreachable. Render's health check times the deploy out if this route waits on
     Atlas. Mongo details belong at /api/db/status.
  2. index.html is served with Cache-Control: no-cache, otherwise browsers keep running
     the previous JS bundle after a deploy.

Run (from voicego/backend):  py -m pytest tests -q      or   py -m unittest discover -s tests -v
"""
import os
import sys
import time
import unittest

# Point MongoDB at a closed port BEFORE importing the app (load_dotenv does not override
# variables that are already set). Any Mongo call would then block ~1.2s
# (serverSelectionTimeoutMS in db.py), which the timing assertion below would catch.
os.environ["MONGODB_URI"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=1200"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

# No `with TestClient(...)`: startup events (SDK warmup thread) are not run.
client = TestClient(main.app)


class HealthIsLiveness(unittest.TestCase):
    def test_get_is_fast_and_ok_without_mongo(self):
        t = time.perf_counter()
        r = client.get("/api/health")
        ms = (time.perf_counter() - t) * 1000
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ok")
        self.assertLess(ms, 500, f"/api/health took {ms:.0f}ms; it must not touch MongoDB")

    def test_head_is_allowed(self):
        # Uptime monitors and Render default to HEAD; a GET-only route answers 405.
        self.assertEqual(client.head("/api/health").status_code, 200)

    def test_reports_engine_defaults_for_frontend(self):
        body = client.get("/api/health").json()
        self.assertIn(body.get("stt_engine"), ("gemini-live", "whisper"))
        self.assertIn(body.get("tts_engine"), ("browser", "edge"))


@unittest.skipUnless(os.path.isfile(os.path.join(BACKEND_DIR, "..", "frontend", "dist", "index.html")),
                     "frontend/dist not built (index.html route only exists when dist is present)")
class IndexHtmlNotCached(unittest.TestCase):
    def test_root_index_is_no_cache(self):
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("cache-control"), "no-cache")

    def test_spa_route_index_is_no_cache(self):
        r = client.get("/some/client/route")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("cache-control"), "no-cache")


if __name__ == "__main__":
    unittest.main()
