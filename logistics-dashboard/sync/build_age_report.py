# -*- coding: utf-8 -*-
"""build_age_report.py —— 单店「库龄库存报告」（FBA 店铺 A / sid=00001）

输出：
  shandi-v5/age_report_1shop.html   一页自包含 HTML（纯 SVG，无外部依赖）
  data/age_report_1shop.json         底层数据（便于复核）

口径（与页面同尺子，报告里只出数字）：
  · 当前库存 / 五段库龄 / 可售：wh_raw/fba_inventory.json，nzF 过滤 + SPU 键
    sku→msku→seller_sku 三级兜底 + Amazon.Found.* 归「无款号」
    —— 与 build_wh_snapshot.py / build_age_spu.py 同一把尺子，
    店级五段之和必须等于页面库龄条 __WH.fba.shops[].summary.age
  · 动销：wh_raw/ledger_events.json，逐日 cShip − cRet（FBA 库位 location=US），
    窗口以分类账最后一天为终点（近 30 天 / 近 90 天）
  · 库龄变化：shandi-v5/trend.json 的店级 13 周 SPU 序列（本周 / −1 周 / −2 周）
  · 在途：shandi-v5/records.json 主表（FBA 货件号形态合规 + 未入仓 + 无送达日期），
    件数按 records.sku 的「已发货」落到 SPU
  · 到货日：送达日期（实际）→ 到港日期 + 地区落地天数（估算）→
    发货日期 + 地区落地天数 + 15 天（估算，主表无船期/到港时）
"""
import io
import json
import os
import re
import datetime
import collections
from decimal import Decimal, ROUND_HALF_UP

BASE = os.path.dirname(os.path.abspath(__file__))
SID = "00001"
SHOP = "FBA 店铺 A"

NZ_KEYS = ["total", "available_total", "afn_fulfillable_quantity", "afn_reserved_quantity",
            "afn_unsellable_quantity", "reserved_customerorders", "quantity", "stock_up_num",
            "afn_inbound_working_quantity", "afn_inbound_shipped_quantity",
            "afn_inbound_receiving_quantity", "afn_researching_quantity",
            "reserved_fc_transfers", "reserved_fc_processing"]
AGE_FIELDS = ["inv_age_0_to_90_days", "inv_age_91_to_180_days", "inv_age_181_to_270_days",
              "inv_age_271_to_365_days", "inv_age_365_plus_days"]
BAND_LABELS = ["0-90天", "91-180天", "181-270天", "271-365天", "365天以上"]
BAND_COLORS = ["#cfd8e0", "#7cb6e6", "#f0b429", "#ef8080", "#c8102e"]
FBA_ID_RE = r"^FBA[A-Z0-9]{9}$"
ARRIVED = {"RECEIVING", "CLOSED", "DELIVERED"}
LAND_DAYS = {"us_west": 28, "us_central": 33, "us_east": 40, "unknown": 40}
DEPARTURE_DELAY = 15          # 开船等待 5 + 清关 3 + FBA 仓预约派送 7
FBA_LOCATION = "US"           # 分类账里 FBA 库位；CN = 国内仓（不属本店 FBA 动销）


# ---------------------------------------------------------------- 基础工具
def rd(rel):
    p = os.path.join(BASE, rel)
    if not os.path.exists(p):
        return None
    return json.load(io.open(p, encoding="utf-8"))


def rdt(rel):
    """读文本文件（共享 CSS / JS 等非 JSON 资源）。"""
    p = os.path.join(BASE, rel)
    if not os.path.exists(p):
        return None
    return io.open(p, encoding="utf-8").read()


def num(v):
    try:
        f = float(v)
    except Exception:
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return f


def dparse(s):
    s = str(s or "").strip()
    if not s:
        return None
    s = s.replace("/", "-")
    try:
        return datetime.date.fromisoformat(s[:10])
    except Exception:
        return None


def dstr(d):
    return d.isoformat() if d else ""


def region_of(label):
    s = str(label or "").strip()
    if s.startswith("美西"):
        return "us_west"
    if s.startswith("美东"):
        return "us_east"
    if s.startswith("美中"):
        return "us_central"
    return "unknown"


def spu_of(sku):
    s = str(sku or "").strip()
    if not s:
        return ""
    spu = s.split("-")[0]
    if not spu or spu.upper().startswith("AMAZON.FOUND"):
        return "无款号"
    return spu


