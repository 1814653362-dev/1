# -*- coding: utf-8 -*-
"""从共享盘「发货记录.xlsx」构建 records.json 的 main 表
主源：共享盘 \\Sd-fwq\\F\\物流部\\发货记录.xlsx（12 个月度 tab）
补充：旧 records.json 的对账字段 + 送达日期 + 箱规字典（按款号学）
输出：shandi-v5/records.json
"""
import io, os, re, sys, json, zipfile, collections, datetime, argparse
sys.stdout.reconfigure(encoding="utf-8")
from xml.etree import ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data", "shipments_share.xlsx")
REC = os.path.join(BASE, "shandi-v5", "records.json")

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
DKEYS = ["对账单价", "对账计费重", "对账物流费", "对账报关费", "对账合计", "对账差异", "对账渠道"]
# WorkBuddy 主表专有字段：共享盘发货记录.xlsx 里没有这些列，必须从旧 records.json 继承。
# ⚠ 2026-10-30 回归：这些字段曾因未写入 rec 字典而整体丢失，
#   其中「货件状态」是页面「全部在途（主表实时）」汇总的唯一判据（normRow: delivery_window = 货件状态），
#   丢了会导致在途汇总显示「主表当前没有在途货件 🎉」。
INHERIT_KEYS = ["货件状态", "物流状态", "入仓日期", "到港日期", "船开日期", "海运天数", "渠道"]

# —— 船型规范化（2026-11-02）——
# 共享盘 6 月之后各 tab 的「船型」列填的其实是渠道名（芝加哥卡派/特惠洛杉矶普船卡派/美西特惠卡派…），
# 规范化过的「普船/快船」原来在旧 WorkBuddy 主表里；切数据源后船型被渠道名污染，
# ③ 卡片「普船/快船」拆分（后端按船型原文分组）从 6 月起整列空。
# 口径照抄页面 isFast()：原文含「美森」「快船」「快线」= 快船，其余 = 普船。
# 实测规范化结果与旧 WorkBuddy 主表逐月完全吻合（6月 84普/28快、9月 179/9、5月 62/11 …）。
def ship_type_norm(raw):
    s = str(raw or "")
    if ("美森" in s) or ("快船" in s) or ("快线" in s):
        return "快船"
    return "普船"


def ship_type_raw_keep(raw):
    """原文是纯「普船/快船」就不另存（渠道列留空）；是渠道名才留原文。"""
    s = str(raw or "")
    return "" if s in ("", "普船", "快船") else s


ALIAS = {
    "shop": ["店铺"], "sku": ["SKU", "sku", "款号"], "fba": ["FBA货件号"],
    "ship_type": ["船型"], "wh": ["FBA仓点/收货地"], "qty": ["件数"], "carton": ["箱数"],
    "fee_weight": ["计费重量"], "price": ["单价"], "logi_fee": ["物流费"],
    "customs": ["报关费"], "insurance": ["保险"], "cart": ["拖车费"], "date": ["发货日期"],
    "region": ["地区", "备注"], "dw": ["Delivery window"], "arrive": ["送达时间", "到港日期"],
    "entry_no": ["货代进仓号", "进仓编号"], "agent": ["货代"], "decl": ["报关单号"],
    "owner": ["运营", "发货运营"], "total_fee": ["总费用"], "ocean_fee": ["海运费"],
    "purchase": ["采购成本"],
}
REGION_VALS = {"美西", "美中", "美东", "美中北", "美中南", "美东南", "美西南", "美西北"}
MONTH_NUM = {"1月": 1, "2月": 2, "3月": 3, "4月": 4, "5月": 5, "6月": 6,
             "7月": 7, "8月": 8, "9月": 9, "10月": 10, "11月": 11, "12月": 12}
CUR_Y, CUR_M = 2026, 10      # 归档惯例：月份 > 当前月 → 上一年


