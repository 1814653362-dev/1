# -*- coding: utf-8 -*-
"""SPU → 运营 映射（从「亚马逊链接情况（含年规）.xlsx」链接基本盘 sheet 读负责人）
只用 zipfile 解析 sheet XML（文件 23MB 主要是图片，openpyxl 会很慢）
输出：spu_owner.json
"""
import io, os, re, sys, json, zipfile
sys.stdout.reconfigure(encoding="utf-8")
from xml.etree import ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE, "data", "亚马逊链接情况（含年规）.xlsx")
COL_SPU, COL_OWNER = 2, 4
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def col_index(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n


def shared_strings(z):
    try:
        xml = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml)
    out = []
    for si in root.findall(NS + "si"):
        out.append("".join(t.text or "" for t in si.iter(NS + "t")))
    return out


def sheet_xml(z, sheet_path):
    xml = z.read(sheet_path)
    root = ET.fromstring(xml)
    rows = {}
    for row in root.iter(NS + "row"):
        r = int(row.get("r") or 0)
        cells = {}
        for c in row.findall(NS + "c"):
            ci = col_index(c.get("r") or "")
            if ci is None:
                continue
            t = c.get("t")
            v = c.find(NS + "v")
            if t == "s":
                val = SST[int(v.text)] if v is not None and v.text else ""
            elif t == "inlineStr":
                isx = c.find(NS + "is")
                val = "".join(x.text or "" for x in isx.iter(NS + "t")) if isx is not None else ""
            else:
                val = v.text if v is not None and v.text is not None else ""
            cells[ci] = val
        rows[r] = cells
    return rows


def read_base():
    z = zipfile.ZipFile(XLSX)
    global SST
    SST = shared_strings(z)
    wbx = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {r.get("Id"): r.get("Target") for r in rels}
    path = None
    for sh in wbx.iter(NS + "sheet"):
        if sh.get("name") == "链接基本盘":
            rid = sh.get(RNS + "id")
            tgt = relmap.get(rid, "")
            path = "xl/" + tgt.lstrip("/").replace("xl/", "", 1) if not tgt.startswith("xl/") else tgt
            break
    if not path:
        raise SystemExit("sheet not found")
    rows = sheet_xml(z, path)
    z.close()
    out = {}
    for r in sorted(rows):
        if r < 2:
            continue
        cells = rows[r]
        spu = (cells.get(COL_SPU) or "").strip()
        owner = (cells.get(COL_OWNER) or "").strip()
        if spu and owner:
            out.setdefault(norm(spu), {"name": spu, "owner": owner})
    return out


def build():
    base = read_base()
    direct = {k: v["owner"] for k, v in base.items()}
    items = sorted(base.items(), key=lambda kv: -len(kv[0]))
    return {"direct": direct, "items": items}


def resolve(spu, idx):
    d = idx["direct"]
    n = norm(spu)
    if not n:
        return ""
    if n in d:
        return d[n]
    for k, owner in idx["items"]:
        if len(k) >= 4 and (k in n or n in k):
            return owner
    return ""


if __name__ == "__main__":
    idx = build()
    out = os.path.join(BASE, "spu_owner.json")
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump({"direct": idx["direct"]}, fh, ensure_ascii=False, indent=1)
    print("spu_owner.json ->", os.path.getsize(out), "bytes |", len(idx["direct"]), "条")
    for k, v in sorted(idx["direct"].items()):
        print("   %-24s %s" % (k, v))
