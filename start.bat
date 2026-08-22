@echo off
title Zia Quant - Signal Intelligence Platform
color 0B

echo =========================================================
echo   LAUNCHING ZIA QUANT PLATFORM...
echo =========================================================
echo.

if not exist ".venv" (
    echo [INFO] Virtual environment not found. Running initial setup first...
    call setup.bat
)

echo Starting Platform Server...
start "" "http://127.0.0.1:5000"
call .venv\Scripts\python.exe run.py

pause
