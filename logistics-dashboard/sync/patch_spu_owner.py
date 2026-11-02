# -*- coding: utf-8 -*-
"""SPU 运营注入：window.__SPUOWNER + 各 SPU 展示位加「运营」
作用位：
  1) FBA 卡「库龄 × 款号」矩阵：款号 SPU 列后加「运营」列
  2) FBA 卡 SPU 可售占比饼图图例：SPU 名后加运营
  3) 国内仓 SPU 库存占比饼图图例：SPU 名后加运营
  4) SPU 下钻标题 +「其他 N 个 SPU」明细表 SPU 列：加运营
口径（2026-10-30 用户定）：查不到负责人的 SPU 一律算 JASON
幂等：可重复运行，不累积
  2026-10-30 修：重复插入运营列（表头+单元格各多一份）、重复排序分支
"""
import io, os, re, sys, json
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(BASE, "shandi-v5", "index.html")
OWNER = os.path.join(BASE, "spu_owner.json")
MANUAL = os.path.join(BASE, "spu_owner_manual.json")

MAP = json.load(io.open(OWNER, encoding="utf-8"))["direct"]
# 人工补录（覆盖 Excel 读出的映射）
if os.path.exists(MANUAL):
    _manual = json.load(io.open(MANUAL, encoding="utf-8"))
    for _k, _v in _manual.items():
        MAP[_k] = _v
    print("  人工补录 %d 条" % len(_manual))

CSS = """
/* ===== SPU 运营标注（2026-10-29） ===== */
#lv1WhLayer .fm-asp-tbl td.own{color:#5c6b7a;font-size:12px;white-space:nowrap;}
#lv1WhLayer .fm-asp-tbl td.own em{font-style:normal;display:inline-block;padding:1px 7px;border-radius:10px;
  background:#eef3f7;color:#0d3b5c;font-size:11px;font-weight:600;}
#lv1WhLayer .fm-pl .own{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:9px;
  background:#eef3f7;color:#0d3b5c;font-size:10.5px;font-weight:600;vertical-align:1px;flex:none;}
#lv1WhLayer .fm-pl .n{display:flex;align-items:baseline;gap:6px;min-width:0;}
#lv1WhLayer .fm-pl .fnn{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;}
#lv1WhLayer .fm-drill-h .own{display:inline-block;margin-left:8px;padding:2px 8px;border-radius:10px;
  background:#eef3f7;color:#0d3b5c;font-size:12px;font-weight:600;}
#lv1WhLayer .fm-drill-b td .own{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:9px;
  background:#eef3f7;color:#0d3b5c;font-size:10.5px;font-weight:600;white-space:nowrap;}
"""

JS = r"""
  /* ===== SPU 运营标注（2026-10-29） ===== */
  var SPU_OWNER_DEFAULT = "JASON";   /* 2026-10-30 用户口径：查不到负责人的一律算 JASON */
  function spuOwner(spu){
    var M = window.__SPUOWNER;
    var t = String(spu == null ? "" : spu).trim();
    if(!t) return "";
    if(!M) return SPU_OWNER_DEFAULT;
    var k = t.toUpperCase().replace(/[^A-Z0-9]/g, "");
    if(M[k]) return M[k];
    var keys = Object.keys(M);
    for(var i=0;i<keys.length;i++){
      if(keys[i].length >= 4 && (keys[i].indexOf(k) >= 0 || k.indexOf(keys[i]) >= 0)) return M[keys[i]];
    }
    return SPU_OWNER_DEFAULT;
  }
  function spuOwnerTag(spu){
    var o = spuOwner(spu);
    return o ? '<em class="own">' + esc(o) + '<\/em>' : '';
  }
"""


def crlf(s):
    return s.replace("\n", "\r\n")


def upsert(html, start_marker, end_marker, new_text):
    new_text = new_text.strip("\r\n") + "\r\n"
    i = html.find(start_marker)
    if i >= 0:
        j = html.find(end_marker, i)
        assert j > i, "end marker missing: " + end_marker
        return html[:i] + new_text + html[j:], "replaced"
    j = html.find(end_marker)
    assert j > 0, "insert anchor missing: " + end_marker
    return html[:j] + new_text + html[j:], "inserted"


html = io.open(IDX, encoding="utf-8").read()   # 通用换行：全部 \n，最后统一转 CRLF
NL = chr(10)

# --- 1) 数据 ---
data_js = "window.__SPUOWNER = " + json.dumps(MAP, ensure_ascii=False, separators=(",", ":")) + ";"
i = html.find("window.__SPUOWNER = ")
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

# --- 2) CSS：放到 FBA 卡 CSS 之后，避免被 patch_vol_v5 抹掉 ---
css_new = crlf(CSS).strip("\r\n") + "\r\n"
i = html.find("#lv1WhLayer .fm-asp-tbl td.own{")
cstat = "inserted"
if i >= 0:
    st = html.rfind("/* =====", 0, i)
    en = html.find("\n/* ===== ", i)
    assert st >= 0 and en > i, "css block bounds"
    html = html[:st] + html[en + 1:]
    cstat = "moved"
