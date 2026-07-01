# VoiceGo Backend - Quick Start
Write-Host "=== VoiceGo Backend ===" -ForegroundColor Cyan
Set-Location $PSScriptRoot
python -m pip install -r requirements.txt
Write-Host "Starting server on http://localhost:8000 ..." -ForegroundColor Green
python -m uvicorn main:socket_app --reload --port 8000
