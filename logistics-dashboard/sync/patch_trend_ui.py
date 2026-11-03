# -*- coding: utf-8 -*-
"""SPU 周度趋势：点矩阵数字 → 居中浮层半幅卡片，看该指标的**周**趋势 + 本周vs上周

数据：shandi-v5/trend.json → window.__TREND（只含最近 13 周 ≈ 3 个月）
结构：{ sid: { weeks:[周结日...], spu:{ SPU:[[可售,总双数,老库龄,0-90,91-180,181-270,271-365,365+], ...] } } }

交互（2026-10-30 用户要求）：
  · 5 个库龄段 / 老库龄 / 可售 / 总双数 → 点开看该指标的周趋势
  · 卡片是居中半幅浮层，**不挡页面**：点卡片外直接穿透到底下的矩阵 → 换个数字就换指标
  · **左右并排**：左边 KPI + 折线，右边周度明细（13 周全展开，不用滚），字放大
  · 折线点悬停出数值、表格行点击 → 顶部 KPI / 折线 / 表格三者联动
  · 关闭：右上角 × / ESC
本脚本是独立 <script>，不依赖仓库页 IIFE 内的 esc/closeDrill，自带一套。

幂等：可重复运行，输出稳定。
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(BASE, "shandi-v5", "index.html")
TREND = os.path.join(BASE, "shandi-v5", "trend.json")

CSS = """/* ===== SPU 周度趋势·样式（2026-10-30） ===== */
/* v2（2026-11-02 用户要求）：弱化数据展示 —— 白色半透明磨砂玻璃浮层，卡内只留一条平滑库存波动曲线 */
#lv1WhLayer .fm-asp-tbl td.tc{cursor:pointer;}
#lv1WhLayer .fm-asp-tbl td.tc:hover{background:#eaf2fa;color:#0d3b5c;}
#lv1WhLayer .fm-asp-tbl td.tc.dn:hover{background:#fdeeee;color:#c8102e;}
/* 浮层卡片：就地浮在被点的格子旁，不遮页面；玻璃 token 同规范 §6 */
.fm-trend-card{position:fixed;z-index:100000;pointer-events:auto;
  width:min(460px,calc(100vw - 24px));padding:10px 14px 9px;
  background:rgba(255,255,255,.68);color:#16212e;
  -webkit-backdrop-filter:blur(20px) saturate(180%);backdrop-filter:blur(20px) saturate(180%);
  border:1px solid rgba(255,255,255,.65);border-radius:10px;
  box-shadow:0 12px 32px rgba(15,23,42,.16),0 1px 2px rgba(15,23,42,.05),inset 0 1px 0 rgba(255,255,255,.9);
  display:flex;flex-direction:column;}
.fm-trend-head{display:flex;align-items:baseline;gap:8px;padding:0 0 8px;margin-bottom:5px;
  border-bottom:1px solid rgba(15,23,42,.12);user-select:none;}
