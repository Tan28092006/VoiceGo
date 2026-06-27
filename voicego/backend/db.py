"""
db.py - MongoDB persistence for VoiceGo.

Collections mirror the hackathon data model:
users, accessibility_profiles, drivers, places, accessibility_places,
ride_requests, reports, reward_transactions.

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
    from pymongo import MongoClient, ASCENDING, DESCENDING
    from pymongo.errors import ServerSelectionTimeoutError
except ImportError:  # pragma: no cover - exercised only when deps are missing.
    MongoClient = None
    ASCENDING = 1
    DESCENDING = -1
    ServerSelectionTimeoutError = Exception


MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "voicego")
DEMO_PASSENGER_ID = os.getenv("DEMO_PASSENGER_ID", "demo-passenger-visual")

DISABILITY_TYPES = {
    "wheelchair",
    "visual_impairment",
    "hearing_impairment",
    "elderly",
    "temporary_injury",
    "other",
}
RIDE_STATUSES = {
    "draft",
    "searching",
    "driver_assigned",
    "accepted",
    "arrived",
    "in_progress",
    "completed",
    "cancelled",
}
REPORT_STATUSES = {"pending", "verified", "rejected"}

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


def clamp_score(score, default=3):
    try:
        value = int(score)
    except (TypeError, ValueError):
        value = default
    return max(1, min(5, value))


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
            "accessibility_profiles": db.accessibility_profiles.count_documents({}),
            "drivers": db.drivers.count_documents({}),
            "places": db.places.count_documents({}),
            "accessibility_places": db.accessibility_places.count_documents({}),
            "rides": db.ride_requests.count_documents({}),
            "reports": db.reports.count_documents({}),
            "reward_transactions": db.reward_transactions.count_documents({}),
        }
    except MongoUnavailable as exc:
        return {"enabled": False, "database": MONGODB_DB, "reason": str(exc)}


def ensure_indexes(db):
    global _indexes_ready
    if _indexes_ready:
        return
    db.users.create_index([("role", ASCENDING)])
    db.accessibility_profiles.create_index([("user_id", ASCENDING)], unique=True)
    db.drivers.create_index([("user_id", ASCENDING)], unique=True)
    db.places.create_index([("location", "2dsphere")])
    db.places.create_index([("name", ASCENDING), ("address", ASCENDING)])
    db.accessibility_places.create_index([("place_id", ASCENDING)], unique=True)
    db.ride_requests.create_index([("passenger_id", ASCENDING), ("created_at", DESCENDING)])
    db.ride_requests.create_index([("driver_id", ASCENDING), ("status", ASCENDING)])
    db.reports.create_index([("location", "2dsphere")])
    db.reports.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    db.reports.create_index([("reporter_id", ASCENDING), ("created_at", DESCENDING)])
    db.reward_transactions.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    db.reward_transactions.create_index([("report_id", ASCENDING)], unique=True)
    _indexes_ready = True


def seed_demo_data():
    """Idempotently seed users, accessibility profiles, drivers, and places."""
    db = get_db()
    now = utcnow()
    users = [
        {
            "_id": DEMO_PASSENGER_ID,
            "full_name": "Minh Anh",
            "email": "minhanh.voicego@example.com",
            "phone": "0900000001",
            "role": "passenger",
            "total_reward_points": 0,
            "created_at": now,
            "updated_at": now,
        },
        {
            "_id": "demo-passenger-wheelchair",
            "full_name": "Quoc Bao",
            "email": "quocbao.voicego@example.com",
            "phone": "0900000003",
            "role": "passenger",
            "total_reward_points": 0,
            "created_at": now,
            "updated_at": now,
        },
        {
            "_id": "demo-driver-user-a",
            "full_name": "Nguyen Van A",
            "email": "driver.a@example.com",
            "phone": "0900000002",
            "role": "driver",
            "total_reward_points": 0,
            "created_at": now,
            "updated_at": now,
        },
    ]
    for user in users:
        db.users.update_one({"_id": user["_id"]}, {"$setOnInsert": user}, upsert=True)

    profiles = [
        (DEMO_PASSENGER_ID, "visual_impairment", True),
        ("demo-passenger-wheelchair", "wheelchair", True),
    ]
    for user_id, disability_type, needs_help in profiles:
        update_accessibility_profile(user_id, {
            "disability_type": disability_type,
            "needs_driver_assistance": needs_help,
        })

    db.drivers.update_one(
        {"_id": "demo-driver-a"},
        {"$setOnInsert": {
            "_id": "demo-driver-a",
            "user_id": "demo-driver-user-a",
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
    for place_id, name, address, lat, lng, entrance, score_avg, score_count in seed_places:
        place_doc = upsert_place(name, address, lat, lng, place_id=place_id)
        upsert_accessibility_place(
            place_doc["_id"],
            accessible_entrance=entrance,
            score=score_avg,
            score_count=score_count,
            replace=True,
        )
    return mongo_status()


def get_accessibility_profile_doc(user_id=DEMO_PASSENGER_ID):
    return get_db().accessibility_profiles.find_one({"user_id": user_id})


def get_user(user_id=DEMO_PASSENGER_ID):
    db = get_db()
    user = serialize_doc(db.users.find_one({"_id": user_id}))
    if not user:
        return None
    user["accessibility_profile"] = serialize_doc(db.accessibility_profiles.find_one({"user_id": user_id}))
    return user


def update_accessibility_profile(user_id, profile):
    db = get_db()
    now = utcnow()
    disability_type = profile.get("disability_type") or "visual_impairment"
    if disability_type not in DISABILITY_TYPES:
        disability_type = "other"

    db.users.update_one(
        {"_id": user_id},
        {
            "$set": {"updated_at": now},
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
    db.accessibility_profiles.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "disability_type": disability_type,
                "needs_driver_assistance": bool(profile.get("needs_driver_assistance", True)),
                "updated_at": now,
            },
            "$setOnInsert": {"_id": new_id(), "created_at": now},
        },
        upsert=True,
    )
    return get_user(user_id)


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


def upsert_place(name, address, lat, lng, place_id=None):
    db = get_db()
    now = utcnow()
    existing = None
    if place_id:
        existing = db.places.find_one({"_id": place_id})
    if not existing:
        existing = _find_place_by_name_or_near(db, name, address, lat, lng)
    if existing:
        db.places.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "name": name,
                "address": address,
                "location": point(lat, lng),
                "updated_at": now,
            }},
        )
        return db.places.find_one({"_id": existing["_id"]})

    doc = {
        "_id": place_id or new_id(),
        "name": name,
        "address": address,
        "location": point(lat, lng),
        "created_at": now,
        "updated_at": now,
    }
    db.places.insert_one(doc)
    return doc


def get_accessibility_place(place_id):
    return get_db().accessibility_places.find_one({"place_id": place_id})


def upsert_accessibility_place(
    place_id,
    accessible_entrance=None,
    score=None,
    score_count=None,
    replace=False,
    source_report_id=None,
):
    db = get_db()
    now = utcnow()
    existing = db.accessibility_places.find_one({"place_id": place_id})
    updates = {"updated_at": now}

    if accessible_entrance is not None:
        updates["disability_accessible_entrance"] = bool(accessible_entrance)
    if source_report_id:
        updates["last_report_id"] = source_report_id

    if score is not None:
        score = float(score)
        if replace:
            count = int(score_count or 1)
            updates["accessibility_score"] = round(score, 2)
            updates["score_count"] = max(1, count)
        else:
            old_count = int((existing or {}).get("score_count") or 0)
            old_avg = float((existing or {}).get("accessibility_score") or 0)
            new_count = old_count + 1
            updates["accessibility_score"] = round(((old_avg * old_count) + score) / new_count, 2)
            updates["score_count"] = new_count

    db.accessibility_places.update_one(
        {"place_id": place_id},
        {
            "$set": updates,
            "$setOnInsert": {"_id": new_id(), "place_id": place_id, "created_at": now},
        },
        upsert=True,
    )
    return db.accessibility_places.find_one({"place_id": place_id})


def _attach_accessibility(place_doc):
    item = serialize_doc(place_doc)
    if not item:
        return None
    item.update(coords(item.get("location")))
    acc = get_accessibility_place(place_doc["_id"])
    item["accessibility"] = serialize_doc(acc)
    return item


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
    return [_attach_accessibility(doc) for doc in cursor]


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
    return db.drivers.find_one(query, sort=[("rating", DESCENDING)]) or db.drivers.find_one(sort=[("rating", DESCENDING)])


def _serialize_ride(doc):
    if not doc:
        return None
    db = get_db()
    result = serialize_doc(doc)
    for key in ("pickup", "destination"):
        if result.get(key):
            result[key].update(coords(result[key].get("location")))
    driver_id = doc.get("driver_id")
    if driver_id:
        driver = db.drivers.find_one({"_id": driver_id})
        result["driver"] = serialize_doc(driver)
        if driver:
            result["driver_user"] = serialize_doc(db.users.find_one({"_id": driver.get("user_id")}))
    passenger_id = doc.get("passenger_id")
    if passenger_id:
        result["passenger"] = serialize_doc(db.users.find_one({"_id": passenger_id}))
        result["accessibility_profile"] = serialize_doc(db.accessibility_profiles.find_one({"user_id": passenger_id}))
    return result


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
    profile = db.accessibility_profiles.find_one({"user_id": passenger_id}) or {}
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
    )
    if accessibility_score is not None:
        upsert_accessibility_place(destination_place["_id"], score=clamp_score(accessibility_score))

    driver = _choose_driver(accessibility_type)
    alert = _driver_alert(profile)
    doc = {
        "_id": new_id(),
        "passenger_id": passenger_id,
        "driver_id": driver["_id"] if driver else None,
        "pickup_place_id": pickup_place["_id"],
        "destination_place_id": destination_place["_id"],
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
    return _serialize_ride(doc)


def get_ride_request(ride_id):
    return _serialize_ride(get_db().ride_requests.find_one({"_id": ride_id}))


def update_ride_status(ride_id, status):
    if status not in RIDE_STATUSES:
        raise ValueError(f"invalid status: {status}")
    db = get_db()
    now = utcnow()
    updates = {"status": status, "updated_at": now}
    if status == "accepted":
        updates["accepted_at"] = now
    elif status == "arrived":
        updates["arrived_at"] = now
    elif status == "in_progress":
        updates["started_at"] = now
    elif status == "completed":
        updates["completed_at"] = now
    elif status == "cancelled":
        updates["cancelled_at"] = now
    db.ride_requests.update_one({"_id": ride_id}, {"$set": updates})
    return get_ride_request(ride_id)


def acknowledge_driver_alert(ride_id):
    db = get_db()
    db.ride_requests.update_one(
        {"_id": ride_id},
        {"$set": {"driver_alert_acknowledged": True, "updated_at": utcnow()}},
    )
    return get_ride_request(ride_id)


def create_accessibility_report(reporter_id=DEMO_PASSENGER_ID, payload=None):
    db = get_db()
    payload = payload or {}
    now = utcnow()
    score = clamp_score(payload.get("accessibility_score"))
    place = upsert_place(
        payload.get("name") or "Dia diem moi",
        payload.get("address") or payload.get("name") or "Dia diem moi",
        payload.get("lat"),
        payload.get("lng"),
    )
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
        "reward_points": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.reports.insert_one(report)
    result = serialize_doc(report)
    result.update(coords(result.get("location")))
    result["place"] = _attach_accessibility(place)
    return result


def list_reports(status=None, limit=100):
    db = get_db()
    query = {}
    if status:
        if status not in REPORT_STATUSES:
            raise ValueError(f"invalid status: {status}")
        query["status"] = status
    reports = []
    for doc in db.reports.find(query).sort("created_at", DESCENDING).limit(int(limit)):
        item = serialize_doc(doc)
        item.update(coords(item.get("location")))
        item["reporter"] = serialize_doc(db.users.find_one({"_id": doc.get("reporter_id")}))
        item["place"] = _attach_accessibility(db.places.find_one({"_id": doc.get("place_id")}))
        reports.append(item)
    return reports


def verify_report(report_id, admin_id=None):
    db = get_db()
    now = utcnow()
    report = db.reports.find_one({"_id": report_id})
    if not report:
        return None
    if report.get("status") == "verified":
        item = serialize_doc(report)
        item["reward_transaction"] = serialize_doc(db.reward_transactions.find_one({"report_id": report_id}))
        return item
    if report.get("status") == "rejected":
        raise ValueError("rejected report cannot be verified")

    acc = upsert_accessibility_place(
        report["place_id"],
        accessible_entrance=report.get("disability_accessible_entrance"),
        score=report.get("accessibility_score"),
        source_report_id=report_id,
    )
    db.reports.update_one(
        {"_id": report_id},
        {"$set": {
            "status": "verified",
            "verified_by": admin_id,
            "verified_at": now,
            "updated_at": now,
            "accessibility_place_id": acc["_id"],
        }},
    )
    reward_points = int(report.get("reward_points") or 1)
    tx = {
        "_id": new_id(),
        "user_id": report["reporter_id"],
        "report_id": report_id,
        "points": reward_points,
        "reason": "helpful_report",
        "created_at": now,
    }
    try:
        db.reward_transactions.insert_one(tx)
        db.users.update_one(
            {"_id": report["reporter_id"]},
            {"$inc": {"total_reward_points": reward_points}, "$set": {"updated_at": now}},
        )
    except Exception:  # noqa: BLE001
        tx = db.reward_transactions.find_one({"report_id": report_id})

    updated = serialize_doc(db.reports.find_one({"_id": report_id}))
    updated.update(coords(updated.get("location")))
    updated["accessibility_place"] = serialize_doc(acc)
    updated["reward_transaction"] = serialize_doc(tx)
    return updated


def reject_report(report_id, admin_id=None, reason=""):
    db = get_db()
    report = db.reports.find_one({"_id": report_id})
    if not report:
        return None
    if report.get("status") == "verified":
        raise ValueError("verified report cannot be rejected")
    db.reports.update_one(
        {"_id": report_id},
        {"$set": {
            "status": "rejected",
            "rejected_by": admin_id,
            "rejected_reason": reason,
            "rejected_at": utcnow(),
            "updated_at": utcnow(),
        }},
    )
    updated = serialize_doc(db.reports.find_one({"_id": report_id}))
    updated.update(coords(updated.get("location")))
    return updated
