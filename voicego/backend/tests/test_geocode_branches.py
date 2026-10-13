"""Branch pinning in geocode._pin / resolve_locations — offline, no network.

Reproduces the real "Bách Khoa" bug (10/2026): every branch-qualified name missed in
OSM, the bare name returned ONE campus (whichever the pickup bias favoured) and BOTH
branches were pinned to it with verified=True — from Quận 1, "cơ sở 1 (Lý Thường Kiệt)"
came out in Dĩ An. Also: a Mapbox city-centroid hit was accepted as verified.
"""
import pytest

import geocode as g

Q10 = (10.7724, 106.6577)      # campus on Lý Thường Kiệt
DIAN = (10.8803, 106.8050)     # campus in Dĩ An
PICKUP_THUDUC = (10.8782, 106.8012)
PICKUP_Q1 = (10.7769, 106.7009)
BARE = "Đại học Bách khoa Thành phố Hồ Chí Minh"
ADDR_Q10 = "268 Lý Thường Kiệt, Phường 14, Quận 10"
ADDR_DIAN = "Đông Hòa, Dĩ An, Bình Dương"


def _fake_osm(calls):
    def nominatim_hits(q, lat=None, lng=None):
        calls.append(q)
        h = one(q, lat, lng)
        return [h] if h else []

    def one(q, lat, lng):
        if q == BARE:
            # Adversarial, like the real run: the bare name lands on the OTHER campus.
            near_thuduc = lat is not None and abs(lat - PICKUP_THUDUC[0]) < 0.05
            return (*Q10, "Đại học Bách Khoa, 268 Lý Thường Kiệt") if near_thuduc else \
                   (*DIAN, "Đại học Bách Khoa - Cơ sở Dĩ An, Tạ Quang Bửu")
        if q == ADDR_Q10:
            return (Q10[0] + 0.001, Q10[1], "Lý Thường Kiệt, Phường 14, Quận 10")
        if q == ADDR_DIAN:
            return (DIAN[0] - 0.004, DIAN[1] - 0.003, "Đông Hòa, Dĩ An, Bình Dương")
        return None      # every branch-qualified form misses, as observed
    return nominatim_hits


def _gemini(coords=True):
    def gemini_locations(text, lat, lng):
        return {"query_type": "poi", "locations": [
            {"name": f"{BARE} (Cơ sở 1)", "map_query": "Đại học Bách khoa cơ sở 1", "map_query_alt": "",
             "address": ADDR_Q10, "lat": Q10[0] + 0.004 if coords else None,
             "lng": Q10[1] - 0.003 if coords else None},
            {"name": f"{BARE} (Cơ sở Dĩ An)", "map_query": "Đại học Bách khoa cơ sở 2",
             "map_query_alt": "Đại học Bách khoa cơ sở Dĩ An", "address": ADDR_DIAN,
             "lat": DIAN[0] - 0.002 if coords else None, "lng": DIAN[1] + 0.002 if coords else None},
        ]}
    return gemini_locations


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # Tests must never reach the real geocoders (Mapbox token is in .env; Nominatim may be
    # DNS-blocked on dev machines). Individual tests patch in fakes on top of this.
    monkeypatch.setattr(g, "_mapbox_geocode", lambda *a, **k: [])
    monkeypatch.setattr(g, "_nominatim_hits", lambda *a, **k: [])
    g._NM_CACHE.clear()


@pytest.fixture
def osm(monkeypatch):
    calls = []
    monkeypatch.setattr(g, "_nominatim_hits", _fake_osm(calls))
    # Mapbox only knows the city centroid — a region-level hit that must never verify.
    monkeypatch.setattr(g, "_mapbox_geocode", lambda *a, **k: [
        {"name": "Thành phố Hồ Chí Minh", "address": "Thành phố Hồ Chí Minh",
         "lat": 10.7755, "lng": 106.7021, "type": "place"}])
    return calls


@pytest.mark.parametrize("pickup", [PICKUP_THUDUC, PICKUP_Q1], ids=["pickup-thuduc", "pickup-q1"])
def test_each_branch_pinned_to_its_own_campus(osm, monkeypatch, pickup):
    monkeypatch.setattr(g, "_gemini_locations", _gemini(coords=True))
    r = g.resolve_locations("Bách Khoa", *pickup)
    assert r["ok"] and len(r["locations"]) == 2
    by_branch = {("Dĩ An" in l["name"]): l for l in r["locations"]}
    for is_dian, truth in ((False, Q10), (True, DIAN)):
        loc = by_branch[is_dian]
        assert g._haversine_km(loc["lat"], loc["lng"], *truth) < 1.0, loc
        assert loc["verified"] is True
    assert "_ref" not in r["locations"][0]


