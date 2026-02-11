#!/usr/bin/env bash
# Kill the OpenScrum server

echo "Stopping OpenScrum server..."

# Find process by port 8000
PID=$(lsof -ti:8000)

if [ -z "$PID" ]; then
    echo "No server process found running on port 8000"
    exit 0
fi

echo "Found server process (PID: $PID)"

# Try graceful shutdown first
echo "Sending SIGTERM..."
kill $PID

# Wait up to 5 seconds for graceful shutdown
for i in {1..5}; do
    if ! ps -p $PID > /dev/null 2>&1; then
        echo "Server stopped gracefully"
        exit 0
    fi
    sleep 1
done

# Force kill if still running
if ps -p $PID > /dev/null 2>&1; then
    echo "Force killing server..."
    kill -9 $PID
    sleep 1
    if ! ps -p $PID > /dev/null 2>&1; then
        echo "Server force killed"
    else
        echo "Failed to kill server"
        exit 1
    fi
fi

echo "Server stopped"
