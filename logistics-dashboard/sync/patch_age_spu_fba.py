# -*- coding: utf-8 -*-
"""FBA 库存卡：库龄 × 款号 模块
顶部 = 原版库龄条（fm-bar + fm-segrow 数字行，用 paintAgeBar 绘制）
下方 = 抓手条 + 5 列图例 + 款号级交叉矩阵（含运营列）
注入 window.__AGESPU + CSS + renderAgeSpu，幂等可重复运行
"""
import io, json, os, re, sys, importlib.util
sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(BASE, "shandi-v5", "index.html")

spec = importlib.util.spec_from_file_location("bas", os.path.join(BASE, "build_age_spu.py"))
bas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bas)
PAYLOAD = bas.compute()

CSS = """
/* ===== 库龄 × 款号 矩阵（FBA 库存卡 2026-10-29） ===== */
#lv1WhLayer .fm-asp-tools{display:flex;align-items:center;gap:12px;margin-top:4px;flex-wrap:wrap;}
#lv1WhLayer .fm-asp-min{display:flex;align-items:center;gap:6px;font-size:12px;color:#5c6b7a;}
#lv1WhLayer .fm-asp-min button{height:28px;padding:0 11px;border-radius:14px;border:1px solid #e6ebf0;background:#fff;
  color:#5c6b7a;font-size:12px;font-family:inherit;cursor:pointer;}
#lv1WhLayer .fm-asp-min button.on{border-color:#0d3b5c;background:#0d3b5c;color:#fff;font-weight:600;}
#lv1WhLayer .fm-asp-q{height:30px;width:190px;border-radius:8px;border:1px solid #e6ebf0;background:#fff;color:#16212e;
  padding:0 11px;font-size:12.5px;font-family:inherit;}
#lv1WhLayer .fm-asp-q:focus{outline:none;border-color:#2b6ea3;}
#lv1WhLayer .fm-asp-cnt{font-size:12px;color:#97a4b0;font-variant-numeric:tabular-nums;}
#lv1WhLayer .fm-asp-wrap{margin-top:10px;border:1px solid #e6ebf0;border-radius:12px;overflow:hidden;}
#lv1WhLayer .fm-asp-scroll{max-height:420px;overflow:auto;}
#lv1WhLayer .fm-asp-tbl{width:100%;border-collapse:collapse;font-size:12.5px;}
#lv1WhLayer .fm-asp-tbl th{position:sticky;top:0;background:#f7f9fb;text-align:right;font-weight:500;color:#97a4b0;
  padding:7px 12px;border-bottom:1px solid #e6ebf0;font-size:11.5px;cursor:pointer;white-space:nowrap;z-index:1;vertical-align:bottom;}
#lv1WhLayer .fm-asp-tbl th.l{text-align:left;}
#lv1WhLayer .fm-asp-tbl th.on{color:#b45309;box-shadow:inset 0 -2px 0 #b45309;}
#lv1WhLayer .fm-asp-tbl th .sn{display:block;font-weight:600;font-size:11.5px;line-height:1.3;}
#lv1WhLayer .fm-asp-tbl th .sc{display:block;font-weight:400;font-size:10.5px;color:#97a4b0;margin-top:1px;letter-spacing:0;}
#lv1WhLayer .fm-asp-tbl td{padding:7px 12px;border-bottom:1px solid #f1f5f9;text-align:right;color:#5c6b7a;font-variant-numeric:tabular-nums;}
#lv1WhLayer .fm-asp-tbl td.l{text-align:left;}
#lv1WhLayer .fm-asp-tbl tr:hover td{background:#f8fafc;}
#lv1WhLayer .fm-asp-tbl td.spu{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#16212e;font-size:12px;}
#lv1WhLayer .fm-asp-tbl td.old{color:#c8102e;font-weight:600;border-left:1px solid #f0d4d8;}
#lv1WhLayer .fm-asp-tbl tr.on td{background:#f2f8fd;}
#lv1WhLayer .fm-asp-empty{padding:26px;text-align:center;color:#97a4b0;font-size:12.5px;}
"""

