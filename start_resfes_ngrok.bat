@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\pmqua\AppData\Local\Programs\Python\Python310\python.exe"
if not exist "%PYTHON_EXE%" (
  echo [ERROR] Khong tim thay Python tai: %PYTHON_EXE%
  echo Hay sua bien PYTHON_EXE trong file start_resfes_ngrok.bat
  pause
  exit /b 1
)

where ngrok >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Khong tim thay lenh ngrok trong PATH.
  echo Ban da login roi, nhung can cai/dat PATH cho ngrok.exe.
  echo Neu da co file ngrok.exe, sua bien RESFES_NGROK_BIN ben duoi.
  rem set "RESFES_NGROK_BIN=D:\tools\ngrok\ngrok.exe"
  pause
  exit /b 1
)

set "RESFES_AUTO_NGROK=1"
set "RESFES_FORCE_HTTP=1"

echo ==========================================
echo  ResFes + Auto ngrok dang khoi dong...
echo  Sau khi chay, tim dong:
echo  [NGROK] Public URL: https://...
echo ==========================================
echo.

"%PYTHON_EXE%" app\src\main\python\resfes.py

echo.
echo [INFO] Server da dung.
pause
