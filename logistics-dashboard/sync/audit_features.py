# -*- coding: utf-8 -*-
"""三个关联功能的准确性核对（2026-10-30 用户点名：这三个会联动别的功能，必须每次都对）。

核对对象：
  ① SKU成本统计        —— 卡片②，engineSkuCost：命中 priced 记录汇总运费 ÷ 汇总件数 = 单件运费
  ② 时间范围平均运费（按地区）—— 卡片③，engineAverage：按地区算 平均运费单价 = Σ(单价×计费重量)/Σ计费重量
  ③ SKU批次在途（备货联动）—— 卡片⑥，build()+renderBatchGrid：按批次汇总 入仓/在途 双数、到货推算

做法（三层，互相独立）：
  第 1 层 源侧独立复算：拿回源快照（WorkBuddy 原始记录）按上面口径自己算一遍
  第 2 层 站侧独立复算：拿站点在用的 records.json 按同一口径自己算一遍
  第 3 层 页面真值：用 py_mini_racer 直接跑 index.html 里原封不动的 JS 函数（engineSkuCost/engineAverage）

判定：
  · 第 3 层 ≠ 第 2 层  → 页面算错（页面 JS 与口径复算对不上）
  · 第 1 层 ≠ 第 2 层  → 源≠站（同步链路问题）；再回源看字段本身是否自相矛盾 → 源数据错
  页面 JS 由 index.html 现场抽取，页面改了这里立刻跟着变，不会各写一套。
"""
import io
import json
import os
import re
import sys
import datetime

sys.stdout.reconfigure(encoding="utf-8")

WS = os.path.dirname(os.path.abspath(__file__))
PAGE_HTML = os.path.join(WS, "shandi-v5", "index.html")

REGION_BY_LABEL = {"美西": "us_west", "美东": "us_east", "美中": "us_central", "未知": "unknown"}
REGION_ALL = ["us_west", "us_east", "us_central", "unknown"]
REGION_LABELS = {"us_west": "美西", "us_east": "美东", "us_central": "美中", "unknown": "未知"}

# 统一口径（2026-10-30 用户定，页面同步中）：地区按「前缀归属」——
# 美西*→us_west，美东*→us_east，美中*→us_central；空值与其余标签→unknown。
# 页面当前 index.html:4272 仍是精确匹配 REGION_BY_LABEL[row["地区"]]，
# 所以抽检时源复算一律用本前缀规则，页面侧差异标注「页面地区映射口径未同步」而非系统异常。
REGION_PREFIX_RULES = (("美西", "us_west"), ("美东", "us_east"), ("美中", "us_central"))
# 页面文件读一次就够，缓存住避免每条记录都重扫 index.html
_PAGE_REGION_MAP = None
_PAGE_REGION_MODE = None


def region_label_status(label):
    """返回 (归属地区, 是否未映射标签)。

    统一口径（用户 2026-10-30 定，页面同步中）：
      空值            → unknown，非未映射（单独算「地区为空」一类计数）
      美西*/美东*/美中* → 对应地区，含子标签（美东南/美中北/美中南…）
      其余非空标签     → unknown，且是未映射标签（计入源数据质量缺口）
    """
    s = str(label or "").strip()
    if not s:
        return "unknown", False
    for pre, reg in REGION_PREFIX_RULES:
        if s.startswith(pre):
            return reg, False
    return "unknown", True


def region_by_prefix(label):
    """统一口径：地区前缀归属。空值 / 未映射标签 → unknown。"""
    return region_label_status(label)[0]


def unknown_bucket_stats(recs):
    """统计记录里的「未知」地区桶：总数 / 其中空标签 / 其中非空未映射标签。"""
    unk = [r for r in (recs or []) if r.get("region") == "unknown"]
    empty = sum(1 for r in unk if not str(r.get("region_label") or "").strip())
    return {"unknown": len(unk), "empty": empty, "unmapped": len(unk) - empty}


def page_region_map():
    """从 index.html 抽页面在用的 REGION_BY_LABEL（抽不到用兜底字典）。"""
    global _PAGE_REGION_MAP
    if _PAGE_REGION_MAP is not None:
        return _PAGE_REGION_MAP
    m = dict(REGION_BY_LABEL)
    if os.path.exists(PAGE_HTML):
        try:
            src = io.open(PAGE_HTML, encoding="utf-8").read()
            vm = re.search(r"var\s+REGION_BY_LABEL\s*=\s*\{([^}]*)\}", src)
            if vm:
                pairs = re.findall(r"\"([^\"]+)\"\s*:\s*\"([^\"]+)\"", vm.group(1))
                if pairs:
                    m = {k: v for k, v in pairs}
        except Exception:
            pass
    _PAGE_REGION_MAP = m
    return m


