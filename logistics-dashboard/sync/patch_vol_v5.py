# -*- coding: utf-8 -*-
"""主页库容模块 v5：全部按方。总容积 450 方，预留 60 方，可存放 390 方，已用 426.7 方。"""
import io, json, os, re, importlib.util, sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(BASE, "shandi-v5", "index.html")

spec = importlib.util.spec_from_file_location("bv5", os.path.join(BASE, "build_vol_v5.py"))
bv5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bv5)

VOL = {
    "svg": bv5.SVG,
    "capTotal": bv5.CAP_TOTAL,
    "used": round(bv5.USED, 1),
    "over": round(bv5.OVER, 1),
    "pct": round(bv5.PCT, 1),
    "resPack": bv5.RES_PACK,
    "resBuy": bv5.RES_BUY,
    "storable": bv5.STORABLE,
    "freeTotal": round(bv5.FREE_TOTAL, 1),
}

CSS = """
/* ===== 国内仓库容占用 · 体积口径剖面（2026-10-27）· 深蓝=已用 / 白虚线=可存放上限 / 红=超出 ===== */
#lv1WhLayer .wh-vol{margin:26px 0 4px;padding-top:22px;border-top:1px solid #eef2f6;}
#lv1WhLayer .wh-vol-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:4px;}
#lv1WhLayer .wh-vol-head h2{margin:0;font-size:15px;font-weight:700;color:#16212e;letter-spacing:.3px;}
#lv1WhLayer .wh-vol-grid{display:grid;grid-template-columns:1.6fr 1fr;gap:26px;align-items:start;}
#lv1WhLayer .wh-vol-l{min-width:0;}
#lv1WhLayer .wh-vol-r{min-width:0;border-left:1px solid #eef2f6;padding-left:26px;}
#lv1WhLayer .wh-vol-svg{width:100%;height:auto;display:block;}
#lv1WhLayer .wh-vol-kpis{display:grid;grid-template-columns:1fr 1fr;gap:16px 26px;margin:0 0 4px;}
#lv1WhLayer .wh-vol-kpi b{display:block;font-size:26px;line-height:1.15;font-weight:700;letter-spacing:-.4px;color:#0d3b5c;font-variant-numeric:tabular-nums;font-feature-settings:'tnum';}
#lv1WhLayer .wh-vol-kpi b.free{color:#0a7f74;}
#lv1WhLayer .wh-vol-kpi b.warn{color:#d92b3f;}
#lv1WhLayer .wh-vol-kpi u{text-decoration:none;font-size:12px;font-weight:400;color:#5c6b7a;margin-left:3px;}
#lv1WhLayer .wh-vol-kpi span{display:block;margin-top:3px;font-size:12.5px;color:#5c6b7a;}
#lv1WhLayer .wh-vol-rows{display:grid;gap:9px;margin:14px 0 0;padding:14px 0 0;border-top:1px solid #eef2f6;}
#lv1WhLayer .wh-vol-rows div{display:flex;align-items:baseline;gap:9px;font-size:12.5px;color:#5c6b7a;}
#lv1WhLayer .wh-vol-rows b{margin-left:auto;color:#16212e;font-variant-numeric:tabular-nums;font-weight:600;}
#lv1WhLayer .wh-vol-rows b.warn{color:#d92b3f;}
#lv1WhLayer .v-axis{font-size:11px;fill:#8b98a4;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
#lv1WhLayer .v-top{font-size:12.5px;font-weight:700;fill:#16212e;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
#lv1WhLayer .v-used{font-size:19px;font-weight:700;fill:#ffffff;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
#lv1WhLayer .v-used2{font-size:13px;font-weight:600;fill:#d5e7f7;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
#lv1WhLayer .v-side{font-size:12.5px;font-weight:700;fill:#16212e;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
#lv1WhLayer .v-side2{font-size:10.5px;fill:#8b98a4;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
#lv1WhLayer .v-over{font-size:12.5px;font-weight:700;fill:#d92b3f;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
@media (max-width:1180px){
  #lv1WhLayer .wh-vol-grid{grid-template-columns:1fr;}
  #lv1WhLayer .wh-vol-r{border-left:none;padding-left:0;border-top:1px solid #eef2f6;padding-top:18px;}
}
"""