def r0(v):
    """四舍五入到整数（half-up，与前端 Math.round 一致）。
    银行家舍入会把 10,694.5 变成 10,694，页面上会跟前端对不上，这里统一 half-up。"""
    if v is None:
        return None
    try:
        return int(Decimal(repr(float(v))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return int(round(v))


def fmt_n(v, dec=0):
    if v is None:
        return "—"
    if dec:
        return format(v, ",.%df" % dec)
    return "{:,.0f}".format(r0(v))


def fmt_days(v):
    if v is None:
        return "—"
    if v >= 999:
        return "999+"
    return "{:.0f}".format(v)


# ---------------------------------------------------------------- 1. 当前库存（页面口径）
def load_inventory():
    fba = rd("wh_raw/fba_inventory.json") or {}
    spus = {}
    sku2 = {}
    for r in (fba.get("rows") or []):
        if str(r.get("sid")) != SID:
            continue
        if not any(num(r.get(k)) > 0 for k in NZ_KEYS):
            continue
        sku = str(r.get("sku") or "").strip() or str(r.get("msku") or "").strip() \
            or str(r.get("seller_sku") or "").strip()
        spu = spu_of(sku)
        if not spu:
            continue
        e = spus.setdefault(spu, {"spu": spu, "bands": [0.0] * 5, "avail": 0.0, "total": 0.0,
                                  "skuRows": 0, "skuIds": set()})
        e["avail"] += num(r.get("afn_fulfillable_quantity"))
        e["total"] += num(r.get("total"))
        ages = [num(r.get(f)) for f in AGE_FIELDS]
        if sum(ages) > 0:
            for i, v in enumerate(ages):
                if v > 0:
                    e["bands"][i] += v
        e["skuRows"] += 1
        for k in ("msku", "sku", "seller_sku"):
            v = str(r.get(k) or "").strip().upper()
            if v:
                sku2.setdefault(v, spu)
                e["skuIds"].add(v)
    for e in spus.values():
        e["skuIds"] = sorted(e["skuIds"])
    return spus, sku2


# ---------------------------------------------------------------- 2. 动销（分类账）
def load_movement(sku2spu):
    led = rd("wh_raw/ledger_events.json") or {}
    days = led.get("days") or {}
    if not days:
        return {}, None, 0
    dlist = sorted(days.keys())
    last = dlist[-1]
    last_d = datetime.date.fromisoformat(last)
    win30 = (last_d - datetime.timedelta(days=29)).isoformat()
    win90 = (last_d - datetime.timedelta(days=89)).isoformat()

    per_spu = collections.defaultdict(lambda: {"d30_ship": 0.0, "d30_ret": 0.0,
                                               "d90_ship": 0.0, "d90_ret": 0.0})
    unmatched = 0
    cn_excluded = 0
    for d, m in days.items():
        for key, arr in m.items():
            parts = key.split("|")
            if len(parts) < 3:
                continue
            msku, _spec, loc = parts[0].strip(), parts[1], parts[2].strip()
            if loc != FBA_LOCATION:
                cn_excluded += 1
                continue
            spu = sku2spu.get(msku.upper())
            if not spu:
                unmatched += 1
                continue
            ship = -num(arr[3]) if len(arr) > 3 else 0.0     # cShip：出库记为负数，取绝对值
            ret = num(arr[4]) if len(arr) > 4 else 0.0       # cRet：退货为正
            if ship <= 0:
                ship = 0.0
            if ret <= 0:
                ret = 0.0
            if ship == 0 and ret == 0:
                continue
            e = per_spu[spu]
            if d >= win30:
                e["d30_ship"] += ship
                e["d30_ret"] += ret
            if d >= win90:
                e["d90_ship"] += ship
                e["d90_ret"] += ret
    return per_spu, {"asOf": last, "win30": [win30, last], "win90": [win90, last],
                     "unmatched": unmatched, "cnExcluded": cn_excluded}, last


# ---------------------------------------------------------------- 3. 库龄周序列
def load_trend():
    tr = rd("shandi-v5/trend.json") or {}
    sh = tr.get(SID) or {}
    weeks = sorted(sh.get("weeks") or [])
    spu = sh.get("spu") or {}

    def row_at(spu_name, w):
        rows = spu.get(spu_name)
        if not rows:
            return None
        if isinstance(rows, list):
            if w not in weeks:
                return None
            return rows[weeks.index(w)]
        return rows.get(w)

    return weeks, row_at


# ---------------------------------------------------------------- 4. 在途与到货日
def load_transit():
    rec = rd("shandi-v5/records.json") or {}
    main = rec.get("main") or []
    skus = rec.get("sku") or []
    today = datetime.date.today()

    ships = {}
    for r in main:
        fba = str(r.get("FBA货件号") or "").strip().upper()
        if not fba or not __import__("re").match(FBA_ID_RE, fba):
            continue
        st = str(r.get("货件状态") or "").strip().upper()
        deliver = str(r.get("送达日期") or "").strip()
        if st in ARRIVED or deliver:
            continue                                   # 已到仓
        region = region_of(r.get("地区"))
        ship_d = dparse(r.get("发货日期"))
        eta_d = dparse(r.get("到港日期"))
        etd_d = dparse(r.get("船开日期"))
        if deliver:
            arrive, how = dparse(deliver), "实际"
        elif eta_d:
            arrive, how = eta_d + datetime.timedelta(days=LAND_DAYS[region]), "估算"
        elif ship_d:
            arrive, how = ship_d + datetime.timedelta(days=LAND_DAYS[region] + DEPARTURE_DELAY), "估算"
        else:
            arrive, how = None, "无数据"
        ships[fba] = {"fba": fba, "qty": num(r.get("件数")), "region": region,
                      "ship": dstr(ship_d), "eta": dstr(eta_d), "etd": dstr(etd_d),
                      "arrive": dstr(arrive), "how": how, "status": st,
                      "month": str(r.get("月份") or "")}

    # 件数落到 SPU（records.sku 有货件级 SKU 明细与已发货件数）
    # 跨店 SKU（同一 SKU 出现在 2 个店）在途件数按店铺数均分到本店（估算，报告会标明）
    idx = rd("shandi-v5/fba_sku_index.json") or {}
    sku_shops = idx.get("skuShops") or {}
    per_spu = collections.defaultdict(lambda: {"qty": 0.0, "arrivals": [], "fbas": set(),
                                               "qtyRaw": 0.0, "qtySplit": 0.0})
    for s in skus:
        fba = str(s.get("货件单号") or "").strip().upper()
        sh = ships.get(fba)
        if not sh:
            continue
        sku = str(s.get("SKU") or "").strip() or str(s.get("_msku") or "").strip()
        spu = spu_of(sku)
        if not spu:
            continue
        q = num(s.get("已发货"))
        if q <= 0:
            continue
        shops = sku_shops.get(sku.upper()) or sku_shops.get(sku) or []
        if SID not in shops:
            continue                      # 不是本店的货，不进本店在途
        share = 1.0 / len(shops) if len(shops) > 1 else 1.0
        e = per_spu[spu]
        e["qty"] += q * share
        e["qtyRaw"] += q
        if share < 1.0:
            e["qtySplit"] += q * share
        e["fbas"].add(fba)
        if sh["arrive"]:
            e["arrivals"].append((sh["arrive"], sh["how"], fba))
    for e in per_spu.values():
        e["arrivals"] = sorted(e["arrivals"])
        e["fbas"] = sorted(e["fbas"])
    overdue = sum(1 for s in ships.values() if s["arrive"] and s["arrive"] < dstr(today))
    return ships, per_spu, today, overdue


# ---------------------------------------------------------------- 5. 判定与建议
# 合格判定线（2026-11-03 主管-主管转达用户拍板，**既定标准，非建议**）：
#   合格 = 周转天数 ≤ 90 天 且 271天以上占比 < 5%（分母 = 库龄五段合计）
#   不满足按主因拆：周转偏慢（周转 > 90 天）/ 271天以上占比超线（占比 ≥ 5%）/ 两项都超
# 尾货（总库存 < 20 双）与库龄库存 = 0 的款不参与合格判定，单列。
# 断货风险是另一维度（可售撑不到在途到货日），单列成标记，不混进合格判定。
TURN_LIMIT_DAYS = 90.0
OLD_LIMIT_PCT = 5.0
# 尾货线（2026-11-03 用户拍板）：总库存 < 20 双的款单列一档「尾货」，不进合格判定
TAIL_STOCK_LIMIT = 20.0


def judge(turn_days, old_ratio, stock):
    """返回合格判定标签。
    turn_days=None 且有库存 = 近 30 天无动销 → 周转天数无穷大 → 判「周转偏慢」。"""
    slow = (stock > 0 and turn_days is None) or (turn_days is not None and turn_days > TURN_LIMIT_DAYS)
    old_over = (old_ratio is not None) and (old_ratio >= OLD_LIMIT_PCT)
    if slow and old_over:
        return "两项都超"
    if slow:
        return "周转偏慢"
    if old_over:
        return "271天以上占比超线"
    return "合格"


def is_risk(spu):
    """断货风险：已断货（可售 0 且近 30 天仍在卖），或可售撑不到在途预计到货日"""
    if spu["avail"] <= 0 and spu["move30"] > 0:
        return True
    if spu["coverDays"] is not None and spu["transitArriveDays"] is not None \
            and spu["coverDays"] < spu["transitArriveDays"]:
        return True
    return False


def advice(spu, jd):
    c = spu
    over = "（到货日估算已过期，货件状态未更新）" if c.get("transitOverdue") else ""
    tail = ""
    if c["transitQty"] > 0:
        tail = "；在途 %s 双将于 %s 到货" % (fmt_n(c["transitQty"]), c["transitArrive"] or "—")
    # 库龄库存为 0 的款不参与判定
    if not jd:
        if c.get("tail"):
            return "尾货：总库存 %s 双、271天以上 %s 双（占 %s%%），建议清货/降权重%s" % (
                fmt_n(c["total"]), fmt_n(c["old271"]), fmt_n(c["oldRatio"], 1), tail)
        return "库龄库存 0 双，不参与判定；可售 %s 双，近30天动销 %s 双" % (
            fmt_n(c["avail"]), fmt_n(c["move30"]))
    if c["risk"]:
        return "断货风险：可售 %s 双只够 %s 天，%s 到货 %s 双，建议补单/催船%s" % (
            fmt_n(c["avail"]), fmt_days(c["coverDays"]), c["transitArrive"] or "—",
            fmt_n(c["transitQty"]), over)
    if jd == "两项都超":
        return "周转偏慢 + 271天以上占比超线：周转 %s 天、271天以上占 %s%%，建议促销降库存并清理271天以上库存%s" % (
            fmt_days(c["turnDays"]), fmt_n(c["oldRatio"], 1), tail)
    if jd == "周转偏慢":
        if c["turnDays"] is None:
            return "近30天净动销 ≤ 0：库存 %s 双、近90天动销 %s 双，建议查 listing / 清货%s" % (
                fmt_n(c["stock"]), fmt_n(c["move90"]), tail)
        return "周转偏慢：周转 %s 天、库存 %s 双、近30天日均 %s 双/天，建议促销/降库存%s" % (
            fmt_days(c["turnDays"]), fmt_n(c["stock"]), fmt_n(c["daily30"], 1), tail)
    if jd == "271天以上占比超线":
        return "271天以上占比超线：271天以上 %s 双占 %s%%，建议停补/清货/降权重%s" % (
            fmt_n(c["old271"]), fmt_n(c["oldRatio"], 1), tail)
    return "周转 %s 天、271天以上占 %s%%，维持现有补货节奏%s" % (
        fmt_days(c["turnDays"]), fmt_n(c["oldRatio"], 1), tail)



# ---------------------------------------------------------------- 主流程
def build():
    inv, sku2spu = load_inventory()
    move, mwin, ledger_last = load_movement(sku2spu)
    weeks, trend_row = load_trend()
    ships, transit, today, transit_overdue = load_transit()
    prod = rd("wh_raw/local_products.json") or {}
    snap = rd("wh_raw/wh_snapshot.json") or {}
    shop_snap = None
    for s in ((snap.get("fba") or {}).get("shops") or []):
        if str(s.get("sid")) == SID:
            shop_snap = s.get("summary") or {}
    snap_updated = snap.get("updatedAt")

    # SKU → 品名（取该 SPU 第一个 SKU 的品名）
    sku2name = {}
    for r in (prod.get("rows") or prod.get("data") or []):
        k = str(r.get("sku") or "").strip()
        n = r.get("product_name") or ""
        if k and n:
            sku2name.setdefault(k.upper(), n)

    # 30 天前的周（周序列里最接近 latest-30d 的一周）
    prev_week = {}
    if weeks:
        latest = datetime.date.fromisoformat(weeks[-1])
        target = latest - datetime.timedelta(days=30)
        prev_week = {"w30": min(weeks, key=lambda w: abs((datetime.date.fromisoformat(w) - target).days)),
                     "w1": weeks[-2] if len(weeks) > 1 else None,
                     "w2": weeks[-3] if len(weeks) > 2 else None}

    rows = []
    for spu in sorted(inv.keys()):
        e = inv[spu]
        stock = sum(e["bands"])                       # 库龄五段合计 = 可计库龄库存
        mv = move.get(spu, {})
        ship30 = mv.get("d30_ship", 0.0)
        ret30 = mv.get("d30_ret", 0.0)
        ship90 = mv.get("d90_ship", 0.0)
        ret90 = mv.get("d90_ret", 0.0)
        move30 = ship30 - ret30
        move90 = ship90 - ret90
        daily30 = move30 / 30.0
        daily90 = move90 / 90.0
        # 撑货天数 / 周转天数 / 断货风险 一律以近 30 天日均为准（更贴近当下）；
        # 近 90 天日均只作趋势对比（升 / 降 / 平）
        # 净动销为负（退货多于出库）时，日均参与测算按 0 计（周转天数记无穷大）
        daily = max(daily30, 0.0)
        d30c, d90c = max(daily30, 0.0), max(daily90, 0.0)
        trend = "平"
        if d30c > 0 and d90c > 0:
            if d30c > d90c * 1.05:
                trend = "升"
            elif d30c < d90c * 0.95:
                trend = "降"
        cover = (e["avail"] / daily) if daily > 0 else None
        turn = (stock / daily) if daily > 0 else None

        # 周转次数：近 30 天动销 ÷ 平均库存（当前与 30 天前均值）
        prev_total = None
        if prev_week.get("w30"):
            pr = trend_row(spu, prev_week["w30"])
            if pr and len(pr) > 1:
                prev_total = num(pr[1])
        if prev_total is not None and stock > 0:
            avg_stock = (stock + prev_total) / 2.0
        else:
            avg_stock = stock or None
        turns = (move30 / avg_stock) if (avg_stock and move30 > 0) else None

        # 库龄变化
        cur = trend_row(spu, weeks[-1]) if weeks else None
        p1 = trend_row(spu, prev_week["w1"]) if prev_week.get("w1") else None
        p2 = trend_row(spu, prev_week["w2"]) if prev_week.get("w2") else None

        def bands_of(r):
            if not r or len(r) < 8:
                return None
            return [num(x) for x in r[3:8]]

        b_now, b_1, b_2 = bands_of(cur), bands_of(p1), bands_of(p2)
        d1 = None
        if b_now and b_1:
            d1 = {"total": sum(b_now) - sum(b_1),
                  "pct": ((sum(b_now) - sum(b_1)) / sum(b_1) * 100) if sum(b_1) > 0 else None,
                  "old": (b_now[3] + b_now[4]) - (b_1[3] + b_1[4]),
                  "bands": [b_now[i] - b_1[i] for i in range(5)]}
        d2 = None
        if b_now and b_2:
            d2 = {"total": sum(b_now) - sum(b_2),
                  "pct": ((sum(b_now) - sum(b_2)) / sum(b_2) * 100) if sum(b_2) > 0 else None,
                  "old": (b_now[3] + b_now[4]) - (b_2[3] + b_2[4]),
                  "bands": [b_now[i] - b_2[i] for i in range(5)]}

        tr = transit.get(spu)
        arrive = tr["arrivals"][0][0] if (tr and tr["arrivals"]) else None
        arrive_how = tr["arrivals"][0][1] if (tr and tr["arrivals"]) else None
        arrive_days = None
        overdue = False
        if arrive:
            d = (datetime.date.fromisoformat(arrive) - today).days
            overdue = d < 0
            arrive_days = max(0, d)          # 估算到货日已过 → 视为即将到（状态未更新）
        old271 = e["bands"][3] + e["bands"][4]
        # 271天以上占比：分母 = 该 SPU 库龄五段合计（页面库龄条同一把尺子：ga[j]/gsum）
        old_ratio = (old271 / stock * 100) if stock > 0 else None
        # 备用：分母 = 该 SPU 当前总库存双数（仅留在底层 JSON 供核对，界面不显示）
        old_ratio_total = (old271 / e["total"] * 100) if e["total"] > 0 else None

        name = ""
        for k in e["skuIds"]:
            if k.upper() in sku2name:
                name = sku2name[k.upper()]
                break

        row = {
            "spu": spu, "name": name, "avail": e["avail"], "total": e["total"],
            "bands": e["bands"], "stock": stock,
            "ship30": ship30, "ret30": ret30, "move30": move30,
            "ship90": ship90, "ret90": ret90, "move90": move90,
            "daily30": daily30, "daily90": daily90, "daily": daily,
            "coverDays": cover, "turnDays": turn, "turns": turns,
            "oldRatio": old_ratio, "oldRatioTotal": old_ratio_total, "old271": old271,
            "trend": trend,
            "ageChange1w": d1, "ageChange2w": d2,
            "transitQty": tr["qty"] if tr else 0.0,
            "transitQtyRaw": tr["qtyRaw"] if tr else 0.0,
            "transitQtySplit": tr["qtySplit"] if tr else 0.0,
            "transitArrive": arrive, "transitArriveHow": arrive_how,
            "transitArriveDays": arrive_days, "transitOverdue": overdue,
            "transitFbas": tr["fbas"] if tr else [],
            "skuCount": e["skuRows"],
        }
        # 判定分档（2026-11-03 用户拍板）：
        #   · 库龄库存（库龄五段合计）= 0 的款 → 不参与判定，单独说明
        #   · 总库存 < 20 双的尾货 → 单列一档「尾货」，不进合格判定，但仍给清货/降权重建议
        #   · 其余（库龄库存 > 0 且 总库存 ≥ 20 双）→ 参与合格判定
        row["tail"] = False
        if stock <= 0:
            row["judged"] = False
            row["judge"] = ""
        elif e["total"] < TAIL_STOCK_LIMIT:
            row["tail"] = True
            row["judged"] = False
            row["judge"] = ""
        else:
            row["judged"] = True
            row["judge"] = judge(turn, old_ratio, stock)
        row["risk"] = is_risk(row)
        row["advice"] = advice(row, row["judge"])
        rows.append(row)

    # 只看有货的 SPU（有可售 或 有库龄）
    rows = [r for r in rows if r["avail"] > 0 or r["stock"] > 0]
    rows.sort(key=lambda r: (-r["stock"], r["spu"]))

    # 店级汇总
    sum_bands = [sum(r["bands"][i] for r in rows) for i in range(5)]
    sum_stock = sum(sum_bands)
    sum_avail = sum(r["avail"] for r in rows)
    sum_total = sum(r["total"] for r in rows)
    sum_move30 = sum(r["move30"] for r in rows)
    sum_move90 = sum(r["move90"] for r in rows)
    sum_ship30 = sum(r["ship30"] for r in rows)
    sum_ret30 = sum(r["ret30"] for r in rows)
    sum_ship90 = sum(r["ship90"] for r in rows)
    sum_ret90 = sum(r["ret90"] for r in rows)
    daily30 = sum_move30 / 30.0
    daily90 = sum_move90 / 90.0
    turn_days = (sum_stock / daily30) if daily30 > 0 else None
    turns_shop = (sum_move30 / sum_stock) if sum_stock > 0 else None
    old_shop = sum_bands[3] + sum_bands[4]
    # 271天以上占比：分母 = 库龄五段合计（页面库龄条同一把尺子：ga[j]/gsum）
    old_ratio_shop = old_shop / sum_stock * 100 if sum_stock > 0 else None
    # 备用：分母 = 当前总库存双数（仅留在底层 JSON 供核对，界面不显示）
    old_ratio_total_shop = old_shop / sum_total * 100 if sum_total > 0 else None
    le180 = (sum_bands[0] + sum_bands[1]) / sum_stock * 100 if sum_stock > 0 else None
    risk_cnt = sum(1 for r in rows if r["risk"])
    # 判定只统计有库龄库存且非尾货的款；尾货、库龄库存为 0 的款单列，不参与判定
    judged_rows = [r for r in rows if r.get("judged")]
    tail_rows = [r for r in rows if r.get("tail")]
    judge_cnt = collections.Counter(r["judge"] for r in judged_rows)
    ok_cnt = judge_cnt.get("合格", 0)
    ok_stock = sum(r["stock"] for r in judged_rows if r["judge"] == "合格")
    ok_avail = sum(r["avail"] for r in judged_rows if r["judge"] == "合格")
    bad_cnt = len(judged_rows) - ok_cnt
    bad_stock = sum(r["stock"] for r in judged_rows if r["judge"] != "合格")
    bad_avail = sum(r["avail"] for r in judged_rows if r["judge"] != "合格")
    judged_count = len(judged_rows)
    tail_count = len(tail_rows)
    tail_stock = sum(r["stock"] for r in tail_rows)
    tail_avail = sum(r["avail"] for r in tail_rows)
    no_age_count = sum(1 for r in rows if not r.get("judged") and not r.get("tail"))
    transit_rows = [r for r in rows if r["transitQty"] > 0]
    transit_total = sum(r["transitQty"] for r in transit_rows)
    transit_split = sum(r["transitQtySplit"] for r in transit_rows)

    # 硬校验：店级五段 == 页面库龄条
    bar = (shop_snap or {}).get("age") or []
    diff = [round(sum_bands[i] - num(bar[i]), 2) for i in range(5)] if len(bar) == 5 else None

    # 交叉核对：页面 SPU 饼图（__SPU，sku 首段 + FBA 可售 > 0）vs 本报告 SPU 集合
    page_spu_set, page_spu_map = load_page_spu()
    ours = set(r["spu"] for r in rows)
    ours_avail = set(r["spu"] for r in rows if r["avail"] > 0)
    cross = None
    if page_spu_set:
        cross = {
            "pageSpuCount": len(page_spu_set),
            "oursSpuCount": len(ours),
            "oursAvailSpuCount": len(ours_avail),
            "pageOnly": sorted(page_spu_set - ours),
            "oursOnly": sorted(ours - page_spu_set),
            "oursAvailOnly": sorted(ours_avail - page_spu_set),
        }

    shop = {
        "sid": SID, "name": SHOP, "today": dstr(today),
        "ledgerAsOf": mwin["asOf"] if mwin else None,
        "win30": mwin["win30"] if mwin else None,
        "win90": mwin["win90"] if mwin else None,
        "kpi": {
            "totalStock": sum_total, "avail": sum_avail, "ageStock": sum_stock,
            "bands": sum_bands, "move30": sum_move30, "move90": sum_move90,
            "ship30": sum_ship30, "ret30": sum_ret30, "ship90": sum_ship90, "ret90": sum_ret90,
            "daily30": daily30, "daily90": daily90, "turnDays": turn_days, "turns": turns_shop,
            "oldRatio": old_ratio_shop, "oldRatioTotal": old_ratio_total_shop,
            "le180Ratio": le180, "oldQty": old_shop,
            "spuCount": len(rows), "riskCount": risk_cnt,
            "judgedCount": judged_count, "noAgeCount": no_age_count,
            "tailCount": tail_count, "tailStock": tail_stock, "tailAvail": tail_avail,
            "transitQty": transit_total, "transitSpuCount": len(transit_rows),
            "transitSplitQty": transit_split, "transitOverdueShip": transit_overdue,
            "transitFbaCount": len(set(f for r in transit_rows for f in r["transitFbas"])),
            "judgeCounts": dict(judge_cnt),
            "okCount": ok_cnt, "okStock": ok_stock, "okAvail": ok_avail,
            "badCount": bad_cnt, "badStock": bad_stock, "badAvail": bad_avail,
            "badStockRatio": (bad_stock / sum_stock * 100) if sum_stock > 0 else None,
        },
        "pageAgeBar": bar, "pageAgeDiff": diff,
        "pageSummary": shop_snap,
        "snapshotUpdatedAt": snap_updated,
        "spuCross": cross,
        "criteria": {
            "note": "判定标准",
            "turnLimit": int(TURN_LIMIT_DAYS),
            "oldLimit": int(OLD_LIMIT_PCT),
            "spu": [
                "合格：周转天数 ≤ 90 天 且 271天以上占比 < 5%",
                "周转偏慢（>90天）：周转天数 > 90 天；近 30 天净动销 ≤ 0 且有库存的，周转天数记为无穷大，同样落此档",
                "271天以上占比超线（≥5%）：271天以上占比 ≥ 5%",
                "两项都超：周转天数 > 90 天 且 271天以上占比 ≥ 5%",
                "库龄库存（库龄五段合计）= 0 双的款不参与判定，单独列出",
            ],
            "shop": [
                "周转天数 ≤ 90 天",
                "271天以上占比 < 5%",
            ],
            "def": [
                "周转天数 = 该款库龄五段合计（双）÷ 近 30 天日均动销（双/天）；近 30 天净动销 ≤ 0 且有库存的，周转天数记为无穷大",
                "271天以上占比 =（271-365天 + 365天以上）双数 ÷ 该款库龄五段合计双数；店级用该店库龄五段合计双数",
                "近 30 天日均动销 =（近 30 天出库双数 − 近 30 天退货双数）÷ 30",
                "近 90 天日均动销 =（近 90 天出库双数 − 近 90 天退货双数）÷ 90，只用于看动销趋势方向",
                "断货风险：可售 = 0 且近 30 天仍有动销，或可售撑不到在途预计到货日；此项单列标记，不参与合格判定",
            ],
        },
        "rows": rows,
        "shopTrend": load_shop_trend(),
    }
    return shop


def load_shop_trend():
    d = rd("data/age_trend_shop.json")
    if not d:
        return None
    for s in (d.get("shops") or []):
        if str(s.get("sid")) == SID:
            return s
    return None


def load_page_spu():
    """页面 window.__SPU.byShop[00001].spu（SPU 饼图口径：sku 首段 + FBA 可售 > 0）
    用于与本报告 SPU 集合交叉核对。返回 (页面SPU集合, 页面SPU字典)"""
    p = os.path.join(BASE, "shandi-v5", "index.html")
    if not os.path.exists(p):
        return None, None
    h = io.open(p, encoding="utf-8", errors="replace").read()
    i = h.find("window.__SPU=")
    if i < 0:
        return None, None
    j = h.find('"spu":', i)
    if j < 0:
        return None, None
    k = h.find("{", j)
    depth = 0
    end = -1
    for e in range(k, len(h)):
        if h[e] == "{":
            depth += 1
        elif h[e] == "}":
            depth -= 1
            if depth == 0:
                end = e + 1
                break
    if end < 0:
        return None, None
    try:
        d = json.loads(h[k:end])
    except Exception:
        return None, None
    # 定位该店：byShop 结构 {"byShop": {sid: {"name":..., "spu":{...}}}}
    bidx = h.find('"byShop"', i)
    if bidx < 0:
        return None, None
    m = re.search(r'"%s"\s*:\s*\{' % SID, h[bidx:bidx + 20000])
    if not m:
        return None, None
    sidx = h.find('"spu":', bidx + m.end())
    if sidx < 0:
        return None, None
    k2 = h.find("{", sidx)
    depth = 0
    end2 = -1
    for e in range(k2, len(h)):
        if h[e] == "{":
            depth += 1
        elif h[e] == "}":
            depth -= 1
            if depth == 0:
                end2 = e + 1
                break
    if end2 < 0:
        return None, None
    try:
        spu = json.loads(h[k2:end2])
    except Exception:
        return None, None
    return set(spu.keys()), spu


# ---------------------------------------------------------------- HTML
def esc(s):
    return (str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# 视图 payload：独立 HTML 与站点页面模块共用这一份数据 + 同一个渲染器（age_report_view.js）
VIEW_ROW_KEYS = ["spu", "name", "avail", "total", "bands", "stock", "move30", "daily30",
                  "daily90", "trend", "turnDays", "turns", "coverDays", "oldRatio",
                  "transitQty", "transitArrive", "transitArriveHow", "transitOverdue",
                  "ageChange1w", "ageChange2w", "judge", "judged", "tail", "risk", "advice"]
VIEW_KPI_KEYS = ["totalStock", "avail", "ageStock", "bands", "move30", "move90", "ship30",
                 "ret30", "ship90", "ret90", "daily30", "daily90", "turnDays", "turns",
                 "oldRatio", "oldQty", "spuCount", "riskCount", "judgeCounts",
                 "judgedCount", "noAgeCount", "tailCount", "tailStock", "tailAvail",
                 "okCount", "okStock", "okAvail", "badCount", "badStock", "badAvail",
                 "badStockRatio", "transitQty", "transitFbaCount", "transitSplitQty",
                 "transitOverdueShip"]
# 视图数据取整字段：页面上不能出现半双（在途件数按跨店均分会产生 .5）
VIEW_ROUND_KEYS = set(["transitQty", "transitSplitQty"])


def _rv(v):
    return r0(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def view_payload(shop):
    """页面与独立 HTML 共用的视图数据（去掉核对用的中间字段，控制注入体积）。

    · 只放渲染要用的数字，口径说明文字留在 data/age_report_1shop.json（criteria.def）
    · 在途双数取整（half-up），页面不出现 .5；底层 JSON 保留原值
    """
    k = shop["kpi"]
    rows = []
    for r in shop["rows"]:
        row = dict((x, r.get(x)) for x in VIEW_ROW_KEYS)
        if "transitQty" in VIEW_ROUND_KEYS:
            row["transitQty"] = _rv(row["transitQty"])
        rows.append(row)
    st = shop.get("shopTrend") or {}
    series = []
    for x in (st.get("series") or []):
        series.append({"d": x.get("d"), "bands": x.get("bands")})
    kpi = dict((x, k.get(x)) for x in VIEW_KPI_KEYS)
    for x in VIEW_ROUND_KEYS:
        if x in kpi:
            kpi[x] = _rv(kpi[x])
    cr = shop.get("criteria") or {}
    return {
        "sid": shop["sid"], "name": shop["name"], "today": shop["today"],
        "ledgerAsOf": shop.get("ledgerAsOf"), "snapshotUpdatedAt": shop.get("snapshotUpdatedAt"),
        "win30": shop.get("win30"), "win90": shop.get("win90"),
        "kpi": kpi,
        "rows": rows,
        "shopTrend": {"weeks": st.get("weeks"), "series": series},
        "criteria": {"turnLimit": cr.get("turnLimit", 90), "oldLimit": cr.get("oldLimit", 5)},
    }


def build_html(shop):
    """自包含一页 HTML：内嵌共享 CSS + 共享渲染器 JS + 本报告数据（与页面模块同一份数据、同一套渲染）。"""
    css = rdt("age_report_view.css") or ""
    js = rdt("age_report_view.js") or ""
    if not css or not js:
        raise RuntimeError("缺 age_report_view.css / age_report_view.js")
    payload = view_payload(shop)
    data_js = "window.__AGEREP=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"
    html = []
    A = html.append
    A('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A('<title>%s · 库龄库存报告</title>' % esc(SHOP))
    A('<style>')
    A("body{margin:0;background:#f5f7fa;}")
    A(".ar-page{max-width:1180px;margin:0 auto;padding:22px 18px 60px;}")
    A(css)
    A('</style></head><body><div class="ar-page"><div class="ar-wrap" id="arRoot"></div></div>')
    A('<script>')
    A(data_js)
    A('</script>')
    A('<script>')
    A(js)
    A('</script>')
    A('<script>window.AREP.render(document.getElementById("arRoot"), window.__AGEREP);</script>')
    A('</body></html>')
    return "\n".join(html)


def main():
    shop = build()
    out_json = os.path.join(BASE, "data", "age_report_1shop.json")
    out_view = os.path.join(BASE, "data", "age_report_1shop.view.json")
    out_html = os.path.join(BASE, "shandi-v5", "age_report_1shop.html")
    for p in (out_json, out_view, out_html):
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            os.makedirs(d)
    io.open(out_json, "w", encoding="utf-8", newline="\n").write(
        json.dumps(shop, ensure_ascii=False, indent=1))
    io.open(out_view, "w", encoding="utf-8", newline="\n").write(
        json.dumps(view_payload(shop), ensure_ascii=False, separators=(",", ":")))
    io.open(out_html, "w", encoding="utf-8", newline="\n").write(build_html(shop))

    k = shop["kpi"]
    print("SPU 数: %d" % k["spuCount"])
    print("总库存 %s / 可售 %s / 库龄合计 %s" % (fmt_n(k["totalStock"]), fmt_n(k["avail"]),
                                                fmt_n(k["ageStock"])))
    print("五段: %s" % k["bands"])
    print("页面库龄条: %s" % shop["pageAgeBar"])
    print("差值: %s" % shop["pageAgeDiff"])
    print("30天: 出库 %s 退货 %s 动销 %s 日均 %s" % (fmt_n(k["ship30"]), fmt_n(k["ret30"]),
                                                     fmt_n(k["move30"]), fmt_n(k["daily30"], 2)))
    print("90天: 出库 %s 退货 %s 动销 %s 日均 %s" % (fmt_n(k["ship90"]), fmt_n(k["ret90"]),
                                                     fmt_n(k["move90"]), fmt_n(k["daily90"], 2)))
    print("周转天数 %s / 周转次数 %s / 271+占比 %s%%" % (fmt_days(k["turnDays"]),
                                                          fmt_n(k["turns"], 2), fmt_n(k["oldRatio"], 1)))
    print("判定分布: %s / 断货风险 %d 个" % (k["judgeCounts"], k["riskCount"]))
    print("在途 %d 个 SPU / %s 双" % (k["transitSpuCount"], fmt_n(k["transitQty"])))
    print("写入 %s (%.1f KB)" % (out_html, os.path.getsize(out_html) / 1024.0))
    print("写入 %s (%.1f KB)" % (out_json, os.path.getsize(out_json) / 1024.0))
    print("写入 %s (%.1f KB)" % (out_view, os.path.getsize(out_view) / 1024.0))


if __name__ == "__main__":
    main()
