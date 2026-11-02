# -*- coding: utf-8 -*-
"""店级库龄结构趋势总览：FBA 库龄卡内新增模块（每店一行 13 周五色堆叠柱）

数据：data/age_trend_shop.json → window.__AGETREND（build_age_trend.py 产出）
结构：{ ageBands:[5], weeks:[全周历], shops:[{sid,name,weeks[],series[{d,bands[5],total,old,oldPct,qty,spuCount}]}],
        shopsMeta:{sid:{...hardCheck}} }

形态（2026-11-02 小丁要求；11-02 主管复核后补 5 处）：
  · 每店一行 = 13 周五色堆叠柱（横向 13 根柱，五段色自下而上堆叠）
  · 可切段：只看某一个库龄段（0-90/91-180/181-270/271-365/365+）；不切段＝五段堆叠
  · 可切店：点行首店名 → 切到页面顶部的店铺筛选（走原有 fm-chip 点击，不新增流程）
  · hover 某一根柱 → 玻璃浮层气泡：**首行＝店名 + 周结日**（全部态 5 行时必须能认出是哪家），
    下面五段双数 + 五段合计
  · 点某一根柱的某个色段 → 就地弹玻璃小卡片，显示该段 13 周单段走势（一条平滑曲线）
  · 行首同时给出 **老库龄占比**（末个有效周，271 天以上）
  · 全部态位置：各店明细表**之后**（对比表在上、趋势总览在下）；单店态：库龄条正下方
  · **绝对不出跨店合计**：一个店一行，不把多店加在一起
  · 无数据周留白（oldPct == null 视为空周，不当 0 造柱）；各周数值完全相同就不画（显示「—」）
  · 周轴与柱对齐：轴左右各留 17px（= 行卡 1px 边框 + 16px 内距），与 SVG 内容区同宽

视觉：五段色复用现有库龄条同一套 R5 色值（ACOL）；浮层一律 §6 浅色玻璃；页面卡片按 §8。
红线：SKU 绝不跨店合并；不造数；末周五段必须与页面库龄条 summary.age 逐段相等（直接用数据，不另算）。

幂等：可重复运行，输出稳定。行尾纯 CRLF、无 BOM。
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(BASE, "shandi-v5", "index.html")
DATA = os.path.join(BASE, "data", "age_trend_shop.json")

CSS_MARK = "/* ===== 店级库龄结构趋势·样式（2026-11-02） ===== */"
CSS_END = "/* ===== 店级库龄结构趋势·样式 END ===== */"
JS_MARK = "/* ===== 店级库龄结构趋势·交互（2026-11-02） ===== */"
CSS_ANCHOR = "/* ===== SPU 周度趋势·样式（2026-10-30） ===== */"

CSS = """/* ===== 店级库龄结构趋势·样式（2026-11-02） ===== */
/* 五段色复用现有库龄条同一套 R5（ACOL），本块只管版式 */
#lv1WhLayer .fm-aget-wrap{margin:0 0 6px;}
#lv1WhLayer .fm-aget-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 12px;}
#lv1WhLayer .fm-aget-bar em{font-style:normal;font-size:12px;color:#97a4b0;margin-right:2px;}
#lv1WhLayer .fm-aget-tab{font:inherit;font-size:12.5px;font-weight:500;height:28px;padding:0 14px;
  border-radius:14px;cursor:pointer;border:1px solid #e6ebf0;background:#fff;color:#5c6b7a;}
#lv1WhLayer .fm-aget-tab:hover{border-color:#c3ced8;color:#16212e;}
#lv1WhLayer .fm-aget-tab.on{background:#0d3b5c;border-color:#0d3b5c;color:#fff;font-weight:600;}
/* 行卡片：§8 页面卡片形制 */
#lv1WhLayer .fm-aget-row{background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:14px;
  padding:14px 16px 10px;margin-bottom:10px;
  box-shadow:0 1px 2px rgba(15,23,42,.04),0 8px 24px rgba(15,23,42,.06),inset 0 1px 0 rgba(255,255,255,.9);}
