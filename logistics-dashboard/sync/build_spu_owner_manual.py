# -*- coding: utf-8 -*-
"""补全运营映射：系统里所有无运营的 SPU 一律归 JASON（2026-10-30 用户口径）
层次：
  1) Excel 层：spu_owner.json（链接基本盘读出）—— 优先级最高
  2) 人工层：spu_owner_prev.json（用户明确指定过的，Excel 没有的）—— 次之
  3) 默认：其余全部 JASON
输出：spu_owner_manual.json（人工层 + 默认补全，叠加在 Excel 层之上）
"""
import io, os, re, sys, json, collections
sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(BASE, "shandi-v5", "index.html")
OUT = os.path.join(BASE, "spu_owner_manual.json")
PREV = os.path.join(BASE, "spu_owner_prev.json")
DEFAULT = "JASON"


def grab(html, var):
    for pat in ("window." + var + " = ", "window." + var + "="):
        i = html.find(pat)
        if i >= 0:
            break
    j = html.find("\n", i)
    return json.loads(html[i + len(pat):j].rstrip(";"))


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


html = io.open(IDX, encoding="utf-8").read()
spu_fba = grab(html, "__SPU")
spu_loc = grab(html, "__SPUL")
excel_map = grab(html, "__SPUOWNER")          # 线上已合并好的（含 Excel + 人工层）

# 拆出 Excel 层与人工层：用 spu_owner.json（纯 Excel）判断哪些是 Excel 来的
excel_only = json.load(io.open(os.path.join(BASE, "spu_owner.json"), encoding="utf-8"))["direct"]
excel_keys = {norm(k) for k in excel_only}
# 人工层：线上总表里去掉 Excel 层的那 27 条，剩下的就是人工指定过的
manual_prev = {}
for k, v in excel_map.items():
    if norm(k) not in excel_keys:
        manual_prev[k] = v
manual_prev_n = {norm(k): v for k, v in manual_prev.items()}
print("  人工指定层 %d 条: %s" % (len(manual_prev), dict(collections.Counter(manual_prev.values()))))

sysf = set()
for sid, sh in spu_fba["byShop"].items():
    sysf |= set(sh["spu"].keys())
sysl = set(spu_loc.get("all") or {})
allsys = sorted(sysf | sysl)

manual = {}
for spu in allsys:
    n = norm(spu)
    if n in excel_keys:
        continue                                  # Excel 层负责，不重复
    manual[spu] = manual_prev_n.get(n, DEFAULT)   # 人工指定优先，否则默认 JASON

# 人工层里那些 Excel 也有但值不同的（Excel 优先，不进 manual）
for k, v in manual_prev.items():
    if norm(k) in excel_keys:
        continue

by_owner = collections.defaultdict(list)
for s, o in manual.items():
    by_owner[o].append(s)
print("人工层 %d 条 | Excel 层 %d 条" % (len(manual), len(excel_keys)))
for o, lst in sorted(by_owner.items()):
    print("  %-8s %3d 个" % (o, len(lst)))
print("  其中人工指定: %d 条" % len([1 for v in manual.values() if v != DEFAULT]))

with io.open(OUT, "w", encoding="utf-8") as fh:
    json.dump(manual, fh, ensure_ascii=False, indent=1)
print("输出:", OUT, os.path.getsize(OUT), "bytes")
