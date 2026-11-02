# -*- coding: utf-8 -*-
"""从领星库存分类账重建 FBA 库存的**周度历史**，给「库龄 × 款号」矩阵做点击趋势。

输入
  wh_raw/ledger_events.json   分类账日维度事件流（lx_ledger.py 拉）
  wh_raw/fba_inventory.json   当前 FBA 库存快照（SKU→SPU / sid 映射 + 起点批次反推 + 精度对账）

输出
  shandi-v5/trend.json → 注入页面 window.__TREND
  { sid: { "weeks":[周结日...],
           "spu": { SPU: [[可售,总双数,老库龄,0-90,91-180,181-270,271-365,365+], ...] } } }

算法
  1) 逐 SKU 维护 FIFO 批次队列（先进先出，与 FBA 实际出库顺序一致）
     入 = receipts + customerReturns + vendorReturns + found
     出 = 上日期末 + 入 - 本日期末   ← 用期末余额守恒，吸收一切减少原因（破损/丢失/调仓）
  2) **窗口起点的批次日龄用当前快照反推**：快照里 181 天以上档的货在窗口开始时就已存在，
     把它们按各自档位中值倒推成「合成入库日」放进起点队列；窗口内卖掉的算最老。
     这样历史库龄不是「一坨老货」，而是分档的。
  3) 每天按队列批次的日龄分 5 档：0-90 / 91-180 / 181-270 / 271-365 / 365+
  4) 取每周最后一个有数据的日子做周结 → 按 SPU 汇总
  5) 与当前快照对账，误差写构建日志（决定哪些指标敢对外展示）
"""
import datetime
import io
import json
import os
import sys
from collections import defaultdict, deque

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.path.join(BASE, "wh_raw", "ledger_events.json")
INV = os.path.join(BASE, "wh_raw", "fba_inventory.json")
OUT = os.path.join(BASE, "shandi-v5", "trend.json")

KEYS = ["start", "end", "receipts", "cShip", "cRet", "vRet", "found",
        "disposed", "damaged", "lost", "transfer"]
SELLABLE = "01"
AGE_FIELDS = ("inv_age_0_to_90_days", "inv_age_91_to_180_days",
              "inv_age_181_to_270_days", "inv_age_271_to_365_days",
              "inv_age_365_plus_days")
AGE_MID = [45, 135, 225, 318, 400]      # 各档日龄中值

# 校准比例护栏：实测/推算 的比值超出这个区间就说明"账上这个 SPU 几乎没记录"，
# 不能拿它去乘历史周（会造出假峰值），改用店级比例。
RATIO_MAX = 10.0


def num(v):
    try:
        n = float(v)
        return n if n == n and n not in (float("inf"), float("-inf")) else 0.0
    except Exception:
        return 0.0


def spu_of(sku):
    s = str(sku or "").strip()
    return s.split("-")[0] if s else s


def load_events():
    ev = json.load(io.open(EVENTS, encoding="utf-8"))
    per = {}
    for d in sorted((ev.get("days") or {}).keys()):
        agg = {}
        for key, vals in (ev["days"][d]).items():
            parts = key.split("|")
            sku = parts[0].upper()
            disp = parts[1] if len(parts) > 1 else ""
            a = agg.setdefault(sku, {"sell_end": 0.0, "sell_start": 0.0,
                                     "all_end": 0.0, "in": 0.0})
            v = dict(zip(KEYS, vals))
            a["all_end"] += num(v["end"])
            if disp == SELLABLE:
                a["sell_end"] += num(v["end"])
                a["sell_start"] += num(v["start"])
                a["in"] += (num(v["receipts"]) + num(v["cRet"]) + num(v["vRet"])
                            + num(v["found"]))
        per[d] = agg
    return ev.get("asOf"), per


