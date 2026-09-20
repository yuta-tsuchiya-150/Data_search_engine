#!/bin/bash
# =========================================================
# ConoHa WING 用 DataSearchHub 起動・再起動管理スクリプト
# =========================================================

# プロジェクトルートディレクトリへ移動
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# 既存の uvicorn および関連ワーカープロセスを停止
pkill -9 -f "multiprocessing" 2>/dev/null || true
pkill -9 -f "uvicorn app.main:app" 2>/dev/null || true
sleep 2

# 仮想環境のアクティベート (venv または .venv)
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Creating python 3.11 virtualenv..."
    if [ -f "/opt/alt/python311/bin/python3" ]; then
        /opt/alt/python311/bin/python3 -m venv .venv
    else
        python3 -m venv .venv
    fi
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# データベースマイグレーション＆アプリのバックグラウンド起動 (Port 8000)
echo "Starting DataSearchHub on http://127.0.0.1:8000 ..."
nohup uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 > app.log 2>&1 &

sleep 2
NEW_PID=$(pgrep -f "uvicorn app.main:app")
if [ -n "$NEW_PID" ]; then
    echo "✅ Successfully started DataSearchHub on ConoHa WING! (PID: $NEW_PID)"
else
    echo "❌ Failed to start. Check app.log for details."
    cat app.log | tail -n 20
fi
