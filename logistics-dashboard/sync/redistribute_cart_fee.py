# -*- coding: utf-8 -*-
"""公盘「发货记录.xlsx」拖车费按箱数重摊（2026-11-03 用户定）。

分摊口径与用户既有公式一致（3月拖车费 `139.51/56*H19`、11月海运费 `209.42/115*I12`，
H/I 都是箱数列）＝「总额 ÷ 总箱数 × 本行箱数」。

模型：
  · 单元 unit：拖车费列上的**合并区域**是一个单元（整块总值只写在左上角，其余行为空）；
    非合并的每行各自是一个单元
  · 批次 batch：
      - 合并块自己就是一批（它的值覆盖多行，甚至跨多个进仓号）
      - 非合并的单行单元按「货代进仓号」归批；没有进仓号的行各自一批
  · 批次总额守恒：先按单元权重（单元内箱数之和）把批次总额分到单元，
    单元内再按各行箱数分到行；两位小数舍入的尾差补给该批次权重最大的行
  · 权重：箱数 > 0 用箱数；否则用件数；再否则按行数均分
  · 只改拖车费列；该列上的合并区域会解除（否则 Excel 不允许逐行写值）；
    该列上的公式单元格替换为算出的数值

用法：python redistribute_cart_fee.py --in <src> --out <dst> [--apply]
默认只演算，不写文件。
"""
import collections, io, os, re, sys, zipfile

sys.stdout.reconfigure(encoding="utf-8")
WS = os.path.dirname(os.path.abspath(__file__))
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NSE = "{%s}" % NS
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

APPLY = "--apply" in sys.argv
SRC = OUT = None
for i, a in enumerate(sys.argv):
    if a == "--in" and i + 1 < len(sys.argv):
        SRC = sys.argv[i + 1]
    if a == "--out" and i + 1 < len(sys.argv):
        OUT = sys.argv[i + 1]
SRC = SRC or os.path.join(WS, "data", "shipments_share.xlsx")
OUT = OUT or os.path.join(WS, "data", "shipments_share.fair.xlsx")
ET.register_namespace("main", NS) if False else None


def col_num(s):
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def col_letters(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_rng(a):
    m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)$", a or "")
    if not m:
        return None
    return (col_num(m.group(1)), int(m.group(2)), col_num(m.group(3)), int(m.group(4)))


def num(s):
    try:
        return float(str(s).strip())
    except Exception:
        return 0.0


import xml.etree.ElementTree as ET

z = zipfile.ZipFile(SRC)
names = z.namelist()
ss = []
if "xl/sharedStrings.xml" in names:
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    for si in root.findall(NSE + "si"):
        ss.append("".join(t.text or "" for t in si.iter(NSE + "t")))
wb = ET.fromstring(z.read("xl/workbook.xml"))
rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
rmap = {r.get("Id"): r.get("Target") for r in rels}
sheet_files = {}
for sh in wb.find(NSE + "sheets"):
    tgt = rmap.get(sh.get(RNS + "id"), "")
    if not tgt.startswith("xl/"):
        tgt = "xl/" + tgt.lstrip("/")
    sheet_files[sh.get("name")] = tgt


def text_of(c):
    t = c.get("t")
    v = c.find(NSE + "v")
    if t == "s" and v is not None and v.text:
        return ss[int(v.text)]
    if t == "inlineStr":
        is_ = c.find(NSE + "is")
        return "".join(x.text or "" for x in is_.iter(NSE + "t")) if is_ is not None else ""
    return v.text if v is not None and v.text is not None else ""


plan, unmerge = {}, {}
summary = []

