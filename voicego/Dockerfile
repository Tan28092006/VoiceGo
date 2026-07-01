# VoiceGo — 1 image phục vụ CẢ frontend (React build) + backend (FastAPI).
# Stage 1: build frontend tĩnh bằng Node.  Stage 2: chạy FastAPI, phục vụ luôn dist.

# ---- Stage 1: build frontend ----
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build          # -> /app/frontend/dist

# ---- Stage 2: backend Python (phục vụ API + dist) ----
FROM python:3.11-slim
WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
# main.py tìm dist ở ../frontend/dist (so với backend/) -> đặt đúng vị trí đó
COPY --from=frontend /app/frontend/dist ./frontend/dist

WORKDIR /app/backend
ENV PORT=8000
# shell-form để $PORT do host (Render/Railway/...) cấp được expand
# main:socket_app = FastAPI + Socket.IO relay (luồng PIN realtime)
CMD uvicorn main:socket_app --host 0.0.0.0 --port ${PORT:-8000}