def test_branch_without_gemini_coords_uses_its_own_address(osm, monkeypatch):
    monkeypatch.setattr(g, "_gemini_locations", _gemini(coords=False))
    # resolve_locations drops Gemini items with no coords, so pin directly like the
    # DeepSeek fallback path does (lat/lng = None).
    loc = {"name": f"{BARE} (Cơ sở 1)", "map_query": "Đại học Bách khoa cơ sở 1",
           "address": ADDR_Q10, "lat": None, "lng": None}
    # From Quận 1 the bare name lands on the Dĩ An campus — the adversarial case.
    out, ok = g._pin(loc, *PICKUP_Q1, is_address=False, pickup=PICKUP_Q1, one_shot=True)
    assert ok and g._haversine_km(out["lat"], out["lng"], *Q10) < 1.0, out


def test_mapbox_region_level_hit_is_never_a_destination(monkeypatch):
    monkeypatch.setattr(g, "_mapbox_geocode", lambda *a, **k: [
        {"name": "Thành phố Hồ Chí Minh", "address": "Thành phố Hồ Chí Minh",
         "lat": 10.7755, "lng": 106.7021, "type": "place"}])
    assert g._mapbox_first("Bách Khoa cơ sở 2", *PICKUP_Q1) is None


def _osm_table(table, calls):
    def hits(q, lat=None, lng=None):
        calls.append(q)
        return list(table.get(q, []))
    return hits


def test_single_poi_name_hit_far_from_gemini_but_address_agrees_uses_address(monkeypatch):
    # Real case: "Landmark 81" -> Nominatim "PetroVietnam Landmark" ~3 km away, while
    # Gemini's coords AND its address both point at the real tower: 2 of 3 win.
    calls = []
    monkeypatch.setattr(g, "_nominatim_hits", _osm_table({
        "Landmark 81": [(10.7970, 106.7505, "PetroVietnam Landmark, Phường Bình Trưng")],
        "720A Điện Biên Phủ, Phường 22, Quận Bình Thạnh": [
            (10.7952, 106.7215, "Vincom, 720A, Điện Biên Phủ, Phường 22, Bình Thạnh")],
    }, calls))
    loc = {"name": "Landmark 81", "map_query": "Landmark 81",
           "address": "720A Điện Biên Phủ, Phường 22, Quận Bình Thạnh", "lat": 10.7948, "lng": 106.7219}
    out, ok = g._pin(loc, *PICKUP_Q1, is_address=False, pickup=PICKUP_Q1)
    assert ok and g._haversine_km(out["lat"], out["lng"], 10.7948, 106.7219) < 0.5, out
    assert not out["address"].startswith("Vincom"), out["address"]   # foreign POI name dropped


def test_single_poi_gemini_coords_wrong_trusts_name(monkeypatch):
    calls = []
    monkeypatch.setattr(g, "_nominatim_hits", _osm_table({
        "Chợ Bến Thành": [(10.77253, 106.69804, "Chợ Bến Thành, Quận 1")],
        "Lê Lợi, Quận 1": [(10.7731, 106.7000, "Lê Lợi, Quận 1")],
    }, calls))
    loc = {"name": "Chợ Bến Thành", "map_query": "Chợ Bến Thành", "address": "Lê Lợi, Quận 1",
           "lat": 10.80, "lng": 106.80}     # Gemini coords ~10 km off, address disagrees with them
    out, ok = g._pin(loc, *PICKUP_Q1, is_address=False, pickup=PICKUP_Q1)
    assert ok and abs(out["lat"] - 10.77253) < 1e-6, out


def test_street_address_retry_drops_old_admin_units(monkeypatch):
    # Gemini gives pre-2025 units ("Phường 8, Quận 5"); OSM has renamed them, so the full
    # address misses but house number + street hits.
    calls = []
    monkeypatch.setattr(g, "_nominatim_hits", _osm_table({
        "468 Nguyễn Trãi, Thành phố Hồ Chí Minh": [(10.7552, 106.6700, "468, Nguyễn Trãi, Phường An Đông")],
    }, calls))
    loc = {"name": "Bệnh viện X (Cơ sở 2)", "map_query": "Bệnh viện X cơ sở 2",
           "address": "468 Nguyễn Trãi, Phường 8, Quận 5, Thành phố Hồ Chí Minh", "lat": 10.7583, "lng": 106.6699}
    out, ok = g._pin(loc, *PICKUP_Q1, is_address=False, pickup=PICKUP_Q1, one_shot=True)
    assert ok and g._haversine_km(out["lat"], out["lng"], 10.7552, 106.6700) < 0.1, out


