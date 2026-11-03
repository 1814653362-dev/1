# -*- coding: utf-8 -*-
"""SPU 口径修正：只取第一个 “-” 之前的字段（如 230918-ND-S-Z → 230918）。
按店铺聚合 SPU 库存并就地替换页面里的 window.__SPU 数据。
红线（2026-10-28 小丁）：FBA 绝不跨店合并 —— 只输出 byShop，不再有顶层 all 合并层。
国内仓 SPU 走 build_spu_local.py（window.__SPUL），本地仓口径不属分店口径，不受此红线约束。"""
import json, io, os, sys, collections
sys.stdout.reconfigure(encoding="utf-8")

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(WS, "wh_raw")
PAGE = os.path.join(WS, "shandi-v5", "index.html")


def spu_of(sku):
    s = (sku or "").strip()
    if not s:
        return ""
    return s.split("-")[0]


def num(v):
    try:
        n = float(v)
        return n if n == n else 0.0
    except Exception:
        return 0.0


fba = json.load(io.open(os.path.join(RAW, "fba_inventory.json"), encoding="utf-8"))
sellers = json.load(io.open(os.path.join(RAW, "sellers.json"), encoding="utf-8"))
sid2name = {str(it["sid"]): (it.get("name") or str(it["sid"])) for it in (sellers.get("data") or [])}

# ---- 只按店铺聚合，不做跨店求和 ----
by_shop = collections.defaultdict(lambda: collections.defaultdict(float))
for r in fba.get("rows") or []:
    spu = spu_of(r.get("sku"))
    if not spu:
        continue
    # 口径（2026-10-29 小丁纠正）：SPU 饼图必须与 FBA 卡 KPI 同源 → 用 FBA 可售
    # afn_fulfillable_quantity；旧代码用 total（总库存），导致 Top8 占比 93.9% 与
    # 卡片 KPI「FBA 可售」对不上。available_total 含 FBM、total_fulfillable_quantity
    # 重复计数，都不能用。
    by_shop[str(r.get("sid"))][spu] += num(r.get("afn_fulfillable_quantity"))

payload = {
    "byShop": {
        sid: {"name": sid2name.get(sid, sid), "spu": {k: round(v) for k, v in m.items() if v > 0}}
        for sid, m in by_shop.items()
    },
}
blob = "window.__SPU=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"

s = io.open(PAGE, encoding="utf-8").read()
start = s.find("window.__SPU=")
if start >= 0:
    end = s.find("};\n", start)
    if end < 0:
        print("MISS end")
        sys.exit(1)
    end += 3
    s = s[:start] + blob + "\n" + s[end:]
    print("replaced in place")
else:
    anchor = s.find("window.__WH = ")
    line_end = s.find("\n", anchor)
    s = s[:line_end + 1] + blob + "\n" + s[line_end + 1:]
    print("inserted")

io.open(PAGE, "w", encoding="utf-8", newline="\r\n").write(s)
print("注入字节", len(blob), "| 顶层无 all 合并层（红线：绝不跨店合并）")
for sid in sorted(payload["byShop"], key=lambda x: -sum(payload["byShop"][x]["spu"].values())):
    m = payload["byShop"][sid]["spu"]
    print("  店铺 %s %-18s SPU %4d | 可售 %7d" % (sid, payload["byShop"][sid]["name"], len(m), sum(m.values())))
print("page", len(s))
