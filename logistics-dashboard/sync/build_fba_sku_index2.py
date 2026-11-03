# -*- coding: utf-8 -*-
"""构建 FBA SKU 索引（按店铺拆分，绝不跨店合并）
口径：
  期初库存 = 领星分类账 startingWarehouseBalance（真实历史快照）
  销售出库 = 领星分类账 customerShipments
  当前库存 = 领星 FBA 库存明细
结构：
  _meta      窗口与口径说明 + 每店各自小计（无任何跨店合计）
  skuShops   sku -> 所在店铺 id 列表（目录，不含任何可售/库存/出库数值）
  shops      sid -> {name, sellerId, skus{sku: [9 项数值]}}  唯一事实源
"""
import json, io, os, sys, collections, datetime, calendar
sys.stdout.reconfigure(encoding="utf-8")

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(WS, "wh_raw")
OUT = os.path.join(WS, "shandi-v5", "fba_sku_index.json")


def num(v):
    try:
        n = float(v)
        return n if n == n else 0.0
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


sellers = json.load(io.open(os.path.join(RAW, "sellers.json"), encoding="utf-8"))
sid2seller = {}
sid2name = {}
for it in sellers.get("data") or []:
    it["name"] = fix(it.get("name"))
    sid2seller[str(it["sid"])] = it["seller_id"]
    sid2name[str(it["sid"])] = it["name"]

fba = json.load(io.open(os.path.join(RAW, "fba_inventory.json"), encoding="utf-8"))

# msku(seller_sku) -> sku ：全局 + 每店铺
msku_to_sku = {}
shop_msku_to_sku = collections.defaultdict(dict)
for r in fba.get("rows") or []:
    m = (r.get("seller_sku") or "").strip()
    s = (r.get("sku") or "").strip()
    if not m or not s:
        continue
    if m not in msku_to_sku:
        msku_to_sku[m] = s
    sid = str(r.get("sid"))
    shop_msku_to_sku[sid].setdefault(m, s)

month = json.load(io.open(os.path.join(RAW, "fba_ledger_month.json"), encoding="utf-8"))
day = json.load(io.open(os.path.join(RAW, "fba_ledger_day.json"), encoding="utf-8"))

seller2sid = {v: k for k, v in sid2seller.items()}

# key = (sid, sku)
day_out = collections.defaultdict(lambda: collections.defaultdict(float))
day_open = collections.defaultdict(lambda: collections.defaultdict(float))
mon_out = collections.defaultdict(lambda: collections.defaultdict(float))
mon_open = collections.defaultdict(lambda: collections.defaultdict(float))


def key_of(rec, sid):
    m = (rec.get("msku") or "").strip()
    return shop_msku_to_sku.get(sid, {}).get(m) or msku_to_sku.get(m, "") or m


for rec in day.get("records") or []:
    d = str(rec.get("date") or "")[:10]
    if len(d) != 10:
        continue
    sid = seller2sid.get(rec.get("sellerId"))
    if not sid:
        continue
    k = key_of(rec, sid)
    if not k:
        continue
    ship = num(rec.get("customerShipments"))
    if ship:
        day_out[d][(sid, k)] += -ship
    bal = num(rec.get("startingWarehouseBalance"))
    if bal:
        day_open[d][(sid, k)] += bal

for rec in month.get("records") or []:
    d = str(rec.get("date") or "")[:7]
    if len(d) != 7:
        continue
    sid = seller2sid.get(rec.get("sellerId"))
    if not sid:
        continue
    k = key_of(rec, sid)
    if not k:
        continue
    ship = num(rec.get("customerShipments"))
    if ship:
        mon_out[d][(sid, k)] += -ship
    bal = num(rec.get("startingWarehouseBalance"))
    if bal:
        mon_open[d][(sid, k)] += bal

ASOF = day.get("asOf") or ""
if not ASOF:
    _ds = sorted({str(r.get("date") or "")[:10] for r in (day.get("records") or []) if len(str(r.get("date") or "")) == 10})
    ASOF = _ds[-1] if _ds else datetime.date.today().isoformat()
OPEN3 = day.get("open3") or (datetime.date.fromisoformat(ASOF) - datetime.timedelta(days=90)).isoformat()
OPEN6 = day.get("open6") or (datetime.date.fromisoformat(ASOF) - datetime.timedelta(days=180)).isoformat()
CLOSE = ASOF


def d(s):
    return datetime.date.fromisoformat(s)


