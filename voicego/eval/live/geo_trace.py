"""Trace geocode.resolve_locations for spoken place names, logging every provider call.

OPT-IN, LIVE: calls Gemini (quota, keys from voicego/backend/.env — never printed) and the
public Nominatim / Mapbox APIs. Ask the user before running (voicego/AGENTS.md section 0).

    PYTHONIOENCODING=utf-8 py voicego/eval/live/geo_trace.py "Bách Khoa" "Landmark 81"   # utf-8: Windows console
    py voicego/eval/live/geo_trace.py --pickup 10.8782,106.8012 "Bách Khoa"
    py voicego/eval/live/geo_trace.py --nominatim-ip 151.101.193.91 "Bách Khoa"

--nominatim-ip: some dev networks resolve nominatim.openstreetmap.org to 127.0.0.1 (seen
10/2026), so every Nominatim call fails, geocode logs "[geocode] Nominatim lỗi" and the flow
falls back to Mapbox — not what production does. Get a real IP with
`nslookup -type=A nominatim.openstreetmap.org 8.8.8.8` and pass it to pin the name for this
process only (TLS/SNI still uses the hostname).

What to read in the output: GEMINI = candidate names/branches; NOMINATIM q=... = each query
tried and its first hit; RESULT = what the agent would get (verified=False means no geocoder
evidence agreed, so the app is using Gemini's own point).
"""
import argparse
import json
import os
import socket
import sys
import time

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("places", nargs="+")
    ap.add_argument("--pickup", default="10.7769,106.7009", help="lat,lng (default: Quận 1)")
    ap.add_argument("--nominatim-ip", default="")
    a = ap.parse_args()

    if a.nominatim_ip:
        orig = socket.getaddrinfo

        def gai(host, *args, **kw):
            return orig(a.nominatim_ip if host == "nominatim.openstreetmap.org" else host, *args, **kw)
        socket.getaddrinfo = gai

    sys.path.insert(0, os.path.abspath(BACKEND))
    os.chdir(os.path.abspath(BACKEND))
    import geocode as g  # noqa: E402  (after the DNS pin and path setup)

    ogem, omb, ohits = g._gemini_locations, g._mapbox_first, g._nominatim_hits

    def hits(q, *x, **k):
        r = ohits(q, *x, **k)
        top = r[0] if r else None
        print(f"   NOMINATIM q={q!r} -> {('%.5f,%.5f %s' % (top[0], top[1], top[2][:75])) if top else None}"
              f"{f'  (+{len(r) - 1} more)' if len(r) > 1 else ''}")
        return r

    def gem(*x, **k):
        r = ogem(*x, **k)
        locs = (r or {}).get("locations", [])
        print("   GEMINI ->", json.dumps([{f: l.get(f) for f in ("name", "map_query", "map_query_alt", "address")}
                                          for l in locs], ensure_ascii=False) if r else None)
        return r

    def mb(*x, **k):
        r = omb(*x, **k)
        print("   MAPBOX ->", (r or {}).get("name"), (r or {}).get("type"))
        return r

    g._nominatim_hits, g._gemini_locations, g._mapbox_first = hits, gem, mb
    lat, lng = (float(v) for v in a.pickup.split(","))
    for q in a.places:
        print(f"\n=== {q!r} | pickup {lat},{lng}")
        t = time.time()
        r = g.resolve_locations(q, lat, lng)
        print(f"   RESULT ({time.time() - t:.1f}s) source={r.get('source')} ok={r.get('ok')}")
        for l in r.get("locations", []):
            print(f"     - {l['name']} | {l['address']} | {l['lat']},{l['lng']} | {l['distanceKm']} km | verified={l['verified']}")


if __name__ == "__main__":
    main()