def _extract_func_any(src, name):
    """抽函数：兼容 function name(...) 和 var name = function(...) 两种写法。"""
    code = _extract_func(src, name)
    if code:
        return code
    m = re.search(r"(?:var|let|const)\s+%s\s*=\s*function\s*\(" % re.escape(name), src)
    if not m:
        return None
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    return None


def _is_prefix_region_body(body):
    """判断一个函数体是否做「前缀归属」（而不是精确查表）。"""
    if not body:
        return False
    if re.search(r"startsWith\(\s*[\"']美[东西中][\"']", body):
        return True
    if re.search(r"indexOf\(\s*[\"']美[东西中][\"']\s*\)\s*===?\s*0", body):
        return True
    if re.search(r"slice\(\s*0\s*,\s*\d\s*\)\s*===?\s*[\"']美[东西中][\"']", body):
        return True
    return False


def page_region_mode():
    """探测 index.html 当前地区映射口径：prefix（前缀归属）/ exact（精确匹配）。

    只看 normRow 里 region: 那一行实际怎么取地区：
      region: REGION_BY_LABEL[row["地区"]] → exact
      region: regionOf(row["地区"])          → 看 regionOf 函数体是不是前缀归属
    """
    global _PAGE_REGION_MODE
    if _PAGE_REGION_MODE is not None:
        return _PAGE_REGION_MODE
    mode = "exact"
    if os.path.exists(PAGE_HTML):
        try:
            src = io.open(PAGE_HTML, encoding="utf-8").read()
            seg = _extract_func(src, "normRow") or src
            m = re.search(r"region\s*:\s*([^\n,]+)", seg)
            expr = m.group(1) if m else ""
            if "REGION_BY_LABEL[" in expr:
                mode = "exact"          # 页面直接查表 = 精确匹配
            else:
                hm = re.search(r"([A-Za-z_$][\w$]*)\s*\(", expr)
                if hm:
                    body = _extract_func_any(src, hm.group(1))
                    mode = "prefix" if _is_prefix_region_body(body) else "exact"
        except Exception:
            mode = "exact"
    _PAGE_REGION_MODE = mode
    return mode


def resolve_region(label, mode="page"):
    """按指定口径解析地区。mode: page（镜像页面）/ prefix（统一前缀口径）。"""
    if mode == "prefix":
        return region_by_prefix(label)
    if mode == "page":
        mode = page_region_mode()
        if mode == "prefix":
            return region_by_prefix(label)
    return page_region_map().get(str(label or "").strip(), "unknown")

# 批次在途用到的页面常量：运行时从 index.html 抽，抽不到才用这里的兜底值
DEFAULT_PAGE_CONST = {
    "SAILING_WAIT": 5, "CUSTOMS_DAYS": 3, "FBA_PICKUP_DAYS": 7, "DEPARTURE_DELAY": 15,
    "landDays": {"us_west": 28, "us_central": 33, "us_east": 43, "unknown": 40},
}


# ---------------------------------------------------------------- 基础工具
def num(v):
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except Exception:
        return None
    return n if n == n else None


def d10(v):
    """还原平台把本地零点存成 UTC 前一天 16:00 的日期（与页面 d10 一致）。"""
    if v is None:
        return ""
    s = str(v)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", s)
    if m:
        t = (datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                int(m.group(4)), int(m.group(5)), tzinfo=datetime.timezone.utc)
             + datetime.timedelta(hours=8))
        return t.strftime("%Y-%m-%d")
    return s[:10]


def split_skus(s):
    return [x.strip() for x in str(s or "").split("&") if x.strip()]


def norm_sku(s):
    return str(s or "").strip().upper()