JS_DATA = "window.__VOL = " + json.dumps(VOL, ensure_ascii=False) + ";\n"

JS_FUNC = r"""
  /* ===== 仓库库容占用 · 体积口径剖面（2026-10-27）===== */
  function renderVolCard(el){
    if(!el) return;
    var V = window.__VOL;
    if(!V || !V.svg) return;
    var box = el.querySelector("#whVolBox");
    if(!box) return;

    function nn(n){ return Number(n || 0).toLocaleString("en-US"); }
    function f1(n){ return (Math.round(n * 10) / 10).toFixed(1); }

    var h = '';
    h += '<div class="wh-vol">';
    h += '<div class="wh-vol-head"><h2>国内仓库库容占用<\/h2><\/div>';
    h += '<div class="wh-vol-grid">';
    h += '<div class="wh-vol-l">' + V.svg + '<\/div>';
    h += '<div class="wh-vol-r">';
    h += '<div class="wh-vol-kpis">'
       + '<div class="wh-vol-kpi"><b>' + nn(V.capTotal) + '<u>方<\/u><\/b><span>仓库总容积<\/span><\/div>'
       + '<div class="wh-vol-kpi"><b>' + f1(V.used) + '<u>方<\/u><\/b><span>已用容积<\/span><\/div>'
       + '<div class="wh-vol-kpi"><b class="' + (V.pct > 100 ? "warn" : "") + '">' + f1(V.pct) + '<u>%<\/u><\/b><span>库容占用率<\/span><\/div>'
       + '<div class="wh-vol-kpi"><b class="' + (V.over > 0 ? "warn" : "free") + '">' + f1(V.over) + '<u>方<\/u><\/b><span>' + (V.over > 0 ? '超出库容' : '剩余库容') + '<\/span><\/div>'
       + '<\/div>';
    h += '<div class="wh-vol-rows">'
       + '<div>打包预留<b>' + nn(V.resPack) + ' 方<\/b><\/div>'
       + '<div>进货预留<b>' + nn(V.resBuy) + ' 方<\/b><\/div>'
       + '<div>可存放<b>' + nn(V.storable) + ' 方<\/b><\/div>'
       + '<div>总容积剩余<b class="' + (V.freeTotal <= 0 ? "warn" : "") + '">' + f1(V.freeTotal) + ' 方<\/b><\/div>'
       + '<\/div>';
    h += '<\/div>';
    h += '<\/div>';
    h += '<\/div>';
    box.innerHTML = h;
  }
"""


def crlf(s):
    return s.replace("\n", "\r\n")


html = io.open(IDX, encoding="utf-8", newline="").read()

# --- 1) CSS 段 ----------------------------------------------------------
css_start = html.find("/* ===== 国内仓库容占用 ·")
assert css_start >= 0, "css start missing"
css_end = html.find("/* ===== FBA 合并卡（2026-10-21）", css_start)
assert css_end > css_start, "css end missing"
html = html[:css_start] + crlf(CSS).strip("\r\n") + "\r\n" + html[css_end:]

# --- 2) 数据 ------------------------------------------------------------
m = re.search(r"window\.__VOL = \{.*?\};\r?\n", html, re.S)
assert m, "__VOL data missing"
html = html[:m.start()] + crlf(JS_DATA) + html[m.end():]

# --- 3) 渲染函数 --------------------------------------------------------
fn_start = html.find("  /* ===== 仓库库容占用 ·")
assert fn_start >= 0, "fn start missing"
fn_end = html.find("  function renderMergedCard(){", fn_start)
assert fn_end > fn_start, "fn end missing"
html = html[:fn_start] + crlf(JS_FUNC).strip("\r\n") + "\r\n" + html[fn_end:]

io.open(IDX, "w", encoding="utf-8", newline="").write(html)
b = open(IDX, "rb").read()
print("patched | bytes", len(b), "| crlf", b.count(b"\r\n"), "| lf-only", b.count(b"\n") - b.count(b"\r\n"))
for k in ["双数口径", "90,000 双", "口径说明", "100,000"]:
    print("  %-12s left=%d" % (k, html.count(k)))
