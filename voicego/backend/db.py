"""
db.py - MongoDB persistence for VoiceGo.

The app can still run without MongoDB during voice/STT demos. Database-backed
features return a clear "database_unavailable" response instead of crashing.
"""
import os
import uuid
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

try:
    from pymongo import MongoClient, ASCENDING
    from pymongo.errors import ServerSelectionTimeoutError
except ImportError:  # pragma: no cover - exercised only when deps are missing.
    MongoClient = None
    ASCENDING = 1
    ServerSelectionTimeoutError = Exception


MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "voicego")
DEMO_PASSENGER_ID = os.getenv("DEMO_PASSENGER_ID", "demo-passenger-visual")

_client = None
_indexes_ready = False


class MongoUnavailable(RuntimeError):
    """Raised when MongoDB is not configured, installed, or reachable."""


def utcnow():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def point(lat, lng):
    if lat is None or lng is None:
        return None
    return {"type": "Point", "coordinates": [float(lng), float(lat)]}


def coords(location):
    if not location:
        return {}
    lng, lat = location.get("coordinates", [None, None])
    return {"lat": lat, "lng": lng}


def serialize_doc(doc):
    """Return a JSON-friendly copy of a Mongo document."""
    if doc is None:
        return None
    out = {}
    for key, value in doc.items():
        out["id" if key == "_id" else key] = serialize_value(value)
    return out


def serialize_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    return value


def _client_or_raise():
    global _client
    if MongoClient is None:
        raise MongoUnavailable("pymongo is not installed")
    if not MONGODB_URI:
        raise MongoUnavailable("MONGODB_URI is empty")
    if _client is None:
        _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=1200)
    try:
        _client.admin.command("ping")
    except ServerSelectionTimeoutError as exc:
        raise MongoUnavailable(str(exc)) from exc
    return _client


def get_db():
    db = _client_or_raise()[MONGODB_DB]
    ensure_indexes(db)
    return db


def mongo_status():
    try:
        db = get_db()
        return {
            "enabled": True,
            "database": MONGODB_DB,
            "users": db.users.count_documents({}),
            "places": db.places.count_documents({}),
            "rides": db.ride_requests.count_documents({}),
            "reports": db.reports.count_documents({}),
        }
    except MongoUnavailable as exc:
        return {"enabled": False, "database": MONGODB_DB, "reason": str(exc)}


def ensure_indexes(db):
    global _indexes_ready
    if _indexes_ready:
        return
    db.users.create_index([("role", ASCENDING)])
    db.drivers.create_index([("user_id", ASCENDING)], unique=True)
    db.places.create_index([("location", "2dsphere")])
    db.places.create_index([("name", ASCENDING), ("address", ASCENDING)])
    db.ride_requests.create_index([("passenger_id", ASCENDING), ("created_at", ASCENDING)])
    db.reports.create_index([("location", "2dsphere")])
    db.reports.create_index([("reporter_id", ASCENDING), ("created_at", ASCENDING)])
    db.reward_transactions.create_index([("user_id", ASCENDING), ("created_at", ASCENDING)])
    _indexes_ready = True


def seed_demo_data():
    """Idempotently seed a passenger, driver, and accessible demo places."""
    db = get_db()
    now = utcnow()
    passenger = {
        "_id": DEMO_PASSENGER_ID,
        "full_name": "Minh Anh",
        "email": "minhanh.voicego@example.com",
        "phone": "0900000001",
        "role": "passenger",
        "total_reward_points": 0,
        "accessibility_profile": {
            "disability_type": "visual_impairment",
            "needs_driver_assistance": True,
        },
        "created_at": now,
        "updated_at": now,
    }
    driver_user = {
        "_id": "demo-driver-user-a",
        "full_name": "Nguyen Van A",
        "email": "driver.a@example.com",
        "phone": "0900000002",
        "role": "driver",
        "total_reward_points": 0,
        "created_at": now,
        "updated_at": now,
    }
    db.users.update_one({"_id": passenger["_id"]}, {"$setOnInsert": passenger}, upsert=True)
    db.users.update_one({"_id": driver_user["_id"]}, {"$setOnInsert": driver_user}, upsert=True)

    db.drivers.update_one(
        {"_id": "demo-driver-a"},
        {"$setOnInsert": {
            "_id": "demo-driver-a",
            "user_id": driver_user["_id"],
            "vehicle_type": "electric_bike",
            "vehicle_model": "GrabBike EV",
            "license_plate": "59-X1 234.56",
            "has_low_step_vehicle": True,
            "accessibility_training_completed": True,
            "rating": 4.92,
            "created_at": now,
            "updated_at": now,
        }},
        upsert=True,
    )

    seed_places = [
        ("place-iu", "Truong Dai hoc Quoc te", "Khu pho 6, phuong Linh Trung, TP Thu Duc, TP.HCM", 10.8782, 106.8012, True, 4.0, 3),
        ("place-ben-thanh", "Ben Thanh", "Cho Ben Thanh, phuong Ben Thanh, Quan 1, TP.HCM", 10.7769, 106.7009, True, 4.4, 5),
        ("place-crescent", "Crescent Mall", "101 Ton Dat Tien, Tan Phu, Quan 7, TP.HCM", 10.7250, 106.7180, True, 4.7, 8),
        ("place-bach-khoa", "Dai hoc Bach Khoa TP.HCM", "268 Ly Thuong Kiet, Quan 10, TP.HCM", 10.7724, 106.6578, False, 3.2, 4),
    ]
    for place_id, name, address, lat, lng, entrance, score, count in seed_places:
        db.places.update_one(
            {"_id": place_id},
            {"$setOnInsert": {
                "_id": place_id,
                "name": name,
                "address": address,
                "location": point(lat, lng),
                "accessibility": {
                    "accessible_entrance": entrance,
                    "score_avg": score,
                    "score_count": count,
                },
                "created_at": now,
                "updated_at": now,
            }},
            upsert=True,
        )
    return mongo_status()


