import json, os, sys, time

D = sys.argv[1] if len(sys.argv) > 1 else "wh_raw"
OUT = sys.argv[2] if len(sys.argv) > 2 else "wh_snapshot.json"

def rd(f):
    with open(os.path.join(D, f), encoding="utf-8") as fh:
        return json.load(fh)

def num(v):
    try:
        n = float(v)
        return n if n == n and n not in (float('inf'), float('-inf')) else 0.0
    except Exception:
        return 0.0

WAREHOUSES = [
    {"wid": 17915, "name": "环新路仓库", "short": "环新路"},
    {"wid": 9039, "name": "默认仓库", "short": "默认"},
    {"wid": 26677, "name": "TK平台环新仓", "short": "TK"},
    {"wid": 25024, "name": "Temu平台环新仓", "short": "Temu"},
    {"wid": 31665, "name": "Shein平台环新仓", "short": "Shein"},
]

# ---------- 本地仓 ----------
L = rd("local_inventory.json")
rows_all = L.get("rows") or []
by_wid = {}
for r in rows_all:
    by_wid.setdefault(r.get("wid"), []).append(r)

# ---------- 库存单价修正 / 脏值护栏（2026-10-30） ----------
# 领星库存明细的 stock_cost_total = 加权单价 x 数量。个别 SKU 的加权单价会被算错
# （商品档案 cg_price 是正常的），一行就能把全仓库存成本带偏。这里两种处理：
#   1) cost_override.json 显式指定单价（人工修正，优先）
#   2) 单价 > COST_UNIT_LIMIT 视为录错，不计入总额（脏值护栏）
OVERRIDE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cost_override.json")
COST_OVERRIDE = {}
if os.path.exists(OVERRIDE_FILE):
    _ov = json.load(open(OVERRIDE_FILE, encoding="utf-8"))
    COST_OVERRIDE = {k: float(v) for k, v in _ov.items() if not str(k).startswith("_")}
COST_UNIT_LIMIT = 500.0        # 元/双，超过此值视为录错

_cost_fix = []
for _r in rows_all:
    _sku = str(_r.get("sku") or "")
    _qty = num(_r.get("product_total"))
    _ct = num(_r.get("stock_cost_total"))
    if _sku in COST_OVERRIDE and _qty > 0:
        _unit = COST_OVERRIDE[_sku]
        _old = _ct
        _r["stock_cost_total"] = round(_unit * _qty, 2)
        _r["stock_cost"] = _unit
        _cost_fix.append(("人工修正", _sku, _qty, _old, _r["stock_cost_total"], _unit))
    elif _qty > 0 and _ct > 0 and _ct / _qty > COST_UNIT_LIMIT:
        _cost_fix.append(("剔除脏值", _sku, _qty, _ct, 0.0, round(_ct / _qty, 4)))
        _r["stock_cost_total"] = 0.0
        _r["stock_cost"] = 0.0

if _cost_fix:
    print("库存成本修正 %d 行：" % len(_cost_fix))
    for _k, _s, _q, _o, _n, _u in _cost_fix:
        print("   [%s] %-18s 数量=%-8s 原成本=%-16s 新成本=%-14s 单价=%s" % (_k, _s, _q, _o, _n, _u))
else:
    print("库存成本修正：0 行")

local_whs = []
for w in WAREHOUSES:
    allrows = by_wid.get(w["wid"], [])
    nz = [r for r in allrows if num(r.get("product_total")) > 0 or num(r.get("quantity_receive")) > 0
          or num(r.get("product_onway")) > 0 or num(r.get("storage_distribute_num")) > 0]

    def sumf(f, rs=None):
        rs = nz if rs is None else rs
        return sum(num(r.get(f)) for r in rs)

    ages = [0.0] * 5
    for r in nz:
        for i, a in enumerate(r.get("stock_age_list") or []):
            if i < 5:
                ages[i] += num(a.get("qty"))

    age_w = age_s = 0.0
    for r in nz:
        if num(r.get("average_age")) > 0 and num(r.get("product_total")) > 0:
            age_w += num(r.get("product_total"))
            age_s += num(r.get("average_age")) * num(r.get("product_total"))

    def g(i):
        sa = r.get("stock_age_list") or []
        return num(sa[i].get("qty")) if i < len(sa) else 0.0

    rows = []
    for r in nz:
        rows.append([
            r.get("sku") or "", r.get("fnsku") or "",
            num(r.get("product_total")), num(r.get("product_valid_num")), num(r.get("product_bad_num")),
            num(r.get("product_qc_num")), num(r.get("product_lock_num")), num(r.get("quantity_receive")),
            num(r.get("product_onway")), num(r.get("stock_cost_total")), num(r.get("stock_cost")),
            num(r.get("average_age")), g(0), g(1), g(2), g(3), g(4), num(r.get("storage_distribute_num")),
        ])
    rows.sort(key=lambda a: (-a[2], a[0]))

    local_whs.append({
        "wid": w["wid"], "name": w["name"], "short": w["short"],
        "summary": {
            "skuAll": len(allrows), "skuNz": len(nz),
            "total": sumf("product_total"), "valid": sumf("product_valid_num"), "bad": sumf("product_bad_num"),
            "qc": sumf("product_qc_num"), "lock": sumf("product_lock_num"),
            "receive": sumf("quantity_receive"), "onway": sumf("product_onway"),
            "distribute": sumf("storage_distribute_num"),
            "cost": round(sumf("stock_cost_total"), 2),
            "avgAge": round(age_s / age_w, 1) if age_w else 0,
            "ageBuckets": ages,
        },
        "rows": rows,
    })

