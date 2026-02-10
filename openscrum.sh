#!/usr/bin/env bash
# OpenScrum launcher: start backend if not running, then start TUI client.
# Workspace root = current directory when you run the command (run from your project folder).
# Requires mamba environment "openscrum" (mamba activate openscrum).

set -e

# Workspace root = current directory (no assumed location)
export OPENSCRUM_WORKSPACE_ROOT="$(pwd)"

# Find the OpenScrum repo root (directory containing server/ and client/), resolving symlinks so it works when this script is in PATH
SCRIPT_PATH="${BASH_SOURCE[0]}"
while [ -L "$SCRIPT_PATH" ]; do
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
  SCRIPT_PATH="$(readlink "$SCRIPT_PATH")"
  case "$SCRIPT_PATH" in
    /*) ;;
    *) SCRIPT_PATH="$SCRIPT_DIR/$SCRIPT_PATH" ;;
  esac
done
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

# Load ~/.env so OPENAI_API_KEY, OPENAI_MODEL, etc. are available
if [ -f "${HOME}/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  . "${HOME}/.env"
  set +a
fi

# Activate mamba environment "openscrum" so uvicorn and deps are available
if [ -n "$(command -v mamba)" ]; then
  eval "$(mamba shell.hook activate bash 2>/dev/null)" || true
  mamba activate openscrum
elif [ -n "$(command -v conda)" ]; then
  eval "$(conda shell.hook activate bash 2>/dev/null)" || true
  conda activate openscrum
fi

# Add to PATH (run from anywhere): symlink this script into a directory on your PATH, e.g.:
#   ln -sf /path/to/openscrum/openscrum/openscrum.sh ~/bin/openscrum
# Then run: cd /path/to/your/project && openscrum

PORT="${OPENSCRUM_PORT:-8000}"
BASE_URL="${OPENSCRUM_URL:-http://localhost:$PORT}"

# Parse options (don't pass these to the client)
RESTART=0
while [ $# -gt 0 ]; do
  case "$1" in
    --restart|-r) RESTART=1; shift ;;
    --help|-h)
      echo "Usage: openscrum [OPTIONS] [URL]"
      echo "  Run from your project directory; that directory is the workspace root."
      echo "  Options:"
      echo "    --restart, -r   Restart the backend server (kill existing, then start)"
      echo "    --help, -h      Show this help"
      echo "  Requires: mamba activate openscrum (or conda env openscrum)"
      echo "  Add to PATH: ln -sf $SCRIPT_DIR/openscrum.sh ~/bin/openscrum"
      exit 0
      ;;
    *) break ;;
  esac
done

# Check if backend is already up
backend_up() {
  curl -sf --max-time 2 "${BASE_URL}/health" >/dev/null 2>&1
}

# Stop backend (processes listening on PORT)
kill_backend() {
  local pids
  pids=$(lsof -ti ":$PORT" 2>/dev/null) || true
  if [ -n "$pids" ]; then
    echo "Stopping OpenScrum backend on port $PORT..."
    echo "$pids" | xargs kill 2>/dev/null || true
    sleep 1
    pids=$(lsof -ti ":$PORT" 2>/dev/null) || true
    [ -n "$pids" ] && echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

if [ "$RESTART" = 1 ]; then
  kill_backend
fi

if ! backend_up; then
  echo "Starting OpenScrum backend on port $PORT..."
  UVICORN_LOG="$(mktemp)"
  python -m uvicorn server.main:app --host 127.0.0.1 --port "$PORT" >>"$UVICORN_LOG" 2>&1 &
  UVICORN_PID=$!
  for i in $(seq 1 30); do
    if backend_up; then
      rm -f "$UVICORN_LOG"
      break
    fi
    if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
      echo "Backend failed to start." >&2
      [ -s "$UVICORN_LOG" ] && { echo "Output:" >&2; cat "$UVICORN_LOG" >&2; }
      rm -f "$UVICORN_LOG"
      echo "Activate env first: mamba activate openscrum" >&2
      exit 1
    fi
    sleep 0.5
  done
  rm -f "$UVICORN_LOG"
  if ! backend_up; then
    echo "Backend did not become ready in time." >&2
    kill "$UVICORN_PID" 2>/dev/null || true
    exit 1
  fi
  echo "Backend ready."
fi

exec python -m client.tui "$BASE_URL" "$@"