k = html.find("/* ===== SKU ")
assert k > 0, "css insert anchor missing"
html = html[:k] + css_new + html[k:]

# --- 3) JS 助手函数 ---
# 锚点：放在「库龄 × 款号」JS 块之前，两者互不吞并
OWNER_START = "  /* ===== SPU 运营标注（2026-10-29）"
ASP_START = "  /* ===== 库龄 × 款号 矩阵（FBA 库存卡"
RENDER_START = "  function renderFbaByShop(){"

# 先删旧块（到下一个 "  /* ===== " 标记或 renderFbaByShop 为止）
i = html.find(OWNER_START)
if i >= 0:
    j = html.find("\n  /* ===== ", i)
    k = html.find("\n" + RENDER_START, i)
    if j < 0 or (k > 0 and k < j):
        j = k
    assert j > i, "owner js block end missing"
    html = html[:i] + html[j + 1:]
    jstat = "replaced"
else:
    jstat = "inserted"

anchor = ASP_START if ASP_START in html else RENDER_START
j = html.find(anchor)
assert j > 0, "js insert anchor missing"
html = html[:j] + JS.strip("\r\n") + "\n" + html[j:]

# --- 4) FBA 库龄×款号矩阵：加「运营」列 ---
# 幂等做法：先删掉历史上所有「运营」表头/单元格，再统一插入一份
Q = chr(39); DQ = chr(34)
if 'data-k="spu">款号 SPU</th>' in html:
    lines = html.split(NL)
    kept = []
    n_th = n_td = 0
    for ln in lines:
        if "<th" in ln and 'data-k="owner"' in ln:
            n_th += 1
            continue
        if "<td" in ln and 'class="own"' in ln and "spuOwner(rr.spu)" in ln:
            n_td += 1
            continue
        kept.append(ln)
    html = NL.join(kept)
    if n_th or n_td:
        print("  清理重复运营列：表头 %d 行 / 单元格 %d 行" % (n_th, n_td))

    # 表头：款号 SPU 后加「运营」列
    OWN_TH = ("h += " + Q + "<th data-k=" + DQ + "owner" + DQ + ">运营</th>" + Q + ";")
    lines = html.split(NL)
    n_m1 = 0
    for k, ln in enumerate(lines):
        if "data-k=" in ln and "款号 SPU" in ln and "<th" in ln:
            indent = ln[:len(ln) - len(ln.lstrip())]
            lines[k] = ln + NL + indent + OWN_TH
            n_m1 += 1
    html = NL.join(lines)
    m1 = ("replaced(%d)" % n_m1) if n_m1 else "skipped"

    # 矩阵行：款号 SPU 后加「运营」列
    OWN_ROW = ("h += " + Q + "<td class=" + DQ + "own" + DQ + ">" + Q + " + "
               + "(spuOwner(rr.spu) ? " + Q + "<em>" + Q + " + esc(spuOwner(rr.spu)) + " + Q + "</em>" + Q + " : " + Q + "" + Q + ")"
               + " + " + Q + "</td>" + Q + ";" + NL)
    lines = html.split(NL)
    n_m2 = 0
    for k, ln in enumerate(lines):
        if "rr.spu" in ln and "<tr><td" in ln and "l spu" in ln:
            indent = ln[:len(ln) - len(ln.lstrip())]
            lines[k] = ln + NL + indent + OWN_ROW.rstrip(NL)
            n_m2 += 1
    html = NL.join(lines)
    m2 = ("replaced(%d)" % n_m2) if n_m2 else "skipped"

    # 矩阵 colspan：总列数 = 款号1 + 运营1 + 段数 + 老库龄/可售/总双数3 = keys.length + 5
    def _fix_colspan(mo):
        return mo.group(1) + "(keys.length + 5)" + mo.group(2)
    html, n_cs = re.subn(r"(colspan=\"'\s*\+\s*)\(keys\.length \+ \d+\)(\s*\+\s*')", _fix_colspan, html, count=1)
    m3 = ("replaced" if n_cs else "already")

    # 排序：点击「运营」列不排序（保留 spu 排序）——先去重再插入一条
    lines = html.split(NL)
    kept = []
    n_sort = 0
    for ln in lines:
        if 'else if(k === "owner") AGESP.sort = "spu";' in ln:
            n_sort += 1
            continue
        kept.append(ln)
    html = NL.join(kept)
    if n_sort:
        print("  清理重复运营排序分支 %d 条" % n_sort)
    lines = html.split(NL)
    n_m4 = 0
    for k, ln in enumerate(lines):
        if ln.strip() == 'else AGESP.sort = k;':
            indent = ln[:len(ln) - len(ln.lstrip())]
            lines[k] = indent + 'else if(k === "owner") AGESP.sort = "spu";' + NL + ln
            n_m4 += 1
            break
    html = NL.join(lines)
    m4 = ("replaced(%d)" % n_m4) if n_m4 else "skipped"
