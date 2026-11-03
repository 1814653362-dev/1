# -*- coding: utf-8 -*-
"""库龄库存报告 · 站点页面模块（FBA 店铺 A / sid=00001）

数据：data/age_report_1shop.view.json → window.__AGEREP（build_age_report.py 产出）
渲染：age_report_view.js（共享渲染器，与独立 HTML 报告同一份逻辑）
样式：age_report_view.css（共享样式）

形态（2026-11-03 主管-主管口径）：
  · 位置：仓库 FBA 分店卡里，库龄条正下方 = 店级库龄结构趋势模块的正下方（同位置体系）
  · **只做 1 店**：报告就是 FBA 店铺 A 这一家，不做多店切换、不出跨店合计
  · 入口块：标题 + 4 个关键数字 + 「打开报告」按钮；点开是浅色玻璃弹窗（§6）出完整报告
  · 弹窗内是独立 HTML 报告的同一份内容（同一份数据 + 同一个渲染器）
  · 样式照现有规范：§6 浅色玻璃浮层 / §8 页面卡片白底描边柔影 / 表头与数字同列视觉居中 / 小字 ≥11px
  · 只显示数字与单位（双/天/%/件），不写算法说明段落

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
VIEW = os.path.join(BASE, "data", "age_report_1shop.view.json")
CSS_SRC = os.path.join(BASE, "age_report_view.css")
JS_SRC = os.path.join(BASE, "age_report_view.js")

SID = "00001"
CSS_MARK = "/* ===== 库龄库存报告·样式（2026-11-03） ===== */"
CSS_END = "/* ===== 库龄库存报告·样式 END ===== */"
JS_MARK = "/* ===== 库龄库存报告·交互（2026-11-03） ===== */"
CSS_ANCHOR = "/* ===== 店级库龄结构趋势·样式（2026-11-02） ===== */"


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


# ------------------------------------------------------------------ 页面 JS
JS = r"""/* ===== 库龄库存报告·交互（2026-11-03） ===== */
  (function(){
    var A = window.__AGEREP || null;
    var host = document.getElementById("whFbaByShop");
    var SID = "00001";
    var modal = null;

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

    /* ---------- 入口块（页面内） ---------- */
    function entryHTML(){
      if(!A || !A.kpi) return "";
      var k = A.kpi;
      var h = '<div class="ar-entry">';
      h += '<div class="ar-entry-hd"><b>库龄库存报告</b><span>' + esc(A.name || "") + '</span></div>';
      h += '<div class="ar-entry-kpis">';
      h += '<div><b>' + fn(k.totalStock) + '<i>双</i></b><span>总库存</span></div>';
      h += '<div><b>' + fn(k.move30) + '<i>双</i></b><span>近30天动销</span></div>';
      h += '<div><b>' + fd(k.turnDays) + '<i>天</i></b><span>周转天数</span></div>';
      h += '<div><b>' + fn(k.badCount) + '<i>个</i></b><span>不合格 SPU</span></div>';
      h += '</div>';
      h += '<button type="button" class="ar-open-btn" data-ar-open="1">打开报告</button>';
      h += '</div>';
      return h;
    }

    /* ---------- 弹窗（§6 浅色玻璃） ---------- */
    function closeModal(){
      if(modal && modal.parentNode) modal.parentNode.removeChild(modal);
      modal = null;
    }
    function openModal(){
      if(!A || !window.AREP) return;
      closeModal();
      var holder = document.createElement("div");
      holder.innerHTML = '<div class="ar-modal"><div class="ar-modal-hd"><b>库龄库存报告</b>'
        + '<span>' + esc(A.name || "") + '</span>'
        + '<button type="button" class="ar-modal-x" aria-label="关闭">×</button></div>'
        + '<div class="ar-wrap" id="arModalBody"></div></div>';
      modal = holder.querySelector(".ar-modal");
      var layer = document.getElementById("lv1WhLayer") || document.body;
      layer.appendChild(modal);
      window.AREP.render(modal.querySelector("#arModalBody"), A, {showHead:false});
      modal.querySelector(".ar-modal-x").addEventListener("click", function(e){
        e.stopPropagation(); closeModal();
      });
    }

    /* ---------- 挂载：FBA 卡重渲染时自动跟着重画 ----------
       注意：insertBefore 本身也是 DOM 变更 → 会再次触发 MutationObserver，
       所以「位置锚定」必须在比对 sig 之后做，否则自己触发自己（死循环）。 */
    function render(){
      if(!A || !host) return;
      var chip = host.querySelector(".fm-chip.on[data-fmsid]");
      var sid = chip ? chip.getAttribute("data-fmsid") : "all";
      var wrap = host.querySelector("#fmAgeReport");
      /* 只做 1 店：不是 FBA 店铺 A 就不出这个模块 */
      if(String(sid) !== SID){
        if(wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap);
        return;
      }
      /* 位置：库龄条正下方 = 店级库龄结构趋势模块（#fmAgeTrend）的正下方 */
      var trend = host.querySelector("#fmAgeTrend");
      var anchor = trend || host.querySelector(".fm-segrow");
      var sig = String(sid);
      /* 已在正确位置且内容已是最新 → 什么都不做（insertBefore 也会触发观察器） */
      if(wrap && wrap.getAttribute("data-sig") === sig){
        if(!anchor || wrap.previousSibling === anchor) return;
      }
      if(!wrap){
        wrap = document.createElement("div");
        wrap.id = "fmAgeReport";
      }
      if(anchor && anchor.parentNode) anchor.parentNode.insertBefore(wrap, anchor.nextSibling);
      else host.appendChild(wrap);
      wrap.setAttribute("data-sig", sig);
      wrap.innerHTML = entryHTML();
    }

    /* ---------- 事件 ---------- */
    document.addEventListener("click", function(e){
      var t = e.target;
      if(!t || !t.getAttribute) return;
      if(t.getAttribute("data-ar-open") === "1"){
        e.stopPropagation();
        openModal();
        return;
      }
      if(t.closest && t.closest(".ar-modal-x")){ closeModal(); return; }
    });
    document.addEventListener("keydown", function(e){
      if((e.key === "Escape" || e.keyCode === 27) && modal) closeModal();
    });
    if(!window.__arModalBound){
      window.__arModalBound = 1;
      document.addEventListener("pointerdown", function(e){
        if(!modal) return;
        var t = e.target;
        if(t && t.closest && t.closest(".ar-modal")) return;
        closeModal();
      }, true);
    }

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


def main():
    if not os.path.exists(VIEW):
        print("没有 data/age_report_1shop.view.json，先跑 build_age_report.py")
        return 1
    if not os.path.exists(IDX):
        print("没有 index.html")
        return 1
    if not (os.path.exists(CSS_SRC) and os.path.exists(JS_SRC)):
        print("缺 age_report_view.css / age_report_view.js")
        return 1

    V = json.load(io.open(VIEW, encoding="utf-8"))
    css_raw = io.open(CSS_SRC, encoding="utf-8").read()
    js_raw = io.open(JS_SRC, encoding="utf-8").read()
    html = io.open(IDX, encoding="utf-8").read()
    NL = chr(10)

    # ---------- 1) 数据：window.__AGEREP ----------
    data_js = "window.__AGEREP=" + json.dumps(V, ensure_ascii=False, separators=(",", ":")) + ";"
    i = html.find("window.__AGEREP=")
    if i >= 0:
        j = html.find(NL, i)
        html = html[:i] + data_js + html[j:]
        dstat = "replaced"
    else:
        k = html.find("window.__AGETREND = ")
        assert k > 0, "__AGETREND 锚点丢失"
        j = html.find(NL, k)
        html = html[:j + 1] + data_js + NL + html[j + 1:]
        dstat = "inserted"

    # ---------- 2) CSS：先清掉所有旧段，再插到店级趋势样式标记之前（幂等） ----------
    css_block = CSS_MARK + NL + crlf(css_raw).strip() + NL + CSS_END + NL
    html, css_n = drop_block(html, CSS_MARK, CSS_END)
    k = html.find(CSS_ANCHOR)
    assert k > 0, "CSS 锚点丢失：" + CSS_ANCHOR
    html = html[:k] + css_block + html[k:]
    cstat = "replaced" if css_n else "inserted"

    # ---------- 3) JS：共享渲染器 + 页面交互，同一个 <script> 块（保证整块可幂等替换） ----------
    js_block = ("<script>" + NL + crlf(js_raw).strip() + NL + NL + JS.strip() + NL + "</script>")
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
    print("  data:%s css:%s js:%s | __AGEREP:%d | fmAgeReport:%d | ar-open-btn:%d"
          % (dstat, cstat, jstat,
             html.count("window.__AGEREP="), html.count("fmAgeReport"), html.count("ar-open-btn")))
    print("  共享渲染器 window.AREP 定义：%d 处；共享样式 .ar-wrap：%d 处"
          % (html.count("window.AREP ="), html.count(".ar-wrap")))
    # 数据自检：注入的必须是 1 店
    ok = (str(V.get("sid")) == SID) and len(V.get("rows") or []) == len(
        [r for r in (V.get("rows") or []) if r.get("stock", 0) > 0 or r.get("avail", 0) > 0])
    print("  1 店自检 sid=%s SPU=%d：%s"
          % (V.get("sid"), len(V.get("rows") or []), "通过" if ok else "不通过"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