.fm-trend-head b{font-size:13px;font-weight:700;color:#0d3b5c;}
.fm-trend-head span{font-size:12px;color:#5c6b7a;}
.fm-trend-x{margin-left:auto;width:22px;height:22px;border:0;border-radius:6px;background:transparent;
  color:#97a4b0;font-size:16px;line-height:1;cursor:pointer;}
.fm-trend-x:hover{background:rgba(13,59,92,.08);color:#0d3b5c;}
.fm-trend-chart{height:190px;position:relative;}
.fm-trend-chart svg{display:block;width:100%;height:100%;}
.fm-trend-chart circle.hit{fill:transparent;cursor:pointer;}
.fm-trend-chart line.hl{stroke:#b8c4cf;stroke-width:1;stroke-dasharray:3 3;}
.fm-trend-axis{display:flex;justify-content:space-between;padding:2px 0 0;font-size:11px;color:#97a4b0;
  font-variant-numeric:tabular-nums;}
.fm-trend-tip{position:fixed;z-index:100001;display:none;pointer-events:none;
  background:rgba(255,255,255,.68);color:#16212e;
  -webkit-backdrop-filter:blur(20px) saturate(180%);backdrop-filter:blur(20px) saturate(180%);
  border:1px solid rgba(255,255,255,.65);border-radius:10px;padding:6px 10px;
  font-size:12.5px;white-space:nowrap;
  font-variant-numeric:tabular-nums;box-shadow:0 12px 32px rgba(15,23,42,.16),0 1px 2px rgba(15,23,42,.05),inset 0 1px 0 rgba(255,255,255,.9);}
.fm-trend-tip b{font-size:14px;font-weight:700;margin-left:4px;}
.fm-trend-empty{padding:38px 10px;text-align:center;font-size:12.5px;color:#97a4b0;}
"""

JS = r"""  /* ===== SPU 周度趋势·交互（2026-10-30） ===== */
  /* v2（2026-11-02 用户要求）：
     ① 弱化数据展示 —— 点开不再弹「KPI 三数 + 周度明细表」的大卡片，改为一张白色半透明磨砂玻璃
        小卡片，卡内只有一条平滑的库存波动曲线（该 SPU 在该库龄段的双数波动），就地浮在被点的格子旁；
     ② 修掉「日期 数量」气泡关卡片后不消失的 bug —— 以前每次开卡片都往层里塞一个新气泡，
        关闭时只隐藏了第一个，于是页面上越积越多。 */
  var TREND_META = {
    c0:   {i:3, t:"0-90天",    bad:false},
    c1:   {i:4, t:"91-180天",  bad:false},
    c2:   {i:5, t:"181-270天", bad:false},
    c3:   {i:6, t:"271-365天", bad:true},
    c4:   {i:7, t:"365天以上", bad:true},
    old:  {i:2, t:"271天以上",  bad:true},
    avail:{i:0, t:"可售",      bad:false},
    total:{i:1, t:"总双数",    bad:false}
  };

  function tEsc(s){
    s = String(s == null ? "" : s);
    var o = "", i, c;
    for(i = 0; i < s.length; i++){
      c = s.charAt(i);
      if(c === "&") o += "&amp;";
      else if(c === "<") o += "&lt;";
      else if(c === ">") o += "&gt;";
      else if(c === '"') o += "&quot;";
      else if(c === "'") o += "&#39;";
      else o += c;
    }
    return o;
  }

  /* 关闭：卡片与气泡一律从 DOM 移除（只隐藏第一个气泡就是「关不掉」的根因） */
  function tClose(){
    var cards = document.querySelectorAll(".fm-trend-card"), i;
    for(i = 0; i < cards.length; i++){ if(cards[i].parentNode) cards[i].parentNode.removeChild(cards[i]); }
    var tips = document.querySelectorAll(".fm-trend-tip");
    for(i = 0; i < tips.length; i++){ if(tips[i].parentNode) tips[i].parentNode.removeChild(tips[i]); }
    window.__fmTrendAnchor = null;
  }

  function trendSeries(spu, metric, sid){
    var T = window.__TREND || {};
    var sh = T[String(sid)];
    if(!sh || !sh.spu) return null;
    var row = sh.spu[spu];
    if(!row) return null;
    var meta = TREND_META[metric] || TREND_META.total;
    var out = [];
    for(var i = 0; i < sh.weeks.length; i++){
      var r = row[i];
      if(!r) continue;
      out.push({ d: sh.weeks[i], v: Number(r[meta.i]) || 0 });
    }
    return out.length ? out : null;
  }

  function trendNum(v){
    return (Math.round(Number(v) || 0)).toLocaleString("en-US");
  }
  function trendPct(cur, prev){
    if(!prev) return cur > 0 ? "+100%" : "0%";
    var p = (cur - prev) / prev * 100;
    return (p >= 0 ? "+" : "") + p.toFixed(1) + "%";
  }
  function trendDay(s){
    var p = String(s || "").split("-");
    return p.length >= 3 ? (p[1] + "/" + p[2]) : String(s || "");
  }
  function trendFull(s){
    var p = String(s || "").split("-");
    return p.length >= 3 ? (p[0] + "-" + p[1] + "-" + p[2]) : String(s || "");
  }

  /* 平滑曲线：Catmull-Rom → 三次贝塞尔（原来是折线段 L） */
  function trendSmooth(pts){
    var n = pts.length, i, d;
    if(!n) return "";
    d = "M" + pts[0][0].toFixed(1) + " " + pts[0][1].toFixed(1);
    if(n === 1) return d;
    for(i = 0; i < n - 1; i++){
      var p0 = pts[i > 0 ? i-1 : 0], p1 = pts[i], p2 = pts[i+1], p3 = pts[i+2 < n ? i+2 : n-1];
      var c1x = p1[0] + (p2[0]-p0[0]) * 0.16, c1y = p1[1] + (p2[1]-p0[1]) * 0.16;
      var c2x = p2[0] - (p3[0]-p1[0]) * 0.16, c2y = p2[1] - (p3[1]-p1[1]) * 0.16;
      d += " C" + c1x.toFixed(1) + " " + c1y.toFixed(1) + "," + c2x.toFixed(1) + " " + c2y.toFixed(1)
         + "," + p2[0].toFixed(1) + " " + p2[1].toFixed(1);
    }
    return d;
  }

  function trendChartSVG(series, bad, W, H){
    W = W || 430; H = H || 190;
    var PL = 42, PR = 16, PT = 14, PB = 16;
    var n = series.length;
    var max = 0, min = 1e18, i;
    for(i = 0; i < n; i++){ if(series[i].v > max) max = series[i].v; if(series[i].v < min) min = series[i].v; }
    if(max <= 0) max = 1;
    var lo = Math.max(0, min - (max - min) * 0.35);
    if(max - lo < 1) lo = 0;
    var iw = W - PL - PR, ih = H - PT - PB;
    var step = n > 1 ? iw / (n - 1) : 0;
    var color = bad ? "#c8102e" : "#0d3b5c";
    var fill = bad ? "rgba(200,16,46,.09)" : "rgba(13,59,92,.09)";
    var pts = [], d = "", area = "";
    for(i = 0; i < n; i++){
      var x = PL + (n > 1 ? i * step : iw / 2);
      var y = PT + ih - ((series[i].v - lo) / (max - lo)) * ih;
      pts.push([x, y]);
    }
    d = trendSmooth(pts);
    area = d + " L" + pts[n-1][0].toFixed(1) + " " + (PT + ih) + " L" + pts[0][0].toFixed(1) + " " + (PT + ih) + " Z";
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="周度趋势">';
    s += '<line class="hl" x1="0" y1="0" x2="0" y2="' + (PT + ih) + '" style="display:none"/>';
    s += '<g class="ax">';
    var g;
    for(g = 0; g <= 3; g++){
      var gy = PT + ih - ih * g / 3;
      var gv = Math.round(lo + (max - lo) * g / 3);
      s += '<line x1="' + PL + '" y1="' + gy.toFixed(1) + '" x2="' + (W - PR) + '" y2="' + gy.toFixed(1) + '" stroke="#eef2f6" stroke-width="1"/>';
      s += '<text x="' + (PL - 8) + '" y="' + (gy + 4).toFixed(1) + '" text-anchor="end" font-size="10.5" fill="#a9b6c1">' + trendNum(gv) + '</text>';
    }
    s += '<path d="' + area + '" fill="' + fill + '"/>';
    s += '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>';
    for(i = 0; i < n; i++){
      var last = (i === n - 1);
      s += '<circle cx="' + pts[i][0].toFixed(1) + '" cy="' + pts[i][1].toFixed(1) + '" r="' + (last ? 4.2 : 2.4) + '" fill="' + (last ? color : "#fff") + '" stroke="' + color + '" stroke-width="1.8"/>';
      s += '<circle class="hit" data-i="' + i + '" cx="' + pts[i][0].toFixed(1) + '" cy="' + pts[i][1].toFixed(1) + '" r="10"/>';
    }
    var lx = pts[n-1][0], ly = pts[n-1][1];
    var anchor = (lx > W - 90) ? "end" : "start";
    var tx = (anchor === "end") ? lx - 9 : lx + 10;
    s += '<text x="' + tx.toFixed(1) + '" y="' + (Math.max(PT + 11, ly - 10)).toFixed(1) + '" text-anchor="' + anchor + '" font-size="12.5" font-weight="700" fill="' + color + '">' + trendNum(series[n-1].v) + '</text>';
    s += '</g></svg>';
    return s;
  }

  /* 就地摆放：贴着被点的格子；下方放得下就下方，上方够就上方，两边都不够就选空间大的一边 */
  function trendPlace(card, anchor){
    if(!card) return;
    var W = card.offsetWidth || 460, H = card.offsetHeight || 260, x, y;
    var ar = (anchor && anchor.getBoundingClientRect) ? anchor.getBoundingClientRect() : null;
    if(ar){
      x = ar.left + ar.width / 2 - W / 2;
      y = ar.bottom + 10;
      if(y + H > window.innerHeight - 12){
        var y2 = ar.top - H - 10;
        y = (y2 >= 12) ? y2 : Math.max(12, window.innerHeight - H - 12);
      }
    }else{
      x = Math.max(12, (window.innerWidth - W) / 2);
      y = Math.max(12, (window.innerHeight - H) / 2 - 30);
    }
    x = Math.min(Math.max(8, x), Math.max(8, window.innerWidth - W - 8));
    y = Math.min(Math.max(8, y), Math.max(8, window.innerHeight - H - 8));
    card.style.left = x + "px";
    card.style.top = y + "px";
  }

  function trendOpen(spu, metric, sid, anchor){
    var meta = TREND_META[metric] || TREND_META.total;
    var series = trendSeries(spu, metric, sid);
    tClose();
    var host = document.getElementById("lv1WhLayer") || document.body;

    var h = '<div class="fm-trend-card" data-spu="' + tEsc(spu) + '">'
      + '<div class="fm-trend-head"><b>' + tEsc(spu) + '</b><span>' + tEsc(meta.t) + '</span>'
      + '<button type="button" class="fm-trend-x" aria-label="关闭">×</button></div>';
    if(!series){
      h += '<div class="fm-trend-empty">暂无历史数据<\/div>';
    }else{
      h += '<div class="fm-trend-chart" id="fmTrendChart"><\/div>'
        + '<div class="fm-trend-axis"><span>' + tEsc(trendDay(series[0].d)) + '</span><span>'
        + tEsc(trendDay(series[series.length - 1].d)) + '</span></div>';
    }
    h += '<\/div><div class="fm-trend-tip"><\/div>';

    var wrap = document.createElement("div");
    wrap.innerHTML = h;
    var card = wrap.querySelector(".fm-trend-card");
    var tip = wrap.querySelector(".fm-trend-tip");
    host.appendChild(card);
    host.appendChild(tip);
    window.__fmTrendAnchor = anchor || null;

    card.querySelector(".fm-trend-x").addEventListener("click", function(e){
      e.stopPropagation();
      tClose();
    });

    if(!series){ trendPlace(card, anchor); return; }

    var chartBox = card.querySelector("#fmTrendChart");
    var svg = null;
    if(chartBox){
      var cw = chartBox.clientWidth || 430;
      var ch = chartBox.clientHeight || 190;
      chartBox.innerHTML = trendChartSVG(series, meta.bad, cw, ch);
      svg = chartBox.querySelector("svg");
    }
    var hl = card.querySelector("line.hl");

    /* SVG 坐标换算：viewBox 与容器尺寸不一定同比例（preserveAspectRatio 会留边），
       必须按「等比缩放 + 居中」换算，否则虚线（viewBox 单位）和节点（屏幕像素）对不齐 */
    function trendMap(){
      if(!svg) return null;
      var hb = svg.getBoundingClientRect();
      var a = (svg.getAttribute("viewBox") || "0 0 430 190").split(/\s+/);
      var x0 = Number(a[0]) || 0, y0 = Number(a[1]) || 0;
      var vw = Number(a[2]) || 430, vh = Number(a[3]) || 190;
      var sc = Math.min(hb.width / vw, hb.height / vh);
      if(!(sc > 0)) sc = 1;
      var offX = hb.left + (hb.width - vw * sc) / 2;
      var offY = hb.top + (hb.height - vh * sc) / 2;
      return { x0:x0, y0:y0, vw:vw, vh:vh, sc:sc, offX:offX, offY:offY };
    }
    function focusPoint(i){
      if(i == null || !series[i]) return;
      var hits = card.querySelectorAll("circle.hit");
      var c = hits[i];
      if(!c) return;
      var M = trendMap();
      if(!M) return;
      var ux = Number(c.getAttribute("cx")), uy = Number(c.getAttribute("cy"));
      var px = M.offX + ux * M.sc, py = M.offY + uy * M.sc;
      hl.setAttribute("x1", M.x0 + ux); hl.setAttribute("x2", M.x0 + ux);
      hl.setAttribute("y1", M.y0); hl.setAttribute("y2", M.y0 + M.vh);
      hl.style.display = "";
      tip.innerHTML = tEsc(trendFull(series[i].d)) + " &nbsp;<b>" + trendNum(series[i].v) + "</b> 双";
      tip.style.display = "block";
      tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 8, px + 14) + "px";
      tip.style.top = Math.max(6, py - 36) + "px";
    }
    if(svg){
      svg.addEventListener("mousemove", function(e){
        var t = e.target;
        if(!t || !t.getAttribute || !t.getAttribute("data-i")) return;
        focusPoint(Number(t.getAttribute("data-i")));
      });
      svg.addEventListener("mouseleave", function(){
        if(hl) hl.style.display = "none";
        tip.style.display = "none";
      });
    }
    trendPlace(card, anchor);
  }

  /* ESC 关闭 */
  document.addEventListener("keydown", function(e){
    if((e.key === "Escape" || e.keyCode === 27) && document.querySelector(".fm-trend-card")){
      tClose();
    }
  });

  /* 点卡片外收起（只注册一次） */
  if(!window.__fmTrendOutsideBound){
    window.__fmTrendOutsideBound = 1;
    document.addEventListener("pointerdown", function(e){
      var c = document.querySelector(".fm-trend-card");
      if(!c) return;
      var t = e.target;
      if(t && t.closest && t.closest(".fm-trend-card")) return;
      tClose();
    }, true);
  }

  /* 滚动/缩放时跟着锚点走；锚点滚出视口就收起 */
  if(!window.__fmTrendFollowBound){
    window.__fmTrendFollowBound = 1;
    var follow = function(){
      var c = document.querySelector(".fm-trend-card");
      if(!c) return;
      var a = window.__fmTrendAnchor;
      if(a && a.getBoundingClientRect){
        var r = a.getBoundingClientRect();
        if(r.bottom < 0 || r.top > window.innerHeight){ tClose(); return; }
        trendPlace(c, a);
      }
    };
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
  }

  /* 全局事件委托：矩阵数值格可点（表头排序不受影响） */
  document.addEventListener("click", function(e){
    var td = (e.target && e.target.closest) ? e.target.closest("td[data-trend]") : null;
    if(!td) return;
    var tr = td.closest("tr");
    if(!tr) return;
    var spuTd = tr.querySelector("td.spu");
    if(!spuTd) return;
    var wrap = td.closest("#fmAgeSpu");
    var sid = wrap ? (wrap.getAttribute("data-sid") || "") : "";
    var spu = spuTd.getAttribute("data-spu") || (spuTd.textContent || "").trim();
    trendOpen(spu, td.getAttribute("data-trend"), sid, td);
  });
"""


def crlf(s):
    return s.replace("\n", "\r\n")


def swap(text, old, new, label):
    old_n = old.replace("\n", chr(10))
    new_n = new.replace("\n", chr(10))
    if new_n in text:
        return text, label + ":already"
    assert old_n in text, label + ": 未找到待替换块"
    return text.replace(old_n, new_n, 1), label + ":replaced"


html = io.open(IDX, encoding="utf-8").read()
NL = chr(10)

if not os.path.exists(TREND):
    print("没有 trend.json，先跑 build_trend.py")
    sys.exit(1)
T = json.load(io.open(TREND, encoding="utf-8"))
data_js = "window.__TREND = " + json.dumps(T, ensure_ascii=False, separators=(",", ":")) + ";"

# 1) 数据
i = html.find("window.__TREND = ")
if i >= 0:
    j = html.find("\n", i)
    html = html[:i] + data_js + html[j:]
    dstat = "replaced"
else:
    k = html.find("window.__AGESPU = ")
    assert k > 0, "__AGESPU 锚点丢失"
    j = html.find("\n", k)
    html = html[:j + 1] + data_js + "\r\n" + html[j + 1:]
    dstat = "inserted"

# 2) CSS
# 本脚本读文件用通用换行（内存里全是 \n），注入的 CSS 也必须保持纯 \n，
# 最后由 re.sub 统一转 CRLF。若混入真 \r\n，删除端匹配不到块尾换行 → 删/插不对称，每轮多一个空行（不幂等）。
css_new = CSS.replace("\r\n", "\n").replace("\r", "\n").strip("\n") + "\n"
mark = "/* ===== SPU 周度趋势·样式（2026-10-30） ===== */"
if mark in html:
    # 右边界 = 本块最后一条规则的闭合大括号。旧写法用「下一个 /*===== 」当右边界，
    # 一旦本块不在锚点旁边就会越界删掉几百 KB 页面代码（2026-11-03 夜间链路事故同款）。
    mi = html.find(mark)
    r = html.find(".fm-trend-empty{", mi)
    assert r > mi, "trend css last rule missing"
    e = html.find("}", r) + 1
    if html[e:e + 1] == "\n":
        e += 1                        # 连块尾换行一起删：插入时块尾自带换行，删/插必须严格互补
    html = html[:mi] + html[e:]
    cstat = "moved"
else:
    cstat = "inserted"
# 插入锚点必须落在行首：新插入的段头前面不能带空格（否则会被别的段头检索误认）
ap = html.find("\n/* ===== SKU 模糊搜索（2026-10-26）")
assert ap >= 0, "css 插入锚点丢失"
k = ap + 1
html = html[:k] + css_new + html[k:]

# 3) JS：独立 <script> 块插在 </body> 前（避开所有 patch 脚本的替换区间）
# 同样保持纯 \n（内存统一换行，写回时统一转 CRLF）
JS_SRC = JS.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
JS_BLOCK = "<script>\n" + JS_SRC + "\n</script>"
i = html.find("/* ===== SPU 周度趋势·交互（2026-10-30） ===== */")
if i >= 0:
    st = html.rfind("<script>", 0, i)
    en = html.find("</script>", i)
    if en < 0:                      # 历史上写坏的 <\/script> 形态
        en = html.find("<\\/script>", i)
        tail = len("<\\/script>")
    else:
        tail = len("</script>")
    assert st > 0 and en > i, "趋势 JS 块边界异常"
    cut = en + tail
    if html[cut:cut + 2] == "\r\n":
        cut += 2
    elif html[cut:cut + 1] == "\n":
        cut += 1
    html = html[:st] + html[cut:]
    jstat = "replaced"
else:
    jstat = "inserted"
j = html.find("</body>")
assert j > 0, "</body> 锚点丢失"
html = html[:j] + JS_BLOCK + "\n" + html[j:]

# 4) 矩阵单元格加 data-trend / data-spu
html, m1 = swap(html,
                """      h += '<tr><td class="l spu">' + esc(rr.spu) + '</td>';""",
                """      h += '<tr><td class="l spu" data-spu="' + esc(rr.spu) + '">' + esc(rr.spu) + '</td>';""",
                "SPU列")
html, m2 = swap(html,
                """        h += '<td>' + (v > 0 ? aspN(v) : "·") + '</td>';""",
                """        h += '<td class="tc" data-trend="c' + j + '">' + (v > 0 ? aspN(v) : "·") + '</td>';""",
                "库龄段格")
html, m3 = swap(html,
                """      h += '<td class="old">' + (rr.old > 0 ? aspN(rr.old) : "·") + '</td>';""",
                """      h += '<td class="old tc' + (rr.old > 0 ? ' dn' : '') + '" data-trend="old">' + (rr.old > 0 ? aspN(rr.old) : "·") + '</td>';""",
                "老库龄格")
html, m4 = swap(html,
                """      h += '<td>' + aspN(rr.avail) + '</td>';""",
                """      h += '<td class="tc" data-trend="avail">' + aspN(rr.avail) + '</td>';""",
                "可售格")
html, m5 = swap(html,
                """      h += '<td>' + aspN(rr.total) + '</td></tr>';""",
                """      h += '<td class="tc" data-trend="total">' + aspN(rr.total) + '</td></tr>';""",
                "总双数格")

# 5) 容器带 sid，供事件委托取店铺
html, m6 = swap(html,
                """      '<span class="fm-asp-cnt"></span></div><div class="fm-asp-mx"></div>';
    box.innerHTML = h;""",
                """      '<span class="fm-asp-cnt"></span></div><div class="fm-asp-mx"></div>';
    box.setAttribute("data-sid", String(sid));
    box.innerHTML = h;""",
                "容器sid")

html = re.sub(r"(?<!\r)\n", "\r\n", html)
io.open(IDX, "w", encoding="utf-8", newline="").write(html)
b = open(IDX, "rb").read()
print("patched | bytes %d | crlf %d | lf-only %d" % (len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n")))
print("  data:%s css:%s js:%s | %s %s %s %s %s %s" % (dstat, cstat, jstat, m1, m2, m3, m4, m5, m6))
print("  __TREND: %d | data-trend 格: %d | trendOpen: %d | 卡片式: %d" % (
    html.count("window.__TREND ="), html.count("data-trend="),
    html.count("function trendOpen("), html.count("fm-trend-card")))
