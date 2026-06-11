#!/bin/bash
# kill_app.sh — 强制关闭所有「时间记录器」实例（用于测试）

echo "🔍 查找时间记录器相关进程..."

PIDS=$(pgrep -f "time_recorder" 2>/dev/null)
PIDS2=$(pgrep -f "时间记录器" 2>/dev/null)
ALL_PIDS=$(echo -e "$PIDS\n$PIDS2" | sort -u | grep -v '^$')

if [ -z "$ALL_PIDS" ]; then
    echo "✅ 没有找到运行中的时间记录器实例"
    exit 0
fi

echo "找到以下进程："
for PID in $ALL_PIDS; do
    ps -p "$PID" -o pid,command 2>/dev/null | tail -1
done

echo ""
echo "🔪 正在强制关闭..."
for PID in $ALL_PIDS; do
    kill -9 "$PID" 2>/dev/null && echo "  ✅ 已终止 PID $PID" || echo "  ⚠️  PID $PID 已不存在"
done

echo ""
echo "✅ 完成"
