#!/bin/bash
# =========================================================
# ConoHa WING 用 Uvicorn 死活監視＆自動再起動スクリプト (Cron用)
# =========================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

LOGFILE="$DIR/keep_alive.log"
LOCKFILE="/tmp/keep_alive_datasearchhub.lock"
NOW=$(date '+%Y-%m-%d %H:%M:%S')

# 多重起動防止
if [ -f "$LOCKFILE" ]; then
    # ロックファイルが10分以上前なら強制解除
    if test "$(find "$LOCKFILE" -mmin +10 2>/dev/null)"; then
        rm -f "$LOCKFILE"
    else
        exit 0
    fi
fi
touch "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

# 1. HTTPレスポンスのチェック (Port 8000)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 http://127.0.0.1:8000/ || echo "000")

# 200〜399 または 404/405 等、Uvicornが応答していれば正常
if [[ "$STATUS" =~ ^(200|301|302|303|404|405)$ ]]; then
    # 正常稼働中
    exit 0
fi

echo "[$NOW] ⚠️ Uvicorn is DOWN or not responding (HTTP Status: '$STATUS'). Restarting..." >> "$LOGFILE"

# 既存プロセスの強制クリーンアップ
pkill -9 -f "multiprocessing" >/dev/null 2>&1 || true
pkill -9 -f "uvicorn" >/dev/null 2>&1 || true
pkill -9 -f "DataSearchHub" >/dev/null 2>&1 || true
sleep 3

# 起動スクリプトの実行
if [ -f "$DIR/start_conoha.sh" ]; then
    /bin/bash "$DIR/start_conoha.sh" >> "$LOGFILE" 2>&1
fi

sleep 4
NEW_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 http://127.0.0.1:8000/ || echo "000")
echo "[$NOW] ✅ Restart finished. New HTTP Status: '$NEW_STATUS'" >> "$LOGFILE"

# ログファイルのサイズ制限（最新500行のみ保持）
if [ -f "$LOGFILE" ] && [ "$(wc -l < "$LOGFILE")" -gt 1000 ]; then
    tail -n 500 "$LOGFILE" > "$LOGFILE.tmp" && mv "$LOGFILE.tmp" "$LOGFILE"
fi

