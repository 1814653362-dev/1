# -*- coding: utf-8 -*-
"""库龄 × 款号 数据构建（FBA 按店，不跨店合并）
数据源：wh_raw/fba_inventory.json（领星 FBA 库存明细）+ wh_raw/sellers.json
输出：payload（供 patch 注入 window.__AGESPU），并落一份 age_spu.json 便于抽检
"""
import io, json, os, sys, collections
sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "wh_raw")

KEYS = ["0-90天", "91-180天", "181-270天", "271-365天", "365天以上"]
AGE_FIELDS = ["inv_age_0_to_90_days", "inv_age_91_to_180_days", "inv_age_181_to_270_days",
              "inv_age_271_to_365_days", "inv_age_365_plus_days"]
OLD_IDX = [3, 4]
TOP_SPU = 200
# 与 build_wh_snapshot.py 的 nzF 同一把尺子：只有「有库存动作」的行才算数。
# 否则卡片段数会比库龄条上的数多几双（库龄有值但所有数量字段为 0 的残留行）
NZ_KEYS = ["total", "available_total", "afn_fulfillable_quantity", "afn_reserved_quantity",
            "afn_unsellable_quantity", "reserved_customerorders", "quantity", "stock_up_num",
            "afn_inbound_working_quantity", "afn_inbound_shipped_quantity", "afn_inbound_receiving_quantity",
            "afn_researching_quantity", "reserved_fc_transfers", "reserved_fc_processing"]


def num(v):
    try:
        f = float(v)
        return f if f == f else 0.0
    except Exception:
        return 0.0


def fix(s):
    if not isinstance(s, str):
        return s
    try:
        t = s.encode("latin-1").decode("utf-8")
        return t if t != s else s
    except Exception:
        return s


def compute():
    fba = json.load(io.open(os.path.join(RAW, "fba_inventory.json"), encoding="utf-8"))
    sellers = json.load(io.open(os.path.join(RAW, "sellers.json"), encoding="utf-8"))
    sid2name = {}
    for it in (sellers.get("data") or []):
        sid2name[str(it.get("sid"))] = fix(it.get("name") or str(it.get("sid")))

    per_sid = collections.defaultdict(lambda: [collections.Counter() for _ in range(5)])
    avail = collections.defaultdict(float)   # 可售（对照用）
    avail_spu = collections.defaultdict(collections.Counter)  # 款号级可售
    total = collections.defaultdict(float)   # 总库存（含在途）
    for r in (fba.get("rows") or []):
        if not any(num(r.get(k)) > 0 for k in NZ_KEYS):
            continue                      # 与库龄条同一把尺子：没有库存动作的行不算数
        sid = str(r.get("sid"))
        avail[sid] += num(r.get("afn_fulfillable_quantity"))
        total[sid] += num(r.get("total"))
        # sku 可能为空，但 msku / seller_sku 里有真实货号；亚马逊占位 SKU（Amazon.Found.*）
        # 是真实库存但不属于任何款号 → 归到「无款号」。这样段总数与库龄条（__WH.summary.age）
        # 完全一致，条上数字与卡片明细不再对不上（2026-11-02 主管修，原差 25 双）
        sku = str(r.get("sku") or "").strip()
        if not sku:
            sku = str(r.get("msku") or "").strip()
        if not sku:
            sku = str(r.get("seller_sku") or "").strip()
        spu = sku.split("-")[0] if sku else ""
        if not spu or spu.upper().startswith("AMAZON.FOUND"):
            spu = "无款号"
        avail_spu[sid][spu] += num(r.get("afn_fulfillable_quantity"))
        ages = [num(r.get(f)) for f in AGE_FIELDS]
        if sum(ages) <= 0:
            continue                      # 没有库龄的行不参与段归集
        for i, v in enumerate(ages):
            if v > 0:
                per_sid[sid][i][spu] += v

    shops = {}
    for sid, buckets in per_sid.items():
        bl = []
        for i, k in enumerate(KEYS):
            d = buckets[i]
            pairs = sum(d.values())
            spus = sorted(d.items(), key=lambda kv: -kv[1])
            top1 = (spus[0][1] / pairs * 100) if spus and pairs else 0.0
            top5 = (sum(v for _, v in spus[:5]) / pairs * 100) if spus and pairs else 0.0
            bl.append({"key": k, "pairs": round(pairs, 1), "spuCount": len(spus),
                       "top1Pct": round(top1, 1), "top5Pct": round(top5, 1),
                       "spus": [[s, round(p, 1), round(avail_spu[sid].get(s, 0.0), 1)]
                                for s, p in spus[:TOP_SPU]]})
        allspu = set()
        for d in buckets:
            allspu |= set(d.keys())
        rows = []
        for s in allspu:
            cells = [round(buckets[i].get(s, 0.0), 1) for i in range(5)]
            rows.append({"spu": s, "total": round(sum(cells), 1), "cells": cells,
                         "avail": round(avail_spu[sid].get(s, 0.0), 1),
                         "old": round(sum(cells[i] for i in OLD_IDX), 1)})
        rows.sort(key=lambda r: (-r["old"], -r["total"], r["spu"]))
        shops[sid] = {"name": sid2name.get(sid, sid), "keys": KEYS, "buckets": bl, "rows": rows,
                      "avail": round(avail[sid], 1), "total": round(total[sid], 1),
                      "inStore": round(sum(b["pairs"] for b in bl), 1)}
    return {"shops": shops}


if __name__ == "__main__":
    payload = compute()
    with io.open(os.path.join(BASE, "age_spu.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    for sid, sh in payload["shops"].items():
        print("%s %s" % (sid, sh["name"]))
        for b in sh["buckets"]:
            print("   %-10s %8.0f 双 %4d 款号 | 前5款号占 %5.1f%%" % (
                b["key"], b["pairs"], b["spuCount"], b["top5Pct"]))
        old = [r for r in sh["rows"] if r["old"] > 0]
        print("   老库龄(271天+) %d 双 / %d 款号 | 仓内 %s / 可售 %s" % (
            sum(r["old"] for r in old), len(old), sh["inStore"], sh["avail"]))
    print("age_spu.json ->", os.path.getsize(os.path.join(BASE, "age_spu.json")), "bytes")
