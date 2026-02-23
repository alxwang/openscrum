#!/usr/bin/env bash
# Ensure Ctrl+C works by not trapping signals
# Set PYTHONPATH to include the server directory
clear
mamba run -n openscrum uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload