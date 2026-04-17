#!/usr/bin/env bash
# Start the Agentic Board API server and serve the built UI.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
UVICORN_BIN="${UVICORN_BIN:-}"

if [[ -z "$UVICORN_BIN" ]]; then
  if [[ -x ".venv/bin/uvicorn" ]]; then
    UVICORN_BIN=".venv/bin/uvicorn"
  elif command -v uvicorn >/dev/null 2>&1; then
    UVICORN_BIN="$(command -v uvicorn)"
  elif command -v uv >/dev/null 2>&1; then
    UVICORN_BIN="uv run uvicorn"
  else
    echo "Error: uvicorn was not found."
    echo "Activate the virtualenv or install dependencies with: .venv/bin/pip install -e ."
    exit 1
  fi
fi

if [[ -f "ui/package.json" ]]; then
  if [[ ! -d "ui/node_modules" ]]; then
    echo "Installing UI dependencies..."
    (cd ui && npm install)
  fi

  echo "Building UI..."
  (cd ui && npm run build)
fi

echo "=== Agentic Board ==="
echo "Starting API server on http://${HOST}:${PORT}"
echo "UI at http://${HOST}:${PORT}"
echo "API docs at http://${HOST}:${PORT}/docs"
echo ""

# shellcheck disable=SC2086
exec $UVICORN_BIN server.api:app --reload --host "$HOST" --port "$PORT"
