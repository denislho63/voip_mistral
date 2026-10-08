#!/usr/bin/env bash
# Generate a self-signed TLS certificate for local testing of the
# phone-stream server. Browsers will show a certificate warning that you
# must accept once (self-signed certs cannot be silently trusted).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=phone-stream.local" \
  -addext "subjectAltName=DNS:phone-stream.local,DNS:localhost,IP:127.0.0.1"
chmod 600 certs/key.pem
echo "certificates written to certs/cert.pem and certs/key.pem"
