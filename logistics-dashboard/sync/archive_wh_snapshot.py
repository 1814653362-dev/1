# -*- coding: utf-8 -*-
"""归档 FBA 库龄快照（每周一份实测值）

FIFO 反推的历史库龄有误差（老库龄约 +4%），而**实测快照 100% 准确**。
所以每次构建都把当天的 FBA 库龄按 SPU 存一份，攒够几周后，
趋势序列里的实测点会覆盖推算点 —— 历史越往后越准。

输出：wh_hist/fba/YYYYMMDD.json
  { "date": "...", "shops": { sid: { SPU: [可售,总双数,老库龄,0-90,91-180,181-270,271-365,365+] } } }
"""
import datetime
import io
import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.join(BASE, "wh_raw", "fba_inventory.json")
OUTDIR = os.path.join(BASE, "wh_hist", "fba")

AGE_FIELDS = ("inv_age_0_to_90_days", "inv_age_91_to_180_days",
              "inv_age_181_to_270_days", "inv_age_271_to_365_days",
              "inv_age_365_plus_days")


def num(v):
    try:
        n = float(v)
        return n if n == n and n not in (float("inf"), float("-inf")) else 0.0
    except Exception:
        return 0.0


def main():
    rows = json.load(io.open(INV, encoding="utf-8"))["rows"]
    agg = defaultdict(lambda: defaultdict(lambda: [0.0] * 8))
    for r in rows:
        sid = str(r.get("sid"))
        sku = str(r.get("sku") or r.get("msku") or "")
        spu = sku.split("-")[0] if sku else ""
        if not spu:
            continue
        a = agg[sid][spu]
        a[0] += num(r.get("afn_fulfillable_quantity"))          # 可售
        a[1] += num(r.get("total"))                             # 总库存
        for i, f in enumerate(AGE_FIELDS):
            a[3 + i] += num(r.get(f))
        a[2] = a[6] + a[7]                                     # 老库龄 271+
    shops = {}
    for sid, d in agg.items():
        shops[sid] = {spu: [round(x, 1) for x in v] for spu, v in d.items()}

    today = datetime.date.today().isoformat()
    if not os.path.isdir(OUTDIR):
        os.makedirs(OUTDIR)
    path = os.path.join(OUTDIR, today + ".json")
    io.open(path, "w", encoding="utf-8").write(
        json.dumps({"date": today, "shops": shops}, ensure_ascii=False, separators=(",", ":")))
    n = sum(len(v) for v in shops.values())
    old = len([f for f in os.listdir(OUTDIR) if f.endswith(".json")])
    print("归档 %s：%d 店 / %d 个 SPU  → %s（已有 %d 份快照）"
          % (today, len(shops), n, os.path.basename(path), old))
    return 0


if __name__ == "__main__":
    sys.exit(main())
