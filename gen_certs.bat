@echo off
REM Generate a self-signed TLS certificate for local testing of the
REM phone-stream server. Browsers will show a certificate warning that you
REM must accept once (self-signed certs cannot be silently trusted).
setlocal
cd /d "%~dp0"
if not exist certs mkdir certs

openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes ^
  -keyout certs\key.pem -out certs\cert.pem ^
  -subj "/CN=phone-stream.local" ^
  -addext "subjectAltName=DNS:phone-stream.local,DNS:localhost,IP:127.0.0.1"
if errorlevel 1 (
  echo OpenSSL is required. Install it or use git's bundled openssl.
  exit /b 1
)

echo certificates written to certs\cert.pem and certs\key.pem
endlocal
