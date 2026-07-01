import { io } from 'socket.io-client';
import { SOCKET_URL } from './config';

let socket = null;

export function connectSocket(callbacks = {}) {
  // Always start from a clean socket so listeners (driver-arrived, pin-verified…)
  // are never registered twice — that caused the PIN to be read aloud twice.
  if (socket) { try { socket.off(); socket.disconnect(); } catch (e) {} socket = null; }
  // Default: SAME-ORIGIN -> goes through this server's /socket.io (Vite proxy in
  // dev). On HTTPS that becomes wss with no mixed-content. Override with
  // ?realtime=http://host:3001 only when the driver server is on another host.
  const override = new URLSearchParams(window.location.search).get('realtime');
  const base = override || SOCKET_URL;   // undefined -> same-origin (dev/Vite proxy)
  const opts = { transports: ['websocket', 'polling'] };
  socket = base ? io(base, opts) : io(opts);

  socket.on('connect', () => callbacks.onConnect?.());
  socket.on('disconnect', () => callbacks.onDisconnect?.());
  socket.on('driver-accepted', (data) => callbacks.onDriverAccepted?.(data));
  socket.on('driver-arrived', (data) => callbacks.onDriverArrived?.(data));
  socket.on('driver-distance', (data) => callbacks.onDriverDistance?.(data));
  socket.on('pin-verified', (data) => callbacks.onPinVerified?.(data));
  socket.on('trip-completed', (data) => callbacks.onTripCompleted?.(data));
  
  return socket;
}

export function emitPassengerWaiting(data) {
  if (socket) socket.emit('passenger-waiting', data);
}

export async function loginPassenger(realtimeUrl, credentials) {
  const res = await fetch(`${realtimeUrl}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  });
  return res.json();
}

export function disconnectSocket() {
  if (socket) { socket.disconnect(); socket = null; }
}
