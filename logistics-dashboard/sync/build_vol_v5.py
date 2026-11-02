# -*- coding: utf-8 -*-
"""国内仓库库容 · 全部按方（v5）
   总容积 450 方（9 万双按 10万双=500方 比例折）
   预留：打包 30 方 + 进货 30 方 = 60 方 → 可存放 390 方
   已用容积：按款号装箱（SPU 独立装箱、向上取整）× 箱规体积
   靴子箱 58×30×35 (0.0609 m³, 4 双/箱)；单鞋箱 58×54×35 (0.10962 m³, 20 双/箱)
"""
import json, io, os, sys, collections, math

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "wh_raw")

WIDS = [17915, 9039, 26677, 25024, 31665]      # 领星 5 个仓库位（同一物理仓）

CAP_TOTAL = 450.0                             # 仓库总容积（方）
RES_PACK = 30.0                               # 打包预留（方）
RES_BUY = 30.0                                # 进货预留（方）
RES_TOTAL = RES_PACK + RES_BUY                # 60 方
STORABLE = CAP_TOTAL - RES_TOTAL              # 可存放 390 方

BOX_BOOT = 58 * 30 * 35 / 1e6                # 0.0609
BOX_PLAIN = 58 * 54 * 35 / 1e6               # 0.10962
PAIR_BOOT, PAIR_PLAIN = 4.0, 20.0

inv = json.load(io.open(os.path.join(RAW, "local_inventory.json"), encoding="utf-8"))["rows"]
prods = json.load(io.open(os.path.join(RAW, "local_products.json"), encoding="utf-8"))["rows"]
name = {str(p.get("sku") or ""): str(p.get("product_name") or "") for p in prods}


def num(v):
    try:
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else 0.0
    except Exception:
        return 0.0


per_sku = collections.Counter()
for r in inv:
    if r.get("wid") not in WIDS:
        continue
    q = num(r.get("product_total"))
    if q > 0:
        per_sku[str(r.get("sku"))] += q

BOOT = set(s for s in per_sku if "靴" in name.get(s, ""))

# 按款号（SPU = SKU 第一个 "-" 之前）分组，靴/单鞋分别累计
spu_boot = collections.Counter()
spu_plain = collections.Counter()
for s, v in per_sku.items():
    k = s.split("-")[0]
    if s in BOOT:
        spu_boot[k] += v
    else:
        spu_plain[k] += v

boot_boxes = sum(math.ceil(spu_boot[k] / PAIR_BOOT) for k in spu_boot if spu_boot[k] > 0)
plain_boxes = sum(math.ceil(spu_plain[k] / PAIR_PLAIN) for k in spu_plain if spu_plain[k] > 0)

USED = boot_boxes * BOX_BOOT + plain_boxes * BOX_PLAIN   # 已用容积（方）
OVER = max(0.0, USED - STORABLE)                        # 超出可存放（方）
PCT = USED / STORABLE * 100                             # 占可存放
FREE_TOTAL = max(0.0, CAP_TOTAL - USED)                 # 总容积剩余（方）

# ---- 绘图 --------------------------------------------------------------
USED_TOP = "#3d84c0"
USED_R = "#1d5382"
OVER_C = "#d92b3f"


def txt(x, y, s, cls, anchor="start", op=1.0):
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="{cls}" '
            f'opacity="{op}">{s}</text>')


def line(p1, p2, stroke, sw=1.0, op=1.0, dash=None):
    d = f'M {p1[0]:.1f} {p1[1]:.1f} L {p2[0]:.1f} {p2[1]:.1f}'
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{sw}" opacity="{op}"{ds}/>')