#lv1WhLayer .fm-aget-hd{display:flex;align-items:baseline;gap:10px;margin-bottom:6px;}
#lv1WhLayer .fm-aget-name{font-size:13px;font-weight:700;color:#0d3b5c;cursor:pointer;}
#lv1WhLayer .fm-aget-name:hover{text-decoration:underline;}
#lv1WhLayer .fm-aget-max{font-size:11.5px;font-weight:400;color:#5c6b7a;font-variant-numeric:tabular-nums;margin-left:auto;}
#lv1WhLayer .fm-aget-old{font-size:11.5px;font-weight:400;color:#5c6b7a;font-variant-numeric:tabular-nums;}
#lv1WhLayer .fm-aget-svg{display:block;width:100%;height:auto;overflow:visible;}
#lv1WhLayer .fm-aget-svg rect.fm-aget-seg{cursor:pointer;}
#lv1WhLayer .fm-aget-svg rect.fm-aget-seg:hover{filter:brightness(.9);}
#lv1WhLayer .fm-aget-axis{display:flex;margin-top:0;padding:0 17px;}
#lv1WhLayer .fm-aget-axis span{flex:1 1 0;text-align:center;font-size:11px;color:#97a4b0;
  font-variant-numeric:tabular-nums;white-space:nowrap;}
/* 柱悬停气泡：§6 浅色玻璃 */
#lv1WhLayer .fm-atrend-tip{position:fixed;z-index:100001;display:none;pointer-events:none;
  background:rgba(255,255,255,.68);color:#16212e;
  -webkit-backdrop-filter:blur(20px) saturate(180%);backdrop-filter:blur(20px) saturate(180%);
  border:1px solid rgba(255,255,255,.65);border-radius:10px;padding:8px 12px;
  font-size:12.5px;box-shadow:0 12px 32px rgba(15,23,42,.16),0 1px 2px rgba(15,23,42,.05),inset 0 1px 0 rgba(255,255,255,.9);}
#lv1WhLayer .fm-atrend-tip .at-hd{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
  margin-bottom:5px;padding-bottom:5px;border-bottom:1px solid rgba(15,23,42,.12);}
#lv1WhLayer .fm-atrend-tip .at-hd b{font-size:12.5px;font-weight:700;color:#0d3b5c;}
#lv1WhLayer .fm-atrend-tip .at-hd span{font-size:11.5px;color:#5c6b7a;font-variant-numeric:tabular-nums;}
#lv1WhLayer .fm-atrend-tip .at-r{display:flex;justify-content:space-between;gap:16px;line-height:1.75;}
#lv1WhLayer .fm-atrend-tip .at-r span{font-size:12px;color:#5c6b7a;}
#lv1WhLayer .fm-atrend-tip .at-r b{font-size:13px;font-weight:700;color:#16212e;font-variant-numeric:tabular-nums;}
#lv1WhLayer .fm-atrend-tip .at-r b i{font-style:normal;font-size:11px;font-weight:400;color:#97a4b0;margin-left:2px;}
#lv1WhLayer .fm-atrend-tip .at-sum{border-top:1px solid rgba(15,23,42,.12);margin-top:5px;padding-top:5px;}
/* 单段走势卡：形态照抄周趋势卡片 v2（白色半透明磨砂玻璃、只有一条曲线、无全屏遮罩） */
#lv1WhLayer .fm-atrend-card{position:fixed;z-index:100000;pointer-events:auto;
  width:min(460px,calc(100vw - 24px));padding:10px 14px 9px;
  background:rgba(255,255,255,.68);color:#16212e;
  -webkit-backdrop-filter:blur(20px) saturate(180%);backdrop-filter:blur(20px) saturate(180%);
  border:1px solid rgba(255,255,255,.65);border-radius:10px;
  box-shadow:0 12px 32px rgba(15,23,42,.16),0 1px 2px rgba(15,23,42,.05),inset 0 1px 0 rgba(255,255,255,.9);
  display:flex;flex-direction:column;}
#lv1WhLayer .fm-atrend-head{display:flex;align-items:baseline;gap:8px;padding:0 0 8px;margin-bottom:5px;
  border-bottom:1px solid rgba(15,23,42,.12);user-select:none;}
#lv1WhLayer .fm-atrend-head b{font-size:13px;font-weight:700;color:#0d3b5c;}
#lv1WhLayer .fm-atrend-head span{font-size:12px;color:#5c6b7a;}
#lv1WhLayer .fm-atrend-x{margin-left:auto;width:22px;height:22px;border:0;border-radius:6px;background:transparent;
  color:#97a4b0;font-size:16px;line-height:1;cursor:pointer;}
