#!/usr/bin/env bash
# Start the phone-stream server (generates certificates on first run).
set -euo pipefail
cd "$(dirname "$0")"
[ -f certs/cert.pem ] || bash gen_certs.sh
exec python3 server.py "${1:-8443}"
