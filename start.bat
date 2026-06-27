@echo off
title VoiceGo Dev Servers

echo =========================================================
echo Starting VoiceGo Local Development Servers...
echo =========================================================

:: Start Python Backend
echo [1/3] Starting Python FastAPI Backend on port 8000...
start "VoiceGo Backend (Python)" cmd /c "cd voicego\backend && python -m uvicorn main:app --port 8000 --reload"

:: Start React Frontend
echo [2/3] Starting React Frontend on port 5173...
start "VoiceGo Frontend (React/Vite)" cmd /c "cd voicego\frontend && npm run dev -- --host"

:: Start Node.js Realtime Socket.IO Backend
echo [3/3] Starting Node.js Socket.IO Backend on port 3001...
start "VoiceGo Realtime (Node.js)" cmd /c "cd backend && node server.js"

echo.
echo =========================================================
echo ✅ VoiceGo Python Backend running at: http://localhost:8000
echo ✅ VoiceGo React Frontend running at: http://localhost:5173
echo ✅ VoiceGo Node Socket.IO running at: http://localhost:3001
echo =========================================================
pause
