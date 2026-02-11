#!/bin/bash
# Kill OpenScrum TUI client process

echo "Looking for OpenScrum TUI client process..."

# Find the process running tui.py
PID=$(ps aux | grep "python.*client/tui.py" | grep -v grep | awk '{print $2}')

if [ -z "$PID" ]; then
    echo "No OpenScrum TUI client process found."
    exit 0
fi

echo "Found OpenScrum TUI client process: PID $PID"
echo "Killing process..."

kill -9 $PID

if [ $? -eq 0 ]; then
    echo "Successfully killed process $PID"
else
    echo "Failed to kill process $PID"
    exit 1
fi
