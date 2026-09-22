#!/bin/bash
cd /home/c6891274/apps/DataSearchHub/Data_search_engine

echo "Stopping existing uvicorn..."
pkill -9 -f uvicorn 2>/dev/null || true
sleep 2

echo "Starting uvicorn in background..."
nohup /home/c6891274/apps/DataSearchHub/Data_search_engine/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 >> app.log 2>&1 &
disown

sleep 2
ps aux | grep uvicorn | grep -v grep