#lv1WhLayer .fm-atrend-x:hover{background:rgba(13,59,92,.08);color:#0d3b5c;}
#lv1WhLayer .fm-atrend-chart{height:190px;position:relative;}
#lv1WhLayer .fm-atrend-chart svg{display:block;width:100%;height:100%;}
#lv1WhLayer .fm-atrend-chart circle.hit{fill:transparent;cursor:pointer;}
#lv1WhLayer .fm-atrend-axis{display:flex;justify-content:space-between;padding:2px 0 0;font-size:11px;color:#97a4b0;
  font-variant-numeric:tabular-nums;}
#lv1WhLayer .fm-atrend-empty{padding:38px 10px;text-align:center;font-size:12.5px;color:#97a4b0;}
#lv1WhLayer .fm-atrend-ctip{position:fixed;z-index:100001;display:none;pointer-events:none;
  background:rgba(255,255,255,.68);color:#16212e;
  -webkit-backdrop-filter:blur(20px) saturate(180%);backdrop-filter:blur(20px) saturate(180%);
  border:1px solid rgba(255,255,255,.65);border-radius:10px;padding:6px 10px;
  font-size:12.5px;white-space:nowrap;font-variant-numeric:tabular-nums;
  box-shadow:0 12px 32px rgba(15,23,42,.16),0 1px 2px rgba(15,23,42,.05),inset 0 1px 0 rgba(255,255,255,.9);}