def month_span(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return d("%04d-%02d-01" % (y, m)), d("%04d-%02d-%02d" % (y, m, calendar.monthrange(y, m)[1]))


def window_out(d_start, d_end):
    out = collections.defaultdict(float)
    ds, de = d(d_start), d(d_end)
    covered = set()
    for ym, mrec in mon_out.items():
        ms, me = month_span(ym)
        if ms >= ds and me <= de:
            for k, v in mrec.items():
                out[k] += v
            for dd in range((me - ms).days + 1):
                covered.add((ms + datetime.timedelta(days=dd)).isoformat())
    cur = ds
    while cur <= de:
        key = cur.isoformat()
        if key not in covered and key in day_out:
            for k, v in day_out[key].items():
                out[k] += v
        cur += datetime.timedelta(days=1)
    return out


def window_open(d_open):
    return day_open.get(d_open, {})


open3 = window_open(OPEN3)
open6 = window_open(OPEN6)
out3 = window_out(OPEN3, CLOSE)
out6 = window_out(OPEN6, CLOSE)

# ---- 当前 FBA 库存：只按店铺，不做跨店聚合 ----
shop_stock = collections.defaultdict(lambda: [0.0] * 7)
for r in fba.get("rows") or []:
    sku = (r.get("sku") or "").strip()
    if not sku:
        continue
    sid = str(r.get("sid"))
    vals = [
        num(r.get("afn_fulfillable_quantity")),
        num(r.get("total")),
        num(r.get("afn_reserved_quantity")),
        num(r.get("afn_unsellable_quantity")),
        num(r.get("stock_up_num")),
        num(r.get("afn_inbound_shipped_quantity")) + num(r.get("afn_inbound_receiving_quantity")) + num(r.get("afn_inbound_working_quantity")),
    ]
    s = shop_stock[(sid, sku)]
    for i in range(6):
        s[i] += vals[i]


def pack(st, p3, o3, p6, o6):
    return [round(st[0], 2), round(st[1], 2), round(st[2], 2), round(st[3], 2), round(st[4], 2),
            round(p3, 2), round(o3, 2), round(p6, 2), round(o6, 2)]


# ---- SKU 出现过的店铺目录：只记录归属，不含任何库存/出库数值（红线：绝不跨店合并） ----
sku_shops = collections.defaultdict(set)
for (sid, sku) in shop_stock.keys():
    sku_shops[sku].add(sid)
for (sid, sku) in list(open3.keys()) + list(open6.keys()) + list(out3.keys()) + list(out6.keys()):
    sku_shops[sku].add(sid)
sku_shops = {sku: sorted(sids) for sku, sids in sku_shops.items()}

# ---- 每店铺 ----
shops = {}
all_sids = set(sid2name.keys())
for (sid, sku) in list(shop_stock.keys()):
    all_sids.add(sid)
for (sid, sku) in list(open3.keys()) + list(open6.keys()) + list(out3.keys()) + list(out6.keys()):
    all_sids.add(sid)

for sid in sorted(all_sids):
    skus = {}
    keys = {k[1] for k in shop_stock if k[0] == sid} | {k[1] for k in open3 if k[0] == sid} | \
           {k[1] for k in open6 if k[0] == sid} | {k[1] for k in out3 if k[0] == sid} | {k[1] for k in out6 if k[0] == sid}
    for sku in keys:
        st = shop_stock.get((sid, sku), [0.0] * 6)
        skus[sku] = pack(st, open3.get((sid, sku), 0.0), out3.get((sid, sku), 0.0),
                         open6.get((sid, sku), 0.0), out6.get((sid, sku), 0.0))
    if not skus:
        continue
    shops[sid] = {
        "name": sid2name.get(sid, sid),
        "sellerId": sid2seller.get(sid, ""),
        "skus": skus,
    }
    print("店铺 %s %-18s SKU %d | 可售 %d | 3月出库 %d" % (
        sid, shops[sid]["name"], len(skus),
        sum(v[0] for v in skus.values()), sum(v[6] for v in skus.values())))

meta = {
    "asOf": CLOSE,
    "open3": OPEN3, "open6": OPEN6, "close": CLOSE,
    "range3": [OPEN3, CLOSE],
    "range6": [OPEN6, CLOSE],
    "stockScope": "FBA 库存明细按内部 SKU 合并（同一店铺内合并，不跨店铺）",
    "openScope": "领星亚马逊库存分类账 startingWarehouseBalance（真实历史库存快照）",
    "outScope": "领星亚马逊库存分类账 customerShipments（销售出库，亚马逊侧真实出库）",
    "rateFormula": "动销率 = 期间销售出库 ÷ 该窗口期初库存（期初为分类账真实快照）",
    "source": "领星 ERP 开放接口 /cost/center/ods/summary/query + /basicOpen/openapi/storage/fbaWarehouseDetail",
    "skuShopsCount": len(sku_shops),
    "shopCount": len(shops),
    # 每个店铺各自的小计，禁止任何跨店合计
    "shops": {
        sid: {
            "name": shops[sid]["name"],
            "sellerId": shops[sid]["sellerId"],
            "skuCount": len(shops[sid]["skus"]),
            "withStock": sum(1 for v in shops[sid]["skus"].values() if v[0] > 0 or v[1] > 0),
            "out3Sum": sum(v[6] for v in shops[sid]["skus"].values()),
            "out6Sum": sum(v[8] for v in shops[sid]["skus"].values()),
            "open3Sum": sum(v[5] for v in shops[sid]["skus"].values()),
            "open6Sum": sum(v[7] for v in shops[sid]["skus"].values()),
        }
        for sid in shops
    },
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, "w", encoding="utf-8") as fh:
    json.dump({"_meta": meta, "skuShops": sku_shops, "shops": shops}, fh, ensure_ascii=False, separators=(",", ":"))

print("SKU 目录 %d 条 | 店铺数 %d（各店独立，不跨店合并）" % (len(sku_shops), len(shops)))
for sid in shops:
    sm = meta["shops"][sid]
    print("  店铺 %s %-18s SKU %4d | 可售 %6d | 3月出库 %6d | 6月出库 %6d" % (
        sid, sm["name"], sm["skuCount"],
        sum(v[0] for v in shops[sid]["skus"].values()), sm["out3Sum"], sm["out6Sum"]))
print("输出", OUT, round(os.path.getsize(OUT) / 1024, 1), "KB")