def test_never_queries_bare_old_ward_or_district(monkeypatch):
    # "Phường 4, Quận 5" matched "Hẻm 491/5 Lạc Long Quân" 3.9 km away (digits matched).
    calls = []
    monkeypatch.setattr(g, "_nominatim_hits", _osm_table({
        "Phường 4, Quận 5": [(10.7740, 106.6470, "Hẻm 491/5 Lạc Long Quân")],
    }, calls))
    loc = {"name": "Đại học Y (Cơ sở Nguyễn Văn Cừ)", "map_query": "Đại học Y cơ sở 1",
           "address": "Khu phố 6, Phường 4, Quận 5", "lat": 10.7630, "lng": 106.6805}
    out, ok = g._pin(loc, *PICKUP_Q1, is_address=False, pickup=PICKUP_Q1, one_shot=True)
    assert "Phường 4, Quận 5" not in calls
    assert ok is False and (out["lat"], out["lng"]) == (10.7630, 106.6805)   # honest: unverified


def test_gemini_coords_hugging_pickup_are_not_used_as_evidence(monkeypatch):
    # Real Landmark 81 run: Gemini put the tower 0.5 km from the pickup (2.7 km off).
    calls = []
    monkeypatch.setattr(g, "_nominatim_hits", _osm_table({
        "Landmark 81": [(10.79696, 106.75045, "PetroVietnam Landmark, Phường Bình Trưng")],
        "720A Điện Biên Phủ, Phường 22, Bình Thạnh, Thành phố Hồ Chí Minh": [
            (10.79484, 106.72174, "Vincom Center, 720A, Điện Biên Phủ, Phường Thạnh Mỹ Tây")],
    }, calls))
    loc = {"name": "Landmark 81", "map_query": "Landmark 81",
           "address": "720A Điện Biên Phủ, Phường 22, Bình Thạnh, Thành phố Hồ Chí Minh",
           "lat": 10.77689, "lng": 106.70547}
    out, ok = g._pin(loc, *PICKUP_Q1, is_address=False, pickup=PICKUP_Q1)
    assert ok and g._haversine_km(out["lat"], out["lng"], 10.79484, 106.72174) < 0.1, out
    assert out["address"].startswith("720A"), out["address"]


def test_nominatim_answers_are_cached(monkeypatch):
    monkeypatch.undo()                     # use the real _nominatim_hits, fake HTTP below
    g._NM_CACHE.clear()
    hits = []

    class R:
        def json(self):
            return [{"lat": "10.77", "lon": "106.66", "display_name": "X, 700000, Việt Nam"}]
    monkeypatch.setattr(g, "_nominatim_throttle", lambda: None)
    monkeypatch.setattr(g.requests, "get", lambda *a, **k: hits.append(1) or R())
    a = g._nominatim_full("Đại học Bách khoa", *PICKUP_Q1)
    b = g._nominatim_full("Đại học Bách khoa", *PICKUP_Q1)
    assert a == b == (10.77, 106.66, "X") and len(hits) == 1
    g._NM_CACHE.clear()


def test_nominatim_network_error_is_not_cached(monkeypatch):
    monkeypatch.undo()
    g._NM_CACHE.clear()
    monkeypatch.setattr(g, "_nominatim_throttle", lambda: None)

    def boom(*a, **k):
        raise ConnectionError("refused")
    monkeypatch.setattr(g.requests, "get", boom)
    assert g._nominatim_full("Đại học Bách khoa", *PICKUP_Q1) is None
    assert not g._NM_CACHE


def test_branch_part_detection():
    assert g._branch_part("Đại học Bách khoa (Cơ sở Dĩ An)") == "Cơ sở Dĩ An"
    assert g._branch_part("Đại học Công nghiệp Hà Nội cơ sở 2") == "cơ sở 2"
    assert g._branch_part("Chợ Bến Thành") == ""
    assert g._branch_part("Đại học Công nghệ Thông tin (UIT)") == ""


def test_street_address_parser():
    assert g._street_address("468 Nguyễn Trãi, Phường 8, Quận 5, Thành phố Hồ Chí Minh") == \
        "468 Nguyễn Trãi, Thành phố Hồ Chí Minh"
    assert g._street_address("268 Lý Thường Kiệt, Phường 14, Quận 10") == "268 Lý Thường Kiệt"
    assert g._street_address("Khu phố 6, Phường Linh Trung, Thành phố Thủ Đức") == ""
    assert g._street_address("Đông Hòa, Dĩ An, Bình Dương") == ""
