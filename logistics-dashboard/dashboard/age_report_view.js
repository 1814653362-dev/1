/* ---------- 库龄库存报告·共享渲染器（2026-11-03）
   独立 HTML 报告 与 站点页面模块 共用这一份渲染逻辑（同一份数据 → 同一份画面）
   数据源：window.__AGEREP（build_age_report.py 产出 data/age_report_1shop.json）
   视觉：§6 浅色玻璃浮层 / §8 页面卡片白底描边柔影 / 表头与数字同列视觉居中 / 小字 ≥11px
   红线：只显示数字与单位（双/天/%/件）；空区留白；不造数；不做跨店合并 */
(function(){
  var KEY = ["0-90天","91-180天","181-270天","271-365天","365天以上"];
  var BCOL = ["#cfd8e0","#7cb6e6","#f0b429","#ef8080","#c8102e"];
  var JUDGE_ORDER = ["合格","周转偏慢","271天以上占比超线","两项都超"];
  var JUDGE_COLOR = {"合格":"#2f855a","周转偏慢":"#b45309","271天以上占比超线":"#2b6ea3","两项都超":"#c8102e"};
  var TAG_CLS = {"合格":"ar-t-ok","周转偏慢":"ar-t-many","271天以上占比超线":"ar-t-low","两项都超":"ar-t-bad","尾货":"ar-t-tail"};

  function esc(s){
    s = String(s == null ? "" : s);
    return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
            .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
  }
  function fn(v, dec){
    if(v === null || v === undefined || v === "") return "—";
    var n = Number(v);
    if(!isFinite(n)) return "—";
    if(dec) return n.toFixed(dec).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return Math.round(n).toLocaleString("en-US");
  }
  function fd(v){
    if(v === null || v === undefined) return "—";
    var n = Number(v);
    if(!isFinite(n)) return "—";
    if(n >= 999) return "999+";
    return String(Math.round(n));
  }
  function fp(v){
    if(v === null || v === undefined) return "—";
    var n = Number(v);
    if(!isFinite(n)) return "—";
    return n.toFixed(1);
  }

  /* ---------- 判定分布条（纯 SVG） ---------- */
  function svgJudge(cnt){
    var W = 980, H = 96, total = 0, i, x = 0, p = [];
    for(i=0;i<JUDGE_ORDER.length;i++) total += Number(cnt[JUDGE_ORDER[i]]) || 0;
    if(!total) total = 1;
    for(i=0;i<JUDGE_ORDER.length;i++){
      var k = JUDGE_ORDER[i], v = Number(cnt[k]) || 0, w = v / total * W;
      if(w > 0){
        p.push('<rect x="'+x.toFixed(1)+'" y="18" width="'+w.toFixed(1)+'" height="34" fill="'+JUDGE_COLOR[k]+'"/>');
        p.push('<text x="'+(x + w/2).toFixed(1)+'" y="40" font-size="11" fill="#fff" text-anchor="middle">'+v+'</text>');
      }
      x += w;
    }
    for(i=0;i<JUDGE_ORDER.length;i++){
      var k2 = JUDGE_ORDER[i], lx = 14 + i * 150;
      p.push('<rect x="'+lx+'" y="66" width="10" height="10" fill="'+JUDGE_COLOR[k2]+'"/>');
      p.push('<text x="'+(lx+16)+'" y="75" font-size="11" fill="#41505f">'+k2+' '+(Number(cnt[k2])||0)+' 个</text>');
    }
    return '<svg viewBox="0 0 '+W+' '+H+'" width="100%" height="'+H+'" role="img">'+p.join("")+'</svg>';
  }

  /* ---------- 店级 13 周五段堆叠柱（纯 SVG） ---------- */
  function svgWeek(series){
    if(!series || !series.length) return "";
    var W = 980, H = 260, ml = 46, mr = 14, mt = 14, mb = 34;
    var iw = W - ml - mr, ih = H - mt - mb, n = series.length, i, k;
    var totals = [], mx = 0;
    for(i=0;i<n;i++){
      var b = series[i].bands || [];
      var t = 0;
      for(k=0;k<5;k++) t += Number(b[k]) || 0;
      totals.push(t);
      if(t > mx) mx = t;
    }
    if(!mx) mx = 1;
    var bw = iw / Math.max(n,1), p = [];
    for(i=0;i<n;i++){
      var b2 = series[i].bands;
      if(!b2) continue;
      var x0 = ml + i*bw + bw*0.18, w = bw*0.64, y = mt + ih;
      for(k=4;k>=0;k--){
        var hh = (Number(b2[k])||0) / mx * ih;
        y -= hh;
        p.push('<rect x="'+x0.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+w.toFixed(1)+'" height="'+hh.toFixed(1)+'" fill="'+BCOL[k]+'"/>');
      }
      p.push('<text x="'+(x0+w/2).toFixed(1)+'" y="'+(mt+ih+14)+'" font-size="11" fill="#8a97a5" text-anchor="middle">'+esc((series[i].d||"").slice(5))+'</text>');
    }
    for(k=0;k<5;k++){
      var yy = mt + ih - ih*k/4;
      p.push('<line x1="'+ml+'" y1="'+yy.toFixed(1)+'" x2="'+(ml+iw)+'" y2="'+yy.toFixed(1)+'" stroke="#e8edf2"/>');
      p.push('<text x="'+(ml-6)+'" y="'+(yy+3).toFixed(1)+'" font-size="11" fill="#8a97a5" text-anchor="end">'+fn(mx*k/4)+'</text>');
    }
    var leg = "", q;
    for(k=0;k<5;k++) leg += '<span class="ar-legend"><i style="background:'+BCOL[k]+'"></i>'+KEY[k]+'</span>';
    return '<svg viewBox="0 0 '+W+' '+H+'" width="100%" height="'+H+'" role="img">'+p.join("")+'</svg>'
         + '<div class="ar-legend">'+leg+'</div>';
  }

  /* ---------- Top SPU：库龄合计条 + 日均动销细条（纯 SVG） ---------- */
  function svgSpuBars(rows, topn){
    topn = topn || 15;
    var list = [];
    for(var i=0;i<rows.length;i++) if(rows[i].stock > 0) list.push(rows[i]);
    list.sort(function(a,b){ return b.stock - a.stock; });
    list = list.slice(0, topn);
    if(!list.length) return "";
    var W = 980, rh = 22, mt = 8, ml = 150, ih = rh*list.length, H = mt+ih+26;
    var mr = 150;                       /* 右侧留标签位：条末的「双数 · 日均」不越界 */
    var iw = W - ml - mr, mx = 0, mxm = 0, i;
    for(i=0;i<list.length;i++){
      if(list[i].stock > mx) mx = list[i].stock;
      var d = Math.max(Number(list[i].daily30)||0, 0);
      if(d > mxm) mxm = d;
    }
    if(!mx) mx = 1;
    if(!mxm) mxm = 1;
    var p = [];
    for(i=0;i<list.length;i++){
      var r = list[i], y = mt + i*rh, w = r.stock/mx*iw;
      p.push('<rect x="'+ml+'" y="'+(y+3).toFixed(1)+'" width="'+w.toFixed(1)+'" height="11" rx="2" fill="#c3d4e2"/>');
      var wd = Math.max(Number(r.daily30)||0,0)/mxm*iw;
      if(wd > 0.4){
        p.push('<rect x="'+ml+'" y="'+(y+15).toFixed(1)+'" width="'+wd.toFixed(1)+'" height="4" fill="#c8102e"/>');
      }
      p.push('<text x="'+(ml-8)+'" y="'+(y+12).toFixed(1)+'" font-size="11" fill="#41505f" text-anchor="end">'+esc(r.spu)+'</text>');
      var dl = Number(r.daily30)||0;
      p.push('<text x="'+(ml+w+6).toFixed(1)+'" y="'+(y+12).toFixed(1)+'" font-size="11" fill="#41505f">'+fn(r.stock)+' 双 · 日均 '+(dl > 0 ? fp(dl)+' 双/天' : "—")+'</text>');
    }
    p.push('<text x="'+ml+'" y="'+(H-6)+'" font-size="11" fill="#8a97a5">条：库龄五段合计（双）　细红条：日均动销（双/天）</text>');
    return '<svg viewBox="0 0 '+W+' '+H+'" width="100%" height="'+H+'" role="img">'+p.join("")+'</svg>';
  }

  /* ---------- 库龄变化显示（双数 + 百分比） ---------- */
  function chg(c){
    if(!c) return "无数据";
    var s = (c.total > 0 ? "+" : "") + fn(c.total) + " 双";
    if(c.pct !== null && c.pct !== undefined) s += " (" + (c.pct > 0 ? "+" : "") + fp(c.pct) + "%)";
    return s;
  }

  /* ---------- 判定标签：尾货档 / 四类判定 / 不参与判定 ---------- */
  function judgeCell(r){
    if(r.tail) return '<span class="ar-tag ar-t-tail">尾货</span>';
    if(r.judge) return '<span class="ar-tag '+(TAG_CLS[r.judge]||"")+'">'+esc(r.judge)+'</span>';
    return "—";
  }
  /* ---------- 271天以上占比（分母＝该款库龄五段合计） ---------- */
  function oldCell(r){
    if(r.oldRatio === null || r.oldRatio === undefined) return "—";
    return fp(r.oldRatio) + "%";
  }

  /* ---------- 主体渲染 ---------- */
  function renderBody(D, opt){
    opt = opt || {};
    var k = D.kpi, rows = D.rows || [], i, r, h = [];
    var showName = opt.showName !== false;

    h.push('<div class="ar-kpis">');
    function kpi(v, unit, label, warn){
      h.push('<div class="ar-kpi'+(warn ? " warn" : "")+'"><b>'+v+(unit ? '<i>'+unit+'</i>' : "")+'</b><span>'+esc(label)+'</span></div>');
    }
    kpi(fn(k.totalStock),"双","总库存");
    kpi(fn(k.avail),"双","FBA 可售");
    kpi(fn(k.ageStock),"双","库龄五段合计");
    kpi(fn(k.move30),"双","近30天动销");
    kpi(fp(k.daily30),"双/天","30天日均");
    kpi(fp(k.daily90),"双/天","90天日均");
    kpi(fd(k.turnDays),"天","周转天数");
    kpi(fp(k.turns),"次","周转次数");
    kpi(String(k.riskCount),"个","断货风险 SPU", k.riskCount > 0);
    kpi(String(k.spuCount),"个","在库 SPU");
    kpi(fn(k.badStock),"双","不合格 SPU 库存", k.badCount > 0);
    h.push('</div>');

    h.push('<h2>一、库龄结构与判定分布</h2>');
    h.push('<div class="ar-card">');
    h.push('<h3>店级 13 周五段库龄结构（双）</h3>');
    h.push(svgWeek((D.shopTrend || {}).series));
    h.push('<h3>库存判定分布</h3>');
    h.push(svgJudge(k.judgeCounts || {}));
    h.push('<ul class="ar-notes">');
    h.push('<li>271天以上 '+fn(k.oldQty)+' 双 ｜ 占库龄五段合计 '+fp(k.oldRatio)+'%（'+fn(k.ageStock)+' 双）</li>');
    h.push('<li>近30天 出库 '+fn(k.ship30)+' 双 － 退货 '+fn(k.ret30)+' 双 ＝ 动销 '+fn(k.move30)+' 双</li>');
    h.push('<li>近90天 出库 '+fn(k.ship90)+' 双 － 退货 '+fn(k.ret90)+' 双 ＝ 动销 '+fn(k.move90)+' 双</li>');
    h.push('<li>合格 SPU '+k.okCount+' 个（库存 '+fn(k.okStock)+' 双 / 可售 '+fn(k.okAvail)+' 双）｜ 不合格 SPU '+k.badCount+' 个（库存 '+fn(k.badStock)+' 双 / 可售 '+fn(k.badAvail)+' 双）</li>');
    h.push('<li>参与判定 '+k.judgedCount+' 个 ｜ 尾货（总库存 &lt; 20 双）'+k.tailCount+' 个（库存 '+fn(k.tailStock)+' 双）｜ 无库龄库存 '+k.noAgeCount+' 个（不参与判定）</li>');
    h.push('</ul></div>');

    h.push('<h2>二、SPU 库存 Top 15（库龄合计 vs 日均动销）</h2>');
    h.push('<div class="ar-card">'+svgSpuBars(rows, 15)+'</div>');

    h.push('<h2>三、SPU 明细</h2>');
    h.push('<div class="ar-tblwrap"><table><thead><tr>');
    h.push('<th class="l">SPU</th><th class="l">品名</th><th>可售</th><th>总库存</th>');
    for(i=0;i<KEY.length;i++) h.push('<th>'+KEY[i]+'</th>');
    h.push('<th>库龄合计</th><th>271天以上占比</th><th>30天动销</th><th>30天日均（双/天）</th><th>90天日均（双/天）</th><th>趋势</th>');
    h.push('<th>周转天数</th><th>周转次数</th><th>可售撑天数</th><th>在途</th><th>到货日</th>');
    h.push('<th>库龄变化1周</th><th>库龄变化2周</th><th>判定</th><th>断货</th><th class="l">建议</th>');
    h.push('</tr></thead><tbody>');
    for(i=0;i<rows.length;i++){
      r = rows[i];
      h.push('<tr><td class="l"><b>'+esc(r.spu)+'</b></td><td class="l">'+esc((r.name||"").slice(0,22))+'</td>');
      h.push('<td>'+fn(r.avail)+'</td><td>'+fn(r.total)+'</td>');
      for(var j=0;j<5;j++) h.push('<td>'+fn(r.bands[j])+'</td>');
      h.push('<td><b>'+fn(r.stock)+'</b></td>');
      h.push('<td>'+oldCell(r)+'</td>');
      h.push('<td>'+fn(r.move30)+'</td><td>'+fp(r.daily30)+'</td><td>'+fp(r.daily90)+'</td>');
      h.push('<td>'+esc(r.trend||"—")+'</td>');
      h.push('<td>'+fd(r.turnDays)+'</td>');
      h.push('<td>'+(r.turns === null || r.turns === undefined ? "—" : fp(r.turns))+'</td>');
      h.push('<td>'+fd(r.coverDays)+'</td>');
      h.push('<td>'+(r.transitQty ? fn(r.transitQty) : "—")+'</td>');
      h.push('<td>'+(r.transitArrive ? esc(r.transitArrive)+(r.transitArriveHow === "实际" ? "" : "（估）") : "—")+'</td>');
      h.push('<td class="chg">'+esc(chg(r.ageChange1w))+'</td>');
      h.push('<td class="chg">'+esc(chg(r.ageChange2w))+'</td>');
      h.push('<td>'+judgeCell(r)+'</td>');
      h.push('<td>'+(r.risk ? "断货" : "—")+'</td>');
      h.push('<td class="adv">'+esc(r.advice)+'</td>');
      h.push('</tr>');
    }
    h.push('</tbody></table></div>');
    h.push('<div class="ar-tip">共 '+rows.length+' 个在库 SPU</div>');

    /* 需关注 */
    var focus = [];
    for(i=0;i<rows.length;i++){
      r = rows[i];
      if(r.risk || r.tail || (r.judge && r.judge !== "合格") || r.transitOverdue) focus.push(r);
    }
    focus.sort(function(a,b){ return (a.risk ? 0 : 1) - (b.risk ? 0 : 1) || b.stock - a.stock; });
    h.push('<h2>四、需关注 SPU</h2>');
    h.push('<div class="ar-tblwrap"><table><thead><tr>');
    h.push('<th class="l">SPU</th><th>判定</th><th>断货</th><th>可售</th><th>总库存</th><th>库龄合计</th><th>30天动销</th>');
    h.push('<th>30天日均（双/天）</th><th>90天日均（双/天）</th><th>趋势</th><th>可售撑天数</th><th>在途</th><th>到货日</th><th class="l">建议</th>');
    h.push('</tr></thead><tbody>');
    for(i=0;i<focus.length;i++){
      r = focus[i];
      h.push('<tr><td class="l"><b>'+esc(r.spu)+'</b></td>');
      h.push('<td>'+judgeCell(r)+'</td>');
      h.push('<td>'+(r.risk ? "断货" : "—")+'</td>');
      h.push('<td>'+fn(r.avail)+'</td>');
      h.push('<td>'+(Number(r.total) <= 12 ? fn(r.total)+' <span class="ar-tag ar-t-tail">≤12 双</span>' : fn(r.total))+'</td>');
      h.push('<td>'+fn(r.stock)+'</td><td>'+fn(r.move30)+'</td>');
      h.push('<td>'+fp(r.daily30)+'</td><td>'+fp(r.daily90)+'</td><td>'+esc(r.trend||"—")+'</td>');
      h.push('<td>'+fd(r.coverDays)+'</td>');
      h.push('<td>'+(r.transitQty ? fn(r.transitQty) : "—")+'</td>');
      h.push('<td>'+(r.transitArrive ? esc(r.transitArrive) : "—")+'</td>');
      h.push('<td class="adv">'+esc(r.advice)+'</td>');
      h.push('</tr>');
    }
    if(!focus.length) h.push('<tr><td class="l" colspan="14">无</td></tr>');
    h.push('</tbody></table></div>');

    /* 合格指标块：只放判定数字与单位（各项定义见 data/age_report_1shop.json 的 criteria.def） */
    var c = D.criteria || {};
    var limT = c.turnLimit || 90, limO = c.oldLimit || 5;
    var jc = k.judgeCounts || {};
    h.push('<h2>五、库龄周转的合格指标</h2>');
    h.push('<div class="ar-tblwrap ar-critwrap"><table class="ar-crit"><thead><tr>');
    h.push('<th class="l">指标</th><th>合格线</th><th>本店当前</th></tr></thead><tbody>');
    h.push('<tr><td class="l">周转天数</td><td>≤ '+limT+' 天</td><td><b>'+fd(k.turnDays)+' 天</b></td></tr>');
    h.push('<tr><td class="l">271天以上占比（分母 库龄五段合计 '+fn(k.ageStock)+' 双）</td><td>&lt; '+limO+'%</td><td><b>'+fp(k.oldRatio)+'%</b></td></tr>');
    h.push('<tr><td class="l">271天以上双数</td><td>—</td><td>'+fn(k.oldQty)+' 双</td></tr>');
    h.push('<tr><td class="l">合格 SPU</td><td>—</td><td>'+(jc["合格"]||0)+' 个</td></tr>');
    h.push('<tr><td class="l">周转偏慢 SPU</td><td>—</td><td>'+(jc["周转偏慢"]||0)+' 个</td></tr>');
    h.push('<tr><td class="l">271天以上占比超线 SPU</td><td>—</td><td>'+(jc["271天以上占比超线"]||0)+' 个</td></tr>');
    h.push('<tr><td class="l">两项都超 SPU</td><td>—</td><td>'+(jc["两项都超"]||0)+' 个</td></tr>');
    h.push('<tr><td class="l">参与判定 SPU</td><td>—</td><td>'+k.judgedCount+' 个</td></tr>');
    h.push('<tr><td class="l">尾货（总库存 &lt; 20 双）</td><td>—</td><td>'+k.tailCount+' 个（库存 '+fn(k.tailStock)+' 双）</td></tr>');
    h.push('<tr><td class="l">无库龄库存 · 不参与判定</td><td>—</td><td>'+k.noAgeCount+' 个</td></tr>');
    h.push('<tr><td class="l">断货风险 SPU</td><td>—</td><td>'+k.riskCount+' 个</td></tr>');
    h.push('<tr><td class="l">在库 SPU</td><td>—</td><td>'+k.spuCount+' 个</td></tr>');
    h.push('<tr><td class="l">不合格 SPU 库存</td><td>—</td><td>'+fn(k.badStock)+' 双（占库龄合计 '+fp(k.badStockRatio)+'%）</td></tr>');
    h.push('<tr><td class="l">在途</td><td>—</td><td>'+fn(k.transitFbaCount)+' 票 / '+fn(k.transitQty)+' 双</td></tr>');
    h.push('<tr><td class="l">在途跨店均分（估）</td><td>—</td><td>'+fn(k.transitSplitQty)+' 双</td></tr>');
    h.push('<tr><td class="l">到货日推算已过期货件</td><td>—</td><td>'+k.transitOverdueShip+' 票</td></tr>');
    h.push('</tbody></table></div>');
    return h.join("");
  }

  window.AREP = {
    renderBody: renderBody,
    render: function(el, D, opt){
      if(!el || !D) return;
      var h = "";
      if((opt||{}).showHead !== false){
        h += '<h1>'+esc(D.name||"")+' · 库龄库存报告</h1>';
        h += '<div class="ar-meta">数据时点 '+esc(D.today||"—")+' ｜ 库存快照 '+esc(D.snapshotUpdatedAt||"—")
           + ' ｜ 动销窗口 近30天 '+esc((D.win30||[])[0]||"—")+' ~ '+esc((D.win30||[])[1]||"—")
           + '、近90天 '+esc((D.win90||[])[0]||"—")+' ~ '+esc((D.win90||[])[1]||"—")
           + '（分类账最后一天 '+esc(D.ledgerAsOf||"—")+'）｜ 在途 '+((D.kpi||{}).transitFbaCount||0)+' 票 / '
           + fn((D.kpi||{}).transitQty)+' 双</div>';
      }
      h += renderBody(D, opt);
      el.innerHTML = h;
    },
    fmt: {n: fn, d: fd, p: fp, esc: esc}
  };
})();