def section_svg():
    W, H = 470.0, 250.0
    ox, oy = 112, 34
    u = H / CAP_TOTAL
    o = []

    # 仓库轮廓（= 总容积）
    o.append(f'<rect x="{ox}" y="{oy}" width="{W}" height="{H}" fill="#ffffff" '
             f'stroke="#c6d2dc" stroke-width="1.4"/>')

    # 已用（深蓝实心 + 白色层线）
    used_h = min(USED, CAP_TOTAL) * u
    o.append(f'<rect x="{ox}" y="{oy+H-used_h:.1f}" width="{W}" height="{used_h:.1f}" '
             f'fill="{USED_TOP}" stroke="{USED_R}" stroke-width="1.3"/>')
    z = 50.0
    while z < USED - 1:
        yy = oy + H - z * u
        o.append(line((ox, yy), (ox + W, yy), "#ffffff", .9, .20))
        z += 50.0

    # 可存放上限线（预留带下沿）：白色虚线，压在深蓝上
    y_st = oy + H - STORABLE * u
    o.append(line((ox, y_st), (ox + W, y_st), "#ffffff", 1.6, .9, "7 5"))
    # 超出段顶部（红色虚线）
    if OVER > 0:
        y_ov = oy + H - USED * u
        o.append(line((ox, y_ov), (ox + W, y_ov), OVER_C, 1.8, 1.0, "6 4"))

    # 左侧容量刻度（方）
    ax = ox - 22
    o.append(line((ax, oy), (ax, oy + H), "#9fadbb", 1.1))
    for c in (0, 100, 200, 300, 450):
        yy = oy + H - c * u
        o.append(line((ax - 5, yy), (ax + 5, yy), "#9fadbb", 1.3))
        o.append(txt(ax - 9, yy + 4, f"{c:,}", "v-axis", "end"))
    o.append(txt(ax - 9, oy - 10, "方", "v-axis", "end"))

    # 顶部总容积
    o.append(txt(ox + W / 2, oy - 12, f"仓库总容积 {CAP_TOTAL:,.0f} 方", "v-top", "middle"))

    # 区内文字
    cy = oy + H - used_h / 2
    o.append(txt(ox + W / 2, cy - 6, f"已用 {USED:.1f} 方", "v-used", "middle"))
    o.append(txt(ox + W / 2, cy + 18, f"占可存放 {PCT:.1f}%", "v-used2", "middle"))

    # 右侧引出标签
    lx = ox + W + 20
    # 超出段（红）
    y_over = oy + H - (STORABLE + OVER / 2) * u
    o.append(line((ox + W, y_over), (lx - 8, y_over), OVER_C, 1.2, .9, "4 3"))
    o.append(txt(lx, y_over + 4, f"超出 {OVER:.1f} 方", "v-over"))
    # 可存放上限（折线向下）
    o.append(line((ox + W, y_st), (lx - 26, y_st), "#ffffff", 1.2, .9, "4 3"))
    o.append(line((lx - 26, y_st), (lx - 14, y_st + 34), "#9fadbb", 1.2, .9, "4 3"))
    o.append(line((lx - 14, y_st + 34), (lx - 8, y_st + 34), "#9fadbb", 1.2, .9, "4 3"))
    o.append(txt(lx, y_st + 38, f"可存放 {STORABLE:,.0f} 方", "v-side"))
    o.append(txt(lx, y_st + 54, f"预留 {RES_TOTAL:,.0f} 方 · 打包 {RES_PACK:,.0f} 方 / 进货 {RES_BUY:,.0f} 方", "v-side2"))

    return ('<svg viewBox="0 0 820 320" class="v-svg" role="img" '
            'aria-label="国内仓库库容剖面图">\n' + "\n".join(o) + '\n</svg>')


SVG = section_svg()

