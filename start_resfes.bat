@echo off
echo ================================================
echo   ResFes AR - Quick Start
echo ================================================
echo.
echo Checking dependencies...
python -c "from OpenSSL import crypto; print('  + pyOpenSSL OK')" 2>nul || (
    echo   - Missing pyOpenSSL
    echo   Installing...
    pip install pyOpenSSL
)
python -c "from groq import Groq; print('  + Groq OK')" 2>nul || (
    echo   - Missing Groq
    echo   Installing...
    pip install groq
)
python -c "from flask import Flask; print('  + Flask OK')" 2>nul || (
    echo   - Missing Flask
    echo   Installing...
    pip install flask flask-cors
)
echo.
echo Checking certificates...
if exist cert.pem (
    echo   + cert.pem found
) else (
    echo   - cert.pem will be auto-generated
)
if exist key.pem (
    echo   + key.pem found
) else (
    echo   - key.pem will be auto-generated
)
echo.
echo ================================================
echo   IMPORTANT: Camera Debug Instructions
echo ================================================
echo.
echo 1. Server will start on HTTPS (required for camera)
echo 2. Open in browser: https://YOUR_IP:5000
echo 3. ACCEPT certificate warning (Advanced ^> Proceed)
echo 4. RELOAD page after accepting certificate
echo.
echo For debug/testing, use: https://YOUR_IP:5000/test
echo.
echo If camera permission not requested, see:
echo    DEBUG_CAMERA.md
echo.
echo ================================================
echo.
echo Starting ResFes AR server...
echo.
python resfes.py
