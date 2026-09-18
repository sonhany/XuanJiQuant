#!/usr/bin/env bash
# ============================================================
#   XuanJiQuant 每日数据更新 (Linux crontab 用)
#   对应 Windows 版 daily_update.bat + schtasks
#
#   建议 crontab: 每个交易日 17:30 运行
#     30 17 * * 1-5  /home/hskj/XuanJiQuant/scripts/daily_update_cron.sh >> /home/hskj/XuanJiQuant/logs/cron.log 2>&1
# ============================================================
set -e
cd "$(dirname "$0")/.."
mkdir -p logs

# 激活虚拟环境 (cron 环境没有 shell 初始化，必须显式激活)
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

export PYTHONIOENCODING=utf-8
export LANG=zh_CN.UTF-8
export QUANT_SKIP_NODE_PROXY=1

TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TS] === 每日数据更新开始 ==="

# 增量更新 K 线 (约 30 分钟)
echo "[$TS] [1] 增量更新 K线..."
if python scripts/daily_update.py; then
    echo "[$TS] [OK] K线更新完成"
else
    echo "[$TS] [错误] K线更新失败"
    exit 1
fi

# 因子快照重算 (可选, 每日数据更新后建议跑一次)
echo "[$TS] [2] 重算因子快照..."
if python scripts/precompute_snapshot.py 2>/dev/null; then
    echo "[$TS] [OK] 因子快照完成"
else
    echo "[$TS] [警告] 因子快照失败 (非致命, 跳过)"
fi

echo "[$TS] === 每日更新完成 ==="
echo