JS = r"""
  /* ===== 库龄 × 款号 矩阵（FBA 库存卡 2026-10-29） ===== */
  var AGESP = { q: "", seg: null, sort: "old", min: 10 };
  var ASP_COL = ["#cfd8e0", "#7cb6e6", "#f0b429", "#ef8080", "#c8102e"];
  var ASP_OLD = [3, 4];

  function aspN(n){ return (Math.round(Number(n || 0) * 10) / 10).toLocaleString("en-US"); }
  function aspHexa(hex, a){
    var n = parseInt(hex.slice(1), 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a.toFixed(3) + ")";
  }

  function aspMatrix(scope){
    var keys = scope.keys, rows = scope.rows, B = scope.buckets, i, j;
    var list = [], hidden = 0;
    for(i=0;i<rows.length;i++){
      var r = rows[i];
      if(AGESP.q && r.spu.toLowerCase().indexOf(AGESP.q.toLowerCase()) < 0) continue;
      if(AGESP.seg !== null && !(r.cells[AGESP.seg] > 0)) continue;
      if(AGESP.min > 0 && r.total < AGESP.min && !(r.old > 0)){ hidden++; continue; }
      list.push(r);
    }
    var sk = AGESP.sort;
    list.sort(function(a, b){
      if(sk === "spu") return a.spu < b.spu ? -1 : 1;
      if(sk.indexOf("c") === 0) return (b.cells[+sk.slice(1)] || 0) - (a.cells[+sk.slice(1)] || 0);
      return (b[sk] || 0) - (a[sk] || 0);
    });
    var h = '<div class="fm-asp-wrap"><div class="fm-asp-scroll"><table class="fm-asp-tbl"><thead><tr>';
    h += '<th class="l" data-k="spu">款号 SPU</th>';
    for(i=0;i<keys.length;i++){
      var on = (sk === "c" + i) ? " on" : "";
      h += '<th data-k="c' + i + '" class="' + on + '"><span class="sn">' + keys[i] + '</span>'
        + '<span class="sc">' + B[i].spuCount + ' 款号</span></th>';
    }
    h += '<th data-k="old" class="' + (sk === "old" ? "on" : "") + '">271天以上</th>';
    h += '<th data-k="avail" class="' + (sk === "avail" ? "on" : "") + '">可售</th>';
    h += '<th data-k="total" class="' + (sk === "total" ? "on" : "") + '">总双数</th></tr></thead><tbody>';
    if(!list.length){
      h += '<tr><td class="l" colspan="' + (keys.length + 4) + '" style="text-align:center;padding:24px;color:#97a4b0;">没有匹配的款号</td></tr>';
    }
    for(i=0;i<list.length && i<300;i++){
      var rr = list[i];
      h += '<tr><td class="l spu">' + esc(rr.spu) + '</td>';
      for(j=0;j<keys.length;j++){
        var v = rr.cells[j] || 0;
        h += '<td>' + (v > 0 ? aspN(v) : "·") + '</td>';
      }
      h += '<td class="old">' + (rr.old > 0 ? aspN(rr.old) : "·") + '</td>';
      h += '<td>' + aspN(rr.avail) + '</td>';
      h += '<td>' + aspN(rr.total) + '</td></tr>';
    }
    h += '</tbody></table></div></div>';
    return { html: h, n: list.length, hidden: hidden };
  }

  function renderAgeSpu(el, sid){
    var box = el.querySelector("#fmAgeSpu");
    if(!box) return;
    var P = window.__AGESPU;
    var scope = (P && P.shops) ? P.shops[String(sid)] : null;
    if(!scope){ box.innerHTML = '<div class="fm-asp-empty">暂无库龄数据</div>'; return; }
    AGESP.q = ""; AGESP.seg = null; AGESP.sort = "old"; AGESP.min = 10;
    var B = scope.buckets, keys = scope.keys, i, j;
    var total = 0;
    for(i=0;i<B.length;i++) total += B[i].pairs;
    if(!total){ box.innerHTML = '<div class="fm-asp-empty">暂无库龄数据</div>'; return; }

    var h = '';

    /* 抓手条已移除（用户 2026-10-29 定：整块删掉，表格直接顶上去） */

    h += '<div class="fm-asp-tools"><input class="fm-asp-q" type="text" placeholder="搜索款号 SPU">' +
      '<div class="fm-asp-min"><span>小额款号</span>' +
      '<button data-m="10" class="on">≥ 10 双</button><button data-m="0">全部</button></div>' +
      '<span class="fm-asp-cnt"></span></div><div class="fm-asp-mx"></div>';
    box.innerHTML = h;

    var mxBox = box.querySelector(".fm-asp-mx");
    var cnt = box.querySelector(".fm-asp-cnt");
    function refresh(){
      var res = aspMatrix(scope);
      mxBox.innerHTML = res.html;
      cnt.textContent = "显示 " + res.n + " / " + scope.rows.length + " 个款号"
        + (res.hidden > 0 ? " · 已隐藏 " + res.hidden + " 个 10 双以下" : "");
      mxBox.querySelectorAll("thead th").forEach(function(th){
        th.onclick = function(){
          var k = th.getAttribute("data-k");
          if(k === "spu") AGESP.sort = "spu";
          else if(k.charAt(0) === "c"){ AGESP.sort = k; AGESP.seg = +k.slice(1); }
          else AGESP.sort = k;
          refresh();
        };
      });
    }
    refresh();

    var q = box.querySelector(".fm-asp-q");
    q.oninput = function(){ AGESP.q = q.value; refresh(); };

    box.querySelectorAll(".fm-asp-min button").forEach(function(btn){
      btn.onclick = function(){
        AGESP.min = +btn.getAttribute("data-m");
        box.querySelectorAll(".fm-asp-min button").forEach(function(x){ x.classList.toggle("on", x === btn); });
        refresh();
      };
    });
  }

"""