# ------------------------------------------------------- 页面口径：normRow
def norm_records(main_rows, region_mode="page"):
    """把主表原始行转成页面在用的记录结构（照抄页面 normRow，index.html:4257）。

    region_mode:
      page   —— 镜像页面当前的映射口径（页面改了就跟着变，用于「页面真值 vs 复算」对账）
      prefix —— 统一口径（前缀归属：用户 2026-10-30 定，页面同步中），用于源侧复算
    """
    out = []
    for row in main_rows or []:
        bs = row.get("箱规")
        out.append({
            "source_sheet": row.get("月份") or "",
            "sku": row.get("SKU") or "",
            "warehouse_code": row.get("仓库代码") or "",
            "wh_no": row.get("进仓编号") or "",
            "ship_date": d10(row.get("发货日期")),
            "ship_type": row.get("船型") or "",
            "total_freight": num(row.get("总运费")),
            "quantity": num(row.get("件数")),
            "box_count": num(row.get("箱数")),
            "unit_price": num(row.get("单价")),
            "chargeable_weight": num(row.get("计费重量")),
            "region": resolve_region(row.get("地区"), region_mode),
            "region_label": str(row.get("地区") or "").strip(),
            "box_spec": None if bs in (None, "") else num(bs),
            "transit_days": num(row.get("时效天数")),
            "fees_complete": row.get("费用完整") in ("是", True, "true"),
            "shandi_status": row.get("物流状态") or "",
            "shandi_deliver_date": d10(row.get("入仓日期")),
            "delivery_window": row.get("货件状态") or "",
            "channel": row.get("渠道") or "",
            "rc_channel": row.get("对账渠道") or "",
            "rc_vessel": row.get("船名航次") or "",
            "rc_etd": d10(row.get("船开日期")),
            "rc_eta": d10(row.get("到港日期")),
            "rc_deliver_date": d10(row.get("送达日期")),
            "fba": row.get("FBA货件号") or "",
        })
    return out


# ------------------------------------------- ① SKU成本统计（engineSkuCost）
def sku_aggregate(sub):
    """页面 skuAggregate（index.html:4591）：价格未确认的货件整条排除。"""
    tf = qty = box = 0.0
    n = un_r = un_q = 0.0
    for r in sub:
        if r.get("total_freight") is not None:
            tf += float(r.get("total_freight") or 0)
            qty += float(r.get("quantity") or 0)
            box += float(r.get("box_count") or 0)
            n += 1
        else:
            un_r += 1
            un_q += float(r.get("quantity") or 0)
    return {
        "record_count": n, "total_quantity": qty, "total_box_count": box,
        "unpriced_records": un_r, "unpriced_quantity": un_q,
        "total_freight": round(tf, 2),
        "per_unit_freight": (round(tf / qty * 10000) / 10000) if qty > 0 else None,
    }


def engine_sku_cost(recs, sku, ship_type=None, time_range=None, target_month=None):
    """页面 engineSkuCost（index.html:4613）的 Python 复刻。"""
    time_recs = recs
    if target_month:
        time_recs = [r for r in recs if r.get("source_sheet") == target_month]
    if ship_type == "快船":
        time_recs = [r for r in time_recs if "快" in (r.get("ship_type") or "")]
    elif ship_type == "普船":
        time_recs = [r for r in time_recs if "快" not in (r.get("ship_type") or "")]

    tokens = [norm_sku(t) for t in split_skus(sku) if norm_sku(t)]
    matched, mode = [], "none"
    if len(tokens) > 1:
        matched = [r for r in time_recs if all(t in [norm_sku(x) for x in split_skus(r.get("sku"))] for t in tokens)]
        if matched:
            mode = "mixed"
        else:
            matched = [r for r in time_recs if any(t in [norm_sku(x) for x in split_skus(r.get("sku"))] for t in tokens)]
            if matched:
                mode = "mixed_union"
    if not matched and tokens:
        matched = [r for r in time_recs if tokens[0] in [norm_sku(x) for x in split_skus(r.get("sku"))]]
        if matched:
            mode = "exact"
    if not matched and tokens:
        matched = [r for r in time_recs
                   if any(t in norm_sku(r.get("sku")) or norm_sku(r.get("sku")) in t
                          for t in [norm_sku(x) for x in split_skus(r.get("sku"))])]
        if matched:
            mode = "fuzzy"
    agg = sku_aggregate(matched)
    return {"mode": mode, "matched": len(matched), "agg": agg, "matched_rows": matched}


