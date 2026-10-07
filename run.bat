@echo off
REM Start the phone-stream server (generates certificates on first run).
REM Usage: run.bat [port]   (default port: 8443)
setlocal
cd /d "%~dp0"

where openssl >nul 2>nul
if errorlevel 1 (
  echo OpenSSL is required to generate certificates. Install it first.
  exit /b 1
)

if not exist certs\cert.pem call gen_certs.bat
if errorlevel 1 exit /b 1

set PORT=%1
if "%PORT%"=="" set PORT=8443

python server.py %PORT%
endlocal
