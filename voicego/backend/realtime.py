"""
realtime.py — Socket.IO relay nhúng thẳng vào FastAPI (KHÔNG cần server Node :3001).

Đủ để DEMO luồng PIN: khách đặt xe (giọng nói) ──> tài xế nhận cuốc ──> đến nơi
──> đọc PIN ──> tài xế nhập PIN ──> "lên xe an toàn".

Khớp đúng "hợp đồng" sự kiện mà frontend đang dùng:
  Khách (useVoiceApp/socket.js)         Tài xế (DriverView.jsx)
  emit  passenger-waiting {userId,name,accessibility}
  on    driver-accepted {driverName,licensePlate}
  on    driver-arrived  {driverName,licensePlate,pin}
  on    pin-verified / trip-completed
                                        emit driver-online {userId}
                                        emit driver-accept {userId}
                                        emit driver-arrive {userId}
                                        emit verify-pin {pin}
                                        emit trip-completed {userId}
                                        on   new-ride / ride-confirmed / pin-display
                                        on   pin-verified / pin-failed

Trạng thái giữ trong RAM, mô hình 1 chuyến đang chạy tại một thời điểm — vừa đủ cho
demo hackathon (1 khách + 1 tài xế). Nhiều chuyến song song KHÔNG nằm trong phạm vi.
"""
import math
import random
import socketio

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


def _haversine_m(lat1, lng1, lat2, lng2):
    """Distance in METERS between two lat/lng points (for the 'last 10m' UI)."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ---- state (1 chuyến đang hoạt động) -------------------------------------
_drivers: set[str] = set()       # sid của các tài xế đang online
_trip: dict = {}                 # {passenger_sid, passenger_name, accessibility, pin, driver_name, plate}

# Thông tin tài xế hiển thị cho khách. Đổi tuỳ thích — chỉ để demo.
_DEMO_DRIVERS = [
    {"name": "Anh Tuấn", "plate": "59-H1 234.56"},
    {"name": "Anh Minh", "plate": "51-F2 678.90"},
    {"name": "Chị Lan", "plate": "59-X3 112.23"},
]


def _coords(data):
    """Pull a {lat,lng} pair out of a socket payload, or None if missing/invalid."""
    data = data or {}
    lat, lng = data.get("lat"), data.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return {"lat": float(lat), "lng": float(lng)}
    return None


def _driver_name(user_id):
    """Best-effort: lấy tên thật của tài xế từ Mongo; lỗi thì dùng mặc định."""
    try:
        from db import get_user
        u = get_user(user_id) or {}
        name = u.get("full_name") or u.get("name")
        if name:
            return name
    except Exception:
        pass
    return None


@sio.event
async def connect(sid, environ):
    pass


@sio.event
async def disconnect(sid):
    _drivers.discard(sid)
    if _trip.get("passenger_sid") == sid:
        _trip.clear()


@sio.on("driver-online")
async def driver_online(sid, data):
    _drivers.add(sid)
    # Nếu đang có khách chờ sẵn -> báo ngay cho tài xế vừa online.
    if _trip.get("passenger_sid"):
        await sio.emit("new-ride", {"accessibility": _trip.get("accessibility", "")}, to=sid)


@sio.on("passenger-waiting")
async def passenger_waiting(sid, data):
    data = data or {}
    drv = random.choice(_DEMO_DRIVERS)
    _trip.clear()
    _trip.update({
        "passenger_sid": sid,
        "passenger_name": data.get("name") or "Hành khách",
        "accessibility": data.get("accessibility", ""),
        "pin": f"{random.randint(0, 9999):04d}",
        "driver_name": drv["name"],
        "plate": drv["plate"],
        # Rider's pickup GPS — lets the driver see the distance to the (blind)
        # passenger for the "last 10 metres" find-each-other step. May be None.
        "passenger_loc": _coords(data),
    })
    # Báo cho mọi tài xế online là có cuốc mới.
    payload = {"accessibility": _trip["accessibility"]}
    for d in list(_drivers):
        await sio.emit("new-ride", payload, to=d)


@sio.on("driver-location")
async def driver_location(sid, data):
    """Driver's live GPS. Relay the driver↔passenger distance to BOTH sides so
    the driver screen shows 'cách khách ~X m' and the (blind) passenger's phone
    tunes its locator beacon (louder/faster as the driver gets closer)."""
    if not _trip.get("passenger_sid"):
        return
    loc = _coords(data)
    if not loc:
        return
    _trip["driver_loc"] = loc
    ploc = _trip.get("passenger_loc")
    if not ploc:
        return
    meters = round(_haversine_m(loc["lat"], loc["lng"], ploc["lat"], ploc["lng"]))
    await sio.emit("ride-distance", {"meters": meters}, to=sid)                       # driver
    await sio.emit("driver-distance", {"meters": meters}, to=_trip["passenger_sid"])  # passenger


@sio.on("driver-accept")
async def driver_accept(sid, data):
    if not _trip.get("passenger_sid"):
        return
    name = _driver_name((data or {}).get("userId")) or _trip["driver_name"]
    _trip["driver_name"] = name
    # -> Khách: "đã có tài xế nhận chuyến" (CHƯA lộ PIN).
    await sio.emit("driver-accepted",
                   {"driverName": name, "licensePlate": _trip["plate"]},
                   to=_trip["passenger_sid"])
    # -> Tài xế: hiện tên khách.
    await sio.emit("ride-confirmed",
                   {"passengerName": _trip["passenger_name"], "accessibility": _trip["accessibility"]},
                   to=sid)


@sio.on("driver-arrive")
async def driver_arrive(sid, data):
    if not _trip.get("passenger_sid"):
        return
    # -> Khách: đọc tên TX + biển số + ĐỌC PIN.
    await sio.emit("driver-arrived",
                   {"driverName": _trip["driver_name"],
                    "licensePlate": _trip["plate"],
                    "pin": _trip["pin"]},
                   to=_trip["passenger_sid"])
    # -> Tài xế: mở bàn phím nhập PIN.
    await sio.emit("pin-display",
                   {"passengerName": _trip["passenger_name"], "accessibility": _trip["accessibility"]},
                   to=sid)


@sio.on("verify-pin")
async def verify_pin(sid, data):
    if not _trip.get("passenger_sid"):
        return
    entered = str((data or {}).get("pin", ""))
    if entered == _trip["pin"]:
        await sio.emit("pin-verified", {}, to=sid)                       # tài xế
        await sio.emit("pin-verified", {}, to=_trip["passenger_sid"])    # khách
    else:
        await sio.emit("pin-failed", {}, to=sid)


@sio.on("trip-completed")
async def trip_completed(sid, data):
    if _trip.get("passenger_sid"):
        await sio.emit("trip-completed", {}, to=_trip["passenger_sid"])
    _trip.clear()


def attach(app):
    """Bọc FastAPI app: /socket.io/* -> Socket.IO, còn lại -> FastAPI."""
    return socketio.ASGIApp(sio, other_asgi_app=app, socketio_path="socket.io")
