#!/bin/bash
# =========================================================
# ConoHa WING 用 Uvicorn 死活監視＆自動再起動スクリプト (Cron用)
# =========================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

LOGFILE="$DIR/keep_alive.log"
NOW=$(date '+%Y-%m-%d %H:%M:%S')

# 1. HTTPレスポンスのチェック (Port 8000)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8000/ || echo "000")

if [ "$STATUS" = "200" ]; then
    # 正常稼働中
    exit 0
fi

echo "[$NOW] ⚠️ Uvicorn is DOWN or not responding (HTTP Status: '$STATUS'). Restarting..." >> "$LOGFILE"

# 既存プロセスの強制クリーンアップ
pkill -9 -f "DataSearchHub" >/dev/null 2>&1 || true
pkill -9 -f "uvicorn" >/dev/null 2>&1 || true
sleep 2

# 起動スクリプトの実行
if [ -f "$DIR/start_conoha.sh" ]; then
    bash "$DIR/start_conoha.sh" >> "$LOGFILE" 2>&1
fi

sleep 3
NEW_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8000/ || echo "000")
echo "[$NOW] ✅ Restart finished. New HTTP Status: '$NEW_STATUS'" >> "$LOGFILE"
