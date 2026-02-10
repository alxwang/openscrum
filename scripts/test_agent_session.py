#!/usr/bin/env python3
"""
Test script against the OpenScrum server: simulates a TUI session.

1. Creates a session with a temporary workspace directory.
2. Sends: "Build a web app for chess game with vue"
3. Streams the response and auto-replies "always" to any permission_request.
4. Optionally sends: "proceed with your plan" and streams again.
5. Asserts that something was built (e.g. package.json, *.vue, or new files).

Usage:
  python scripts/test_agent_session.py [--server URL] [--no-proceed] [--workspace DIR] [--allow-all]

  If the server is not running, it is started automatically from the repo (uvicorn).

  By default, permission requests are shown and you choose: [y]es once / [a]lways / [n]o reject.
  Use --allow-all to auto-allow all permissions (no prompts).

Exit: 0 if something was built, 1 otherwise (or on HTTP/stream error).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import signal
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Need httpx. pip install httpx", file=sys.stderr)
    sys.exit(2)


def _repo_root() -> Path:
    """OpenScrum repo root (directory containing server/ and scripts/)."""
    return Path(__file__).resolve().parent.parent


def _server_up(server: str, timeout: float = 2.0) -> bool:
    try:
        r = httpx.get(f"{server}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def ensure_server(server: str, port: int = 8000) -> None:
    """
    Always start a fresh server from repo root; wait until healthy.

    For test runs we want a clean backend instance every time, so we:
    1. Kill any existing process listening on the target port.
    2. Start a new uvicorn server and wait for /health to succeed.
    """
    # Best-effort kill of any existing process on this port (mirrors openscrum.sh kill_backend).
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True)
    except Exception:
        out = ""
    pids = [p.strip() for p in out.splitlines() if p.strip()]
    for pid_str in pids:
        try:
            os.kill(int(pid_str), signal.SIGTERM)
        except Exception:
            pass
    if pids:
        time.sleep(1)
        for pid_str in pids:
            try:
                os.kill(int(pid_str), signal.SIGKILL)
            except Exception:
                pass

    root = _repo_root()
    if not (root / "server" / "main.py").exists():
        print(f"Repo root not found at {root} (no server/main.py)", file=sys.stderr)
        sys.exit(1)
    print(f"Starting server on port {port}...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env={**os.environ},
    )
    for _ in range(30):
        time.sleep(0.5)
        if _server_up(server):
            print("Server ready.")
            return
        if proc.poll() is not None:
            err = (proc.stderr and proc.stderr.read()) or b""
            print(f"Server exited: {err.decode(errors='replace')}", file=sys.stderr)
            sys.exit(1)
    proc.terminate()
    proc.wait(timeout=5)
    print("Server did not become ready in time.", file=sys.stderr)
    sys.exit(1)


def ask_permission(perm: dict, server: str, client) -> str:
    """Prompt user for permission; return 'once', 'always', or 'reject' and send reply."""
    req_id = perm.get("id")
    if not req_id:
        return "reject"
    name = perm.get("permission", "?")
    tool = (perm.get("metadata") or {}).get("tool", "?")
    patterns = perm.get("patterns", [])
    print(f"\n  Permission: {name} ({tool}) for {patterns}")
    while True:
        try:
            choice = input("  [y]es once / [a]lways / [n]o reject: ").strip().lower() or "y"
        except EOFError:
            choice = "n"
        if choice in ("y", "yes"):
            reply = "once"
            break
        if choice in ("a", "always"):
            reply = "always"
            break
        if choice in ("n", "no"):
            reply = "reject"
            break
        print("  Enter y, a, or n")
    client.post(
        f"{server}/permissions/{req_id}/reply",
        json={"reply": reply},
        timeout=10,
    )
    print(f"  -> {reply}")
    return reply


def main():
    ap = argparse.ArgumentParser(description="Test OpenScrum server session (simulate TUI)")
    ap.add_argument("--server", default="http://127.0.0.1:8000", help="Server base URL")
    ap.add_argument("--no-proceed", action="store_true", help="Do not send 'proceed with your plan'")
    ap.add_argument("--workspace", default=None, help="Workspace directory (default: temp dir)")
    ap.add_argument("--allow-all", action="store_true", help="Auto-allow all permissions (no prompts)")
    args = ap.parse_args()
    server = args.server.rstrip("/")
    port = 8000
    if ":" in server.split("//")[-1]:
        try:
            port = int(server.split(":")[-1].rstrip("/"))
        except ValueError:
            pass

    ensure_server(server, port=port)

    workspace = args.workspace
    if not workspace:
        # Default workspace: "../workspace" relative to the OpenScrum repo root.
        # This keeps all generated files in a dedicated Workspace directory
        # outside the OpenScrum repo, matching the server's default.
        root = _repo_root()
        workspace = os.path.abspath(os.path.join(root.parent, "workspace"))
        Path(workspace).mkdir(parents=True, exist_ok=True)
        print(f"Using default workspace: {workspace}")
        cleanup_workspace = False
    else:
        workspace = os.path.abspath(workspace)
        Path(workspace).mkdir(parents=True, exist_ok=True)
        cleanup_workspace = False

    client = httpx.Client(timeout=300)

    try:
        # Health
        r = client.get(f"{server}/health")
        if r.status_code != 200:
            print(f"Server not healthy: {r.status_code}", file=sys.stderr)
            sys.exit(1)
        print("Server OK")

        # Create session
        r = client.post(f"{server}/sessions", params={"directory": workspace})
        r.raise_for_status()
        session = r.json()
        session_id = session["id"]
        print(f"Session: {session_id}")

        allow_all = args.allow_all

        def stream_message(msg: str, mode: str = "plan"):
            url = f"{server}/sessions/{session_id}/message"
            payload = {"message": msg, "mode": mode}
            with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                # Stream AI tokens and tool activity for visibility.
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:].strip())
                    except json.JSONDecodeError:
                        continue
                    typ = data.get("type")
                    if typ == "permission_request":
                        perm = data.get("permission_request") or {}
                        if allow_all:
                            req_id = perm.get("id")
                            if req_id:
                                client.post(
                                    f"{server}/permissions/{req_id}/reply",
                                    json={"reply": "always"},
                                    timeout=10,
                                )
                                print(f"  [allowed {perm.get('permission', '?')}]")
                        else:
                            ask_permission(perm, server, client)
                    elif typ == "token":
                        # Show AI response tokens as they stream.
                        content = data.get("content", "")
                        if content:
                            print(content, end="", flush=True)
                    elif typ == "tool_call":
                        tool_name = data.get("tool_name", "?")
                        tool_input = data.get("tool_input") or {}
                        print(f"\n  tool: {tool_name}")
                        if tool_name == "bash":
                            cmd = tool_input.get("command")
                            workdir = tool_input.get("workdir")
                            if cmd:
                                print(f"    command: {cmd}")
                            if workdir:
                                print(f"    workdir: {workdir}")
                    elif typ == "tool_result":
                        tool_name = data.get("tool_name", "?")
                        tool_output = data.get("tool_output", "") or ""
                        print(f"\n  tool result: {tool_name}")
                        if tool_output:
                            preview = tool_output[:400]
                            if len(tool_output) > 400:
                                preview += f"\n... ({len(tool_output) - 400} more characters)"
                            # Indent multi-line output for readability
                            indented = "\n".join(f"    {line}" for line in preview.splitlines())
                            print(indented)
                    elif typ == "done":
                        # Ensure we end on a newline after streaming tokens.
                        print()
                        return
                    elif typ == "error":
                        print(f"\n  ERROR: {data.get('content', '')[:200]}", file=sys.stderr)
                        return

        # First message
        print("Sending: Build a web app for chess game with vue")
        stream_message("Build a web app for chess game with vue")

        if not args.no_proceed:
            print("Sending: proceed with your plan")
            stream_message("proceed with your plan", mode="edit")

        # Assert something was built
        w = Path(workspace)
        found = []
        for name in ["package.json", "index.html"]:
            if (w / name).exists():
                found.append(name)
        for p in w.rglob("*.vue"):
            found.append(str(p.relative_to(w)))
        if not found:
            # Any new file that looks like project output
            for p in w.iterdir():
                if p.name.startswith("."):
                    continue
                found.append(p.name)
        if found:
            print(f"PASS: Found built artifacts: {found[:10]}")
            sys.exit(0)
        else:
            print("FAIL: No package.json, index.html, .vue, or other files found in workspace", file=sys.stderr)
            sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        client.close()
        if cleanup_workspace and workspace and os.path.isdir(workspace):
            import shutil
            try:
                shutil.rmtree(workspace)
            except Exception:
                pass


if __name__ == "__main__":
    main()
