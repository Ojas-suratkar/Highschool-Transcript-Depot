#!/bin/bash
# Helper script to run Alembic migrations with proper environment setup
# Usage: ./run_alembic.sh [alembic command]
# Examples:
#   ./run_alembic.sh history
#   ./run_alembic.sh current
#   ./run_alembic.sh upgrade head
#   ./run_alembic.sh revision --autogenerate -m "add new column"

set -e

# Change to the backend directory
cd "$(dirname "$0")"

# Load environment variables using Python's dotenv (handles special characters properly)
if [ -f .env ]; then
    eval $(python3 -c "
from dotenv import dotenv_values
import shlex
config = dotenv_values('.env')
for key, value in config.items():
    if value:
        print(f'export {key}={shlex.quote(value)}')
")
fi

# Check if ALEMBIC_URL is set
if [ -z "$ALEMBIC_URL" ]; then
    echo "❌ Error: ALEMBIC_URL is not set in .env file"
    exit 1
fi

# Check if Cloud SQL Proxy is running
if ! nc -z 127.0.0.1 5432 2>/dev/null; then
    echo "⚠️  Warning: Cloud SQL Proxy doesn't appear to be running on 127.0.0.1:5432"
    echo "   Start it with: cloud-sql-proxy --credentials-file=apps/backend/cloudsql/service-account.json doc-ai-transcript:us-west2:student-transcripts"
    echo ""
fi

# Run alembic with the provided arguments
echo "🔄 Running: python3 -m alembic $@"
python3 -m alembic "$@"

