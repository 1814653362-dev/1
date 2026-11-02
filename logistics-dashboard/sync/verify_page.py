# -*- coding: utf-8 -*-
"""校验主页：内嵌 JSON 可解析、CRLF 完好、库容关键数值一目了然
用法： python verify_page.py [本地路径或URL]
"""
import io, json, os, re, sys, time, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
arg = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "shandi-v5", "index.html")

if arg.startswith("http"):
    # 加随机串穿透 CDN 缓存：否则发布后校验会读到旧版本（2026-10-28 踩过，误判线上仍是旧口径）
    sep = "&" if "?" in arg else "?"
    url = "%s%sv=%d" % (arg, sep, int(time.time() * 1000))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"})
    raw = urllib.request.urlopen(req, timeout=60).read()
    html = raw.decode("utf-8")
    src = arg
else:
    raw = open(arg, "rb").read()
    html = raw.decode("utf-8")
    src = os.path.basename(arg)

def grab(name):
    i = html.find("window.%s" % name)
    if i < 0:
        return None
    i = html.find("=", i) + 1
    while html[i] in " \r\n":
        i += 1
    if html[i] == "{":
        depth, in_str, esc, j = 0, False, False, i
        while j < len(html):
            c = html[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        return json.loads(html[i:j + 1])
    return None

print("== %s ==" % src)
print("bytes %d | crlf %d | lf-only %d" % (len(raw), raw.count(b"\r\n"), raw.count(b"\n") - raw.count(b"\r\n")))
for k in ("__WH", "__SPU", "__SPUL", "__VOL"):
    try:
        o = grab(k)
        print("%-7s OK  %s" % (k, ("keys=" + ",".join(list(o.keys())[:6])) if isinstance(o, dict) else type(o).__name__))
    except Exception as e:
        print("%-7s FAIL %s" % (k, e))

vol = grab("__VOL") or {}
print("VOL: 总容积 %s 方 | 已用 %s 方 | 占用 %s%% | 超出 %s 方 | 可存放 %s 方 | 预留 %s+%s 方 | 总剩余 %s 方" % (
    vol.get("capTotal"), vol.get("used"), vol.get("pct"), vol.get("over"),
    vol.get("storable"), vol.get("resPack"), vol.get("resBuy"), vol.get("freeTotal")))
wh = grab("__WH") or {}
tot = sum(w["summary"]["total"] for w in wh.get("local", []))
print("WH: updatedAt %s | 国内仓 %d 个 | 库存合计 %s 双" % (
    wh.get("updatedAt"), len(wh.get("local", [])), tot))
spu = grab("__SPU") or {}
spul = grab("__SPUL") or {}
spu_shop = sum(len(v.get("spu", {})) for v in spu.get("byShop", {}).values())
print("SPU(FBA) 按店 %d 个（%d 店，无顶层合并层）| SPUL(国内) %d 个 | SPU 图例文字 %d 处" % (
    spu_shop, len(spu.get("byShop", {})), len(spul.get("all", {})),
    len(re.findall(r"口径说明|按款号|合并逻辑|库龄段取", html))))
print("红线残留: whFbaMerged %d | 跨店铺汇总 %d | FBA 库存汇总 %d | skuShops 目录 %s" % (
    html.count("whFbaMerged"), html.count("跨店铺汇总"), html.count("FBA 库存汇总"),
    "有" if "skuShops" in html else "无"))