def get_user(user_id=DEMO_PASSENGER_ID):
    return serialize_doc(get_db().users.find_one({"_id": user_id}))


def update_accessibility_profile(user_id, profile):
    now = utcnow()
    allowed = {
        "wheelchair",
        "visual_impairment",
        "hearing_impairment",
        "elderly",
        "temporary_injury",
        "other",
    }
    disability_type = profile.get("disability_type") or "visual_impairment"
    if disability_type not in allowed:
        disability_type = "other"
    payload = {
        "accessibility_profile": {
            "disability_type": disability_type,
            "needs_driver_assistance": bool(profile.get("needs_driver_assistance", True)),
        },
        "updated_at": now,
    }
    db = get_db()
    db.users.update_one(
        {"_id": user_id},
        {
            "$set": payload,
            "$setOnInsert": {
                "_id": user_id,
                "full_name": "VoiceGo Passenger",
                "email": "",
                "phone": "",
                "role": "passenger",
                "total_reward_points": 0,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return get_user(user_id)


def find_nearby_accessible_places(lat, lng, limit=8, max_meters=2500):
    db = get_db()
    cursor = db.places.find({
        "location": {
            "$near": {
                "$geometry": point(lat, lng),
                "$maxDistance": int(max_meters),
            }
        }
    }).limit(int(limit))
    places = []
    for doc in cursor:
        item = serialize_doc(doc)
        item.update(coords(item.get("location")))
        places.append(item)
    return places


def _find_place_by_name_or_near(db, name, address, lat, lng):
    exact = db.places.find_one({"name": name, "address": address})
    if exact:
        return exact
    if lat is not None and lng is not None:
        near = db.places.find_one({
            "location": {
                "$near": {
                    "$geometry": point(lat, lng),
                    "$maxDistance": 80,
                }
            }
        })
        if near:
            return near
    return None


def upsert_place(name, address, lat, lng, accessible_entrance=None, accessibility_score=None):
    db = get_db()
    now = utcnow()
    existing = _find_place_by_name_or_near(db, name, address, lat, lng)
    if existing:
        updates = {"updated_at": now}
        if accessibility_score is not None:
            acc = existing.get("accessibility") or {}
            count = int(acc.get("score_count") or 0)
            avg = float(acc.get("score_avg") or 0)
            new_count = count + 1
            updates["accessibility.score_avg"] = round(((avg * count) + accessibility_score) / new_count, 2)
            updates["accessibility.score_count"] = new_count
        if accessible_entrance is not None:
            updates["accessibility.accessible_entrance"] = bool(accessible_entrance)
        db.places.update_one({"_id": existing["_id"]}, {"$set": updates})
        return db.places.find_one({"_id": existing["_id"]})

    doc = {
        "_id": new_id(),
        "name": name,
        "address": address,
        "location": point(lat, lng),
        "accessibility": {
            "accessible_entrance": bool(accessible_entrance) if accessible_entrance is not None else None,
            "score_avg": float(accessibility_score) if accessibility_score is not None else None,
            "score_count": 1 if accessibility_score is not None else 0,
        },
        "created_at": now,
        "updated_at": now,
    }
    db.places.insert_one(doc)
    return doc


def _driver_alert(profile):
    dtype = (profile or {}).get("disability_type") or "other"
    needs_help = bool((profile or {}).get("needs_driver_assistance"))
    labels = {
        "wheelchair": "Hanh khach dung xe lan",
        "visual_impairment": "Hanh khach khiem thi",
        "hearing_impairment": "Hanh khach khiem thinh",
        "elderly": "Hanh khach lon tuoi",
        "temporary_injury": "Hanh khach dang chan thuong tam thoi",
        "other": "Hanh khach co nhu cau ho tro tiep can",
    }
    action = "Can chu dong goi dien, xac nhan dung diem don va ho tro len xe." if needs_help else "Hay giao tiep ro rang va kien nhan khi don khach."
    return f"{labels.get(dtype, labels['other'])}. {action}"


def _choose_driver(accessibility_type=None):
    db = get_db()
    query = {"accessibility_training_completed": True}
    if accessibility_type == "wheelchair":
        query["has_low_step_vehicle"] = True
    return db.drivers.find_one(query, sort=[("rating", -1)]) or db.drivers.find_one(sort=[("rating", -1)])


def create_ride_request(
    passenger_id=DEMO_PASSENGER_ID,
    pickup=None,
    destination=None,
    booking_method="ai_voice",
    vehicle="bike",
    estimated_price=None,
    estimated_distance_km=None,
    estimated_arrival_minutes=None,
    accessibility_score=None,
):
    db = get_db()
    now = utcnow()
    passenger = db.users.find_one({"_id": passenger_id}) or {}
    profile = passenger.get("accessibility_profile") or {}
    accessibility_type = profile.get("disability_type")
    pickup = pickup or {}
    destination = destination or {}

    pickup_place = upsert_place(
        pickup.get("name") or "Diem don",
        pickup.get("address") or pickup.get("name") or "Diem don",
        pickup.get("lat"),
        pickup.get("lng"),
    )
    destination_place = upsert_place(
        destination.get("name") or "Diem den",
        destination.get("address") or destination.get("name") or "Diem den",
        destination.get("lat"),
        destination.get("lng"),
        accessibility_score=accessibility_score,
    )
    driver = _choose_driver(accessibility_type)
    alert = _driver_alert(profile)

    doc = {
        "_id": new_id(),
        "passenger_id": passenger_id,
        "driver_id": driver["_id"] if driver else None,
        "pickup": {
            "place_id": pickup_place["_id"],
            "name": pickup_place.get("name"),
            "address": pickup_place.get("address"),
            "location": pickup_place.get("location"),
        },
        "destination": {
            "place_id": destination_place["_id"],
            "name": destination_place.get("name"),
            "address": destination_place.get("address"),
            "location": destination_place.get("location"),
        },
        "booking_method": booking_method,
        "vehicle": vehicle,
        "status": "driver_assigned" if driver else "searching",
        "accessibility_type": accessibility_type,
        "driver_alert_message": alert,
        "driver_alert_acknowledged": False,
        "estimated_price": estimated_price,
        "estimated_distance_km": estimated_distance_km,
        "estimated_arrival_minutes": estimated_arrival_minutes,
        "created_at": now,
        "updated_at": now,
    }
    db.ride_requests.insert_one(doc)
    result = serialize_doc(doc)
    if driver:
        result["driver"] = serialize_doc(driver)
        driver_user = db.users.find_one({"_id": driver.get("user_id")})
        result["driver_user"] = serialize_doc(driver_user)
    result["pickup"].update(coords(result["pickup"].get("location")))
    result["destination"].update(coords(result["destination"].get("location")))
    return result


def acknowledge_driver_alert(ride_id):
    db = get_db()
    db.ride_requests.update_one(
        {"_id": ride_id},
        {"$set": {"driver_alert_acknowledged": True, "updated_at": utcnow()}},
    )
    return serialize_doc(db.ride_requests.find_one({"_id": ride_id}))


def create_accessibility_report(reporter_id=DEMO_PASSENGER_ID, payload=None):
    db = get_db()
    payload = payload or {}
    now = utcnow()
    score = int(payload.get("accessibility_score") or 3)
    score = max(1, min(5, score))
    place = upsert_place(
        payload.get("name") or "Dia diem moi",
        payload.get("address") or payload.get("name") or "Dia diem moi",
        payload.get("lat"),
        payload.get("lng"),
        accessible_entrance=payload.get("disability_accessible_entrance"),
        accessibility_score=score,
    )
    reward_points = int(payload.get("reward_points") or 10)
    report = {
        "_id": new_id(),
        "reporter_id": reporter_id,
        "place_id": place["_id"],
        "name": payload.get("name") or place.get("name"),
        "address": payload.get("address") or place.get("address"),
        "location": place.get("location"),
        "disability_accessible_entrance": bool(payload.get("disability_accessible_entrance")),
        "accessibility_score": score,
        "status": "pending",
        "reward_points": reward_points,
        "created_at": now,
        "updated_at": now,
    }
    db.reports.insert_one(report)
    tx = {
        "_id": new_id(),
        "user_id": reporter_id,
        "report_id": report["_id"],
        "points": reward_points,
        "reason": "helpful_report",
        "created_at": now,
    }
    db.reward_transactions.insert_one(tx)
    db.users.update_one(
        {"_id": reporter_id},
        {"$inc": {"total_reward_points": reward_points}, "$set": {"updated_at": now}},
    )
    result = serialize_doc(report)
    result.update(coords(result.get("location")))
    result["reward_transaction"] = serialize_doc(tx)
    result["place"] = serialize_doc(place)
    return result
