// Nguồn duy nhất cho địa chỉ backend.
//
// - DEV (local): để trống -> same-origin, Vite proxy /api và /socket.io về :8000.
// - PROD (Vercel): đặt biến môi trường VITE_BACKEND_URL = https://<app>.onrender.com
//   khi build -> FE gọi thẳng tới backend Render (CORS đã mở "*").
export const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || '';

// socket.io: '' -> undefined để nối same-origin (dev); có URL -> nối thẳng Render.
export const SOCKET_URL = BACKEND_URL || undefined;
