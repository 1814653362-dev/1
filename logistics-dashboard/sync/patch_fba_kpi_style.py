# -*- coding: utf-8 -*-
"""FBA 卡「库存总览 / 本店明细」指标格风格统一（2026-10-30）

问题：同一张卡里两套指标语言
  · 主指标 .fm-kpi  = 大号数字(30px) + 小单位 + 标签在数字下方
  · 明细 .fm-mgrid  = 小号数字(15px) + 标签在数字左侧(11.5px 浅灰) + 虚线分隔
  → 同一个信息块看起来像两种卡片。

统一口径（与 .fm-kpi / .wh-kpi 共用一套规则）：
  标签 12.5px #5c6b7a（数字下方） · 数字 700 等宽 · 单位 12px #5c6b7a
  明细数字降到 20px（主指标 30px 的 2/3 档），色相与主指标一致
  主指标与明细之间加一条 1px #eef2f6 细线分层
  明细排 4 列（7 项 → 4+3，第 8 格留白）

幂等：可重复运行，输出稳定。
"""
import io, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(BASE, "shandi-v5", "index.html")

CSS_OLD = """#lv1WhLayer .fm-mgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px 18px;margin-top:2px;}
#lv1WhLayer .fm-mgrid .g{display:flex;align-items:baseline;justify-content:space-between;gap:8px;
  border-bottom:1px dashed #eef2f6;padding-bottom:6px;}
#lv1WhLayer .fm-mgrid .g span{font-size:11.5px;color:#97a4b0;white-space:nowrap;}
#lv1WhLayer .fm-mgrid .g b{font-size:15px;font-weight:700;color:#16212e;font-variant-numeric:tabular-nums;white-space:nowrap;}
#lv1WhLayer .fm-mgrid .g b u{font-size:10.5px;font-weight:400;text-decoration:none;color:#97a4b0;margin-left:2px;}"""

CSS_NEW = """#lv1WhLayer .fm-mgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px 20px;margin-top:0;}
#lv1WhLayer .fm-mgrid .g{min-width:0;}
#lv1WhLayer .fm-mgrid .g span{display:block;font-size:12.5px;color:#5c6b7a;white-space:nowrap;}
#lv1WhLayer .fm-mgrid .g b{display:block;margin-top:3px;font-size:20px;line-height:1.15;font-weight:700;
  letter-spacing:-.2px;color:#0d3b5c;font-variant-numeric:tabular-nums;font-feature-settings:'tnum';white-space:nowrap;}
#lv1WhLayer .fm-mgrid .g b i{font-style:normal;font-size:12px;font-weight:400;color:#5c6b7a;margin-left:3px;}"""

DIV_OLD = "#lv1WhLayer .fm-hero-l .fm-sec{margin-top:20px;}"
DIV_NEW = ("#lv1WhLayer .fm-hero-l .fm-sec{margin-top:20px;}\n"
           "#lv1WhLayer .fm-hero-l .fm-sec.fm-div{margin-top:22px;padding-top:18px;border-top:1px solid #eef2f6;}")

JS_OLD = ("""        h += '<div class="g"><span>' + grid[i][0] + '</span><b>' + grid[i][1] + """
          """(grid[i][2] ? '<u>' + grid[i][2] + '<\\/u>' : "") + '<\\/b><\\/div>';
""")
JS_NEW = ("""        h += '<div class="g"><span>' + grid[i][0] + '</span><b>' + grid[i][1] + """
          """(grid[i][2] ? '<i>' + grid[i][2] + '<\\/i>' : "") + '<\\/b><\\/div>';
""")
SEC_OLD = """<div class="fm-sec">本店明细"""
SEC_NEW = """<div class="fm-sec fm-div">本店明细"""

# 数字格式：仓库页大数字统一千分位（同卡饼图/矩阵已有分隔符，KPI 没有）
NN_OLD = "function nn(v){ var x = Number(v) || 0; return String(Math.round(x)); }"
NN_NEW = "function nn(v){ var x = Number(v) || 0; return Math.round(x).toLocaleString(\"en-US\"); }"


def crlf(s):
    return s.replace("\n", "\r\n")


html = io.open(IDX, encoding="utf-8").read()      # 通用换行 -> 全部 \n
NL = chr(10)


def swap(text, old, new, label):
    old_n = old.replace("\n", NL)
    new_n = new.replace("\n", NL)
    if new_n in text:                     # 已替换过（new 含 old 时也优先判定）
        return text, label + ":already"
    assert old_n in text, label + ": 未找到待替换块"
    return text.replace(old_n, new_n, 1), label + ":replaced"


DIV_RULE = "#lv1WhLayer .fm-hero-l .fm-sec.fm-div{margin-top:22px;padding-top:18px;border-top:1px solid #eef2f6;}"


html, c1 = swap(html, CSS_OLD, CSS_NEW, "CSS指标格")
html, c2 = swap(html, DIV_OLD, DIV_NEW, "CSS分隔线")
html, c3 = swap(html, JS_OLD, JS_NEW, "JS单位标签")
html, c4 = swap(html, SEC_OLD, SEC_NEW, "JS分隔线类")
html, c5 = swap(html, NN_OLD, NN_NEW, "数字千分位")

# 去重：历史多跑留下的重复 fm-div 规则只保留一份
n_div = html.count(DIV_RULE)
if n_div > 1:
    html = html.replace(DIV_RULE + NL + DIV_RULE, DIV_RULE)
    while (DIV_RULE + NL + DIV_RULE) in html:
        html = html.replace(DIV_RULE + NL + DIV_RULE, DIV_RULE)
    print("  清理重复 fm-div 规则 %d 条" % n_div)

# 行尾归一
html = re.sub(r"(?<!\r)\n", "\r\n", html)

io.open(IDX, "w", encoding="utf-8", newline="").write(html)
b = open(IDX, "rb").read()
print("patched | bytes %d | crlf %d | lf-only %d" % (len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n")))
print("  " + " | ".join([c1, c2, c3, c4, c5]))
print("  .fm-mgrid 4列:", html.count("grid-template-columns:repeat(4,1fr);gap:16px 20px"),
      "| fm-div:", html.count("fm-div"),
      "| g内 i 标签:", html.count("<i>' + grid[i][2] + '<\\/i>'"),
      "| 旧 u 标签:", html.count("<u>' + grid[i][2]"),
      "| nn千分位:", html.count('Math.round(x).toLocaleString("en-US")'))