for sname, sfile in sheet_files.items():
    sroot = ET.fromstring(z.read(sfile))
    rows = list(sroot.iter(NSE + "row"))
    if not rows:
        continue
    heads = {}
    for c in rows[0].findall(NSE + "c"):
        heads[col_num(re.match(r"([A-Z]+)", c.get("r")).group(1))] = text_of(c)

    def col_of(name):
        hit = [k for k, v in heads.items() if v == name]
        return hit[0] if hit else None

    ccol, qcol, bcol, ecol = col_of("拖车费"), col_of("件数"), col_of("箱数"), col_of("货代进仓号")
    if ccol is None:
        continue
    if qcol is None or bcol is None:
        print("!! %s 缺件数/箱数列" % sname)
        continue

    rowmap = {}
    for row in rows[1:]:
        rnum = int(row.get("r"))
        cells = {}
        for c in row.findall(NSE + "c"):
            cells[col_num(re.match(r"([A-Z]+)", c.get("r")).group(1))] = c
        rowmap[rnum] = cells

    mc = sroot.find(NSE + "mergeCells")
    merges = [m.get("ref") for m in mc] if mc is not None else []
    cart_merges = []
    for m in merges:
        r = parse_rng(m)
        if r and r[0] == ccol and r[2] == ccol:
            cart_merges.append((m, r))

    def rw(r):
        """行权重：(类型, 数值)"""
        cells = rowmap.get(r, {})
        b = num(text_of(cells[bcol])) if bcol in cells else 0
        if b > 0:
            return ("箱", b)
        q = num(text_of(cells[qcol])) if qcol in cells else 0
        if q > 0:
            return ("件", q)
        return ("均", 1.0)

    # ---- 单元 ----
    units = []
    in_merge = {}
    for m, (c1, r1, c2, r2) in cart_merges:
        rowsl = list(range(r1, r2 + 1))
        for r in rowsl:
            in_merge[r] = True
        top = rowmap.get(r1, {}).get(ccol)
        units.append({"rows": rowsl, "merge": m, "val": num(text_of(top)) if top is not None else 0.0})
    for rnum in sorted(rowmap):
        if rnum in in_merge:
            continue
        c = rowmap[rnum].get(ccol)
        units.append({"rows": [rnum], "merge": None, "val": num(text_of(c)) if c is not None else 0.0})

    for u in units:
        u["weight"] = sum(rw(r)[1] for r in u["rows"]) or len(u["rows"])

    # ---- 批次 ----
    batches = collections.OrderedDict()
    for u in units:
        if u["merge"]:
            key = ("merge", u["merge"])
        else:
            cells = rowmap.get(u["rows"][0], {})
            ent = text_of(cells[ecol]).strip() if ecol in cells else ""
            key = ("ent", ent) if ent else ("row", u["rows"][0])
        batches.setdefault(key, []).append(u)

    sp, um = {}, set()
    changed_batches = 0
    for key, us in batches.items():
        total = sum(u["val"] for u in us)
        if total <= 0:
            continue
        tw = sum(u["weight"] for u in us)
        if tw <= 0:
            continue
        changed = False
        for u in us:
            share = total * u["weight"] / tw
            inner = [(r, rw(r)[1]) for r in u["rows"]]
            itw = sum(w for _, w in inner) or len(inner)
            for r, w in inner:
                val = round(share * w / itw, 2)
                c = rowmap.get(r, {}).get(ccol)
                old = num(text_of(c)) if c is not None else 0.0
                if abs(old - val) > 0.004:
                    changed = True
                sp["%s!%s%d" % (sname, col_letters(ccol), r)] = val
            if u["merge"]:
                um.add(u["merge"])
        # 尾差：批次内权重最大的行补差，保证批次总额分毫不差
        rows_all = [r for u in us for r in u["rows"]]
        keyed = [(r, "%s!%s%d" % (sname, col_letters(ccol), r)) for r in rows_all]
        keyed = [(r, k) for r, k in keyed if k in sp]
        if keyed:
            best = max(keyed, key=lambda x: rw(x[0])[1])[1]
            others = sum(sp[k] for _, k in keyed if k != best)
            sp[best] = round(total - others, 6)   # 尾差用高精度，保证批次总额分毫不差
        if changed:
            changed_batches += 1
            summary.append((sname, key[1], len(us), total))

    if sp:
        plan[sname] = sp
        unmerge[sname] = um
        print("  %-6s 拖车费列=%s | 批次 %d 个（变动 %d）| 单元格 %d | 解除合并 %d"
              % (sname, col_letters(ccol), len(batches), changed_batches, len(sp), len(um)))

print("\n=== 汇总 ===")
print("涉及 sheet %d | 改动单元格 %d | 解除合并 %d | 变动批次 %d"
      % (len(plan), sum(len(v) for v in plan.values()), sum(len(v) for v in unmerge.values()), len(summary)))
for s in summary[:25]:
    print("   %-6s %-16s 单元 %d 个，总额 %.2f" % s)

if not APPLY:
    print("\n[dry-run] 未写文件。加 --apply 生成新文件。")
    sys.exit(0)

if os.path.exists(OUT):
    os.remove(OUT)
outz = zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED)
for item in z.infolist():
    data = z.read(item.filename)
    sname = next((n for n, f in sheet_files.items() if f == item.filename), None)
    if sname and sname in plan:
        sroot = ET.fromstring(data)
        sp = plan[sname]
        for row in sroot.iter(NSE + "row"):
            for c in row.findall(NSE + "c"):
                key = "%s!%s" % (sname, c.get("r"))
                if key in sp:
                    f_el = c.find(NSE + "f")
                    if f_el is not None:
                        c.remove(f_el)
                    ve = c.find(NSE + "v")
                    if ve is None:
                        ve = ET.SubElement(c, NSE + "v")
                    ve.text = ("%g" % sp[key])
                    if c.get("t") in ("s", "str", "inlineStr"):
                        del c.attrib["t"]
        mc = sroot.find(NSE + "mergeCells")
        if mc is not None:
            for m in list(mc):
                if m.get("ref") in unmerge.get(sname, set()):
                    mc.remove(m)
            if len(mc) == 0:
                sroot.remove(mc)
        data = ET.tostring(sroot, encoding="UTF-8", xml_declaration=True)
    outz.writestr(item, data)
outz.close()
z.close()
print("\n写出:", OUT, os.path.getsize(OUT), "字节")
