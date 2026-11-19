#!/bin/sh
# Start the isolated Transcript Extraction Lab on http://localhost:8900
# Runs from the repo root so `lab.backend.app` resolves as a package.
cd "$(dirname "$0")/.." || exit 1
exec python3 -m uvicorn lab.backend.app:app --host 127.0.0.1 --port 8900 "$@"
