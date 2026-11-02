# -*- coding: utf-8 -*-
"""生成「写回共享盘发货记录」的计划文件。

口径（2026-11-02 小丁定）：
  · Delivery window 列(T) ← 领星 shipment_status（照原样写英文枚举）
  · 送达时间 列(U)       ← 领星 receiving_time 的日期部分，统一 YYYY-MM-DD
  · 领星查不到的行一律不动（保留原值和原公式）
  · 已有值也覆盖（把时效口径统一切到领星）
  · 共享盘不新增列

输出：data/lx_writeback_plan.json
  {"_meta": {...}, "sheets": [{"name": "9月", "rows": [{"row": 12, "fba": "FBA19...",
             "dw_old": "...", "dw_new": "...", "dt_old": "...", "dt_new": "2026-10-09"}]}]}

行号用 xlsx 内部 row 的 r 属性（真实行号），不是序号，避免空行/删行导致的偏移。
"""
import collections
import io
import json
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def nk(s):
    return str(s or "").strip()


def col_index(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letter(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def cellval(c, SST):
    t = c.get("t")
    v = c.find(NS + "v")
    if t == "s":
        return SST[int(v.text)] if v is not None and v.text else ""
    if t == "inlineStr":
        isx = c.find(NS + "is")
        return "".join(x.text or "" for x in isx.iter(NS + "t")) if isx is not None else ""
    return v.text if v is not None and v.text is not None else ""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--lx", default=os.path.join(BASE, "lx_raw", "shipments.json"))
    ap.add_argument("--share", default=os.path.join(BASE, "data", "shipments_share.xlsx"))
    ap.add_argument("--out", default=os.path.join(BASE, "data", "lx_writeback_plan.json"))
    args = ap.parse_args()

    lx = json.load(io.open(args.lx, encoding="utf-8"))
    lxmap = {nk(s.get("shipment_id")): s for s in lx if nk(s.get("shipment_id"))}

    z = zipfile.ZipFile(args.share)
    SST = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(NS + "si"):
            SST.append("".join(t.text or "" for t in si.iter(NS + "t")))
    wbx = ET.fromstring(z.read("xl/workbook.xml"))
    rel = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {r.get("Id"): r.get("Target") for r in rel}
    sheets = []
    for sh in wbx.iter(NS + "sheet"):
        tgt = relmap.get(sh.get(RNS + "id"), "")
        p = tgt if tgt.startswith("xl/") else "xl/" + tgt.lstrip("/")
        sheets.append((sh.get("name"), p))

    out_sheets = []
    stat = collections.Counter()
    for name, p in sheets:
        root = ET.fromstring(z.read(p))
        rows = list(root.iter(NS + "row"))
        if not rows:
            continue
        hdr = {}
        for c in rows[0].findall(NS + "c"):
            ci = col_index(c.get("r") or "")
            if ci:
                hdr[ci] = cellval(c, SST).strip()
        col_fba = col_dw = col_dt = None
        for ci, h in hdr.items():
            if h == "FBA货件号":
                col_fba = ci
            elif h == "Delivery window":
                col_dw = ci
            elif h == "送达时间":
                col_dt = ci
        if not col_fba:
            continue
        # 缺 Delivery window / 送达时间 列的 tab 由写入脚本（Excel COM）在表尾新增，
        # 这里照常出计划，行号与真实 Excel 行号一致。
        plan_rows = []
        for row in rows[1:]:
            rno = int(row.get("r") or 0)
            d = {}
            for c in row.findall(NS + "c"):
                ci = col_index(c.get("r") or "")
                if ci:
                    d[ci] = cellval(c, SST).strip()
            if not any(str(v).strip() for v in d.values()):
                continue
            fba = nk(d.get(col_fba))
            s = None
            for pid in [x.strip() for x in fba.split("&") if x.strip()]:
                if pid in lxmap:
                    s = lxmap[pid]
                    break
            if not s:
                stat["无领星(不动)"] += 1
                continue
            stat["可join"] += 1
            dw_old = nk(d.get(col_dw))
            dt_old = nk(d.get(col_dt))
            dw_new = nk(s.get("shipment_status"))
            rt = nk(s.get("receiving_time"))
            dt_new = rt[:10] if len(rt) >= 10 and rt[4] == "-" else ""
            dw_chg = bool(dw_new) and dw_old != dw_new
            dt_chg = bool(dt_new) and dt_old[:10] != dt_new
            if not dw_chg and not dt_chg:
                stat["值相同(不写)"] += 1
                continue
            if dw_chg:
                stat["DW会写"] += 1
            if dt_chg:
                stat["DT会写"] += 1
            plan_rows.append({
                "row": rno,
                "fba": fba,
                "dw_old": dw_old, "dw_new": dw_new,
                "dt_old": dt_old, "dt_new": dt_new,
                "dw_chg": dw_chg, "dt_chg": dt_chg,
                "recv_time": rt,
            })
        if plan_rows:
            out_sheets.append({"name": name, "rows": plan_rows})

    meta = {
        "generatedAt": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lxSnapshot": os.path.relpath(args.lx, BASE),
        "shareFile": os.path.relpath(args.share, BASE),
        "stat": dict(stat),
        "sheets": len(out_sheets),
        "plannedRows": sum(len(s["rows"]) for s in out_sheets),
    }
    d = os.path.dirname(args.out)
    if d and not os.path.exists(d):
        os.makedirs(d)
    with io.open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"_meta": meta, "sheets": out_sheets}, fh, ensure_ascii=False)
    print("写回计划 → %s" % args.out)
    print("  统计: %s" % json.dumps(meta["stat"], ensure_ascii=False))
    print("  tab %d 个，计划写 %d 行" % (len(out_sheets), meta["plannedRows"]))
    for s in out_sheets:
        ndw = len([r for r in s["rows"] if r["dw_chg"]])
        ndt = len([r for r in s["rows"] if r["dt_chg"]])
        print("     [%s] %d 行（DW %d / DT %d）" % (s["name"], len(s["rows"]), ndw, ndt))


if __name__ == "__main__":
    main()