#lv1WhLayer .fm-atrend-ctip b{font-size:14px;font-weight:700;margin-left:4px;}
/* ===== 店级库龄结构趋势·样式 END ===== */"""

JS = r"""  /* ===== 店级库龄结构趋势·交互（2026-11-02） ===== */
  (function(){
    var A = window.__AGETREND || null;
    /* 五段色 = 现有库龄条同一套 R5（ACOL），不另配色 */
    var ACOL = ["#cfd8e0","#7cb6e6","#f0b429","#ef8080","#c8102e"];
    var KEY  = ["0-90天","91-180天","181-270天","271-365天","365天以上"];
    var BAD  = [false,false,false,true,true];
    var band = -1;                    /* -1 = 五段堆叠；0..4 = 只看某一段 */
    var host = document.getElementById("whFbaByShop");
    var VW = 1120, PLOT = 96, BARW = 26;

    function esc(s){
      s = String(s == null ? "" : s);
      return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
              .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
    }
    function num(v){ return (Math.round(Number(v) || 0)).toLocaleString("en-US"); }
    function day(s){ var p = String(s || "").split("-"); return p.length >= 3 ? (p[1] + "/" + p[2]) : String(s || ""); }

    function weeks(){ return (A && A.weeks) || []; }
    function shopById(sid){
      if(!A || !A.shops) return null;
      for(var i=0;i<A.shops.length;i++) if(String(A.shops[i].sid) === String(sid)) return A.shops[i];
      return null;
    }
    /* 当前作用域：单店态＝该店一行；全部态＝每店一行。绝不合并 */
    function scope(){
      if(!A || !A.shops) return [];
      var chip = host ? host.querySelector(".fm-chip.on[data-fmsid]") : null;
      var sid = chip ? chip.getAttribute("data-fmsid") : "all";
      if(sid && sid !== "all"){
        var one = shopById(sid);
        if(one) return [one];
      }
      return A.shops.slice();
    }
    /* 空周：oldPct == null（或没有该周记录）＝留白，不当 0 造柱 */
    function recOf(sh, w){
      for(var i=0;i<sh.weeks.length;i++) if(sh.weeks[i] === w) return sh.series[i];
      return null;
    }
    function isEmpty(r){ return !r || r.oldPct == null; }
    /* 末个有效周的老库龄占比（271 天以上），空周不算 */
    function latestPct(sh){
      var ss = (sh && sh.series) || [];
      for(var i=ss.length-1;i>=0;i--){ if(ss[i] && ss[i].oldPct != null) return ss[i].oldPct; }
      return null;
    }

    /* ---------- 柱 ---------- */
    function rowSVG(sh){
      var ws = weeks(), n = ws.length, i, k, r, v;
      var slot = n ? (VW / n) : VW;
      var bw = Math.min(BARW, Math.max(10, slot - 16));
      var max = 0;
      for(i=0;i<n;i++){
        r = recOf(sh, ws[i]);
        if(isEmpty(r)) continue;
        v = (band < 0) ? (Number(r.total) || 0) : (Number(r.bands[band]) || 0);
        if(v > max) max = v;
      }
      var s = '<svg class="fm-aget-svg" viewBox="0 0 ' + VW + ' ' + PLOT + '" role="img" aria-label="库龄结构趋势">';
      if(max <= 0){
        s += '<\/svg>';
        return {svg:s, max:0};
      }
      for(i=0;i<n;i++){
        r = recOf(sh, ws[i]);
        if(isEmpty(r)) continue;                       /* 空周留白 */
        var x = i * slot + (slot - bw) / 2;
        s += '<rect class="fm-aget-hit" data-sid="' + esc(sh.sid) + '" data-i="' + i + '" data-w="' + esc(ws[i]) + '"'
           + ' x="' + x.toFixed(1) + '" y="0" width="' + bw.toFixed(1) + '" height="' + PLOT + '" fill="transparent"/>';
      }
      for(i=0;i<n;i++){
        r = recOf(sh, ws[i]);
        if(isEmpty(r)) continue;
        var x = i * slot + (slot - bw) / 2;
        var acc = 0;
        for(k=0;k<5;k++){
          if(band >= 0 && k !== band) continue;
          v = Number(r.bands[k]) || 0;
          if(v <= 0) continue;
          var h = Math.max((v / max) * PLOT, 2);
          var y = PLOT - acc - h;
          s += '<rect class="fm-aget-seg" data-sid="' + esc(sh.sid) + '" data-band="' + k + '" data-i="' + i + '"'
             + ' data-w="' + esc(ws[i]) + '" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '"'
             + ' width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) + '" fill="' + ACOL[k] + '"/>';
          acc += h;
        }
      }
      s += '<\/svg>';
      return {svg:s, max:max};
    }

    /* ---------- 模块渲染 ---------- */
    function render(){
      if(!A || !host) return;
      if(!host.querySelector(".fm-chip")) return;      /* FBA 卡还没渲染，等它渲染完 */
      var list = scope();
      var sig = list.map(function(s){ return String(s.sid); }).join(",") + "|" + band;
      var wrap = host.querySelector("#fmAgeTrend");
      if(wrap && wrap.getAttribute("data-sig") === sig) return;   /* 已是最新，直接返回（避免自循环） */
      if(!wrap){
        wrap = document.createElement("div");
        wrap.id = "fmAgeTrend";
        wrap.className = "fm-aget-wrap";
      }
      var anchor = host.querySelector(".fm-segrow");
      if(anchor && anchor.parentNode) anchor.parentNode.insertBefore(wrap, anchor.nextSibling);
      else{
        /* 全部态：放在各店明细表之后（对比表在上、趋势总览在下，主次分明） */
        var hero = host.querySelector(".fm-hero");
        if(hero && hero.parentNode) hero.parentNode.insertBefore(wrap, hero.nextSibling);
        else host.appendChild(wrap);
      }
      wrap.setAttribute("data-sig", sig);

      var h = '<div class="fm-aget-bar"><em>库龄段</em>';
      h += '<button type="button" class="fm-aget-tab' + (band < 0 ? " on" : "") + '" data-band="-1">堆叠<\/button>';
      for(var k=0;k<5;k++){
        h += '<button type="button" class="fm-aget-tab' + (band === k ? " on" : "") + '" data-band="' + k + '">' + esc(KEY[k]) + '<\/button>';
      }
      h += '<\/div>';

      var axis = '';
      var ws = weeks();
      for(var i=0;i<ws.length;i++) axis += '<span>' + esc(day(ws[i])) + '<\/span>';

      for(var s2=0;s2<list.length;s2++){
        var sh = list[s2];
        var r = rowSVG(sh);
        var label = (band < 0) ? "峰值 " : KEY[band] + " 峰值 ";
        var op = latestPct(sh);
        h += '<div class="fm-aget-row" data-sid="' + esc(sh.sid) + '">'
          + '<div class="fm-aget-hd"><span class="fm-aget-name" data-goto="' + esc(sh.sid) + '">' + esc(sh.name || sh.sid) + '<\/span>'
          + '<span class="fm-aget-old">老库龄 ' + (op == null ? "—" : Number(op).toFixed(1) + "%") + '<\/span>'
          + '<span class="fm-aget-max">' + esc(label) + (r.max > 0 ? num(r.max) : "0") + ' 双<\/span><\/div>'
          + r.svg + '<\/div>';
      }
      h += '<div class="fm-aget-axis">' + axis + '<\/div>';
      wrap.innerHTML = h;
    }

    /* ---------- 气泡（§6 浅色玻璃） ---------- */
    var tip = null;
    function tipEl(){
      if(!tip || !tip.parentNode){
        tip = document.createElement("div");
        tip.className = "fm-atrend-tip";
        (document.getElementById("lv1WhLayer") || document.body).appendChild(tip);
      }
      return tip;
    }
    function hideTip(){ if(tip) tip.style.display = "none"; }
    function showTip(sh, w, x, y){
      var r = recOf(sh, w);
      if(isEmpty(r)){ hideTip(); return; }
      var t = tipEl();
      var h = '<div class="at-hd"><b>' + esc(sh.name || sh.sid) + '<\/b><span>' + esc(w) + '<\/span><\/div>';
      for(var k=0;k<5;k++){
        h += '<div class="at-r"><span>' + esc(KEY[k]) + '<\/span><b>' + num(r.bands[k]) + '<i>双<\/i><\/b><\/div>';
      }
      h += '<div class="at-r at-sum"><span>五段合计<\/span><b>' + num(r.total) + '<i>双<\/i><\/b><\/div>';
      t.innerHTML = h;
      t.style.display = "block";
      var tw = t.offsetWidth || 180, th = t.offsetHeight || 120;
      t.style.left = Math.max(8, Math.min(window.innerWidth - tw - 8, x + 14)) + "px";
      t.style.top = Math.max(8, Math.min(window.innerHeight - th - 8, y - th - 12)) + "px";
    }

    /* ---------- 单段走势卡（形态照抄周趋势卡片 v2） ---------- */
    var card = null, cardAnchor = null;
    function closeCard(){
      if(card && card.parentNode) card.parentNode.removeChild(card);
      var cs = document.querySelectorAll(".fm-atrend-ctip"), i;
      for(i=0;i<cs.length;i++){ if(cs[i].parentNode) cs[i].parentNode.removeChild(cs[i]); }
      card = null; cardAnchor = null;
    }
    function smooth(pts){
      var n = pts.length, i, d;
      if(!n) return "";
      d = "M" + pts[0][0].toFixed(1) + " " + pts[0][1].toFixed(1);
      if(n === 1) return d;
      for(i=0;i<n-1;i++){
        var p0 = pts[i>0?i-1:0], p1 = pts[i], p2 = pts[i+1], p3 = pts[i+2<n?i+2:n-1];
        var c1x = p1[0] + (p2[0]-p0[0])*0.16, c1y = p1[1] + (p2[1]-p0[1])*0.16;
        var c2x = p2[0] - (p3[0]-p1[0])*0.16, c2y = p2[1] - (p3[1]-p1[1])*0.16;
        d += " C" + c1x.toFixed(1) + " " + c1y.toFixed(1) + "," + c2x.toFixed(1) + " " + c2y.toFixed(1)
           + "," + p2[0].toFixed(1) + " " + p2[1].toFixed(1);
      }
      return d;
    }
    function curveSVG(series, bad, W, H){
      W = W || 430; H = H || 190;
      var PL = 42, PR = 16, PT = 14, PB = 16, n = series.length, i;
      var max = 0, min = 1e18;
      for(i=0;i<n;i++){ if(series[i].v > max) max = series[i].v; if(series[i].v < min) min = series[i].v; }
      if(max <= 0) max = 1;
      var lo = Math.max(0, min - (max - min) * 0.35);
      if(max - lo < 1) lo = 0;
      var iw = W - PL - PR, ih = H - PT - PB;
      var step = n > 1 ? iw / (n - 1) : 0;
      var color = bad ? "#c8102e" : "#0d3b5c";
      var fill = bad ? "rgba(200,16,46,.09)" : "rgba(13,59,92,.09)";
      var pts = [], d = "", area = "";
      for(i=0;i<n;i++){
        var x = PL + (n > 1 ? i * step : iw / 2);
        var y = PT + ih - ((series[i].v - lo) / (max - lo)) * ih;
        pts.push([x,y]);
      }
      d = smooth(pts);
      area = d + " L" + pts[n-1][0].toFixed(1) + " " + (PT + ih) + " L" + pts[0][0].toFixed(1) + " " + (PT + ih) + " Z";
      var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="库龄段周走势">';
      var g;
      for(g=0;g<=3;g++){
        var gy = PT + ih - ih * g / 3;
        var gv = Math.round(lo + (max - lo) * g / 3);
        s += '<line x1="' + PL + '" y1="' + gy.toFixed(1) + '" x2="' + (W - PR) + '" y2="' + gy.toFixed(1) + '" stroke="#eef2f6" stroke-width="1"/>';
        s += '<text x="' + (PL - 8) + '" y="' + (gy + 4).toFixed(1) + '" text-anchor="end" font-size="10.5" fill="#a9b6c1">' + num(gv) + '<\/text>';
      }
      s += '<path d="' + area + '" fill="' + fill + '"/>';
      s += '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>';
      for(i=0;i<n;i++){
        var last = (i === n - 1);
        s += '<circle cx="' + pts[i][0].toFixed(1) + '" cy="' + pts[i][1].toFixed(1) + '" r="' + (last ? 4.2 : 2.4) + '" fill="' + (last ? color : "#fff") + '" stroke="' + color + '" stroke-width="1.8"/>';
        s += '<circle class="hit" data-i="' + i + '" cx="' + pts[i][0].toFixed(1) + '" cy="' + pts[i][1].toFixed(1) + '" r="10"/>';
      }
      var lx = pts[n-1][0], ly = pts[n-1][1];
      var anchorEnd = (lx > W - 90) ? "end" : "start";
      var tx = (anchorEnd === "end") ? lx - 9 : lx + 10;
      s += '<text x="' + tx.toFixed(1) + '" y="' + (Math.max(PT + 11, ly - 10)).toFixed(1) + '" text-anchor="' + anchorEnd + '" font-size="12.5" font-weight="700" fill="' + color + '">' + num(series[n-1].v) + '<\/text>';
      s += '<\/svg>';
      return s;
    }
    function placeCard(el, anc){
      if(!el) return;
      var W = el.offsetWidth || 460, H = el.offsetHeight || 260, x, y;
      var ar = (anc && anc.getBoundingClientRect) ? anc.getBoundingClientRect() : null;
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
      el.style.left = x + "px";
      el.style.top = y + "px";
    }
    function openCard(sid, bandIdx, anc){
      var sh = shopById(sid);
      if(!sh) return;
      closeCard();
      /* 单段 13 周序列：空周不取、不插值 */
      var series = [], ws = weeks(), i, r;
      for(i=0;i<ws.length;i++){
        r = recOf(sh, ws[i]);
        if(isEmpty(r)) continue;
        series.push({ d: ws[i], v: Number(r.bands[bandIdx]) || 0 });
      }
      var same = true;
      for(i=1;i<series.length;i++){ if(series[i].v !== series[0].v){ same = false; break; } }
      var draw = (series.length >= 2 && !same);      /* 各周完全相同就不画（显示「—」） */

      var h = '<div class="fm-atrend-card">'
        + '<div class="fm-atrend-head"><b>' + esc(sh.name || sh.sid) + '<\/b><span>' + esc(KEY[bandIdx]) + '<\/span>'
        + '<button type="button" class="fm-atrend-x" aria-label="关闭">×<\/button><\/div>';
      if(draw){
        h += '<div class="fm-atrend-chart" id="fmAtrendChart"><\/div>'
          + '<div class="fm-atrend-axis"><span>' + esc(day(series[0].d)) + '<\/span><span>'
          + esc(day(series[series.length-1].d)) + '<\/span><\/div>';
      }else{
        h += '<div class="fm-atrend-empty">—<\/div>';
      }
      h += '<\/div>';

      var holder = document.createElement("div");
      holder.innerHTML = h;
      card = holder.querySelector(".fm-atrend-card");
      var layer = document.getElementById("lv1WhLayer") || document.body;
      layer.appendChild(card);
      cardAnchor = anc || null;
      card.querySelector(".fm-atrend-x").addEventListener("click", function(e){ e.stopPropagation(); closeCard(); });
      if(!draw){ placeCard(card, anc); return; }

      var box = card.querySelector("#fmAtrendChart");
      var cw = box.clientWidth || 430, ch = box.clientHeight || 190;
      box.innerHTML = curveSVG(series, BAD[bandIdx], cw, ch);
      var svg = box.querySelector("svg");
      var ctip = document.createElement("div");
      ctip.className = "fm-atrend-ctip";
      layer.appendChild(ctip);
      if(svg){
        svg.addEventListener("mousemove", function(e){
          var t = e.target;
          if(!t || !t.getAttribute || !t.getAttribute("data-i")) return;
          var idx = Number(t.getAttribute("data-i"));
          if(!series[idx]) return;
          ctip.innerHTML = esc(series[idx].d) + ' &nbsp;<b>' + num(series[idx].v) + '<\/b> 双';
          ctip.style.display = "block";
          ctip.style.left = Math.max(6, Math.min(window.innerWidth - ctip.offsetWidth - 8, e.clientX + 14)) + "px";
          ctip.style.top = Math.max(6, e.clientY - 34) + "px";
        });
        svg.addEventListener("mouseleave", function(){ ctip.style.display = "none"; });
      }
      placeCard(card, anc);
    }

    /* ---------- 事件 ---------- */
    document.addEventListener("mouseover", function(e){
      var t = e.target;
      if(!t || !t.getAttribute) return;
      var i = t.getAttribute("data-i");
      if(i == null) return;
      var sid = t.getAttribute("data-sid"), w = t.getAttribute("data-w");
      if(!sid || !w) return;
      var sh = shopById(sid);
      if(!sh) return;
      showTip(sh, w, e.clientX, e.clientY);
    });
    document.addEventListener("mouseout", function(e){
      var t = e.target;
      if(t && t.getAttribute && t.getAttribute("data-i") != null) hideTip();
    });
    document.addEventListener("click", function(e){
      var t = e.target;
      if(!t || !t.getAttribute) return;
      hideTip();                                   /* 点任何东西都收起气泡 */
      /* 段切换 */
      var tb = t.getAttribute("data-band");
      if(tb != null && t.classList && t.classList.contains("fm-aget-tab")){
        band = Number(tb);
        render();
        return;
      }
      /* 店名 → 切到页面顶部店铺筛选（走原有 chip，不新增流程） */
      var gs = t.getAttribute("data-goto");
      if(gs){
        var chip = host ? host.querySelector(".fm-chip[data-fmsid='" + gs + "']") : null;
        if(chip) chip.click();
        return;
      }
      /* 点色段 → 单段走势卡 */
      if(tb != null && t.getAttribute("data-sid")){
        openCard(t.getAttribute("data-sid"), Number(tb), t);
        return;
      }
    });
    document.addEventListener("keydown", function(e){
      if((e.key === "Escape" || e.keyCode === 27) && card){ closeCard(); }
    });
    if(!window.__atOutsideBound){
      window.__atOutsideBound = 1;
      document.addEventListener("pointerdown", function(e){
        if(card){
          var c = card;
          var t = e.target;
          if(t && t.closest && t.closest(".fm-atrend-card")) return;
          closeCard();
        }
      }, true);
    }
    if(!window.__atFollowBound){
      window.__atFollowBound = 1;
      var follow = function(){
        if(!card) return;
        var a = cardAnchor;
        if(a && a.getBoundingClientRect){
          var r = a.getBoundingClientRect();
          if(r.bottom < 0 || r.top > window.innerHeight){ closeCard(); return; }
          placeCard(card, a);
        }
      };
      window.addEventListener("scroll", follow, true);
      window.addEventListener("resize", follow);
    }

    /* ---------- 挂载：FBA 卡重渲染时自动跟着重画 ---------- */
    if(host){
      if(window.MutationObserver){
        var mo = new MutationObserver(function(){ render(); });
        mo.observe(host, {childList:true});
      }
      render();
    }
    if(document.readyState === "loading"){
      document.addEventListener("DOMContentLoaded", render);
    }else{
      setTimeout(render, 0);
    }
  })();
