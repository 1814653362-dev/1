# -*- coding: utf-8 -*-
"""国内仓 SPU 库存聚合（同样取第一个 “-” 之前），按仓库 + 全部合并，
以 window.__SPUL 注入页面，供国内仓卡片右侧 SPU 饼图使用。"""
import json, io, os, sys, collections
sys.stdout.reconfigure(encoding="utf-8")

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(WS, "wh_raw")
PAGE = os.path.join(WS, "shandi-v5", "index.html")


def spu_of(sku):
    s = (sku or "").strip()
    return s.split("-")[0] if s else ""


def num(v):
    try:
        n = float(v)
        return n if n == n else 0.0
    except Exception:
        return 0.0


rows = json.load(io.open(os.path.join(RAW, "local_inventory.json"), encoding="utf-8")).get("rows") or []
by_wh = collections.defaultdict(lambda: collections.defaultdict(float))
for r in rows:
    spu = spu_of(r.get("sku"))
    if not spu:
        continue
    q = num(r.get("product_total"))
    if q <= 0:
        continue
    by_wh[str(r.get("wid"))][spu] += q

allmap = collections.defaultdict(float)
for wid, m in by_wh.items():
    for spu, q in m.items():
        allmap[spu] += q

payload = {
    "all": {k: round(v) for k, v in allmap.items() if v > 0},
    "byWh": {wid: {k: round(v) for k, v in m.items() if v > 0} for wid, m in by_wh.items()},
}
blob = "window.__SPUL=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"

s = io.open(PAGE, encoding="utf-8").read()
start = s.find("window.__SPUL=")
if start >= 0:
    end = s.find("};\n", start) + 3
    s = s[:start] + blob + "\n" + s[end:]
    print("replaced")
else:
    anchor = s.find("window.__SPU=")
    end = s.find("};\n", anchor) + 3
    s = s[:end] + blob + "\n" + s[end:]
    print("inserted after __SPU")

io.open(PAGE, "w", encoding="utf-8", newline="\r\n").write(s)
print("SPU 数", len(payload["all"]), "| 仓库", len(payload["byWh"]), "| 字节", len(blob))
for k, v in sorted(payload["all"].items(), key=lambda kv: -kv[1])[:8]:
    print("  ", k, v)