def crlf(s):
    return s.replace("\n", "\r\n")


html = io.open(IDX, encoding="utf-8", newline="").read()

# --- 1) 数据 ---
data_js = "window.__AGESPU = " + json.dumps(PAYLOAD, ensure_ascii=False, separators=(",", ":")) + ";"
i = html.find("window.__AGESPU = ")
if i >= 0:
    j = html.find("\n", i)
    html = html[:i] + data_js + html[j:]
    dstat = "replaced"
else:
    i = html.find("window.__VOL = ")
    assert i > 0, "window.__VOL missing"
    j = html.find("\n", i)
    html = html[:j + 1] + data_js + "\r\n" + html[j + 1:]
    dstat = "inserted"


def upsert(html, start_marker, end_marker, new_text):
    new_text = new_text.strip("\r\n") + "\r\n"
    i = html.find(start_marker)
    if i >= 0:
        j = html.find(end_marker, i)
        assert j > i, "end marker missing"
        return html[:i] + new_text + html[j:], "replaced"
    j = html.find(end_marker)
    assert j > 0, "insert anchor missing"
    return html[:j] + new_text + html[j:], "inserted"


# --- 2) CSS（放在 FBA 卡 CSS 之后，避免被 patch_vol_v5 替换区间抹掉） ---
css_new = crlf(CSS).strip("\r\n") + "\r\n"
i = html.find("#lv1WhLayer .fm-asp-tools{")
cstat = "inserted"
if i >= 0:
    # 定位「上一轮插入的整块 CSS」：段头必须在**行首**。
    # 若段头前面带空格（插入锚点落在缩进上下文里），它会被后面的「JS 段头检索」误认成
    # JS 段的段头 → upsert 把 600KB 仓库模块代码整段当成 JS 块替换掉。
    # 2026-11-03 00:07 夜间链路实测事故：index.html 1,348,490 → 716,135 字节，页面崩、
    # 后面注入步骤连着失败。根因就是段头混淆 + 删除右边界越界，两个都要防。
    hp = html.rfind("\n/* =====", 0, i)
    assert hp >= 0, "css block head missing"
    st = hp + 1
    r = html.find("#lv1WhLayer .fm-asp-empty{", i)
    assert r > i, "css last rule missing"
    e = html.find("}", r)
    assert e > r, "css last rule end missing"
    e += 1
    if html[e:e + 2] == "\r\n":
        e += 2                        # 连块尾换行一起删：插入时块尾自带换行，删/插必须严格互补
    html = html[:st] + html[e:]
    cstat = "moved"
# 插入锚点同样必须落在行首：新插入的 CSS 段头前面不能带空格
ap = html.find("\n/* ===== SKU ")
assert ap >= 0, "css insert anchor missing"
k = ap + 1
html = html[:k] + css_new + html[k:]