"""


def crlf(s):
    return s.replace("\r\n", "\n").replace("\n", "\r\n")


def _tighten(text, s, e):
    """删除 [s,e) 后把块前的连续换行归位为 1 个（与插入方式严格互补，保证幂等）。"""
    cnt = 0
    k = s - 1
    while k >= 0 and text[k] == "\n":
        cnt += 1
        k -= 1
    if cnt > 1:
        s = s - (cnt - 1)
    return text[:s] + text[e:]


def drop_block(text, start_mark, end_mark):
    """删除所有 [start_mark, end_mark] 段（含其后紧跟的一个换行），返回 (text, 个数)。"""
    n = 0
    while True:
        s = text.find(start_mark)
        if s < 0:
            break
        e = text.find(end_mark, s)
        assert e > s, "结束标记丢失：" + end_mark
        e += len(end_mark)
        if text[e:e + 1] == "\n":
            e += 1
        text = _tighten(text, s, e)
        n += 1
    return text, n


def drop_script_blocks(text, mark):
    """删除所有包含 mark 的 <script>…</script> 整块（含其后紧跟的一个换行）。"""
    n = 0
    while True:
        s = text.find(mark)
        if s < 0:
            break
        st = text.rfind("<script>", 0, s)
        en = text.find("</script>", s)
        if st < 0 or en < 0:
            break
        e = en + len("</script>")
        if text[e:e + 1] == "\n":
            e += 1
        text = _tighten(text, st, e)
        n += 1
    return text, n


def main():
    if not os.path.exists(DATA):
        print("没有 data/age_trend_shop.json，先跑 build_age_trend.py")
        return 1
    if not os.path.exists(IDX):
        print("没有 index.html")
        return 1
    T = json.load(io.open(DATA, encoding="utf-8"))
    html = io.open(IDX, encoding="utf-8").read()
    NL = chr(10)

    # ---------- 1) 数据：window.__AGETREND ----------
    data_js = "window.__AGETREND = " + json.dumps(T, ensure_ascii=False, separators=(",", ":")) + ";"
    i = html.find("window.__AGETREND = ")
    if i >= 0:
        j = html.find(NL, i)
        html = html[:i] + data_js + html[j:]
        dstat = "replaced"
    else:
        k = html.find("window.__TREND = ")
        assert k > 0, "__TREND 锚点丢失"
        j = html.find(NL, k)
        html = html[:j + 1] + data_js + NL + html[j + 1:]
        dstat = "inserted"

    # ---------- 2) CSS：先清掉所有旧段，再插到 SPU 趋势样式标记之前（幂等） ----------
    css_block = crlf(CSS).strip() + NL
    html, css_n = drop_block(html, CSS_MARK, CSS_END)
    k = html.find(CSS_ANCHOR)
    assert k > 0, "CSS 锚点丢失：" + CSS_ANCHOR
    html = html[:k] + css_block + NL + html[k:]
    cstat = "replaced" if css_n else "inserted"

    # ---------- 3) JS：先清掉所有旧块，再插一份到 </body> 前（幂等） ----------
    js_block = "<script>" + NL + crlf(JS).strip() + NL + "</script>"
    html, js_n = drop_script_blocks(html, JS_MARK)
    j = html.find("</body>")
    assert j > 0, "</body> 锚点丢失"
    html = html[:j] + js_block + NL + html[j:]
    jstat = "replaced" if js_n else "inserted"

    # ---------- 4) 行尾归一（纯 CRLF、无 BOM） ----------
    html = re.sub(r"(?<!\r)\n", "\r\n", html)
    io.open(IDX, "w", encoding="utf-8", newline="").write(html)

    b = open(IDX, "rb").read()
    lf_only = b.count(b"\n") - b.count(b"\r\n")
    print("patched | bytes %d | crlf %d | lf-only %d | bom %s"
          % (len(b), b.count(b"\r\n"), lf_only, b[:3] == b"\xef\xbb\xbf"))
    print("  data:%s css:%s js:%s | __AGETREND:%d | fm-aget-row:%d | openCard:%d"
          % (dstat, cstat, jstat,
             html.count("window.__AGETREND ="), html.count("fm-aget-row"), html.count("function openCard(")))
    # 硬校验：末周五段必须与数据里的 hardCheck 一致（不重算，只核对注入的数据本身）
    bad = [sid for sid, m in (T.get("shopsMeta") or {}).items() if not (m.get("hardCheck") or {}).get("ok")]
    print("  硬校验 hardCheck 全部通过：%s" % ("是" if not bad else "否 " + ",".join(bad)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
