"""PIN handoff relay (realtime.py), offline: calls the Socket.IO handlers directly with
sio.emit recorded, so no server, network or MongoDB is needed.

Covers the event contract the passenger app (useVoiceApp/socket.js) and the driver app
(DriverView.jsx) rely on:
  passenger-waiting -> new-ride (driver) ; driver-accept -> driver-accepted (no PIN yet)
  driver-arrive -> driver-arrived WITH pin (passenger) ; verify-pin ok -> pin-verified to both
  wrong PIN -> pin-failed to the driver only ; passenger disconnect clears the trip.

NOT covered: real sockets/reconnect, two passengers at once (realtime.py keeps ONE global
trip in process memory), the simulated driver's timing, a server restart mid-trip.

Run (from voicego/backend):  py -m pytest tests -q
"""
import asyncio
import os
import sys
import unittest

os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import realtime  # noqa: E402

P, D = "sid-passenger", "sid-driver"


class PinRelay(unittest.TestCase):
    def setUp(self):
        self.sent = []

        async def emit(event, data=None, to=None, **_):
            self.sent.append((event, data, to))

        self._orig = (realtime.sio.emit, realtime._driver_name)
        realtime.sio.emit = emit
        realtime._driver_name = lambda _uid: None  # skip the Mongo lookup
        realtime._drivers.clear()
        realtime._trip.clear()

    def tearDown(self):
        realtime.sio.emit, realtime._driver_name = self._orig
        realtime._drivers.clear()
        realtime._trip.clear()

    def run_(self, coro):
        return asyncio.run(coro)

    def events(self, to):
        return [(e, d) for e, d, t in self.sent if t == to]

    def book_with_online_driver(self):
        self.run_(realtime.driver_online(D, {}))
        self.run_(realtime.passenger_waiting(P, {"name": "Minh Anh", "accessibility": "visual_impairment"}))

    def test_happy_path_pin_handoff(self):
        self.book_with_online_driver()
        self.assertIn("new-ride", [e for e, _ in self.events(D)])
        pin = realtime._trip["pin"]
        self.assertRegex(pin, r"^\d{4}$")

        self.run_(realtime.driver_accept(D, {}))
        accepted = dict(self.events(P))["driver-accepted"]
        self.assertNotIn("pin", accepted)  # PIN is not revealed before arrival

        self.run_(realtime.driver_arrive(D, {}))
        self.assertEqual(dict(self.events(P))["driver-arrived"]["pin"], pin)
        self.assertIn("pin-display", [e for e, _ in self.events(D)])

        self.run_(realtime.verify_pin(D, {"pin": pin}))
        self.assertIn("pin-verified", [e for e, _ in self.events(D)])
        self.assertIn("pin-verified", [e for e, _ in self.events(P)])

        self.run_(realtime.trip_completed(D, {}))
        self.assertIn("trip-completed", [e for e, _ in self.events(P)])
        self.assertEqual(realtime._trip, {})

    def test_wrong_pin_fails_only_for_driver(self):
        self.book_with_online_driver()
        self.run_(realtime.driver_arrive(D, {}))
        wrong = "0000" if realtime._trip["pin"] != "0000" else "1111"
        self.run_(realtime.verify_pin(D, {"pin": wrong}))
        self.assertIn("pin-failed", [e for e, _ in self.events(D)])
        self.assertNotIn("pin-verified", [e for e, _ in self.events(P)])

    def test_passenger_disconnect_clears_trip(self):
        self.book_with_online_driver()
        self.run_(realtime.disconnect(P))
        self.assertEqual(realtime._trip, {})
        n = len(self.sent)
        self.run_(realtime.verify_pin(D, {"pin": "1234"}))  # no trip -> no-op
        self.assertEqual(len(self.sent), n)


if __name__ == "__main__":
    unittest.main()