def col_index(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n


def cellval(c, SST, dstyles=None):
    t = c.get("t")
    v = c.find(NS + "v")
    if t == "s":
        return SST[int(v.text)] if v is not None and v.text else ""
    if t == "inlineStr":
        isx = c.find(NS + "is")
        return "".join(x.text or "" for x in isx.iter(NS + "t")) if isx is not None else ""
    raw = v.text if v is not None and v.text is not None else ""
    # 数值单元格 + 日期数字格式 → 转成 YYYY-MM-DD（否则会读到裸序列号）
    if raw and (t is None or t == "n") and dstyles:
        try:
            si = int(c.get("s") or 0)
        except (TypeError, ValueError):
            si = 0
        if dstyles.get(si):
            d = _serial_to_date(raw)
            if d:
                return d
    return raw


# Excel 内置日期格式 numFmtId（14~22、45~47 等）与自定义格式里含 y/m/d 的都算日期格式
_BUILTIN_DATE_FMT = set(list(range(14, 23)) + [45, 46, 47])


def _date_styles(z):
    """读 styles.xml → {样式索引: True}（该样式是日期格式）。"""
    out = {}
    try:
        root = ET.fromstring(z.read("xl/styles.xml"))
    except Exception:
        return out
    custom = {}
    nf = root.find(NS + "numFmts")
    if nf is not None:
        for x in nf.findall(NS + "numFmt"):
            try:
                custom[int(x.get("numFmtId"))] = (x.get("formatCode") or "")
            except (TypeError, ValueError):
                continue
    xfs = root.find(NS + "cellXfs")
    if xfs is None:
        return out
    for i, xf in enumerate(xfs.findall(NS + "xf")):
        fid = xf.get("numFmtId")
        try:
            fid_i = int(fid)
        except (TypeError, ValueError):
            fid_i = 0
        if fid_i in _BUILTIN_DATE_FMT:
            out[i] = True
        elif fid_i in custom:
            code = custom[fid_i]
            # 含 y/m/d 且不是纯数字格式 → 日期
            if any(ch in code for ch in "ymdYMD") and not code.startswith("["):
                out[i] = True
    return out


def _serial_to_date(v):
    """Excel 日期序列号 → YYYY-MM-DD（1900 日期系统）。"""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 2958465:      # 合法日期范围（约 9999-12-31）
        return None
    import datetime as _dt
    try:
        return (_dt.date(1899, 12, 30) + _dt.timedelta(days=int(n))).isoformat()
    except (OverflowError, ValueError):
        return None


def read_sheets(path):
    z = zipfile.ZipFile(path)
    dstyles = _date_styles(z)
    SST = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(NS + "si"):
            SST.append("".join(t.text or "" for t in si.iter(NS + "t")))
    wbx = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {r.get("Id"): r.get("Target") for r in rels}
    sheets = []
    for sh in wbx.iter(NS + "sheet"):
        tgt = relmap.get(sh.get(RNS + "id"), "")
        sheets.append((sh.get("name"), tgt if tgt.startswith("xl/") else "xl/" + tgt.lstrip("/")))
    out = []
    for name, p in sheets:
        root = ET.fromstring(z.read(p))
        rows = list(root.iter(NS + "row"))
        if not rows:
            continue
        hdr = {}
        for c in rows[0].findall(NS + "c"):
            ci = col_index(c.get("r") or "")
            if ci:
                hdr[ci] = cellval(c, SST, dstyles).strip()
        recs = []
        for row in rows[1:]:
            d = {}
            for c in row.findall(NS + "c"):
                ci = col_index(c.get("r") or "")
                if ci:
                    d[ci] = cellval(c, SST, dstyles).strip()
            if any(str(v).strip() for v in d.values()):
                recs.append(d)
        out.append((name, hdr, recs))
    z.close()
    return out


def num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def to_int(v):
    n = num(v)
    return int(n) if n else 0


def tokens(sku):
    s = str(sku or "").replace("\n", " ").replace("\r", " ").strip()
    return [p.strip() for p in re.split(r"[&+]", s) if p.strip()]


def ym_of(sheet):
    m = MONTH_NUM.get(sheet)
    if not m:
        return None, None
    y = CUR_Y if m <= CUR_M else CUR_Y - 1
    return y, m


def d10_py(v):
    """复刻页面 d10()（index.html:4354）：平台 ISO 串还原成真实日期。

    平台把 "YYYY-MM-DD"（东八区零点）存成 UTC 串 "YYYY-MM-DDT16:00:00Z"，
    页面显示时用 d10() 加 8 小时还原。这里同样还原并统一成 YYYY-MM-DD，
    页面显示不变，但时效天数能跟显示日期对上。
    """
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", s)
    if m:
        try:
            t = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                  int(m.group(4)), int(m.group(5))) + datetime.timedelta(hours=8)
            return t.strftime("%Y-%m-%d")
        except ValueError:
            return s[:10]
    return s[:10]


