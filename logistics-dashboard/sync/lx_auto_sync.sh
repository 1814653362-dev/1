#!/usr/bin/env bash
# 领星 FBA 货件状态 → 看板数据库「货件状态」自动同步
# 用法: printf '%s' "<op_token>" | bash lx_auto_sync.sh [--dry]
# 步骤: ① 拉主表库 ② 拉 SKU 批次明细库 ③ 按对碰范围定向拉领星 ④ 计算并写库
# 对碰范围（2026-10-20 用户明确）: 主表 FBA 货件号 ∩ SKU 批次明细「货件单号」
set -euo pipefail
cd "$(dirname "$0")"

TOKEN="$(cat)"
[ -z "$TOKEN" ] && { echo "缺少 op token"; exit 1; }
PY="${PY:-python3}"   # WorkBuddy 内置 Python 路径，或任意 python3
NODE="${NODE:-node}"   # WorkBuddy 内置 Node 路径，或任意 node
MAIN_DB="YOUR_MAIN_DATABASE_ID"
SKU_DB="YOUR_SKU_DATABASE_ID"
APPLY="--apply"
[ "${1:-}" = "--dry" ] && APPLY=""

echo "[1/4] 拉取看板主表库记录 ..."
printf '%s' "$TOKEN" | "$PY" db_query.py --database-id "$MAIN_DB" --page-size 200 --out db_records.json

echo "[2/4] 拉取 SKU 批次明细库（确定对碰范围）..."
printf '%s' "$TOKEN" | "$PY" db_query.py --database-id "$SKU_DB" --page-size 200 --out sku_records.json

echo "[3/4] 按对碰范围定向拉取领星 FBA 状态 ..."
"$NODE" fetch_lx_ship_targeted.js db_records.json sku_records.json

echo "[4/4] 计算并同步（$APPLY）..."
printf '%s' "$TOKEN" | "$PY" lx_sync_status.py --db db_records.json --lx lx_shipments.json \
    --sku sku_records.json $APPLY --out lx_sync_plan.json

echo "DONE"