# ---------- FBA ----------
S = rd("sellers.json")
seller_map = {s.get("sid"): {"sid": s.get("sid"), "name": s.get("name"), "region": s.get("region"),
                            "country": s.get("country"), "status": s.get("status")} for s in (S.get("data") or [])}

F = rd("fba_inventory.json")
fba_rows = F.get("rows") or []

def fix(s):
    """PowerShell 5.1 按 Latin-1 解码导致的 UTF-8 乱码，还原"""
    if not isinstance(s, str):
        return s
    try:
        t = s.encode("latin-1").decode("utf-8")
        return t if t != s else s
    except Exception:
        return s

for _r in fba_rows:
    if "name" in _r:
        _r["name"] = fix(_r.get("name"))
    if "seller_group_name" in _r:
        _r["seller_group_name"] = fix(_r.get("seller_group_name"))

NZ_KEYS = ["total", "available_total", "afn_fulfillable_quantity", "afn_reserved_quantity",
            "afn_unsellable_quantity", "reserved_customerorders", "quantity", "stock_up_num",
            "afn_inbound_working_quantity", "afn_inbound_shipped_quantity", "afn_inbound_receiving_quantity",
            "afn_researching_quantity", "reserved_fc_transfers", "reserved_fc_processing"]
nzF = [r for r in fba_rows if any(num(r.get(k)) > 0 for k in NZ_KEYS)]

name_vote, wh_vote = {}, {}
for r in nzF:
    k = r.get("sid")
    nm = seller_map.get(k, {}).get("name") or (r.get("seller_group_name") or ("sid-" + str(k)))
    name_vote.setdefault(k, {})
    name_vote[k][nm] = name_vote[k].get(nm, 0) + 1
    wh_vote.setdefault(k, {})
    wn = r.get("name") or ""
    wh_vote[k][wn] = wh_vote[k].get(wn, 0) + 1

shop_name, shop_wh = {}, {}
for k, votes in name_vote.items():
    shop_name[k] = sorted(votes.items(), key=lambda a: -a[1])[0][0]
    whs = sorted(wh_vote[k].items(), key=lambda a: -a[1])
    good = [{"name": n, "rows": c} for n, c in whs if "\ufffd" not in n]
    bad = [(n, c) for n, c in whs if "\ufffd" in n]
    for n, c in bad:
        pre = n.rstrip("\ufffd").strip()
        hit = next((m for m in good if pre and (m["name"].startswith(pre) or pre.startswith(m["name"]))), None)
        if hit:
            hit["rows"] += c
        else:
            good.append({"name": n, "rows": c})
    shop_wh[k] = sorted([m for m in good if m["rows"] > 0], key=lambda m: -m["rows"])

by_sid = {}
for r in nzF:
    by_sid.setdefault(r.get("sid"), []).append(r)

def shop_wh_name(sid, wn):
    if "\ufffd" not in wn:
        return wn
    pre = wn.rstrip("\ufffd").strip()
    hit = next((m for m in shop_wh.get(sid, []) if pre and (m["name"].startswith(pre) or pre.startswith(m["name"]))), None)
    if hit:
        return hit["name"]
    return wn.replace("\ufffd", "") or shop_name.get(sid, "")

