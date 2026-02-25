#!/usr/bin/env bash
# Run OpenScrum backend, optionally frontend dev server, with shared Ctrl+C cleanup.
# Prefer mamba; fallback to conda reliably for non-interactive shells.
set -euo pipefail

ENABLE_DETAILED_LOG=0
START_WEBCLIENT=0
UVICORN_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --log)
      ENABLE_DETAILED_LOG=1
      shift
      ;;
    --web)
      START_WEBCLIENT=1
      shift
      ;;
    --help|-h)
      echo "Usage: ./server.sh [--log] [--web] [uvicorn args...]"
      echo "  --log     Enable detailed workspace logging"
      echo "  --web     Also start webclient dev server (npm run dev)"
      exit 0
      ;;
    *)
      UVICORN_ARGS+=("$1")
      shift
      ;;
  esac
done

if [ "$ENABLE_DETAILED_LOG" = "1" ]; then
  export OPENSCRUM_DETAILED_LOG=1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BACKEND_PID=""
WEB_PID=""

cleanup() {
  set +e
  if [ -n "$WEB_PID" ] && kill -0 "$WEB_PID" 2>/dev/null; then
    kill "$WEB_PID" 2>/dev/null || true
    wait "$WEB_PID" 2>/dev/null || true
  fi
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

start_backend() {
  if command -v mamba >/dev/null 2>&1; then
    mamba run -n openscrum uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload "$@" &
    BACKEND_PID=$!
    return 0
  fi

  if command -v conda >/dev/null 2>&1; then
    # Use conda shell hook when available (works better in some terminals).
    if eval "$(conda shell.bash hook 2>/dev/null)"; then
      conda activate openscrum
      uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload "$@" &
      BACKEND_PID=$!
      return 0
    fi
    # Final fallback if shell hook is unavailable.
    conda run -n openscrum uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload "$@" &
    BACKEND_PID=$!
    return 0
  fi

  echo "Neither mamba nor conda was found in PATH." >&2
  echo "If conda is installed, add it to PATH before running server.sh." >&2
  exit 1
}

start_webclient() {
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm was not found in PATH, cannot start webclient." >&2
    exit 1
  fi
  (
    cd "$SCRIPT_DIR/webclient"
    npm run dev
  ) &
  WEB_PID=$!
}

if [ "${#UVICORN_ARGS[@]}" -gt 0 ]; then
  start_backend "${UVICORN_ARGS[@]}"
else
  start_backend
fi
echo "Backend started (pid: $BACKEND_PID)"

if [ "$START_WEBCLIENT" = "1" ]; then
  start_webclient
  echo "Webclient started (pid: $WEB_PID)"
  # Portable replacement for `wait -n` (not available in older macOS bash).
  while true; do
    backend_alive=0
    web_alive=0
    if kill -0 "$BACKEND_PID" 2>/dev/null; then backend_alive=1; fi
    if kill -0 "$WEB_PID" 2>/dev/null; then web_alive=1; fi
    if [ "$backend_alive" -eq 0 ] || [ "$web_alive" -eq 0 ]; then
      break
    fi
    sleep 1
  done
else
  wait "$BACKEND_PID" || true
fi
