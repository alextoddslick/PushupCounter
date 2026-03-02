#!/bin/bash
echo "Stopping any existing servers on ports 5000 and 5001..."
lsof -ti:5000,5001 | xargs kill -9 2>/dev/null || true
echo "Starting Pushup Counter..."
python3 app.py
