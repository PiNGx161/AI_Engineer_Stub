#!/bin/bash
set -e

echo "Waiting for database to be ready..."
sleep 2

echo "Running seed script..."
uv run python seed.py || echo "Seed skipped (data may already exist)"

echo "Starting API server..."
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
