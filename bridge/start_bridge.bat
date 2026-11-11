@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Create virtualenv and install requirements first.
    pause
    exit /b 1
)

echo [INFO] Checking local MetaTrader 5 terminal connection...
".venv\Scripts\python.exe" -m bridge.mt5_bridge --self-check
if errorlevel 1 (
    echo [ERROR] MetaTrader 5 self-check failed. Ensure MT5 terminal is open and logged into your Demo account.
    pause
    exit /b 1
)

echo [INFO] Starting Zia Quant Read-Only MT5 Render Bridge (reads .env)...
".venv\Scripts\python.exe" -m bridge.mt5_bridge --interval 15