fba_shops = []
for sid, rs in by_sid.items():
    meta = seller_map.get(sid, {"sid": sid, "name": shop_name.get(sid), "region": "", "country": "", "status": None})
    def s(k, rs=rs):
        return sum(num(r.get(k)) for r in rs)
    rows = []
    for r in rs:
        rows.append([
            r.get("asin") or "", r.get("seller_sku") or "", r.get("fnsku") or "", r.get("sku") or "",
            num(r.get("total")), num(r.get("afn_fulfillable_quantity")), num(r.get("afn_reserved_quantity")),
            num(r.get("afn_unsellable_quantity")), num(r.get("reserved_customerorders")), num(r.get("quantity")),
            num(r.get("afn_inbound_working_quantity")), num(r.get("afn_inbound_shipped_quantity")),
            num(r.get("afn_inbound_receiving_quantity")), num(r.get("stock_up_num")),
            round(num(r.get("available_total_price")), 2),
            num(r.get("inv_age_0_to_90_days")), num(r.get("inv_age_91_to_180_days")),
            num(r.get("inv_age_181_to_270_days")), num(r.get("inv_age_271_to_365_days")),
            num(r.get("inv_age_365_plus_days")), r.get("product_brand_text") or "",
            shop_wh_name(sid, r.get("name") or ""),
        ])
    rows.sort(key=lambda a: (-a[4], a[1]))
    fba_shops.append({
        "sid": sid, "name": shop_name.get(sid), "region": meta.get("region") or "",
        "country": meta.get("country") or "", "inList": sid in seller_map,
        "warehouses": shop_wh.get(sid, []),
        "summary": {
            "sku": len(rows), "total": s("total"), "fulfillable": s("afn_fulfillable_quantity"),
            "reserved": s("afn_reserved_quantity"), "unsellable": s("afn_unsellable_quantity"),
            "customerOrders": s("reserved_customerorders"), "fbm": s("quantity"),
            "inboundWorking": s("afn_inbound_working_quantity"), "inboundShipped": s("afn_inbound_shipped_quantity"),
            "inboundReceiving": s("afn_inbound_receiving_quantity"), "onway": s("stock_up_num"),
            "cost": round(s("available_total_price"), 2),
            "age": [s("inv_age_0_to_90_days"), s("inv_age_91_to_180_days"), s("inv_age_181_to_270_days"),
                    s("inv_age_271_to_365_days"), s("inv_age_365_plus_days")],
        },
        "rows": rows,
    })
fba_shops.sort(key=lambda a: -a["summary"]["total"])

LOCAL_COLS = ["sku", "fnsku", "库存总量", "可用", "次品", "待检待上架", "锁定", "待到货", "调拨在途",
              "库存成本", "单位成本", "平均库龄", "0-30天", "31-90天", "91-180天", "181-360天", "361天+", "FBA待配货"]
FBA_COLS = ["asin", "msku", "fnsku", "sku", "总库存", "FBA可售", "FBA预留", "不可售", "待发货", "FBM可售",
            "入库处理中", "已发在途", "接收中", "实际在途", "可售成本", "0-90天", "91-180天", "181-270天",
            "271-365天", "365天+", "品牌", "仓库"]

snap = {
    "updatedAt": os.environ.get("WH_ASOF") or time.strftime("%Y-%m-%d"),
    "source": "领星 ERP 开放接口",
    "endpoints": {
        "warehouse": "/erp/sc/data/local_inventory/warehouse (type=1)",
        "localDetail": "/erp/sc/routing/data/local_inventory/inventoryDetails",
        "sellers": "/erp/sc/data/seller/lists",
        "fba": "/basicOpen/openapi/storage/fbaWarehouseDetail (is_hide_zero_stock=0)",
    },
    "localCols": LOCAL_COLS,
    "fbaCols": FBA_COLS,
    "local": local_whs,
    "fba": {"shops": fba_shops, "shopCount": len(S.get("data") or []),
            "rowsAllCount": F.get("total"), "rowsNzCount": len(nzF)},
}

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(snap, fh, ensure_ascii=False, separators=(",", ":"))

print("本地仓：")
for w in local_whs:
    sm = w["summary"]
    print("  %-14s SKU %5d 行  库存 %7d  可用 %7d  待到货 %6d  成本 %.2f  均龄 %.1f 天" %
          (w["name"], sm["skuNz"], sm["total"], sm["valid"], sm["receive"], sm["cost"], sm["avgAge"]))
tot = sum(w["summary"]["total"] for w in local_whs)
print("合计库存 =", tot, " 平均库龄(加权) =",
      round(sum(w["summary"]["avgAge"] * w["summary"]["total"] for w in local_whs) / tot, 1) if tot else 0)
print("FBA 店铺:", len(fba_shops), " 行数:", sum(len(s["rows"]) for s in fba_shops))
print("快照", OUT, round(os.path.getsize(OUT) / 1024, 1), "KB")