# ---- 预览页 ------------------------------------------------------------
HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>国内仓库库容占用 · 预览</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#eef2f6;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#16212e;padding:22px}
.wrap{max-width:1240px;margin:0 auto}
.card{background:#fff;border:1px solid #e6ebf0;border-radius:16px;box-shadow:0 1px 3px rgba(15,23,42,.05)}
.hd{padding:18px 22px 0}
.hd h1{margin:0;font-size:20px;font-weight:700;letter-spacing:.3px}
.grid{display:grid;grid-template-columns:1.6fr 1fr;gap:26px;padding:16px 22px 22px;align-items:start}
.v-svg{width:100%;height:auto;display:block}
.v-axis{font-size:11px;fill:#8b98a4;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.v-top{font-size:12.5px;font-weight:700;fill:#16212e;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.v-used{font-size:19px;font-weight:700;fill:#ffffff;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.v-used2{font-size:13px;font-weight:600;fill:#d5e7f7;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.v-side{font-size:12.5px;font-weight:700;fill:#16212e;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.v-side2{font-size:10.5px;fill:#8b98a4;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.v-over{font-size:12.5px;font-weight:700;fill:#d92b3f;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:16px 20px;margin:0 0 6px}
.kpi b{display:block;font-size:28px;font-weight:700;letter-spacing:-.4px;color:#0d3b5c;font-variant-numeric:tabular-nums;line-height:1.15}
.kpi b u{font-size:13px;font-weight:600;font-style:normal;margin-left:3px;color:#8b98a4}
.kpi b.free{color:#0a7f74}
.kpi b.warn{color:#d92b3f}
.kpi span{display:block;font-size:12px;color:#8b98a4;margin-top:3px}
.rows{display:grid;gap:9px;margin:16px 0 0;padding:14px 0 0;border-top:1px solid #eef2f6}
.rows div{display:flex;align-items:baseline;gap:9px;font-size:12.5px;color:#5c6b7a}
.rows b{margin-left:auto;color:#16212e;font-variant-numeric:tabular-nums;font-weight:600}
.rows b.warn{color:#d92b3f}
</style></head><body><div class="wrap">
<div class="card">
  <div class="hd"><h1>国内仓库库容占用</h1></div>
  <div class="grid">
    <div>__SVG__</div>
    <div>
      <div class="kpis">
        <div class="kpi"><b>__CAP__<u>方</u></b><span>仓库总容积</span></div>
        <div class="kpi"><b>__USED__<u>方</u></b><span>已用容积</span></div>
        <div class="kpi"><b class="warn">__PCT__<u>%</u></b><span>库容占用率</span></div>
        <div class="kpi"><b class="warn">__OVER__<u>方</u></b><span>超出库容</span></div>
      </div>
      <div class="rows">
        <div>打包预留<b>__RESP__ 方</b></div>
        <div>进货预留<b>__RESB__ 方</b></div>
        <div>可存放<b>__STOR__ 方</b></div>
        <div>总容积剩余<b class="warn">__FREE__ 方</b></div>
      </div>
    </div>
  </div>
</div>
</div>
</body></html>
"""

html = (HTML.replace("__SVG__", SVG)
            .replace("__CAP__", f"{CAP_TOTAL:,.0f}")
            .replace("__USED__", f"{USED:.1f}")
            .replace("__OVER__", f"{OVER:.1f}")
            .replace("__PCT__", f"{PCT:.1f}")
            .replace("__RESP__", f"{RES_PACK:,.0f}")
            .replace("__RESB__", f"{RES_BUY:,.0f}")
            .replace("__STOR__", f"{STORABLE:,.0f}")
            .replace("__FREE__", f"{FREE_TOTAL:.1f}"))

outp = os.path.join(BASE, "shandi-v5", "vol_preview.html")
io.open(outp, "w", encoding="utf-8", newline="\r\n").write(html)
print(json.dumps({
    "capTotal": CAP_TOTAL, "resPack": RES_PACK, "resBuy": RES_BUY, "storable": STORABLE,
    "bootBoxes": boot_boxes, "plainBoxes": plain_boxes,
    "used": round(USED, 2), "over": round(OVER, 2), "pct": round(PCT, 1),
    "freeTotal": round(FREE_TOTAL, 2),
}, ensure_ascii=False))
print("preview ->", outp, os.path.getsize(outp), "bytes")
