#!/usr/bin/env bash
# Ensure Ctrl+C works by not trapping signals
# Set PYTHONPATH to include the server directory
clear
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --log-level info