# ------------------------------------------- 页面「全部在途（主表实时）」复算
# 页面 computeAllTransit（index.html）：在途 = 货件状态判定为「在途」
# 且发货日期 ≥ TRANSIT_CUTOFF(2026-07-01)。货件状态来自主表 delivery_window 字段。
TRANSIT_CUTOFF = "2026-07-01"


def compute_all_transit(recs, cutoff=TRANSIT_CUTOFF):
    """页面 computeAllTransit 的 Python 复刻：在途票数/件数/地区分布/船型分布。"""
    total_qty = 0.0
    rec_count = 0
    sku_set, fba_set = set(), set()
    region = {}
    ship = {"快船": 0, "普船": 0}
    for r in recs or []:
        if dw_dim(r.get("delivery_window")) != "在途":
            continue
        sd = r.get("ship_date") or ""
        if not sd or sd < cutoff:
            continue
        rec_count += 1
        q = num(r.get("quantity")) or 0.0
        total_qty += q
        for t in split_skus(r.get("sku")):
            sku_set.add(norm_sku(t))
        for t in str(r.get("fba") or "").split("&"):
            t = t.strip().upper()
            if t:
                fba_set.add(t)
        reg = r.get("region") or "unknown"
        region.setdefault(reg, {"qty": 0.0, "count": 0})
        region[reg]["qty"] += q
        region[reg]["count"] += 1
        st = r.get("ship_type") or ""
        ship["快船" if "快" in st else "普船"] += 1
    return {"rec_count": rec_count, "total_qty": total_qty,
            "sku_count": len(sku_set), "fba_count": len(fba_set),
            "region": region, "ship": ship}


# ------------------------------- ② 时间范围平均运费（按地区）（engineAverage）
def category_of(r):
    """页面 categoryOf（index.html:4445）：件数÷箱数 比值划品类。"""
    q = float(r.get("quantity") or 0)
    b = float(r.get("box_count") or 0)
    if not q or not b:
        return "其他"
    ratio = q / b
    if 16 < ratio <= 20:
        return "单鞋"
    if 27 < ratio <= 30:
        return "凉鞋"
    if 3 < ratio <= 5:
        return "靴子"
    return "其他"


def engine_average(recs, cat_filter=None, range_months=12, now=None):
    """页面 engineAverage（index.html:4423）的 Python 复刻：按地区算平均运费单价等。"""
    now = now or datetime.date.today()
    ny, nm = now.year, now.month
    filtered = []
    for r in recs:
        sd = r.get("ship_date")
        try:
            d = datetime.date.fromisoformat(sd) if sd else None
        except Exception:
            d = None
        if not d:
            filtered.append(r)
            continue
        diff = (ny - d.year) * 12 + (nm - d.month)
        if 0 <= diff < range_months:
            filtered.append(r)

    valid = [r for r in filtered
             if r.get("fees_complete") and r.get("total_freight") is not None
             and r.get("quantity") is not None and float(r.get("quantity")) > 0]
    if cat_filter:
        valid = [r for r in valid if category_of(r) == cat_filter]

    bucket = {}
    for r in valid:
        k = r.get("region")
        b = bucket.setdefault(k, {"tf": 0.0, "qty": 0.0, "count": 0, "wsum": 0.0, "wqty": 0.0})
        b["tf"] += float(r.get("total_freight") or 0)
        b["qty"] += float(r.get("quantity") or 0)
        b["count"] += 1
        up, cw = r.get("unit_price"), r.get("chargeable_weight")
        if up is not None and cw is not None and float(cw) > 0:
            b["wsum"] += float(up) * float(cw)
            b["wqty"] += float(cw)
        bd = b.setdefault("_bd", {})
        sb = bd.setdefault(r.get("ship_type") or "", {"tf": 0.0, "qty": 0.0, "count": 0, "wsum": 0.0, "wqty": 0.0})
        sb["tf"] += float(r.get("total_freight") or 0)
        sb["qty"] += float(r.get("quantity") or 0)
        sb["count"] += 1
        if up is not None and cw is not None and float(cw) > 0:
            sb["wsum"] += float(up) * float(cw)
            sb["wqty"] += float(cw)

    items = []
    for reg in REGION_ALL:
        b = bucket.get(reg)
        if not b or b["qty"] == 0:
            continue
        bd = b.get("_bd", {})
        items.append({
            "region": reg,
            "average_unit_price": (round(b["wsum"] / b["wqty"] * 100) / 100) if b["wqty"] > 0 else None,
            "record_count": b["count"],
            "weighted_quantity": b["qty"],
            "total_freight": round(b["tf"], 2),
            "breakdown": {st: {"average_unit_price": (round(d["wsum"] / d["wqty"] * 100) / 100) if d["wqty"] > 0 else None,
                               "record_count": d["count"]}
                          for st, d in bd.items()},
        })
    return {"total_records": len(filtered), "valid_records": len(valid), "items": items,
            "valid_rows": valid}


