# -*- coding: utf-8 -*-
"""读取 .xlsx（无第三方依赖）—— 公盘发货记录 Excel 的解析器。

用 zipfile + xml.etree 直接解析 sharedStrings / worksheet，
返回 [(sheet 名, [行字典列表])]，行字典是 {列序号: 单元格文本}。
日期单元格返回 Excel 序列号（如 46304），由调用方决定怎么转。
"""
import re, zipfile
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def col_index(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return 0
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(path):
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(NS + "si"):
            ss.append("".join(t.text or "" for t in si.iter(NS + "t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rmap = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    for sh in wb.find(NS + "sheets"):
        tgt = rmap.get(sh.get(RNS + "id"), "")
        if not tgt.startswith("xl/"):
            tgt = "xl/" + tgt.lstrip("/")
        if tgt not in z.namelist():
            continue
        sroot = ET.fromstring(z.read(tgt))
        rows = []
        for row in sroot.iter(NS + "row"):
            cells = {}
            for c in row.findall(NS + "c"):
                ci = col_index(c.get("r"))
                t = c.get("t")
                v = c.find(NS + "v")
                if t == "s":
                    val = ss[int(v.text)] if v is not None and v.text else ""
                elif t == "inlineStr":
                    is_ = c.find(NS + "is")
                    val = "".join(x.text or "" for x in is_.iter(NS + "t")) if is_ is not None else ""
                else:
                    val = v.text if v is not None and v.text is not None else ""
                cells[ci] = val
            rows.append(cells)
        out.append((sh.get("name"), rows))
    z.close()
    return out