# --- 3) JS 函数 ---
# 用 "var AGESP" 反查块首：CSS 段头与 JS 段头文字相同，只有 var AGESP 只出现在 JS 里，
# 才不会认错块（见上面 2026-11-03 事故说明）。
js_ag = html.find("  var AGESP = ")
assert js_ag > 0, "js block missing"
ag_ls = html.rfind("\n", 0, js_ag) + 1          # var AGESP 所在行行首
hdr_ls = html.rfind("\n", 0, ag_ls - 1) + 1    # 上一行行首 = JS 段头行首
assert html[hdr_ls:].lstrip().startswith("/* ====="), "js block head missing"
en_js = html.find("  function renderFbaByShop(){", js_ag)
assert en_js > js_ag, "js end marker missing"
html = html[:hdr_ls] + crlf(JS).strip("\r\n") + "\r\n" + html[en_js:]
jstat = "replaced"

# --- 4) FBA 卡：库龄结构（条+数字行）+ 款号明细块 ---
# 先删掉所有历史遗留的「库龄 × 款号」块（重复插入会导致标题刷屏），再统一插入一份
DUP = ("      h += '<div class=\"fm-sec\">库龄 × 款号<small>' + esc(cur.name || cur.sid) + "
       "'<\\/small><\\/div>';\r\n"
       "      h += '<div id=\"fmAgeSpu\"><\\/div>';\r\n")
n_dup = html.count(DUP)
if n_dup:
    html = html.replace(DUP, "")
    print("  清理重复「库龄 × 款号」块 %d 个" % n_dup)

old_block = ("      h += '<div class=\"fm-sec\">库龄结构<small>' + esc(cur.name || cur.sid) + "
             "'<\\/small><\\/div>';\r\n"
             "      h += '<div class=\"fm-bar\"><\\/div><div class=\"fm-segrow\"><\\/div>';\r\n")
new_block = (old_block +
             "      h += '<div class=\"fm-sec\">库龄 × 款号<small>' + esc(cur.name || cur.sid) + "
             "'<\\/small><\\/div>';\r\n"
             "      h += '<div id=\"fmAgeSpu\"><\\/div>';\r\n")
if old_block in html:
    html = html.replace(old_block, new_block, 1)
    bstat = "replaced"
elif new_block in html:
    bstat = "already"
else:
    raise AssertionError("库龄块缺失")

# 调用：paintAgeBar 画条 + renderAgeSpu 画明细
old_call = "      paintAgeBar(el, ga, pcts, ACOL, TCOL, TKEY, KEY);\r\n"
new_call = ("      paintAgeBar(el, ga, pcts, ACOL, TCOL, TKEY, KEY);\r\n"
            "      renderAgeSpu(el, fbaShopState.sid);\r\n")
# 先删掉所有历史遗留的重复 renderAgeSpu 调用（只保留紧跟 paintAgeBar 之后的一次）
DUP_CALL = "      renderAgeSpu(el, fbaShopState.sid);\r\n"
n_dupc = html.count(DUP_CALL)
if n_dupc:
    html = html.replace(DUP_CALL, "")
    print("  清理重复 renderAgeSpu 调用 %d 个" % n_dupc)
if old_call in html:
    html = html.replace(old_call, new_call, 1)
    cstat2 = "replaced"
elif new_call in html:
    cstat2 = "already"
else:
    raise AssertionError("库龄条调用缺失")

# --- 5) 行尾归一 ---
html = re.sub(r"(?<!\r)\n", "\r\n", html)

io.open(IDX, "w", encoding="utf-8", newline="").write(html)
b = open(IDX, "rb").read()
print("patched | bytes %d | crlf %d | lf-only %d" % (len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n")))
print("  data:%s css:%s js:%s block:%s call:%s" % (dstat, cstat, jstat, bstat, cstat2))
print("  __AGESPU:", html.count("window.__AGESPU ="), "| renderAgeSpu 定义:",
      html.count("function renderAgeSpu"), "| fm-bar 块:", html.count('<div class="fm-bar">'),
      "| paintAgeBar 调用:", html.count("paintAgeBar(el, ga"))