# --------------------------------- ③ SKU批次在途（备货联动）（build + renderBatchGrid）
def dw_dim(dw):
    """页面 dwDim（index.html:6738）：货件状态 → 在途 / 入仓。"""
    s = str(dw or "").strip().upper()
    if not s:
        return None
    if s in ("SHIPPED", "IN_TRANSIT", "INTRANSIT", "WORKING", "READY_TO_SHIP", "UNCONFIRMED", "待预约", "派送预约"):
        return "在途"
    if s in ("RECEIVING", "CHECKED_IN", "CLOSED", "正在接收", "已入仓", "货件关闭", "上架", "已关闭"):
        return "入仓"
    return None


def build_batches(sku_rows, records, page_const=None, today=None):
    """页面 build()（index.html:7055）+ renderBatchGrid 的批次口径复刻。

    sku_rows: SKU备货明细行（需含 货件单号 / SKU / 已发货）
    返回：批次维度 的 入仓/在途 双数、货件数、SKU 数、批次明细
    """
    pc = dict(DEFAULT_PAGE_CONST)
    if page_const:
        pc.update(page_const)
    land = dict(pc["landDays"])
    delay = pc["DEPARTURE_DELAY"]

    fba_map = {}
    for r in records:
        for f in str(r.get("fba") or "").split("&"):
            f = f.strip().upper()
            if f:
                fba_map.setdefault(f, []).append(r)

    # 页面 build() 会用「对账单 开船日→送达日」的实际海运天数覆盖默认 landDays（样本≥3 才覆盖）
    acc = {}
    for r in records:
        etd, dl = r.get("rc_etd"), r.get("rc_deliver_date")
        if not etd or not dl:
            continue
        try:
            d = (datetime.date.fromisoformat(dl) - datetime.date.fromisoformat(etd)).days
        except Exception:
            continue
        if 0 < d < 150:
            acc.setdefault(r.get("region") or "unknown", []).append(d)
    for g, arr in acc.items():
        if len(arr) >= 3:
            land[g] = int(round(sum(arr) / len(arr)))

    def norm_sku_row(row):
        qty_raw = row.get("已发货")
        if qty_raw in (None, ""):
            qty_raw = row.get("已发货数量")
        try:
            qty = float(qty_raw)
        except Exception:
            qty = 0.0
        return {"fba": str(row.get("货件单号") or "").strip(),
                "sku": str(row.get("SKU") or "").strip(),
                "qty": qty}

    lines = [norm_sku_row(r) for r in (sku_rows or [])]
    lines = [l for l in lines if l["fba"] and l["sku"]]

    meta = {}
    for f, rs in fba_map.items():
        ships = sorted([r.get("ship_date") for r in rs if r.get("ship_date")])
        dls = sorted([r.get("rc_deliver_date") for r in rs if r.get("rc_deliver_date")])
        region = "unknown"
        for r in rs:
            if r.get("region") and r["region"] != "unknown":
                region = r["region"]
                break
        dw = next((r.get("delivery_window") for r in rs if r.get("delivery_window")), None)
        meta[f] = {"ship": ships[0] if ships else None,
                   "deliver": dls[-1] if dls else None,
                   "region": region, "delivery_window": dw}

    # 2026-11-02 用户定：页面放开「最近3个月」窗口，改成「只显示还在途的货件」
    # （已入仓的老批次不显示；还没入仓的老批次照样显示）。
    keep = []
    for l in lines:
        m = meta.get(l["fba"].upper())
        if not m:
            m = {"ship": None, "deliver": None, "region": "unknown", "delivery_window": None}
        if not m["ship"]:
            continue
        l["meta"] = m
        l["batchKey"] = m["ship"][5:10]
        l["arrived"] = (dw_dim(m["delivery_window"]) == "入仓") or bool(m["deliver"])
        if l["arrived"]:
            continue                      # 只显示还在途的货件
        l["eta"] = (datetime.date.fromisoformat(m["ship"]) + datetime.timedelta(days=land.get(m["region"], 40) + delay)).isoformat()
        keep.append(l)

    by_batch = {}
    for l in keep:
        by_batch.setdefault(l["batchKey"], []).append(l)

    batches = []
    for bk in sorted(by_batch.keys()):
        ls = by_batch[bk]
        total = sum(l["qty"] for l in ls)
        arrived = sum(l["qty"] for l in ls if l["arrived"])
        regs = {}
        for l in ls:
            regs[l["meta"]["region"]] = regs.get(l["meta"]["region"], 0.0) + l["qty"]
        main_reg = max(regs.items(), key=lambda x: x[1])[0] if regs else "unknown"
        pend = [l for l in ls if not l["arrived"]]
        # 批次预计到仓 = 未入仓行里最早的发货日 + 该批次主体地区海运天数 + 发货前置天数
        # （与页面 pendingEta 同口径：region 取按件数占比最大的地区，不用逐行最小值）
        ship_dates = sorted(l["meta"]["ship"] for l in pend if l["meta"].get("ship"))
        eta = None
        if ship_dates:
            eta = (datetime.date.fromisoformat(ship_dates[0])
                   + datetime.timedelta(days=land.get(main_reg, 40) + delay)).isoformat()
        batches.append({
            "batch": bk, "total": total, "arrived": arrived, "in_transit": total - arrived,
            "lines": len(ls), "skus": len({l["sku"] for l in ls}), "fbas": len({l["fba"] for l in ls}),
            "region": main_reg, "eta": eta,
        })
    # 命中记录：批次实际用到的主表记录（供「未知地区桶」统计）
    hit_fbas = {str(l["fba"] or "").strip().upper() for l in keep}
    hit_records = [r for fba, rs in fba_map.items() if fba in hit_fbas for r in rs]
    return {"lines_total": len(keep), "lines_dropped": len(lines) - len(keep),
            "batches": batches, "hit_records": hit_records}


