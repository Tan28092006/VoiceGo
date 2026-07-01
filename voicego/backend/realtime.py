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
import random
import socketio

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# ---- state (1 chuyến đang hoạt động) -------------------------------------
_drivers: set[str] = set()       # sid của các tài xế đang online
_trip: dict = {}                 # {passenger_sid, passenger_name, accessibility, pin, driver_name, plate}

# Thông tin tài xế hiển thị cho khách. Đổi tuỳ thích — chỉ để demo.
_DEMO_DRIVERS = [
    {"name": "Anh Tuấn", "plate": "59-H1 234.56"},
    {"name": "Anh Minh", "plate": "51-F2 678.90"},
    {"name": "Chị Lan", "plate": "59-X3 112.23"},
]


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
    })
    # Báo cho mọi tài xế online là có cuốc mới.
    payload = {"accessibility": _trip["accessibility"]}
    for d in list(_drivers):
        await sio.emit("new-ride", payload, to=d)


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