def iso_date(v, y, m):
    """'10.17' / '2026-10-17' / ISO → 'YYYY-MM-DD'（缺年份用 tab 推断）
    占位符（#N/A / - / N/A / 待定 等）返回空串"""
    s = str(v or "").strip()
    if not s:
        return ""
    if s.startswith("#") or s.upper() in ("N/A", "NA", "-", "--", "TBD", "待定", "无"):
        return ""
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return "%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})$", s)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        if y:
            return "%04d-%02d-%02d" % (y, mm, dd)
        return ""
    return ""


def spec_by_spu(old_main):
    """从旧表学「款号 token → 箱规」（多数派投票，避免个别拼箱污染）
    箱规是「包装规格」属性（20/4/30 双一箱），比 件数÷箱数 更准：
    拼箱/尾箱会让实算比值偏离（30双装2箱→15），但真实箱规仍是 20。"""
    votes = collections.defaultdict(collections.Counter)
    for r in old_main:
        sp = r.get("箱规")
        if sp in (None, "", 0):
            continue
        for t in tokens(r.get("SKU")):
            t = t.upper()
            if t:
                votes[t][sp] += 1
    return {t: c.most_common(1)[0][0] for t, c in votes.items()}


def guess_spec(sku_tokens, qty, carton, spec_map):
    """款号字典优先（箱规是包装规格，最准）；字典没有时按 件数÷箱数 比值推（文档口径兜底）"""
    for t in sku_tokens:
        t = t.upper()
        if t in spec_map:
            return spec_map[t]
    if carton > 0 and qty > 0:
        ratio = qty / float(carton)
        if 16 <= ratio <= 21:
            return 20
        if 26 <= ratio <= 31:
            return 30
        if 3 <= ratio <= 5:
            return 4
    return 20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default=REC, help="旧 records.json 路径（取对账字段/送达日期/箱规字典）")
    ap.add_argument("--out", default=REC, help="输出 records.json 路径")
    ap.add_argument("--lx", default="", help="领星 shipmentList 快照路径；用它直接覆盖主表「货件状态」")
    ap.add_argument("--no-lx", action="store_true", help="强制不用领星快照（只用继承的 WorkBuddy 值）")
    ap.add_argument("--lx-recv", default="",
                    help="领星「货件号→receiving_time」映射路径（data/lx_recv_time.json）；"
                         "用它回填主表「送达日期」空值，并写「仓库接收时间」列")
    ap.add_argument("--no-lx-recv", action="store_true",
                    help="不做系统侧回填：只用共享盘「送达时间」列 + 旧记录继承值。"
                         "2026-11-02 主管定：领星值已写回共享盘，共享盘是唯一事实源，"
                         "系统侧再回填一次属于重复写源。")
    args = ap.parse_args()
    old_path, out_path = args.old, args.out

    # ---- 领星快照（SKU 批次明细 / 主表货件状态的事实源）----
    lx_path = args.lx
    if not args.no_lx and not lx_path:
        # 自动探测：lx_raw（周一/周三批次明细维护写的）与 wh_raw（00:00 链路写的），
        # 取文件时间最新的那个 —— 否则 00:00 重建可能用到更旧的 lx_raw 快照。
        cands = [c for c in (os.path.join(BASE, "lx_raw", "shipments.json"),
                             os.path.join(BASE, "wh_raw", "shipments.json"))
                 if os.path.exists(c)]
        if cands:
            lx_path = max(cands, key=lambda c: os.path.getmtime(c))
    lxmap, lxmod = {}, {}
    lx_cutoff = "2026-07-01"
    if lx_path:
        try:
            import lx_status as LX
            lxmap, lxmod = LX.load_lx(lx_path)
            lx_cutoff = LX.page_cutoff(os.path.join(BASE, "shandi-v5", "index.html"))
            print("领星快照 %s: %d 个货件号 | 对碰范围 发货日期≥%s"
                  % (os.path.relpath(lx_path, BASE), len(lxmap), lx_cutoff))
        except Exception as e:
            print("领星快照读取失败(%s)，本次只用继承值：%s" % (lx_path, e))
            lxmap, lxmod = {}, {}
    else:
        print("未找到领星快照，本次「货件状态」只用 WorkBuddy 继承值")

    # ---- 领星「仓库接收时间」映射（回填送达日期用）----
    # 2026-11-02 小丁提、主管定：领星货件转 RECEIVING 时记的时间 = receiving_time（仓库开始接收），
    # 就是真正的到仓时刻；用它回填主表「送达日期」空值 + 新增「仓库接收时间」列。
    # ⚠ 不用 gmt_modified（「更新时间」列）：会被后续编辑刷新，且比 receiving_time 晚约 1 天。
    recv_map, recv_meta = {}, {}
    recv_path = args.lx_recv
    if args.no_lx_recv:
        recv_path = ""
        print("按 --no-lx-recv：本次不做系统侧回填（共享盘「送达时间」列是唯一事实源）")
    if not recv_path and not args.no_lx_recv:
        cand = os.path.join(BASE, "data", "lx_recv_time.json")
        if os.path.exists(cand):
            recv_path = cand
    if recv_path and os.path.exists(recv_path):
        try:
            import lx_recv_time as LXR
            recv_map, recv_meta = LXR.load_map(recv_path)
            # 防陈旧：映射文件比本次用的领星快照旧 → 直接按快照重建并落盘，
            # 保证回填用的是最新 receiving_time，不是一次性快照。
            snap_mt = os.path.getmtime(lx_path) if lx_path and os.path.exists(lx_path) else 0
            map_mt = os.path.getmtime(recv_path)
            if snap_mt and map_mt < snap_mt:
                print("  ⚠ 接收时间映射比领星快照旧（映射 %s < 快照 %s），按快照重建"
                      % (datetime.datetime.fromtimestamp(map_mt).strftime("%m-%d %H:%M"),
                         datetime.datetime.fromtimestamp(snap_mt).strftime("%m-%d %H:%M")))
                recv_map = LXR.build_map(lx_path)
                out = {"_meta": {"generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 "source": os.path.relpath(lx_path, BASE),
                                 "sourceMtime": datetime.datetime.fromtimestamp(snap_mt).strftime("%Y-%m-%d %H:%M:%S"),
                                 "shipments": len(recv_map),
                                 "withReceivingTime": len([1 for v in recv_map.values() if v.get("receiving_time")]),
                                 "field": "receiving_time（仓库开始接收时刻）；不用 gmt_modified（会被后续编辑刷新）"},
                       "map": recv_map}
                with io.open(recv_path, "w", encoding="utf-8") as fh:
                    json.dump(out, fh, ensure_ascii=False)
            print("领星接收时间映射 %s：%d 个货件（有 receiving_time %d 个）"
                  % (os.path.relpath(recv_path, BASE), len(recv_map),
                     len([1 for v in recv_map.values() if v.get("receiving_time")])))
        except Exception as e:
            print("领星接收时间映射读取失败(%s)，本次不回填：%s" % (recv_path, e))
            recv_map, recv_meta = {}, {}
    else:
        print("未找到领星接收时间映射，本次不回填「送达日期」")

    if not os.path.exists(SRC):
        raise SystemExit("缺 data/shipments_share.xlsx，先跑 sync_share_xlsx.ps1")
    sheets = read_sheets(SRC)
    print("共享盘: %d 个 tab" % len(sheets))

    old_main, sku_tbl = [], []
    if os.path.exists(old_path):
        rec = json.load(io.open(old_path, encoding="utf-8"))
        old_main = rec.get("main", [])
        sku_tbl = rec.get("sku", [])
        print("旧 records.json(%s): main %d / sku %d" % (os.path.basename(old_path), len(old_main), len(sku_tbl)))

    # ---- SKU 备货明细：改用领星 item_list（2026-11-02 小丁/主管定：SKU 明细换领星，切断 WorkBuddy 依赖）----
    # 领星 shipmentList.item_list 就是「SKU × 货件」级明细（quantity_shipped = 已发货），
    # 比 WorkBuddy 的 SKU 备货明细表更新及时、覆盖多。产物由 build_sku_from_lx.py 生成，
    # 比领星快照旧就按快照重建（保证每天跟最新领星一致）。
    sku_src = os.path.join(BASE, "data", "sku_from_lx.json")
    if lx_path and os.path.exists(lx_path):
        try:
            if (not os.path.exists(sku_src)) or os.path.getmtime(sku_src) < os.path.getmtime(lx_path):
                print("  ⚠ 领星 SKU 明细比领星快照旧 → 按快照重建")
                import build_sku_from_lx as BSL
                BSL.build(argparse.Namespace(
                    lx=lx_path, records=old_path, out=sku_src,
                    sku_index=os.path.join(BASE, "shandi-v5", "sku_index.json"),
                    fba_sku_index=os.path.join(BASE, "shandi-v5", "fba_sku_index.json"),
                    local_products=os.path.join(BASE, "wh_raw", "local_products.json"),
                    fba_inventory=os.path.join(BASE, "wh_raw", "fba_inventory.json"),
                    report=False))
            if os.path.exists(sku_src):
                d = json.load(io.open(sku_src, encoding="utf-8"))
                rows = d.get("sku") or []
                if rows:
                    sku_tbl = rows
                    print("SKU 备货明细换领星源：%d 行（%s）"
                          % (len(rows), (d.get("_meta") or {}).get("generatedAt", "")))
        except Exception as e:
            print("  ⚠ 领星 SKU 明细不可用（%s），本次沿用旧 SKU 表" % e)

    spec_map = spec_by_spu(old_main)
    print("箱规字典: %d 个款号" % len(spec_map))

    # 旧表索引：FBA货件号 → 记录列表（用于对账字段/送达日期/年份）
    by_fba = collections.defaultdict(list)
    for r in old_main:
        by_fba[str(r.get("FBA货件号") or "").strip()].append(r)

    def pick_old(fba, sku, qty):
        cands = by_fba.get(fba, [])
        if not cands:
            return None
        for c in cands:
            if str(c.get("SKU") or "").strip() == sku:
                return c
        if len(cands) == 1:
            return cands[0]
        cands = sorted(cands, key=lambda x: abs(num(x.get("件数")) - qty))
        return cands[0] if abs(num(cands[0].get("件数")) - qty) <= 1 else None

    merged, n_dui, n_new = [], 0, 0
    lx_stat, lx_written, lx_reports = {}, [], []
    n_recv_filled, recv_kept, recv_filled = 0, 0, []
    n_transit_recalc, n_transit_dropped = 0, 0
    n_transit_invalid = 0
    for name, hdr, recs in sheets:
        names = {}
        for ci, h in hdr.items():
            names.setdefault(h, ci)
        col = {}
        for key, alts in ALIAS.items():
            for a in alts:
                if a in names:
                    col[key] = names[a]
                    break
        remark_ci = names.get("备注")
        y, mth = ym_of(name)
        for r in recs:
            def g(key):
                ci = col.get(key)
                return str(r.get(ci, "") or "").strip() if ci else ""

            region, dw = g("region"), g("dw")
            if remark_ci is not None:
                rv = str(r.get(remark_ci, "") or "").strip()
                if rv and rv not in REGION_VALS:
                    if not dw:
                        dw = rv
                    region = ""
            fba, sku = g("fba"), g("sku")
            if not fba:
                continue
            qty, carton = to_int(g("qty")), to_int(g("carton"))
            o = pick_old(fba, sku, qty)

            # 年份（2026-11-02 修正）：**tab 推断优先**，旧记录只兜底。
            # 旧实现是「旧记录年份优先」——WorkBuddy 里 1月 tab 的 18 行发货日期记成了 2025-01-10，
            # 于是共享盘「1.10」被套成 2025-01-10，时效算出 400+ 天（领星收货在 2026-02/03，
            # 说明这批其实是 2026-01 发货）。现在 tab 认得月份就用 tab 年（11/12月=上一年，其余=今年），
            # 只有 tab 认不出月份时才用旧记录的年份。
            if not y and o and o.get("发货日期"):
                mm = re.match(r"^(\d{4})", str(o["发货日期"]))
                if mm:
                    y = int(mm.group(1))
            ship = iso_date(g("date"), y, mth)
            arrive_raw = g("arrive")
            arrive = iso_date(arrive_raw, y, mth)
            # 送达日期（2026-11-02 小丁定）：**共享盘新值优先**，旧 records.json 继承值兜底。
            # 共享盘「送达时间」列(U) 已由领星 receiving_time 回填（仓库接收时刻），
            # 那是时效口径的新事实源；旧值优先会把刚写回去的领星值盖掉。
            # 继承的旧值若是平台 ISO 串（"YYYY-MM-DDTHH:MMZ"，平台把东八区零点存成 UTC），
            # 一律按页面 d10() 的还原值统一成 YYYY-MM-DD：
            #   页面显示 = d10(旧值) = 还原值 → 换成纯日期后页面显示完全不变；
            #   但时效天数用哪个日期算会差 1 天，所以统一后才能和显示日期对得上。
            deliver = arrive or d10_py((o or {}).get("送达日期", ""))

            # 箱规 = 包装规格（20/4/30 双一箱），款号字典最准；字典没有才用旧记录单票值，
            # 都没有再按 件数÷箱数 比值推（文档口径兜底）
            toks = [t.upper() for t in tokens(sku)]
            hit = next((spec_map[t] for t in toks if t in spec_map), None)
            if hit is not None:
                spec = hit
            elif o and o.get("箱规") not in (None, "", 0):
                spec = o["箱规"]
            else:
                spec = guess_spec(toks, qty, carton, spec_map)

            # 总运费 = 物流费+报关费+拖车费+保险费（2026-10-30 起保险计入，见算法一致性说明 §三-B）
            # ⚠ 共享盘早期月份（1-3月等）的费用列是「合并单元格」：
            #   「物流费/报关费/拖车费」列是摊分到单票的值，但「总费用」列仍是整块总值，
            #   两者不同源、不能混用。所以总运费一律用四项重算，不用共享盘的总费用列，
            #   也不用旧记录继承值（不同源）。
            _has_fee = any(num(g(k)) > 0 for k in ("logi_fee", "customs", "cart", "insurance"))
            total_fee = num(g("logi_fee")) + num(g("customs")) + num(g("cart")) + num(g("insurance"))

            rec = {
                "FBA货件号": fba,
                "SKU": sku,
                "_id": (o or {}).get("_id", ""),
                "仓库代码": re.sub(r"[^A-Za-z0-9]", "", g("wh")),
                "件数": qty,
                "箱数": carton,
                "箱规": spec,
                "单价": num(g("price")),
                "物流费": num(g("logi_fee")),
                "报关费": num(g("customs")),
                "保险": num(g("insurance")),
                "拖车费": num(g("cart")),
                "货拉拉费": (o or {}).get("货拉拉费", 0),
                "总运费": total_fee,
                "发货日期": ship,
                "送达日期": deliver,
                "送达时间": arrive,
                "地区": region,
                "船型": ship_type_norm(g("ship_type")),
                "船型原文": ship_type_raw_keep(g("ship_type")),
                "船名航次": (o or {}).get("船名航次", ""),
                "货代": g("agent"),
                "货代进仓号": g("entry_no"),
                "报关单号": g("decl"),
                "进仓编号": g("entry_no"),
                "月份": name,
                "计费重量": num(g("fee_weight")),
                "备注": dw,
                "运营": g("owner"),
                # 保险为可选附加项：金额计入总运费，但不作为「费用完整」的必需项
                # （共享盘里绝大多数票没有保险，纳入必需项会导致全部票被判为未确认价格）
                # 费用完整 = 共享盘里物流费/报关费/拖车费三项都有值；
                # 若共享盘这三列整列为空（合并单元格未摊分到本票），则沿用旧记录的判定。
                "费用完整": (bool(num(g("logi_fee")) and num(g("customs")) and num(g("cart")))
                             if _has_fee else bool((o or {}).get("费用完整"))),
                # 共享盘「总费用」列是整块总值（早期月份合并单元格），与摊分后的分项不同源，
                # 仅作留档，不参与总运费计算。
                "共享盘总费用": num(g("total_fee")),
            }
            # 时效天数 / 全程天数（2026-11-02 小丁定：**按新的送达日期全部重算**）
            # 原来是从旧 records.json 继承旧值、只在缺失时才算 —— 那是「人工/账单旧口径」，
            # 共享盘「送达时间」列换成领星 receiving_time（仓库接收时刻）后必须全量重算，
            # 否则页面功能③的时效（effTransit 优先读「时效天数」列）还是旧口径。
            # 重算口径：发货日期 → 送达日期；任一缺失就没有时效，留空。
            rec["时效天数"] = ""
            rec["全程天数"] = ""
            if ship and deliver:
                try:
                    a = datetime.date(*[int(x) for x in str(ship)[:10].split("-")])
                    b = datetime.date(*[int(x) for x in str(deliver)[:10].split("-")])
                    days = (b - a).days
                    if days < 0:
                        # 送达早于发货 = 源数据矛盾（如共享盘 1月 tab 那行 RVSDGF-251223-0001
                        # 的发货日期写成 2026-12-27），不落负时效，只记一笔留给源数据修正。
                        n_transit_invalid += 1
                    else:
                        rec["时效天数"] = days
                        rec["全程天数"] = days
                        n_transit_recalc += 1
                except Exception:
                    pass
            elif (o or {}).get("时效天数") not in (None, ""):
                # 没有新送达日期 → 旧值作废（口径要统一），但记一笔便于核对
                n_transit_dropped += 1
            for dk in DKEYS:
                rec[dk] = (o or {}).get(dk, "")
            # WorkBuddy 专有字段（货件状态/物流状态/入仓日期/到港日期/船开日期/海运天数/渠道）：
            # 共享盘没有这些列，只能从匹配的旧记录继承。匹配不到就留空（新批次票本来就没有）。
            for dk in INHERIT_KEYS:
                rec[dk] = (o or {}).get(dk, "") or ""
            # ---- 领星状态直接覆盖「货件状态」 ----
            # 小丁 2026-10-30 口径：主表「货件状态」的事实源是领星 API 的 shipment_status，
            # 不是 WorkBuddy（那边一周才同步一次）。所以继承值只是兜底，建表阶段用领星覆盖。
            # 判定规则照抄 lx_status.py（与 ex/1-main/.../lx_sync_status.py 同口径）：
            # 到仓=RECEIVING/CLOSED/DELIVERED；终止态不写只报；领星在途但超 60 天未更新=陈旧不写只报。
            if lxmap:
                try:
                    import lx_status as LX
                    r = LX.resolve_record(rec, lxmap, lxmod, cutoff=lx_cutoff)
                    lx_stat[r["action"]] = lx_stat.get(r["action"], 0) + 1
                    if r["action"] == "write":
                        rec["货件状态"] = r["new"]
                        lx_written.append({"fba": rec.get("FBA货件号"), "old": r["old"],
                                           "new": r["new"], "reason": r["reason"]})
                    elif r["action"] in ("terminal", "stale"):
                        lx_reports.append({"fba": rec.get("FBA货件号"), "old": r["old"],
                                           "action": r["action"], "reason": r["reason"]})
                except Exception as e:
                    print("  ⚠ 单行领星对碰异常（跳过该行）：%s" % e)
            # ---- 领星「仓库接收时间」回填 ----
            # 2026-11-02 小丁提、主管定：领星 receiving_time = 仓库开始接收时刻 = 真正的到仓时间。
            # 规则：① 「仓库接收时间」列一律写领星原值（有就写，没有就空）；
            #       ② 「送达日期」列**只填空值**，已有的人工/账单值一字不动（两套语义不同，
            #          全量换不换等小丁定）；新回填的值写成纯日期 YYYY-MM-DD。
            if recv_map:
                rids = [x.strip().upper() for x in str(fba or "").split("&") if x.strip()]
                rinfo = None
                for rid in rids:
                    v = recv_map.get(rid)
                    if v and v.get("receiving_time"):
                        rinfo = v
                        break
                if rinfo:
                    rec["仓库接收时间"] = rinfo["receiving_time"]
                    if not str(rec.get("送达日期") or "").strip():
                        rd = str(rinfo["receiving_time"])[:10]
                        if len(rd) == 10:
                            rec["送达日期"] = rd
                            n_recv_filled += 1
                            recv_filled.append({
                                "FBA货件号": fba, "SKU": sku,
                                "送达日期": rd,
                                "仓库接收时间": rinfo["receiving_time"],
                                "货件状态": rec.get("货件状态"),
                                "月份": name,
                            })
                        else:
                            rec["仓库接收时间"] = ""
                    else:
                        recv_kept += 1
                else:
                    rec["仓库接收时间"] = ""
            else:
                rec["仓库接收时间"] = ""
            if o and any(rec.get(dk) not in (None, "") for dk in DKEYS):
                n_dui += 1
            else:
                n_new += 1
            merged.append(rec)

    out = {"main": merged, "sku": sku_tbl,
           "_meta": {"fetchedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "source": "shared-drive shipments + WorkBuddy reconciliation",
                     "shareRows": len(merged), "duiMerged": n_dui, "newRows": n_new}}

    # ---------- 写出：先写临时文件 → 校验 → 原子替换 ----------
    # ⚠ --old 与 --out 默认是同一个 records.json：直接 open(out,"w") 会在中途失败时把源写坏。
    # 改成先写 .tmp，校验通过后再 os.replace 原子替换，源文件要么是旧的要么是新的，不会半截。
    tmp_path = out_path + ".tmp"
    with io.open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)

    # 校验：能读回、行数对得上、关键字段没整体丢失，才允许替换正式文件
    check = json.load(io.open(tmp_path, encoding="utf-8"))
    cm = check.get("main") or []
    if len(cm) != len(merged):
        os.remove(tmp_path)
        raise SystemExit("写出校验失败：回读行数 %d ≠ 期望 %d，已放弃替换（正式文件未动）"
                         % (len(cm), len(merged)))
    # 货件状态等继承字段的整体健康度：旧表有值而新表全空 → 判定继承失败，拒绝替换
    for dk in INHERIT_KEYS:
        old_n = len([r for r in old_main if str(r.get(dk) or "").strip()])
        new_n = len([r for r in cm if str(r.get(dk) or "").strip()])
        if old_n > 0 and new_n == 0:
            os.remove(tmp_path)
            raise SystemExit("写出校验失败：字段「%s」旧表 %d 条有值、新表 0 条（继承失败），"
                             "已放弃替换（正式文件未动）" % (dk, old_n))
    # ⚠ 兜底：--old 默认指向同一个 records.json。若它本身已经是坏的（继承字段整列为空），
    # 上一条校验会因「旧表也全空」而放行，坏数据照样发布。因此对关键字段加绝对基线：
    # 货件状态必须有值（页面「全部在途」汇总的唯一判据），否则拒绝替换。
    for dk, min_n in (("货件状态", 1),):
        new_n = len([r for r in cm if str(r.get(dk) or "").strip()])
        if new_n < min_n:
            os.remove(tmp_path)
            raise SystemExit("写出校验失败：字段「%s」新表非空记录数 %d < 基线 %d，"
                             "已放弃替换（正式文件未动）。请先修 WorkBuddy 主表回源，"
                             "或用 --old 指向一份含该字段的旧 records.json。" % (dk, new_n, min_n))
    os.replace(tmp_path, out_path)

    p = out_path
    print("写出 %s (%d bytes)  [临时文件校验通过后原子替换]" % (p, os.path.getsize(p)))
    print("  main %d 行 | 对账字段命中 %d | 无对账(新批次) %d | sku %d" % (len(merged), n_dui, n_new, len(sku_tbl)))
    print("  件数 %.0f | 总运费 %.0f | 有送达日期 %d | 箱规 %s" % (
        sum(r["件数"] for r in merged), sum(r["总运费"] for r in merged),
        len([r for r in merged if r.get("送达日期")]),
        dict(collections.Counter(str(r.get("箱规")) for r in merged))))
    print("  继承字段命中：%s" % ("；".join(
        "%s %d/%d" % (dk, len([r for r in merged if str(r.get(dk) or "").strip()]), len(merged))
        for dk in INHERIT_KEYS)))
    print("  时效天数：按新送达日期重算 %d 行 | 无送达日期（旧值作废）%d 行 | 送达早于发货（不落库）%d 行 | 有时效 %d 行"
          % (n_transit_recalc, n_transit_dropped, n_transit_invalid,
             len([r for r in merged if str(r.get("时效天数") or "").strip()])))
    if lxmap:
        print("  领星覆盖：写 %d | 动作统计 %s"
              % (len(lx_written), json.dumps(lx_stat, ensure_ascii=False)))
        for w in lx_written[:5]:
            print("     · %s  %s → %s  (%s)" % (str(w["fba"])[:36], w["old"] or "(空)", w["new"], w["reason"]))
        if lx_reports:
            print("  领星只报不写 %d 条：" % len(lx_reports))
            for t in lx_reports[:5]:
                print("     · %s  主表=%s  %s" % (str(t["fba"])[:36], t["old"] or "(空)", t["reason"]))
    if recv_map:
        print("  领星接收时间回填：新填「送达日期」%d 行 | 已有值保留未覆盖 %d 行 | 「仓库接收时间」列已写"
              % (n_recv_filled, recv_kept))
        if recv_filled:
            lst = os.path.join(BASE, "data", "recv_time_filled.json")
            d2 = os.path.dirname(lst)
            if d2 and not os.path.exists(d2):
                os.makedirs(d2)
            with io.open(lst, "w", encoding="utf-8") as fh:
                json.dump({"_meta": {"generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                     "count": len(recv_filled),
                                     "source": os.path.relpath(recv_path, BASE) if recv_path else "",
                                     "field": "receiving_time"},
                           "rows": recv_filled}, fh, ensure_ascii=False)
            print("  回填清单 → %s（%d 行）" % (lst, len(recv_filled)))
            for t in recv_filled[:5]:
                print("     · %s %s → 送达日期=%s（仓库接收 %s，状态 %s）"
                      % (str(t["FBA货件号"])[:36], str(t["SKU"])[:18], t["送达日期"],
                         t["仓库接收时间"], t["货件状态"]))


if __name__ == "__main__":
    main()