def initial_queue(s_start, snap_age, snap_date, first_day):
    """用当前快照的库龄段反推窗口起点的批次日龄 → 起点队列"""
    q = []
    if s_start <= 0:
        # 该 SKU 首次出现时余额为 0 → 库存全部由窗口内入库形成，不该有「老货起点」
        return q
    # 窗口起点的存量：按**当前快照的库龄档位比例**拆成 5 个「合成批次」，
    # 每个批次的合成入库日 = 快照日 - 该档日龄中值（AGE_MID）。
    # 这样推算出来的历史库龄是一份有结构的分布，而不是「一坨老货」：
    #   · 181-270 / 271-365 / 365+ 三档在窗口内才有值（原来恒为 0，
    #     校准段只能把实测值复制到每一周 → 13 周被写成同一个数）；
    #   · 老货按 FIFO 先卖，与实物一致。
    # 快照没有库龄数据时，退回「全部当 366 天以上老货」。
    tot = sum(snap_age) if snap_age else 0.0
    if tot > 0:
        for i, qty in enumerate(snap_age):
            if qty <= 0:
                continue
            d = snap_date - datetime.timedelta(days=AGE_MID[i])
            if d >= first_day:
                d = first_day - datetime.timedelta(days=1)
            q.append([d, s_start * qty / tot])
    else:
        d = first_day - datetime.timedelta(days=366)
        q.append([d, s_start])
    # FIFO 要求队列按入库日升序（最老在前），否则出库顺序会错
    q.sort(key=lambda b: b[0])
    return q


def fifo_buckets(series, init_q):
    """逐日 FIFO 推算库龄档；返回 [(date, buckets[5], sell_end, all_end)]"""
    q = deque(init_q)
    out = []
    prev_end = None
    for (d, s_start, s_end, inflow, all_end) in series:
        dd = datetime.date.fromisoformat(d)
        if prev_end is None:
            prev_end = s_start
        if inflow > 0:
            q.append([dd, inflow])
        outqty = max(0.0, prev_end + inflow - s_end)
        rem = outqty
        while rem > 1e-9 and q:
            head = q[0]
            take = min(head[1], rem)
            head[1] -= take
            rem -= take
            if head[1] <= 1e-6:
                q.popleft()
        qtot = sum(b[1] for b in q)
        if qtot > 0 and abs(qtot - s_end) > 0.5:
            f = s_end / qtot
            for b in q:
                b[1] *= f
        prev_end = s_end
        b = [0.0] * 5
        for bdate, bqty in q:
            age = (dd - bdate).days
            if age < 0:
                age = 0
            idx = 0 if age <= 90 else 1 if age <= 180 else 2 if age <= 270 else 3 if age <= 365 else 4
            b[idx] += bqty
        out.append((d, b, s_end, all_end))
    return out


def week_end(d):
    dd = datetime.date.fromisoformat(d)
    return (dd + datetime.timedelta(days=6 - dd.weekday())).isoformat()