# ------------------------------------------------------------ 页面 JS 真值
def _extract_func(src, name):
    m = re.search(r"function\s+%s\s*\(" % re.escape(name), src)
    if not m:
        return None
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    return None


def _extract_var(src, pattern):
    m = re.search(pattern, src)
    return m.group(0) if m else None


def page_constants():
    """从 index.html 抽批次在途用的常量（抽不到用兜底值）。"""
    const = dict(DEFAULT_PAGE_CONST)
    if not os.path.exists(PAGE_HTML):
        return const
    src = io.open(PAGE_HTML, encoding="utf-8").read()
    for key in ("SAILING_WAIT", "CUSTOMS_DAYS", "FBA_PICKUP_DAYS", "DEPARTURE_DELAY"):
        m = re.search(r"var\s+%s\s*=\s*(-?\d+)" % key, src)
        if m:
            const[key] = int(m.group(1))
    m = re.search(r"var\s+landDays\s*=\s*\{([^}]*)\}", src)
    if m:
        ld = {}
        for k, v in re.findall(r"(\w+)\s*:\s*(\d+)", m.group(1)):
            ld[k] = int(v)
        if ld:
            const["landDays"] = ld
    return const


JS_FUNCS = ["num", "d10", "parseDate", "monthRangeFilter", "isFast", "effTransit", "avg1",
            "recentTransitStats", "splitSkus", "normSku", "recTokens", "skuAggregate",
            "monthKey", "normRow", "engineSkuCost", "engineAverage"]
# 地区归属函数：页面用 regionOf(label) 做前缀归属（开发 2026-10-30 同步），
# 老版本页面没有这个函数（直接 REGION_BY_LABEL 精确匹配），抽不到就跳过。
JS_REGION_FUNCS = ["regionOf"]
JS_VARS = [
    r"var\s+REGION_LABELS\s*=\s*\{[^}]*\}",
    r"var\s+REGION_BY_LABEL\s*=\s*\{[^}]*\}",
    r"var\s+REGION_ALL\s*=\s*\[[^\]]*\]",
    r"var\s+MONTHS_OF\s*=\s*\{[^}]*\}",
]

