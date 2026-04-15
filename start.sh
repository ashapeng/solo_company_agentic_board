#!/usr/bin/env bash
# Start the Agentic Board API server
set -euo pipefail

echo "=== Agentic Board ==="
echo "Starting API server on http://localhost:8000"
echo "UI at http://localhost:8000"
echo "API docs at http://localhost:8000/docs"
echo ""

uv run uvicorn server.api:app --reload --port 8000