else:
    m1 = m2 = m3 = m4 = "skipped(矩阵已移除)"

# --- 5/6) 饼图图例加运营（2 处：FBA + 国内仓） ---
# 自愈：历史上误写成 '>"'（多一个双引号），会把 SPU 名挤出可视区
BAD_LEG = ("          + '<span class=\"n\" title=\"' + esc(items[i][0]) + '\">\"' + esc(items[i][0])")
GOOD_LEG = ("          + '<span class=\"n\" title=\"' + esc(items[i][0]) + '\"><span class=\"fnn\">' + esc(items[i][0]) + '</span>'")
n_bad = html.count(BAD_LEG)
if n_bad:
    html = html.replace(BAD_LEG, GOOD_LEG)
    print("  修复图例坏形态 '>\"' %d 处" % n_bad)

LEG_A = ("      lg += '<div class=\"fm-pl\" data-i=\"' + i + '\"><u style=\"background:' + col + '\"><\\/u>'\n"
         "          + '<span class=\"n\" title=\"' + esc(items[i][0]) + '\">' + esc(items[i][0]) + '<\\/span>'\n")
LEG_B = ("      lg += '<div class=\"fm-pl\" data-i=\"' + i + '\"><u style=\"background:' + col + '\"><\\/u>'\n"
         "          + '<span class=\"n\" title=\"' + esc(items[i][0]) + '\"><span class=\"fnn\">' + esc(items[i][0]) + '</span>' + spuOwnerTag(items[i][0]) + '<\\/span>'\n")
LEG_C = LEG_B
LEG_D = ("      lg += '<div class=\"fm-pl\" data-i=\"' + i + '\"><u style=\"background:' + col + '\"><\\/u>'\n"
         "          + '<span class=\"n\" title=\"' + esc(items[i][0]) + '\">' + esc(items[i][0]) + spuOwnerTag(items[i][0]) + '<\\/span>'\n")

n_leg = 0
for _ in range(4):
    if LEG_A in html:
        html = html.replace(LEG_A, LEG_C, 1); n_leg += 1
    elif LEG_D in html:
        html = html.replace(LEG_D, LEG_C, 1); n_leg += 1
    elif LEG_C in html:
        break
    else:
        break
assert n_leg in (0, 2), "饼图图例处理数异常: %d" % n_leg
p1 = p2 = ("already" if n_leg == 0 else "replaced")

# --- 7) SPU 下钻标题加运营 ---
DRILL_A = ("      + '<div class=\"fm-drill-h\"><b>' + esc(spu) + '</b>'\n")
DRILL_B = ("      + '<div class=\"fm-drill-h\">' + '<b>' + esc(spu) + '</b>' + spuOwnerTag(spu)\n")
DRILL_C = ("      + '<div class=\"fm-drill-h\">' + spuPicTag(spu) + '<b>' + esc(spu) + '</b>' + spuOwnerTag(spu)\n")
if DRILL_B in html:
    d1 = "already"
elif DRILL_A in html:
    html = html.replace(DRILL_A, DRILL_B, 1); d1 = "replaced"
elif DRILL_C in html:
    d1 = "already"
else:
    raise AssertionError("下钻标题状态未知")

# --- 8)「其他 N 个 SPU」明细表：SPU 列后加运营 ---
AGG_A = ("        h += '<tr><td>' + esc(nm) + '</td>'\n")
AGG_B = ("        h += '<tr><td>' + esc(nm) + spuOwnerTag(nm) + '</td>'\n")
if AGG_B in html:
    a1 = "already"
elif AGG_A in html:
    html = html.replace(AGG_A, AGG_B, 1); a1 = "replaced"
else:
    raise AssertionError("「其他 SPU」明细表状态未知")

# --- 9) 行尾归一 ---
html = re.sub(r"(?<!\r)\n", "\r\n", html)

io.open(IDX, "w", encoding="utf-8", newline="").write(html)
b = open(IDX, "rb").read()
print("patched | bytes %d | crlf %d | lf-only %d" % (len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n")))
print("  data:%s css:%s js:%s | 矩阵:%s %s %s %s | FBA图例:%s 国内仓图例:%s | 下钻:%s 其他SPU表:%s" % (
    dstat, cstat, jstat, m1, m2, m3, m4, p1, p2, d1, a1))
print("  __SPUOWNER:", html.count("window.__SPUOWNER ="), "| spuOwner 定义:", html.count("function spuOwner("),
      "| spuOwnerTag 调用:", html.count("spuOwnerTag("))
print("  运营表头:", html.count('data-k="owner">运营</th>'), "| 运营单元格:", html.count('<td class="own">'),
      "| owner排序分支:", html.count('else if(k === "owner")'))