# ③ 批次在途：直接调用页面自己的判定函数（dwDim / lineArrived / sumArrived /
# pendingEta / batchRegion / addDaysStr），只把编排（build 的组装过程）在 harness 里重写一遍
JS_BATCH_FUNCS = ["dwDim", "fbaDim", "lineArrived", "pendingLines", "sumArrived", "pendingEta",
                  "batchRegion", "addDaysStr", "pad2", "shortMD"]
JS_SKU_ROW_FUNC = r"function\s+normSku\s*\(\s*row\s*\)"


def page_truth(main_rows, sku_probes, now=None):
    """跑 index.html 里原封不动的 JS 算页面真值。返回 None 表示引擎不可用。"""
    if not os.path.exists(PAGE_HTML):
        return None
    try:
        import py_mini_racer  # noqa: F401
    except Exception:
        return None
    src = io.open(PAGE_HTML, encoding="utf-8").read()
    parts = []
    for pat in JS_VARS:
        v = _extract_var(src, pat)
        if v:
            parts.append(v)
    # 地区归属函数要排在 normRow 之前（normRow 内部会调它）
    for fn in JS_REGION_FUNCS:
        code = _extract_func(src, fn)
        if code:
            parts.append(code)
    for fn in JS_FUNCS:
        code = _extract_func(src, fn)
        if not code:
            continue
        # 固定"今天"，让页面真值与 Python 复算落在同一天，避免跨零点漂移
        code = code.replace("var now = new Date();", "var now = new Date(__NOW__);")
        parts.append(code)
    if not any("function engineSkuCost" in p for p in parts) or not any("function engineAverage" in p for p in parts):
        return None

    now = now or datetime.date.today()
    harness = """
var __NOW__ = "%s";
%s
var records = __RAW__.map(normRow);
var __out = {};
__out.sku = %s.map(function(t){
  var r = engineSkuCost({sku: t});
  return {sku: t, match_mode: r.match_mode, matched_records: r.matched_records,
          priced_records: r.priced_records, unpriced_records: r.unpriced_records,
          total_quantity: r.total_quantity, total_box_count: r.total_box_count,
          total_freight: r.total_freight, per_unit_freight: r.per_unit_freight};
});
__out.avg = (function(){
  var a = engineAverage({range_option: "last_12m", category: null});
  return {total_records: a.total_records, items: (a.items||[]).map(function(it){
    return {region: it.region, average_unit_price: it.average_unit_price,
            record_count: it.record_count, weighted_quantity: it.weighted_quantity,
            breakdown: it.breakdown};
  })};
})();
JSON.stringify(__out);
""" % (now.isoformat(), "\n".join(parts), json.dumps(sku_probes, ensure_ascii=False))

    try:
        import py_mini_racer
        ctx = py_mini_racer.MiniRacer()
        ctx.eval("var __RAW__ = %s;" % json.dumps(main_rows, ensure_ascii=False))
        raw = ctx.eval(harness)
        return json.loads(raw)
    except Exception as e:
        sys.stderr.write("[page_truth] 页面真值不可用：%s\n" % e)
        return None


