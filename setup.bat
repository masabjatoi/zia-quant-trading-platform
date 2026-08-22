@echo off
title Zia Quant - Initial Setup
color 0A

echo =========================================================
echo   ZIA QUANT - ONE-CLICK INSTALLATION FOR ZIA
echo =========================================================
echo.

echo [1/3] Checking Python installation...
python --version
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b
)

echo.
echo [2/3] Creating Python Virtual Environment (.venv)...
if not exist ".venv" (
    python -m venv .venv
)

echo.
echo [3/3] Installing Dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo =========================================================
echo   SETUP COMPLETE! 
echo   Double click 'start.bat' whenever you want to trade!
echo =========================================================
echo.
pause
