# -*- coding: utf-8 -*-
"""公盘 Excel → 钉钉「发货记录」同步模块（映射 + 差异计算 + 可选写入）。

Excel 列（各 tab 不同）→ 钉钉 29 字段映射见文件头。
"""
import collections, datetime, io, json, os, re, sys

# 公盘发货记录 Excel 的本地副本路径（由 sync_share_xlsx.ps1 从共享盘复制过来）
XLSX = os.environ.get("SHARE_XLSX_LOCAL", os.path.join("data", "shipments_share.xlsx"))

ALIAS = {
    "AmazonReferenceID": ["Amazon Reference ID"],
    "SKU款号": ["SKU", "sku", "款号"],
    "FBA仓点收货地": ["FBA仓点/收货地", "FBA仓点收货地"],
    "运费物流海运费": ["物流费", "海运费"],
    # 钉钉「店铺运营」列混装两种东西：11/12 月 tab 有「发货运营/运营」列（人名），
    # 1~10 月 tab 只有「店铺」列（店名）。按优先级取，不能一律取「店铺」。
    "店铺运营": ["发货运营", "运营", "店铺"],
    "送达时间": ["送达时间"],
}
SIMPLE = {
    "FBA货件号": "FBA货件号", "船型": "船型", "件数": "件数", "箱数": "箱数",
    "货代": "货代", "货代进仓号": "货代进仓号", "报关单号": "报关单号",
    "计费重量": "计费重量", "单价": "单价", "报关费": "报关费", "保险": "保险",
    "拖车费": "拖车费", "发货日期": "发货日期", "备注": "备注",
    "展俊发票号": "展俊发票号", "补货单号": "补货单号", "采购成本": "采购成本",
    "总费用": "总费用", "开船日期": "开船日期", "到港日期": "到港日期",
    "船名航次": "船名航次",
}
NUM_FIELDS = {"计费重量", "总费用", "件数", "采购成本", "单价", "箱数", "运费物流海运费",
              "拖车费", "报关费", "保险"}
MONTH_RE = re.compile(r"^(\d+)月$")

# —— 本表只同步「今年」数据（用户口径 2026-11-03 定：去年数据不放进钉钉表）——
# 公盘 12 个月度 tab 里，11/12 月两个 tab 目前装的是 2025 年的货（报关单号 ZJSD25… 可验证），
# 其余 1~10 月是 2026 年。同步只处理 CURRENT_YEAR_MONTHS 里的月份，
# 到 12 月把 "11月"、"12月" 加进来即可；加了之后要把它们从旧表里补录回去。
CURRENT_YEAR = 2026
CURRENT_YEAR_MONTHS = {"1月", "2月", "3月", "4月", "5月",
                        "6月", "7月", "8月", "9月", "10月"}


def excel_serial_to_md(s):
    """Excel 日期序列号 → 钉钉表在用的 M.D 格式（如 10.9 / 10.10）。"""
    d = excel_serial_to_iso(s)
    if not d:
        return None
    y, m, day = d.split("-")
    return "%d.%d" % (int(m), int(day))


def excel_serial_to_iso(s):
    try:
        n = float(s)
    except (TypeError, ValueError):
        return None
    if n < 20000 or n > 80000:
        return None
    return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(n))).isoformat()


def build_excel_rows(read_xlsx, xlsx=XLSX, months=None):
    """读 Excel 各月度 tab → 行字典列表（跳过对照表 Sheet1）。
    months=None 表示不过滤（全部月份）；传集合则只保留这些月份的行。"""
    tabs = read_xlsx(xlsx)
    out, sheet1 = [], []
    for name, rows in tabs:
        if not rows:
            continue
        hdr = rows[0]
        heads = [str(hdr.get(i, "")).strip() for i in range(max(hdr) + 1 if hdr else 0)]
        if not any(heads):
            continue
        if name.lower() == "sheet1" and "FBA货件号" not in heads:
            for r in rows[1:]:
                vals = [str(r.get(i, "")).strip() for i in range(len(heads))]
                if any(vals):
                    sheet1.append(dict(zip(heads, vals)))
            continue
        month = name.strip() if MONTH_RE.match(name.strip()) else ""
        if months is not None and month and month not in months:
            continue                      # 不在本年范围内（如 11月/12月 = 去年）
        for r in rows[1:]:
            rec = {}
            for i, h in enumerate(heads):
                if not h:
                    continue
                v = str(r.get(i, "")).strip()
                if v:
                    rec[h] = v
            if not rec:
                continue
            if not (rec.get("FBA货件号") or rec.get("货代进仓号")):
                continue
            rec["_月份"] = month
            rec["_tab"] = name
            out.append(rec)
    return out, sheet1


def to_ding_fields(rec):
    f = {}
    for dfld, cols in ALIAS.items():
        for c in cols:
            v = str(rec.get(c) or "").strip()
            if v and v != "#N/A":       # #N/A 是 Excel 公式错误，不是数据，不写
                f[dfld] = v
                break
    for dfld, c in SIMPLE.items():
        v = str(rec.get(c) or "").strip()
        if v and v != "#N/A" and dfld not in f:
            f[dfld] = v
    dw = str(rec.get("Delivery window") or "").strip()
    if dw and dw != "#N/A":
        f["DeliveryWindow"] = dw
    if rec.get("_月份"):
        f["月份"] = rec["_月份"]
    if rec.get("送达时间"):
        md = excel_serial_to_md(rec["送达时间"])
        if md:
            f["送达时间"] = md
    for k in list(f):
        if k in NUM_FIELDS:
            f[k] = str(f[k]).strip()
    return f


def key_of(fields):
    fba = str(fields.get("FBA货件号") or "").strip()
    sku = str(fields.get("SKU款号") or "").strip()
    ent = str(fields.get("货代进仓号") or "").strip()
    return (fba, sku) if fba else ("", sku, ent)


def build_target(read_xlsx, months=None):
    """本年范围（months=None → CURRENT_YEAR_MONTHS）内的 Excel 行 → 目标记录字典。"""
    if months is None:
        months = CURRENT_YEAR_MONTHS
    rows, sheet1 = build_excel_rows(read_xlsx, months=months)
    target = {}
    for r in rows:
        f = to_ding_fields(r)
        target[key_of(f)] = f
    return target, rows, sheet1


def diff(target, dt_rows):
    dt_map = {}
    for r in dt_rows:
        dt_map.setdefault(key_of(r["fields"]), r)
    missing, changed, same = [], [], 0
    for k, f in target.items():
        old = dt_map.get(k)
        if old is None:
            missing.append((k, f))
            continue
        of = old["fields"]
        diffs = {}
        for fld, val in f.items():
            ov = of.get(fld)
            ov = "" if ov is None else str(ov).strip()
            if ov != str(val).strip():
                diffs[fld] = (ov, str(val).strip())
        # 钉钉里残留的 #N/A 是 Excel 公式错误标记（公盘那边没有真值）→ 清空
        for fld, ov in of.items():
            if str(ov).strip() == "#N/A" and fld not in f:
                diffs[fld] = ("#N/A", "")
        if diffs:
            changed.append((k, old["id"], diffs, f))
        else:
            same += 1
    extra = [(k, dt_map[k]["id"], dt_map[k]["fields"]) for k in dt_map if k not in target]
    return missing, changed, same, extra, dt_map