BATCH_HARNESS = """
__PARTS__
var records = __RAW__.map(normRow);
var fbaMeta = {};
var landDays = __LANDDAYS__;
var DEPARTURE_DELAY = __DELAY__;
var fbaMap = {};
records.forEach(function (r) {
  String(r.fba || "").split("&").forEach(function (f) {
    f = f.trim().toUpperCase(); if (!f) return;
    (fbaMap[f] = fbaMap[f] || []).push(r);
  });
});
/* landDays 动态覆盖（与页面 build() 同口径：对账单 开船日→送达日，样本≥3 才覆盖） */
var acc = {};
records.forEach(function (r) {
  if (!r.rc_etd || !r.rc_deliver_date) return;
  var d = (new Date(r.rc_deliver_date) - new Date(r.rc_etd)) / 86400000;
  if (!(d > 0 && d < 150)) return;
  var g = r.region || "unknown";
  (acc[g] = acc[g] || []).push(d);
});
Object.keys(acc).forEach(function (g) {
  var a = acc[g];
  if (a.length >= 3) landDays[g] = Math.round(a.reduce(function (x, y) { return x + y; }, 0) / a.length);
});
Object.keys(fbaMap).forEach(function (f) {
  var rs = fbaMap[f];
  var ships = rs.map(function (r) { return r.ship_date; }).filter(Boolean).sort();
  var dls = rs.map(function (r) { return r.rc_deliver_date; }).filter(Boolean).sort();
  var region = "unknown";
  for (var i = 0; i < rs.length; i++) {
    if (rs[i].region && rs[i].region !== "unknown") { region = rs[i].region; break; }
  }
  fbaMeta[f] = { recs: rs, ship: ships[0] || null, deliver: dls[dls.length - 1] || null,
                 region: region, delivery_window: (rs.map(function (r) { return r.delivery_window; }).filter(Boolean)[0] || null) };
});
var skuRows = __SKURAW__.map(__normSkuRow).filter(function (s) { return s.fba && s.sku; });
skuRows.forEach(function (l) {
  l.meta = fbaMeta[l.fba.toUpperCase()] || { recs: [], ship: null, deliver: null, region: "unknown", delivery_window: null };
  l.batchKey = l.meta.ship ? l.meta.ship.slice(5, 10) : "未知";
});
/* 2026-11-02 用户定：放开「最近3个月」窗口，改成「只显示还在途的货件」（与页面 build() 同口径）。
   已入仓的老批次不显示；还没入仓的老批次照样显示。 */
skuRows = skuRows.filter(function (l) {
  if (!l.meta || !l.meta.ship) return false;
  return !lineArrived(l);
});
var byBatch = {};
skuRows.forEach(function (l) { (byBatch[l.batchKey] = byBatch[l.batchKey] || []).push(l); });
var __out = [];
Object.keys(byBatch).sort().forEach(function (bk) {
  var ls = byBatch[bk];
  var total = ls.reduce(function (a, l) { return a + l.qty; }, 0);
  var ar = sumArrived(ls);
  var pend = pendingLines(ls);
  var top = pend.length ? batchRegion(pend) : null;
  var pe = pendingEta(ls);
  __out.push({ batch: bk, total: total, arrived: ar, in_transit: total - ar,
               lines: ls.length, skus: Object.keys(ls.reduce(function (m, l) { m[l.sku] = 1; return m; }, {})).length,
               region: top, eta: pe ? pe.date : null });
});
JSON.stringify({lines: skuRows.length, batches: __out});
"""


def page_truth_batch(main_rows, sku_rows, page_const=None, now=None):
    """③ 批次在途的页面真值：调用页面自己的 dwDim/sumArrived/pendingEta/batchRegion。"""
    if not os.path.exists(PAGE_HTML):
        return None
    try:
        import py_mini_racer
    except Exception:
        return None
    src = io.open(PAGE_HTML, encoding="utf-8").read()
    parts = []
    # 地区归属函数要排在 normRow 之前（normRow 内部会调它）
    for fn in JS_REGION_FUNCS:
        code = _extract_func(src, fn)
        if code:
            parts.append(code)
    # normRow / num / d10 是页面「原始行→记录」的转换，批次核对也要用
    for fn in ["num", "d10", "normRow"] + JS_BATCH_FUNCS:
        code = _extract_func(src, fn)
        if code:
            parts.append(code)
    v = _extract_var(src, r"var\s+REGION_BY_LABEL\s*=\s*\{[^}]*\}")
    if v:
        parts.append(v)
    m = re.search(JS_SKU_ROW_FUNC, src)
    if m:
        i = src.index("{", m.end())
        depth = 0
        for j in range(i, len(src)):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    parts.append(src[m.start():j + 1].replace("function normSku(", "function __normSkuRow("))
                    break
    if not any("function sumArrived" in p for p in parts) or not any("function pendingEta" in p for p in parts):
        return None

    pc = dict(DEFAULT_PAGE_CONST)
    if page_const:
        pc.update(page_const)
    harness = (BATCH_HARNESS
               .replace("__PARTS__", "\n".join(parts))
               .replace("__LANDDAYS__", json.dumps(pc["landDays"]))
               .replace("__DELAY__", str(pc["DEPARTURE_DELAY"])))
    try:
        ctx = py_mini_racer.MiniRacer()
        ctx.eval("var __RAW__ = %s;" % json.dumps(main_rows, ensure_ascii=False))
        ctx.eval("var __SKURAW__ = %s;" % json.dumps(sku_rows, ensure_ascii=False))
        return json.loads(ctx.eval(harness))
    except Exception as e:
        sys.stderr.write("[page_truth_batch] 页面真值不可用：%s\n" % e)
        return None
