import json, os, sys, datetime, collections

WS = os.path.dirname(os.path.abspath(__file__))
RAW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WS, "wh_raw")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(WS, "shandi-v5", "sku_index.json")

WHS = {17915, 9039, 26677, 25024, 31665}   # 国内 5 仓（与看板一致）

def rd(f):
    with open(os.path.join(RAW, f), encoding="utf-8") as fh:
        return json.load(fh)

def num(v):
    try:
        n = float(v)
        return n if n == n else 0.0
    except Exception:
        return 0.0

today = datetime.date.today()
d3 = today - datetime.timedelta(days=90)
d6 = today - datetime.timedelta(days=180)

# ---------- 库存（国内 5 仓，同 SKU 合并） ----------
inv = rd("local_inventory.json")
stock = collections.defaultdict(lambda: [0.0, 0.0, 0.0, set()])  # avail, total, receive, whs
for r in inv.get("rows") or []:
    wid = r.get("wid")
    if wid not in WHS:
        continue
    sku = (r.get("sku") or "").strip()
    if not sku:
        continue
    s = stock[sku]
    s[0] += num(r.get("product_valid_num"))
    s[1] += num(r.get("product_total"))
    s[2] += num(r.get("quantity_receive"))
    s[3].add(wid)

# ---------- 出库（FBA 货件出库明细） ----------
ships = rd("shipments.json")
out = collections.defaultdict(lambda: [0.0, 0.0])  # out3, out6
ship_rows = 0
for s in ships if isinstance(ships, list) else (ships.get("data") or []):
    d = s.get("shipped_time") or s.get("sta_shipment_date") or s.get("gmt_create") or ""
    d = str(d)[:10]
    if len(d) != 10:
        continue
    try:
        day = datetime.date.fromisoformat(d)
    except Exception:
        continue
    if day > today:
        continue
    in3 = day >= d3
    in6 = day >= d6
    if not in6:
        continue
    ship_rows += 1
    for it in s.get("item_list") or []:
        sku = (it.get("sku") or it.get("msku") or "").strip()
        if not sku:
            continue
        q = num(it.get("quantity_shipped")) or num(it.get("quantity_shipped_local")) or num(it.get("quantity_received"))
        if q <= 0:
            continue
        out[sku][1] += q
        if in3:
            out[sku][0] += q

# ---------- 合并输出 ----------
skus = {}
for sku, s in stock.items():
    o3, o6 = out.get(sku, (0.0, 0.0))
    skus[sku] = [round(s[0], 2), round(s[1], 2), round(s[2], 2), round(o3, 2), round(o6, 2), len(s[3])]
# 有出库但国内仓已无库存的 SKU 也收录（避免搜不到）
for sku, (o3, o6) in out.items():
    if sku not in skus and (o3 or o6):
        skus[sku] = [0, 0, 0, round(o3, 2), round(o6, 2), 0]

meta = {
    "asOf": today.isoformat(),
    "range3": [d3.isoformat(), today.isoformat()],
    "range6": [d6.isoformat(), today.isoformat()],
    "stockScope": "国内 5 仓可用量合计（仓库A/默认/TK/Temu/Shein），同 SKU 已合并",
    "outScope": "领星 FBA 货件出库数量（quantity_shipped）",
    "source": "领星 ERP 开放接口",
    "shipments": len(ships if isinstance(ships, list) else []),
    "shipRowsInWindow": ship_rows,
    "skuCount": len(skus),
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({"_meta": meta, "skus": skus}, fh, ensure_ascii=False, separators=(",", ":"))

print("SKU 总数", len(skus), "| 有库存", sum(1 for v in skus.values() if v[0] > 0),
      "| 有出库(6月)", sum(1 for v in skus.values() if v[4] > 0))
print("出库货件数(窗口内)", ship_rows, " SKU 出库合计 3月", sum(v[3] for v in skus.values()),
      " 6月", sum(v[4] for v in skus.values()))
print("库存合计(可用)", sum(v[0] for v in skus.values()))
print("输出", OUT, round(os.path.getsize(OUT) / 1024, 1), "KB")