def load_measured(hist_dir):
    """读 wh_hist/fba/*.json → {(sid, spu, 周结日): [8 个数]}
    同一周有多个实测日时，取该周**最晚**的那天（同一天多店多 SPU 覆盖全）。"""
    meas, meas_day = {}, {}
    if not os.path.isdir(hist_dir):
        return meas
    for fn in sorted(os.listdir(hist_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            obj = json.load(io.open(os.path.join(hist_dir, fn), encoding="utf-8"))
        except Exception:
            continue
        d = obj.get("date")
        if not d:
            continue
        w = week_end(d)
        for sid, spumap in (obj.get("shops") or {}).items():
            for spu, v in (spumap or {}).items():
                if not isinstance(v, (list, tuple)) or len(v) < 8:
                    continue
                key = (str(sid), spu, w)
                if key not in meas_day or d > meas_day[key]:
                    meas_day[key] = d
                    meas[key] = [num(x) for x in v[:8]]
    return meas


def main():
    asof, per = load_events()
    if not per:
        print("没有分类账数据，先跑 lx_ledger.py")
        return 1
    days = sorted(per.keys())
    first_day = datetime.date.fromisoformat(days[0])
    snap_date = datetime.date.fromisoformat(days[-1])   # 合成入库日要用日期对象
    print("分类账：%s ~ %s（%d 天）" % (days[0], days[-1], len(days)))

    inv = json.load(io.open(INV, encoding="utf-8"))["rows"]
    sku2sid, sku2age, sku2ful, sku2tot = {}, {}, {}, {}
    for r in inv:
        sid = str(r.get("sid"))
        # 同一行的 msku/sku/seller_sku 常常是同一个值，去重后再累加，避免重复计数
        keys = set()
        for k in ("msku", "sku", "seller_sku"):
            v = str(r.get(k) or "").strip().upper()
            if v:
                keys.add(v)
        for v in keys:
            sku2sid.setdefault(v, sid)
            a = sku2age.setdefault(v, [0.0] * 5)
            for i, f in enumerate(AGE_FIELDS):      # 同一 SKU 可能有多行，全累加
                a[i] += num(r.get(f))
            sku2ful[v] = sku2ful.get(v, 0.0) + num(r.get("afn_fulfillable_quantity"))
            sku2tot[v] = sku2tot.get(v, 0.0) + num(r.get("total"))

    # SPU 键必须与**实测快照**（archive_wh_snapshot.py）完全一致，否则实测点匹配不上，
    # 校准会退化成店级兜底比例 → 比例被放大几千倍 → 早期周出现 10 万双这种假峰值。
    # 实测口径：每行取 (sku 或 msku) 的 '-' 首段。
    # 账里的 SKU 命名有两种（同一批货）：
    #   sid=6574 用 seller_sku，形如 SD-2302153-BK-P-Z-7（带 SD- 前缀）
    #   sid=13120 用 sku，      形如 2302153-RD-S-Z-8.5
    # 所以这里登记**每个 SKU 字段** → SPU 键，账里用哪个字段名都能对上。
    sku2spu = {}
    for r in inv:
        sk = str(r.get("sku") or r.get("msku") or "").strip()
        spu = sk.split("-")[0] if sk else ""
        if not spu:
            continue
        for k2 in ("msku", "sku", "seller_sku"):
            v2 = str(r.get(k2) or "").strip().upper()
            if v2:
                sku2spu.setdefault(v2, spu)
    # ---- 静态库存底数：快照里有、但分类账 180 天内零事件的 SKU ----
    # 这批货在窗口内一直没动 → 数量恒定、不产生周间变化，但**总量要算进去**，
    # 否则推算总量整体偏低 ~20%，校准比例被放大，历史周还会出现「推算 0」。
    # 按快照**行**统计（msku/sku/seller_sku 是同一批货的不同命名，逐行算才不会重复计数）。
    led_skus = set(s.upper() for s in per[days[-1]].keys())
    led_all = set()
    for _d in days:
        for _s in per[_d].keys():
            led_all.add(_s.upper())
    static_base = defaultdict(lambda: [0.0, 0.0])   # (sid,spu) -> [total, 可售]
    n_static_sku = 0
    for r in inv:
        sk = str(r.get("sku") or r.get("msku") or "").strip()
        spu = sk.split("-")[0] if sk else ""
        if not spu or "." in spu or "AMAZON" in spu.upper():
            continue
        names = set()
        for k3 in ("msku", "sku", "seller_sku"):
            v3 = str(r.get(k3) or "").strip().upper()
            if v3:
                names.add(v3)
        if names & led_all:          # 这行在分类账里有记录 → 由 FIFO 推算负责
            continue
        n_static_sku += 1
        sid0 = str(r.get("sid"))
        static_base[(sid0, spu)][0] += num(r.get("total"))
        static_base[(sid0, spu)][1] += num(r.get("afn_fulfillable_quantity"))
    print("静态库存（账里零事件、窗口内不动）：%d 个 SKU 行，%d 个 (店,SPU) 有底数" %
          (n_static_sku, len(static_base)))

    ser = defaultdict(list)
    for d in days:
        for sku, a in per[d].items():
            ser[sku].append((d, a["sell_start"], a["sell_end"], a["in"], a["all_end"]))
    print("SKU 数：%d" % len(ser))

    wday = defaultdict(lambda: {"total": 0.0, "sell": 0.0, "b": [0.0] * 5})
    wk = defaultdict(lambda: {"total": 0.0, "sell": 0.0, "b": [0.0] * 5, "d": ""})
    last_rows = []          # (sid, spu, buckets) 逐 SKU 存
    last_by_sku = {}        # sku -> 末日桶，用于逐 SKU 对账
    miss = 0
    for sku, s in ser.items():
        sid = sku2sid.get(sku.upper())
        if not sid:
            miss += 1
            continue
        spu = (sku2spu.get(sku.upper())
                or spu_of(sku[3:] if sku.upper().startswith("SD-") else sku))
        if "." in spu or "AMAZON" in spu.upper():
            # 领星的占位 SKU（Amazon.Found.*）：不是我们的款号，快照里也没有 → 排除，
            # 否则推算里多算、实测里没有，校准永远对不齐
            miss += 1
            continue
        init = initial_queue(s[0][1], sku2age.get(sku.upper()), snap_date, first_day)
        rows = fifo_buckets(s, init)
        if not rows:
            continue
        last_rows.append((sid, spu, rows[-1][1]))
        last_by_sku[sku] = rows[-1][1]
        for (d, b, sell_end, all_end) in rows:
            day_slot = wday[(sid, spu, week_end(d), d)]   # 同一天内各 SKU 先求和
            day_slot["total"] += all_end
            day_slot["sell"] += sell_end
            for i in range(5):
                day_slot["b"][i] += b[i]
    if miss:
        print("  快照里找不到的 SKU：%d 个（不计入）" % miss)

    # 周结 = 该周最后一天
    for (sid, spu, w, d), ds in wday.items():
        slot = wk[(sid, spu, w)]
        if d > slot.get("d", ""):
            slot["d"] = d
            slot["total"] = ds["total"]
            slot["sell"] = ds["sell"]
            slot["b"] = list(ds["b"])

    # ---- 静态库存底数并入每周（恒定，不改变周间形状）----
    n_static_applied = 0
    for (sid0, spu0), (bt, bf) in static_base.items():
        ws0 = sorted(w for (s2, p2, w) in wk if s2 == sid0 and p2 == spu0)
        if not ws0:
            continue            # 这个 SPU 没有推算周 → 不新增（纯静态 SPU 不进产物）
        n_static_applied += 1
        for w in ws0:
            sl = wk[(sid0, spu0, w)]
            sl["total"] += bt
            sl["sell"] += bf
    print("静态底数并入 %d 个 (店,SPU) 的周序列" % n_static_applied)


    # ---- 合并每周实测快照（wh_hist/fba/*.json）：**实测点优先，推算点只做比例校准** ----
    # 2026-11-02 修（周序列全平的根因）：
    #   旧逻辑只在「最后一个实测周」取一组比例，然后把 **所有** 周（含没有推算值、
    #   sv=0 的周）都按「cur[i] × 比例」改写；凡是推算为 0 的那一项（比例=None），
    #   直接把 **实测值原样写进每一周** → 13 周被写成同一组数，画出来就是水平线。
    #   现在改成：① 有实测的周 → 直接用实测值（实测点优先）；
    #             ② 没实测的周 → FIFO 推算值 × 实测锚点比例（保留推算真实的周间变化）；
    #             ③ 锚点 = 「有实测、且推算里也有同一周」的周；取不到就用**店级比例**兜底。
    #   绝不复制上一周、绝不插值、绝不把整周写成同一个数。
    hist_dir = os.path.join(BASE, "wh_hist", "fba")
    meas = load_measured(hist_dir)
    n_hist = len(meas)
    n_anchor = 0
    n_shop = 0
    n_noratio = 0
    n_extreme = 0
    ext_list = []
    if meas:
        by_spu = defaultdict(list)
        for (sid, spu, w) in meas:
            by_spu[(sid, spu)].append(w)
        wk_keys = list(wk.keys())

        def vec_of(slot):
            return [slot["sell"], slot["total"], slot["b"][3] + slot["b"][4]] + list(slot["b"])

        # ---- ① 先算比例（全部基于**未校准**的推算值）----
        spu_ratios = {}          # (sid,spu) -> [8 个比例] 或 None
        calc_weeks_of = {}       # (sid,spu) -> [没实测的推算周]
        for (sid, spu), wlist in by_spu.items():
            wlist = sorted(wlist)
            calc_weeks = [w for (s2, p2, w) in wk_keys
                          if s2 == sid and p2 == spu and w not in wlist]
            if not any(s2 == sid and p2 == spu for (s2, p2, w) in wk_keys):
                # 这个 SPU 在分类账里根本没有推算记录 → 没有 13 周序列的底子，跳过
                continue
            calc_weeks_of[(sid, spu)] = calc_weeks
            # 锚点 = 有实测、且推算里也有同一周的，取最晚的那个
            ratios = None
            for w in reversed(wlist):
                if (sid, spu, w) in wk:
                    n_anchor += 1
                    mv = meas[(sid, spu, w)]
                    sv = vec_of(wk[(sid, spu, w)])
                    ratios = []
                    for i2 in range(8):
                        if sv[i2] > 0:
                            r2 = mv[i2] / sv[i2]
                            # 护栏：这一档在锚点周「推算≈0、实测有值」→ 比值会大到几十上百倍，
                            # 乘到历史周会出现「桶值比总双数还大」的假值。这种比例直接作废。
                            if r2 > RATIO_MAX or r2 < 1.0 / RATIO_MAX:
                                r2 = None
                            ratios.append(r2)
                        elif mv[i2] == 0:
                            ratios.append(0.0)      # 两边都没有 → 这一项恒为 0
                        else:
                            ratios.append(None)     # 推算看不见这一档 → 后面兜底
                    break
            spu_ratios[(sid, spu)] = ratios
            # 极端比例护栏：同周锚点的实测/推算比如果过大（账上这个 SPU 几乎没记录，
            # 实测却有几千双），拿它去乘所有历史周会造出假峰值（曾出现 10 万双）。
            # 这种情况下退回**店级比例**——店级比值稳定得多。
            if ratios is not None and ratios[1] is not None:
                if ratios[1] > RATIO_MAX or ratios[1] < 1.0 / RATIO_MAX:
                    n_extreme += 1
                    spu_ratios[(sid, spu)] = None
                    ext_list.append((sid, spu, round(ratios[1], 1)))

        # ---- ② 店级兜底比例：给「没有同周锚点」的 SPU 用 ----
        # 某店里「有实测、且推算也有这一周」的那些 SPU 合计起来算比例，
        # 反映这一店整体「推算 ↔ 实测」的口径差，再下发给没有锚点的 SPU。
        shop_ratios = {}
        for sid in sorted(set(k[0] for k in by_spu)):
            shop_weeks = sorted(set(w for (s2, spu, w) in meas if s2 == sid))
            for w in reversed(shop_weeks):
                mv_sum = [0.0] * 8
                sv_sum = [0.0] * 8
                hit = False
                for (s2, spu), wlist in by_spu.items():
                    if s2 != sid or w not in wlist:
                        continue
                    if (sid, spu, w) not in wk:
                        continue
                    hit = True
                    mv = meas[(sid, spu, w)]
                    sv = vec_of(wk[(sid, spu, w)])
                    for i in range(8):
                        mv_sum[i] += mv[i]
                        sv_sum[i] += sv[i]
                if not hit:
                    continue
                ratios = []
                for i in range(8):
                    if sv_sum[i] > 0:
                        ratios.append(mv_sum[i] / sv_sum[i])
                    elif mv_sum[i] == 0:
                        ratios.append(0.0)
                    else:
                        ratios.append(None)
                shop_ratios[sid] = ratios
                n_shop += 1
                break

        # ---- ③ 应用：没实测的周 = 推算值 × 比例（保留推算真实的周间变化）----
        for (sid, spu), calc_weeks in calc_weeks_of.items():
            ratios = spu_ratios.get((sid, spu))
            shop = shop_ratios.get(sid)
            if ratios is None:
                ratios = shop          # 没有同周锚点 → 用店级比例
            if ratios is None:
                ratios = [1.0] * 8     # 店级也没有 → 不校准（保持推算原值）
            # 兜底比例必须**同档位**：某一档推算为 0、实测有值时，
            # 只能用「同档位」的比例去乘（原来错用总双数档的比例，维度不对，
            # 会让库龄档被放大几倍，出现 1.03 → 2.56 这种跳变）。
            for w in calc_weeks:
                sl = wk[(sid, spu, w)]
                cur = vec_of(sl)
                newv = []
                for i in range(8):
                    r = ratios[i]
                    if r is None:
                        # 这一档推算为 0、实测有值 → 本档比例救不了 0，
                        # 依次退：同档位店级比例 → 本 SPU 总双数档比例 → 1.0
                        r = None
                        if shop and shop[i] is not None:
                            r = shop[i]
                        if r is None and ratios[1] is not None:
                            r = ratios[1]
                        if r is None:
                            r = 1.0
                        n_noratio += 1
                    newv.append(cur[i] * r)
                sl["sell"] = newv[0]
                sl["total"] = newv[1]
                sl["b"] = newv[3:8]
                # 一致性钳制：实测口径里「总双数 ≈ 5 档之和」，
                # 各档分别乘不同比例后可能超过总双数 → 按比例压回去（保持档间形状）
                bsum = sum(sl["b"])
                if bsum > sl["total"] > 0:
                    f2 = sl["total"] / bsum
                    sl["b"] = [x * f2 for x in sl["b"]]
        # 实测周：直接落实测值（实测点优先）
        # 只给「分类账里有推算记录」的 SPU 落实测点：
        # 那些只有实测、没有推算的 SPU 没有 13 周序列的底子，不进产物（否则前端一片空）
        for (sid, spu) in calc_weeks_of:
            for w in sorted(by_spu[(sid, spu)]):
                mv = meas[(sid, spu, w)]
                if (sid, spu, w) not in wk:
                    wk[(sid, spu, w)] = {"sell": 0.0, "total": 0.0, "b": [0.0] * 5, "d": w}
                sl = wk[(sid, spu, w)]
                sl["sell"] = mv[0]
                sl["total"] = mv[1]
                sl["b"] = list(mv[3:8])

        print("合并实测快照点：%d 个（%d 个 SPU 有实测；同周锚点 %d 个 SPU，店级兜底比例 %d 个店，比例兜底 %d 处）"
              % (n_hist, len(by_spu), n_anchor, n_shop, n_noratio))
        if ext_list:
            ext_list.sort(key=lambda x: -x[2])
            print("  极端比例退回店级的 SPU：%d 个" % n_extreme)
            for sid, spu, r in ext_list[:8]:
                print("     sid=%s SPU=%s 比值=%.1f" % (sid, spu, r))

    shops = defaultdict(lambda: {"weeks": set(), "spu": defaultdict(dict)})
    for (sid, spu, w), slot in wk.items():
        b = slot["b"]
        old = b[3] + b[4]
        shops[sid]["weeks"].add(w)
        shops[sid]["spu"][spu][w] = [round(slot["sell"], 1), round(slot["total"], 1),
                                     round(old, 1)] + [round(x, 1) for x in b]
    # 只保留最近 KEEP_WEEKS 周（用户 2026-10-30：趋势只看最近 3 个月）
    KEEP_WEEKS = 13
    res = {}
    for sid, sh in shops.items():
        wlist = sorted(sh["weeks"])[-KEEP_WEEKS:]
        res[sid] = {"weeks": wlist,
                    "spu": {spu: [wmap.get(w) for w in wlist]
                            for spu, wmap in sh["spu"].items()}}
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(res, ensure_ascii=False, separators=(",", ":")))

    # ---- 对账 ----
    print("\n== 对账（%s 推算 vs 当前快照）==" % snap_date)
    ga = [0.0] * 5
    gb = [0.0] * 5
    # 只对「两边都有」的 SKU 逐个比，避免重复累加
    for sku, b in last_by_sku.items():
        a = sku2age.get(sku.upper())
        if not a:
            continue
        for i in range(5):
            ga[i] += b[i]
            gb[i] += a[i]
    names = ["0-90", "91-180", "181-270", "271-365", "365+"]
    print("  %-9s %10s %10s %9s" % ("档", "推算", "实际", "误差"))
    for i in range(5):
        print("  %-9s %10.0f %10.0f %8.1f%%" % (
            names[i], ga[i], gb[i], (ga[i] - gb[i]) / gb[i] * 100 if gb[i] else 0))
    print("  %-9s %10.0f %10.0f %8.1f%%" % (
        "合计", sum(ga), sum(gb),
        (sum(ga) - sum(gb)) / sum(gb) * 100 if sum(gb) else 0))
    print("  老库龄(271+)  推算 %.0f | 实际 %.0f" % (ga[3] + ga[4], gb[3] + gb[4]))

    print("\n写入 %s（%.1f KB）" % (OUT, os.path.getsize(OUT) / 1024))
    for sid, d in res.items():
        n = sum(len(v) for v in d["spu"].values())
        print("  sid=%s SPU %d 个 / %d 周 / %d 个周点" % (sid, len(d["spu"]), len(d["weeks"]), n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
