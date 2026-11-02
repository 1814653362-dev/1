# -*- coding: utf-8 -*-
"""物流功能数据随机抽检：回源 WorkBuddy 资料库快照，与站点在用的 records.json 逐字段比对。

用法:
  python audit_logistics.py --src <源快照 records.json> [--sys <站点 records.json>] [--n 10]

三类结论分开报：
  ① 系统异常（页面算错 / 护栏不过 / 源站差异方向混杂或反向 / 站侧构建时间不早于源更新时间）—— 必须为 0，有则退出码 2
  ② 待同步（源比站新：站侧构建时间早于源更新时间，且全部差异行都是单向「站空→源有值」）—— 不算系统异常，退出码 0，报告单列待同步行数
  ③ 源数据质量缺口（源=站，但字段之间互相矛盾，如总运费空缺、日期异常）—— 计数并给样例，不判系统失败

待同步口径（2026-10-30 主管-小天裁决，别自创）：
  · 判「待同步」要同时满足：① 站侧 records.json 的 _meta.fetchedAt 早于源数据更新时间
    （--src-updated-at，即共享盘发货记录.xlsx 的最后修改时间）② 全部行级差异都是
    「站侧空 → 源侧有值」，没有任何反向（站有值、源没有）或同期变化（两边都非空但值不同）。
  · 出现反向差异 / 方向混杂 / 站侧构建时间不早于源更新时间 → 一律算系统异常（退出码 2）。
  · 防掩盖：同一批差异连续两轮都判待同步 → 第二轮起按系统异常报，提示刷新链路可能没跑或没生效；
    轮次记在 --state 指定的文件（默认 workspace\audit_sync_state.json），不碰 audit_plan.py 的抽检规则。

页面口径依据（物流功能卡片）：
  priced 判定 = 总运费列非空；unpriced = 总运费为空（v134.html engineSkuCost / normRow）
  单件运费 = 汇总总运费 ÷ 汇总件数（仅 priced 记录）
  时效天数 = 直接取「时效天数」列，缺列才用 送达日期−发货日期
"""
import json, io, os, sys, random, argparse, collections, datetime, hashlib

sys.stdout.reconfigure(encoding="utf-8")

WS = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SYS = os.path.join(WS, "shandi-v5", "records.json")

try:
    import audit_features as AF
except Exception:  # 复算模块不可用时只跑 A/B/C/D 段
    AF = None

MAIN_FIELDS = [
    ("FBA货件号", "FBA货件号"), ("SKU", "SKU"), ("仓库代码", "仓库代码"), ("件数", "件数"),
    ("箱数", "箱数"), ("发货日期", "发货日期"), ("送达日期", "送达日期"), ("时效天数", "时效天数"),
    ("地区", "地区"), ("船型", "船型"), ("船名航次", "船名航次"), ("进仓编号", "进仓编号"),
    ("单价", "单价"), ("总运费", "总运费"), ("物流费", "物流费"), ("报关费", "报关费"),
    ("拖车费", "拖车费"), ("计费重量", "计费重量"), ("货拉拉费", "货拉拉费"), ("对账单价", "对账单价"),
    ("对账合计", "对账合计"), ("对账差异", "对账差异"), ("费用完整", "费用完整"), ("月份", "月份"),
]
SKU_FIELDS = [("SKU", "SKU"), ("品名", "品名"), ("已发货", "已发货"), ("货件单号", "货件单号")]
# ---- 派生字段（2026-11-02 小丁提、主管定）----
# 「送达日期」现在会由领星 receiving_time（仓库开始接收时刻）回填空值，
# 「仓库接收时间」列是领星 receiving_time 原值。两者在源侧（共享盘发货记录）没有对应值，
# 抽检是拿共享盘当源做逐字段比对 → 这两个字段必然源≠站，天天误报「系统异常」。
# 处理：标为派生字段 —— 差异只报不判（不计系统异常、不参与待同步方向判定）。
DERIVED_FIELDS = ["送达日期", "仓库接收时间"]
FEE3 = ["报关费", "拖车费", "物流费"]


def num(v):
    try:
        if v is None or v == "":
            return None
        n = float(v)
        return n if n == n else None
    except Exception:
        return None


def d10(v):
    s = str(v or "").strip()
    return s[:10] if len(s) >= 10 else ""


def load(path):
    return json.load(io.open(path, encoding="utf-8"))


def by_id(rows):
    return {r["_id"]: r for r in (rows or []) if r.get("_id")}


def cmp_field(a, b):
    na, nb = num(a), num(b)
    if na is not None or nb is not None:
        if na is None or nb is None:
            return (na or 0) == (nb or 0)
        return abs(na - nb) <= 0.01
    return str(a if a is not None else "") == str(b if b is not None else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="回源快照 records.json 路径")
    ap.add_argument("--sys", default=DEFAULT_SYS, help="站点在用的 records.json 路径")
    ap.add_argument("--n", type=int, default=10, help="随机抽检记录数")
    ap.add_argument("--src-updated-at", default="",
                    help="源数据最后修改时间 'YYYY-MM-DD HH:MM:SS'（共享盘发货记录.xlsx 的 mtime）；"
                         "用于判定「源比站新」。WorkBuddy 回源只有抓取时刻（恒为当前），拿它当判据会让"
                         "「站侧早于源」永真、真回归反而判不出来，故不采用")
    ap.add_argument("--state", default=os.path.join(WS, "audit_sync_state.json"),
                    help="防掩盖状态文件（连续两轮待同步 → 第二轮起判系统异常）")
    ap.add_argument("--degraded", action="store_true",
                    help="本次回源降级（WorkBuddy 拉不到、用本地快照）："
                         "WorkBuddy 补充字段与站侧同源，不可独立核验，差异不计系统异常")
    ap.add_argument("--degraded-snapshot-at", default="",
                    help="降级所用快照的时间（报告里写明）")
    ap.add_argument("--degraded-fields", default="",
                    help="本次未独立回源的字段名，逗号分隔")
    ap.add_argument("--degraded-reason", default="",
                    help="降级原因（报告里写明）")
    ap.add_argument("--derived-fields", default="",
                    help="派生字段名（逗号分隔）：源侧没有对应值，差异只报不判。"
                         "默认用内置 DERIVED_FIELDS（送达日期/仓库接收时间）")
    args = ap.parse_args()

    src, sysd = load(args.src), load(args.sys)
    s_main, s_sku = src.get("main") or [], src.get("sku") or []
    y_main, y_sku = sysd.get("main") or [], sysd.get("sku") or []

    # ---------- SKU 备货明细换领星源（2026-11-02 小丁/主管定）----------
    # 站侧 SKU 表 = 领星 shipmentList.item_list；源侧（WorkBuddy 回源）的 SKU 表是另一套数据，
    # 口径与覆盖都不同（领星多 3 万多双、多覆盖 800 多个货件），两者无法逐条核验。
    # 处理：SKU 表的行数 / 逐条差异 / 批次源站对账一律「只报不判」，不计系统异常。
    SKU_FROM_LX = bool(y_sku) and any("_shipment_status" in r for r in y_sku[:50])
    if SKU_FROM_LX:
        print("\n[SKU 源] 站侧 SKU 备货明细已换领星源（%d 行）；源侧快照的 SKU 表 %d 行"
              "（与站侧同源或口径不同，均不可逐条独立核验）→ SKU 表相关差异只报不判"
              % (len(y_sku), len(s_sku)))

    # ---------- 回源降级标记（2026-11-02 小丁定） ----------
    # WorkBuddy 拉不到时 refresh_data.ps1 降级用本地快照。此时 WorkBuddy 补充字段
    # （SKU表 / 对账字段 / 送达日期 / 时效天数 / 箱规 / 货件状态等继承字段）
    # 在「源侧」和「站侧」同源 —— 不可独立核验，不能假装核过、也不能当成系统异常。
    # 处理：这些字段的差异单独记入 unverif（未独立核验），不计系统异常、不参与方向判定。
    DEGRADED = bool(args.degraded)
    UNVERIF = set()
    if DEGRADED:
        for x in (args.degraded_fields or "").split(","):
            x = x.strip()
            if x:
                UNVERIF.add(x)
        print("\n" + "!" * 72)
        print("!! 本次回源降级：WorkBuddy 拉取失败，改用本地快照继续抽检")
        print("!!   快照时间 = %s" % (args.degraded_snapshot_at or "(未知)"))
        print("!!   降级原因 = %s" % (args.degraded_reason or "(未提供)"))
        print("!!   本次未独立回源的字段（与站侧同源、不可独立核验）：%s"
              % ("、".join(sorted(UNVERIF)) or "(未列出)"))
        print("!!   → 这些字段的差异单列「未独立核验」，不计系统异常、不参与待同步方向判定")
        print("!" * 72)
    UNVERIF_EXTRA = set()
    if SKU_FROM_LX:
        UNVERIF_EXTRA.add("SKU表")
    DERIVED = set(DERIVED_FIELDS)
    if args.derived_fields:
        DERIVED = set(x.strip() for x in args.derived_fields.split(",") if x.strip())
    unverif = []      # 降级模式下不可独立核验的差异（kind, 描述）
    derived_diff = []  # 派生字段差异（只报不判）

    def is_unverif(label):
        return (DEGRADED and label in UNVERIF) or (label in UNVERIF_EXTRA)

    print("回源快照 %s（fetchedAt=%s）" % (os.path.basename(args.src), src.get("_meta", {}).get("fetchedAt")))
    print("站点数据 %s（fetchedAt=%s）" % (os.path.basename(args.sys), sysd.get("_meta", {}).get("fetchedAt")))

    sync_bad = []     # (kind, 描述)；kind="real"=真系统异常（页面算错/护栏/方向混杂），kind="src"=源站差异（可能是待同步）
    quality = collections.Counter()   # 源数据质量缺口
    q_samples = collections.defaultdict(list)

    # ---------- A 全量级 ----------
    def agg(rows):
        q = f = 0.0
        unpriced = 0
        for r in rows:
            q += num(r.get("件数")) or 0.0
            f += num(r.get("总运费")) or 0.0
            if num(r.get("总运费")) is None:
                unpriced += 1
        return q, f, unpriced

    aq, af, aun = agg(s_main)
    bq, bf, bun = agg(y_main)
    sreg = collections.Counter(r.get("地区") or "-" for r in s_main)
    yreg = collections.Counter(r.get("地区") or "-" for r in y_main)
    print("\n[A 全量级 源 vs 站]")
    print("主表行数        %d | %d | 差 %d" % (len(s_main), len(y_main), len(y_main) - len(s_main)))
    print("SKU表行数       %d | %d | 差 %d" % (len(s_sku), len(y_sku), len(y_sku) - len(s_sku)))
    print("件数合计(双)    %.0f | %.0f | 差 %.0f" % (aq, bq, bq - aq))
    print("总运费合计(元)  %.0f | %.0f | 差 %.2f" % (af, bf, bf - af))
    print("总运费空缺(条)  %d | %d | 差 %d" % (aun, bun, bun - aun))
    print("地区分布        %s | %s" % (dict(sreg), dict(yreg)))
    if len(s_main) != len(y_main) or (not is_unverif("SKU表") and len(s_sku) != len(y_sku)) \
            or abs(aq - bq) > 0.01 or abs(af - bf) > 1 or sreg != yreg:
        sync_bad.append(("src", "全量级：行数/件数合计/总运费合计/地区分布 源≠站"))

    # ---------- A2 地区标签分布 + 未映射标签告警（2026-10-30 小丁要求） ----------
    # 归属规则（页面统一口径）：前缀归属——美西*→美西、美东*→美东、美中*→美中；
    # 空值与其余标签→未知。凡「既非空、又不在美西/美东/美中及其子标签里」的标签，
    # 计入源数据质量缺口；空值标签单独算「地区为空」一类计数，不与未知标签混为一类。
    print("\n[A2 地区标签分布与映射护栏]")
    label_dist = collections.Counter()
    for r in s_main:
        lab = str(r.get("地区") or "").strip()
        label_dist[lab] += 1
    reg_bucket = collections.Counter()
    unmapped_labels = collections.Counter()
    empty_label = 0
    for lab, c in label_dist.items():
        if not lab:
            empty_label += c
            reg_bucket["unknown"] += c
            continue
        reg, is_unmapped = AF.region_label_status(lab) if AF else ("unknown", True)
        reg_bucket[reg] += c
        if is_unmapped:
            unmapped_labels[lab] += c
    print("  标签分布：%s" % ("、".join("%s %d 条" % (lab if lab else "(空)", c)
                                     for lab, c in label_dist.most_common())))
    print("  前缀归属后：美西 %d / 美东 %d / 美中 %d / 未知 %d 条"
          % (reg_bucket.get("us_west", 0), reg_bucket.get("us_east", 0),
             reg_bucket.get("us_central", 0), reg_bucket.get("unknown", 0)))
    print("  地区为空 %d 条（单列一类，不与未知标签混淆）" % empty_label)
    if unmapped_labels:
        print("  ⚠ 未映射标签 %d 类：" % len(unmapped_labels))
        for lab, c in unmapped_labels.most_common():
            print("     · %s %d 条" % (lab, c))
    else:
        print("  未映射标签 0 类（现有标签全部可归入美西/美东/美中或其子标签）")
    if empty_label:
        quality["地区为空"] = empty_label
    if unmapped_labels:
        quality["地区标签未映射"] = sum(unmapped_labels.values())
        for lab, c in unmapped_labels.most_common():
            if len(q_samples["地区标签未映射"]) < 2:
                q_samples["地区标签未映射"].append((lab, c))

    # ---------- B 记录级随机抽检 ----------
    smap, ymap = by_id(s_main), by_id(y_main)
    common = [k for k in smap if k in ymap]
    random.shuffle(common)
    picks = common[: max(1, args.n)]
    print("\n[B 记录级 随机抽检 %d 条主表]（候选 %d 条）" % (len(picks), len(common)))
    print("FBA货件号 | 字段 | 源值 | 站点值")
    bdiff = 0
    n_cmp = 0
    for k in picks:
        sr, yr = smap[k], ymap[k]
        for col, label in MAIN_FIELDS:
            a, b = sr.get(col), yr.get(col)
            if label in DERIVED:
                # 派生字段：源侧本就没有这个值，比出来必不一致 → 只记不计
                if not cmp_field(a, b):
                    derived_diff.append(("B", "记录级 %s | %s：源≠站（派生字段，只报不判）"
                                         % (sr.get("FBA货件号"), label)))
                continue
            if is_unverif(label):
                # 本次未独立回源：不判定一致/不一致，只记「不可核验」
                if not cmp_field(a, b):
                    unverif.append(("B", "记录级 %s | %s：源≠站（未独立回源，不可核验）" % (sr.get("FBA货件号"), label)))
                continue
            n_cmp += 1
            if cmp_field(a, b):
                continue
            bdiff += 1
            sync_bad.append(("src", "记录级 %s | %s：源≠站" % (sr.get("FBA货件号"), label)))
            print("%s | %s | %s | %s" % (sr.get("FBA货件号"), label, a, b))
    if bdiff == 0:
        print("全部一致（每条比对 %d 个字段）" % (n_cmp // max(1, len(picks))))

    ssmap, ysmap = by_id(s_sku), by_id(y_sku)
    scommon = [k for k in ssmap if k in ysmap]
    random.shuffle(scommon)
    spicks = scommon[: max(1, args.n // 2)]
    sdiff = 0
    sku_unverif = is_unverif("SKU表")
    for k in spicks:
        sr, yr = ssmap[k], ysmap[k]
        for col, label in SKU_FIELDS:
            a, b = sr.get(col), yr.get(col)
            if cmp_field(a, b):
                continue
            sdiff += 1
            if sku_unverif:
                unverif.append(("B2", "SKU表 %s | %s：源≠站（未独立回源，不可核验）" % (sr.get("货件单号"), label)))
            else:
                sync_bad.append(("src", "SKU表 %s | %s：源≠站" % (sr.get("货件单号"), label)))
    print("[B2 SKU表 随机抽检 %d 条] 差异 %d 处%s"
          % (len(spicks), sdiff, "（未独立回源，不计系统异常）" if sku_unverif else ""))
    if SKU_FROM_LX:
        print("     ⚠ SKU 表已换领星源：源侧 WorkBuddy 表与站侧领星表 _id 不同源，无法逐条抽检（只报不判）")

    # ---------- A3 全量行级差异方向扫描（2026-10-30 主管裁决：区分「待同步」与「系统异常」） ----------
    # 为什么必须全量：B 段只随机抽 10 条，判「差异是否全部单向」得看全量。
    # 方向定义（按字段逐个判）：
    #   正向 FORWARD  = 站侧该字段为空、源侧有值 → 源被补录/新增，站还没跟上（可能是待同步）
    #   反向 BACKWARD = 站侧该字段有值、源侧为空 → 站多了或源缺，真丢数据 → 系统异常
    #   同期 CHANGED  = 两边都非空但值不同 → 刷新时源数据已在却没落上线，真回归 → 系统异常
    def is_empty(v):
        if v is None:
            return True
        s = str(v).strip()
        return s == "" or s == "None"

    smap_all, ymap_all = by_id(s_main), by_id(y_main)
    a3_rows = collections.defaultdict(list)   # _id → [(字段, 方向, 源值, 站值)]
    for k in set(smap_all) & set(ymap_all):
        sr, yr = smap_all[k], ymap_all[k]
        for col, label in MAIN_FIELDS:
            a, b = sr.get(col), yr.get(col)
            if cmp_field(a, b):
                continue
            if label in DERIVED:
                # 派生字段：差异只报不判，也不参与方向判定（否则天天误报系统异常）
                derived_diff.append(("A3", "行级 %s | %s：源≠站（派生字段，只报不判）" % (k, label)))
                continue
            if is_unverif(label):
                # 未独立回源的字段：源站同源，差异不参与方向判定（不算系统异常、也不算待同步）
                unverif.append(("A3", "行级 %s | %s：源≠站（未独立回源，不可核验）" % (k, label)))
                continue
            if is_empty(b) and not is_empty(a):
                kind = "正向"
            elif is_empty(a) and not is_empty(b):
                kind = "反向"
            else:
                kind = "同期"
            a3_rows[k].append((label, kind, a, b))
    n_fwd = sum(1 for lst in a3_rows.values() for x in lst if x[1] == "正向")
    n_bwd = sum(1 for lst in a3_rows.values() for x in lst if x[1] == "反向")
    n_chg = sum(1 for lst in a3_rows.values() for x in lst if x[1] == "同期")
    print("\n[A3 行级差异方向扫描（全量 %d 行）]" % len(y_main))
    if DEGRADED and unverif:
        print("  （本次降级：未独立回源字段的差异已排除，不参与方向判定）")
    if not a3_rows:
        print("  无行级差异")
    else:
        print("  差异行 %d 行 | 差异字段 %d 处 → 正向(站空→源有值) %d 处 / 反向(站有值→源空) %d 处 / 同期(都非空但不同) %d 处"
              % (len(a3_rows), n_fwd + n_bwd + n_chg, n_fwd, n_bwd, n_chg))
        shown = 0
        for k, lst in a3_rows.items():
            for label, kind, a, b in lst:
                if shown >= 3:
                    break
                print("   例：%s | %s | %s | 站=%s → 源=%s" % (k, label, kind, b, a))
                shown += 1

    # ---------- C 派生级（按页面真实算法） ----------
    priced = [r for r in y_main if num(r.get("总运费")) is not None]
    unpriced = [r for r in y_main if num(r.get("总运费")) is None]
    pq = sum(num(r.get("件数")) or 0.0 for r in priced)
    pf = sum(num(r.get("总运费")) or 0.0 for r in priced)
    print("\n[C 派生级 页面口径复算]")
    print("priced 记录 %d 条 | unpriced %d 条 | priced 件数 %.0f | priced 总运费 %.0f | 单件运费 %.4f 元/件"
          % (len(priced), len(unpriced), pq, pf, (pf / pq if pq else 0)))

    # 抽 3 条真实货件，用页面算法复算该 SKU 的单件运费
    print("SKU 单件运费复算（页面口径：命中该 SKU 的 priced 记录汇总运费÷汇总件数）")
    sample_recs = random.sample(priced, min(3, len(priced)))
    for r in sample_recs:
        toks = [t.strip() for t in str(r.get("SKU") or "").split("&") if t.strip()]
        if not toks:
            continue
        sk = toks[0]
        q = f = 0.0
        n = 0
        for rr in priced:
            rtoks = [t.strip() for t in str(rr.get("SKU") or "").split("&")]
            if sk in rtoks:
                q += num(rr.get("件数")) or 0.0
                f += num(rr.get("总运费")) or 0.0
                n += 1
        if n and q:
            print("   %s | 命中 priced %d 条 | 件数 %.0f | 运费 %.0f | 单件运费 %.4f 元/件"
                  % (sk, n, q, f, f / q))
        else:
            print("   %s | priced 命中 %d 条，无法复算单件运费" % (sk, n))

    # ---------- D 源数据质量缺口（源=站，字段自相矛盾） ----------
    fee_sum_bad = 0
    fee_sum_ok = 0
    fee_empty_but_have3 = []
    for r in y_main:
        f3 = [num(r.get(f)) for f in FEE3]
        if all(v is not None for v in f3):
            fee_sum_ok += 1
            tot = num(r.get("总运费"))
            if tot is None:
                fee_empty_but_have3.append(r.get("FBA货件号"))
            elif abs(sum(f3) - tot) > 0.01:
                fee_sum_bad += 1
                if len(q_samples["总运费≠三项之和"]) < 5:
                    q_samples["总运费≠三项之和"].append((r.get("FBA货件号"), sum(f3), tot))
        else:
            if num(r.get("总运费")) is not None:
                quality["费用三项缺但总运费有值"] += 1
    if fee_empty_but_have3:
        quality["三项齐全但总运费为空"] = len(fee_empty_but_have3)
        for s in fee_empty_but_have3[:5]:
            q_samples["三项齐全但总运费为空"].append(s)
    if fee_sum_bad:
        quality["总运费≠三项之和"] = fee_sum_bad

    # 时效天数 vs 送达−发货（页面以表内列为准，这里只做数据质量提示）
    diff1 = 0
    neg = []
    other = []
    checked = 0
    today = datetime.date.today()
    future_ship = 0
    for r in y_main:
        sd, dd = d10(r.get("发货日期")), d10(r.get("送达日期"))
        td = num(r.get("时效天数"))
        if sd and dd and td is not None:
            try:
                calc = (datetime.date.fromisoformat(dd) - datetime.date.fromisoformat(sd)).days
                checked += 1
                if calc == td:
                    pass
                elif calc == td - 1:
                    diff1 += 1
                elif calc < 0:
                    neg.append((r.get("FBA货件号"), td, calc))
                else:
                    other.append((r.get("FBA货件号"), td, calc))
            except Exception:
                pass
        if sd:
            try:
                if datetime.date.fromisoformat(sd) > today:
                    future_ship += 1
            except Exception:
                pass
    if diff1:
        quality["时效天数比日期差多1天"] = diff1
    if neg:
        quality["发货日期晚于送达日期"] = len(neg)
        for t in neg[:5]:
            q_samples["发货日期晚于送达日期"].append(t)
    if other:
        quality["时效天数与日期差其它值"] = len(other)
        for t in other[:5]:
            q_samples["时效天数与日期差其它值"].append(t)

    # FBA货件号列格式异常：填的是货代进仓号/内部号（RVG…/RVSDGF…/STAR…）而不是真 FBA 号。
    # 这类行与领星 shipmentList 永远对不上（freight_bill_number 也查不到），
    # 货件状态只能靠 WorkBuddy 继承值，人工补录前系统判不出入仓/在途。
    bad_fba = [r for r in y_main if not str(r.get("FBA货件号") or "").strip().startswith("FBA")]
    if bad_fba:
        bad_gap = [r for r in bad_fba
                   if not str(r.get("货件状态") or "").strip() and not str(r.get("送达日期") or "").strip()]
        quality["FBA货件号列非FBA号(进仓号/内部号)"] = len(bad_fba)
        if bad_gap:
            quality["非FBA号行中既不入仓也不在途"] = len(bad_gap)
        for r in bad_gap[:2]:
            q_samples["FBA货件号列非FBA号(进仓号/内部号)"].append(
                "%s / %s / %s双 / 状态=%s" % (r.get("FBA货件号"), r.get("SKU"), r.get("件数"),
                                            r.get("货件状态") or "空"))
    if future_ship:
        quality["发货日期在未来"] = future_ship

    print("\n[D 源数据质量缺口 源=站但字段自相矛盾]")
    if not quality:
        print("无")
    for k, v in quality.most_common():
        print("   %-22s %d 条" % (k, v))
    for k, lst in q_samples.items():
        for item in lst:
            print("   例：%s | %s" % (k, item))

    # ---------- E 三个关联功能核对（2026-10-30 小丁点名：必须每次都对） ----------
    # ① SKU成本统计 ② 时间范围平均运费（按地区）③ SKU批次在途（备货联动）
    # 三层比对：页面真值（跑 index.html 原 JS）vs 站侧独立复算 vs 源侧独立复算
    e_bad = []          # (kind, 描述)；real=页面/算法算错（真异常），src=源站复算差（可能待同步）
    e_quality = collections.Counter()   # E 段新发现的源数据质量缺口（D 段已打印过，这里单独报）
    if AF is None:
        e_bad.append(("real", "核对模块不可用：audit_features.py 导入失败"))

    if AF is not None:
        # 口径说明（2026-10-30 小丁定）：
        #   页面口径（page）—— 镜像 index.html 当前的地区映射，用于「页面真值 vs 复算」查页面算错
        #   统一口径（prefix）—— 前缀归属（美西*/美东*/美中*），源复算一律用这套
        # 若页面仍是精确匹配（page_mode=exact），两套口径的差异是映射未同步，不算系统异常。
        page_mode = AF.page_region_mode()
        src_recs = AF.norm_records(s_main, region_mode="prefix")
        sys_recs = AF.norm_records(y_main, region_mode="page")
        sys_recs_pf = AF.norm_records(y_main, region_mode="prefix")
        pc = AF.page_constants()
        mapping_not_synced = (page_mode != "prefix")

        # 探针 SKU：取站侧记录里出现最多的几个真实 SKU
        token_cnt = collections.Counter()
        for r in sys_recs:
            for t in AF.split_skus(r.get("sku")):
                token_cnt[AF.norm_sku(t)] += 1
        probes = [s for s, _ in token_cnt.most_common(8)][:3]

        truth = AF.page_truth(y_main, probes)
        truth_b = AF.page_truth_batch(y_main, y_sku, page_const=pc)

        print("\n[E 三个关联功能核对]")
        print("  地区映射口径：页面=%s / 源复算=prefix（前缀归属）%s"
              % (page_mode, "（页面映射口径未同步，差异不计系统异常）" if mapping_not_synced else ""))
        if truth is None:
            print("  页面真值不可用（JS 引擎或页面文件缺失），本段只做源/站对账")
            e_bad.append(("real", "页面真值不可用"))

        def cmp_items(a_items, b_items, keys):
            """按 key 对齐两组 item，比对指定字段。返回 (是否一致, 差异描述列表)"""
            bmap = {x.get("region"): x for x in (b_items or [])}
            diffs = []
            for it in (a_items or []):
                j = bmap.get(it.get("region"))
                if j is None:
                    diffs.append("%s 缺项" % it.get("region"))
                    continue
                for key, tol in keys:
                    x, y = it.get(key), j.get(key)
                    if x is None or y is None:
                        if (x is None) != (y is None):
                            diffs.append("%s.%s %s≠%s" % (it.get("region"), key, x, y))
                    elif abs(float(x) - float(y)) > tol:
                        diffs.append("%s.%s %s≠%s" % (it.get("region"), key, x, y))
            for it in (b_items or []):
                if it.get("region") not in {x.get("region") for x in (a_items or [])}:
                    diffs.append("%s 多项" % it.get("region"))
            return (not diffs), diffs

        # ① SKU成本统计
        print("  ① SKU成本统计（单件运费 = priced 汇总运费 ÷ 汇总件数）")
        for p in probes:
            py_sys = AF.engine_sku_cost(sys_recs, p)["agg"]          # 页面口径
            py_sys_pf = AF.engine_sku_cost(sys_recs_pf, p)["agg"]      # 统一前缀口径
            py_src = AF.engine_sku_cost(src_recs, p)["agg"]           # 源侧统一前缀口径
            t = next((x for x in (truth or {}).get("sku", []) if x["sku"] == p), None)
            ok_js = ok_src = True
            if t:
                for key, jkey, tol in (("per_unit_freight", "per_unit_freight", 0.0002),
                                       ("total_quantity", "total_quantity", 0.5),
                                       ("total_box_count", "total_box_count", 0.5),
                                       ("total_freight", "total_freight", 0.05)):
                    a, b = py_sys.get(key), t.get(jkey)
                    if a is None or b is None:
                        ok_js = ok_js and (a is None and b is None)
                    else:
                        ok_js = ok_js and abs(float(a) - float(b)) <= tol
                if not ok_js:
                    e_bad.append(("real", "① SKU成本统计 %s：页面算错（独立复算与页面 JS 不一致）" % p))
            if abs(float(py_sys_pf["total_freight"] or 0) - float(py_src["total_freight"] or 0)) > 0.05 \
                    or abs(float(py_sys_pf["total_quantity"] or 0) - float(py_src["total_quantity"] or 0)) > 0.5:
                ok_src = False
                e_bad.append(("src", "① SKU成本统计 %s：源≠站（源 %.4f 元/件，站 %.4f 元/件）"
                              % (p, py_src.get("per_unit_freight") or 0, py_sys_pf.get("per_unit_freight") or 0)))
            ub = AF.unknown_bucket_stats(AF.engine_sku_cost(sys_recs_pf, p)["matched_rows"])
            print("     %-12s 站复算 %.4f 元/件 | 页面真值 %s | 源复算 %.4f 元/件 | 页面%s 源站%s | 未知桶 %d 条（空值 %d / 未映射 %d）"
                  % (p, py_sys.get("per_unit_freight") or 0,
                     ("%.4f" % t["per_unit_freight"]) if t and t.get("per_unit_freight") is not None else "—",
                     py_src.get("per_unit_freight") or 0,
                     "一致" if ok_js else "不一致", "一致" if ok_src else "不一致",
                     ub["unknown"], ub["empty"], ub["unmapped"]))
            if ub["unmapped"]:
                e_quality["功能命中记录含未映射地区标签"] += ub["unmapped"]

        # ② 时间范围平均运费（按地区）
        print("  ② 时间范围平均运费（按地区，最近12个月，元/kg）")
        avg_sys = AF.engine_average(sys_recs)        # 页面口径
        avg_sys_pf = AF.engine_average(sys_recs_pf)    # 统一前缀口径
        avg_src = AF.engine_average(src_recs)         # 源侧统一前缀口径
        js_map = {x["region"]: x for x in (truth or {}).get("avg", {}).get("items", [])}

        # 2a. 页面真值 vs 页面口径复算 → 查「页面算错」（桶集合按页面自己的口径走）
        for it in avg_sys["items"]:
            j = js_map.get(it["region"])
            if j:
                ok_js = True
                for key, tol in (("average_unit_price", 0.011), ("record_count", 0.5), ("weighted_quantity", 0.5)):
                    a, b = it.get(key), j.get(key)
                    if a is None or b is None:
                        ok_js = ok_js and (a is None and b is None)
                    else:
                        ok_js = ok_js and abs(float(a) - float(b)) <= tol
                if not ok_js:
                    e_bad.append(("real", "② 时间范围平均运费 %s：页面算错（独立复算与页面 JS 不一致）" % it["region"]))

        # 2b. 源站对账 → 两边都用统一前缀口径（桶集合一致，差异才是真源≠站）
        for it_pf in avg_sys_pf["items"]:
            src_it = next((x for x in avg_src["items"] if x["region"] == it_pf["region"]), None)
            ok_src = True
            if src_it:
                for key, tol in (("average_unit_price", 0.011), ("record_count", 0.5), ("weighted_quantity", 0.5)):
                    a, b = it_pf.get(key), src_it.get(key)
                    if a is None or b is None:
                        ok_src = ok_src and (a is None and b is None)
                    else:
                        ok_src = ok_src and abs(float(a) - float(b)) <= tol
            else:
                ok_src = False
            if not ok_src:
                e_bad.append(("src", "② 时间范围平均运费 %s：源≠站" % it_pf["region"]))
            it_page = next((x for x in avg_sys["items"] if x["region"] == it_pf["region"]), None)
            j = js_map.get(it_pf["region"])
            print("     %-10s 站复算 %s 元/kg（%s 条 / %s 双）| 页面真值 %s | 源复算 %s | 页面%s 源站%s"
                  % (it_pf["region"], it_pf.get("average_unit_price"), it_pf.get("record_count"),
                     it_pf.get("weighted_quantity"),
                     (j.get("average_unit_price") if j else "—"),
                     (src_it.get("average_unit_price") if src_it else "—"),
                     ("一致" if it_page and j and abs(float(it_page.get("average_unit_price") or 0)
                                                     - float(j.get("average_unit_price") or 0)) <= 0.011 else "不一致")
                     if j else "—",
                     "一致" if ok_src else "不一致"))
        # 页面口径 vs 统一前缀口径的差异 = 页面地区映射未同步的表现（不计系统异常）
        if mapping_not_synced:
            ok_map, map_diffs = cmp_items(avg_sys_pf["items"], avg_sys["items"],
                                          (("average_unit_price", 0.011), ("record_count", 0.5),
                                           ("weighted_quantity", 0.5)))
            if not ok_map:
                print("     ⚠ 页面地区映射口径未同步（页面仍按精确匹配，源复算按前缀归属）：%s"
                      % "；".join(map_diffs[:4]))
        ub2 = AF.unknown_bucket_stats(avg_sys_pf.get("valid_rows") or [])
        print("     未知地区桶：%d 条（空值 %d / 未映射 %d，未映射应为 0）"
              % (ub2["unknown"], ub2["empty"], ub2["unmapped"]))
        if ub2["unmapped"]:
            e_quality["功能命中记录含未映射地区标签"] += ub2["unmapped"]

        # ③ SKU批次在途（备货联动）
        print("  ③ SKU批次在途（批次双数 / 入仓 / 在途 / 预计到仓）")
        bat_sys = AF.build_batches(y_sku, sys_recs, page_const=pc)         # 页面口径
        bat_sys_pf = AF.build_batches(y_sku, sys_recs_pf, page_const=pc)    # 统一前缀口径
        bat_src = AF.build_batches(s_sku, src_recs, page_const=pc)          # 源侧统一前缀口径
        js_b = {(b["batch"]): b for b in ((truth_b or {}).get("batches") or [])}
        tot_sys = sum(b["total"] for b in bat_sys["batches"])
        arr_sys = sum(b["arrived"] for b in bat_sys["batches"])
        tot_pf = sum(b["total"] for b in bat_sys_pf["batches"])
        arr_pf = sum(b["arrived"] for b in bat_sys_pf["batches"])
        tot_src = sum(b["total"] for b in bat_src["batches"])
        arr_src = sum(b["arrived"] for b in bat_src["batches"])
        js_tot = sum(b["total"] for b in js_b.values()) if js_b else None
        js_arr = sum(b["arrived"] for b in js_b.values()) if js_b else None
        ok_js = (js_tot is None) or (abs(tot_sys - js_tot) < 0.5 and abs(arr_sys - js_arr) < 0.5)
        if not ok_js:
            e_bad.append(("real", "③ SKU批次在途：页面算错（站复算 %.0f/%.0f 与页面 %.0f/%.0f 不一致）"
                          % (tot_sys, arr_sys, js_tot or 0, js_arr or 0)))
        ok_src = (abs(tot_pf - tot_src) < 0.5 and abs(arr_pf - arr_src) < 0.5)
        if not ok_src:
            if is_unverif("SKU表"):
                # 源侧 SKU 表来自降级快照，与站侧同源 → 不可独立核验
                unverif.append(("E", "③ SKU批次在途：源≠站（源 %.0f/%.0f，站 %.0f/%.0f）——未独立回源，不可核验"
                                % (tot_src, arr_src, tot_pf, arr_pf)))
                ok_src = True
                print("     ⚠ 源侧 SKU 表与站侧不同源（降级快照或已换领星源），本项源站对账不可核验，不计系统异常")
            else:
                e_bad.append(("src", "③ SKU批次在途：源≠站（源 %.0f/%.0f，站 %.0f/%.0f）"
                              % (tot_src, arr_src, tot_pf, arr_pf)))
        print("     批次 %d 个 | 站复算 合计 %s 双 / 入仓 %s 双 / 在途 %s 双 | 页面真值 合计 %s 双 / 入仓 %s 双 | 源复算 合计 %s 双 / 入仓 %s 双 | 页面%s 源站%s"
              % (len(bat_sys["batches"]), int(tot_sys), int(arr_sys), int(tot_sys - arr_sys),
                 int(js_tot) if js_tot is not None else "—", int(js_arr) if js_arr is not None else "—",
                 int(tot_src), int(arr_src),
                 "一致" if ok_js else "不一致", "一致" if ok_src else "不一致"))
        ub3 = AF.unknown_bucket_stats(bat_sys_pf.get("hit_records") or [])
        print("     未知地区桶：%d 条（空值 %d / 未映射 %d，未映射应为 0）"
              % (ub3["unknown"], ub3["empty"], ub3["unmapped"]))
        if ub3["unmapped"]:
            e_quality["功能命中记录含未映射地区标签"] += ub3["unmapped"]
        for b in bat_sys["batches"]:
            j = js_b.get(b["batch"])
            flag = "" if not j else ("  页面: %s 双 / 入仓 %s / 预计 %s" % (j["total"], j["arrived"], j.get("eta")))
            print("       %s  %6s 双  入仓 %6s  在途 %6s  %s%s"
                  % (b["batch"], int(b["total"]), int(b["arrived"]), int(b["in_transit"]),
                     AF.REGION_LABELS.get(b["region"], b["region"]), flag))

        if e_bad:
            print("  [E] 异常 %d 处：" % len(e_bad))
            for _k, x in e_bad[:10]:
                print("     - %s" % x)
            sync_bad.extend(e_bad)
        else:
            print("  [E] 三个关联功能：页面真值 / 站侧复算 / 源侧复算 三者一致")
        if mapping_not_synced:
            print("  [E] 说明：页面地区映射仍是精确匹配、尚未同步为前缀归属，"
                  "本次差异按「页面地区映射口径未同步」处理，未判为系统异常（退出码按 0 计）")
        if e_quality:
            print("  [E] 功能命中记录里的源数据质量缺口：")
            for k, v in e_quality.most_common():
                print("     · %-22s %d 条" % (k, v))

    for k, v in e_quality.items():
        quality[k] = quality.get(k, 0) + v

    # ---------- F 站侧自洽护栏（2026-10-30 小丁要求：源站同时坏也要能报出来） ----------
    # 这两条不看「源≠站」，只看站上数据自身的完整性/可用性：
    # 护栏 A：records.json 主表关键字段完整性（货件状态等非空记录数掉到 0 或异常低）
    # 护栏 B：页面「全部在途（主表实时）」可用性（在途票数/地区分布/平均运费三地区）
    print("\n[F 站侧自洽护栏]")
    f_bad = []
    # ---- 护栏 A：主表关键字段完整性 ----
    # 阈值按各字段的历史基线定（2026-10-30 实测 00:07 版 / WorkBuddy 回源）：
    #   货件状态 1009/1048≈96% → 硬依赖，掉到 0 或 <50% 即报
    #   物流状态 38/1048≈3.6% → 本来就稀疏，只查「是否整列丢失」（0 条）
    #   其余字段 ≥60% → <30% 视为异常低
    KEY_FIELDS = ["货件状态", "物流状态", "送达日期", "时效天数", "箱规"]
    HARD_DEP = {"货件状态": 0.5}      # 掉到这个比例以下即报
    SPARSE = {"物流状态"}             # 天然稀疏，只查整列丢失
    a_stat = {}
    for kf in KEY_FIELDS:
        n = len([r for r in y_main if str(r.get(kf) or "").strip()])
        a_stat[kf] = n
        ratio = (n / float(len(y_main))) if y_main else 0.0
        if kf in SPARSE:
            if n == 0:
                f_bad.append("护栏A：主表「%s」非空记录数 0 条，字段整体缺失" % kf)
        elif kf in HARD_DEP:
            if n == 0:
                f_bad.append("护栏A：主表「货件状态」非空记录数 0 条（页面「全部在途」会显示"
                             "「主表当前没有在途货件」）——主表构建时该字段未被写入")
            elif ratio < HARD_DEP[kf]:
                f_bad.append("护栏A：主表「货件状态」非空记录数 %d/%d（%.1f%%），异常低，"
                             "疑似字段大面积丢失" % (n, len(y_main), ratio * 100))
        else:
            if n == 0:
                f_bad.append("护栏A：主表「%s」非空记录数 0 条，字段整体缺失" % kf)
            elif ratio < 0.3:
                f_bad.append("护栏A：主表「%s」非空记录数 %d/%d（%.1f%%），异常低"
                             % (kf, n, len(y_main), ratio * 100))
    print("  A 主表关键字段非空数（主表 %d 行）：%s"
          % (len(y_main), "、".join("%s %d" % (k, v) for k, v in a_stat.items())))

    # ---- 护栏 B：页面「全部在途（主表实时）」可用性 ----
    if AF is not None:
        b_recs = AF.norm_records(y_main, region_mode="page")
        tr = AF.compute_all_transit(b_recs)
        tr_reg = tr["region"]
        avg_b = AF.engine_average(AF.norm_records(y_main, region_mode="prefix"))
        avg_regions = {x["region"]: x for x in avg_b["items"]}
        print("  B 全部在途（主表实时）：%d 票 / %s 件 / SKU %d / 货件 %d | 地区 %s | 快船 %d 票 普船 %d 票"
              % (tr["rec_count"], int(tr["total_qty"]), tr["sku_count"], tr["fba_count"],
                 ("、".join("%s %d 双/%d 票" % (AF.REGION_LABELS.get(k, k), int(v["qty"]), v["count"])
                           for k, v in sorted(tr_reg.items())) or "（空）"),
                 tr["ship"]["快船"], tr["ship"]["普船"]))
        if tr["rec_count"] <= 0:
            f_bad.append("护栏B：页面「全部在途（主表实时）」在途票数 0 —— "
                         "该汇总块会显示「主表当前没有在途货件 🎉」，功能不可用")
        elif not tr_reg:
            f_bad.append("护栏B：在途票数 %d 但地区分布为空" % tr["rec_count"])
        else:
            for need in ("us_west", "us_east", "us_central"):
                if need not in tr_reg:
                    f_bad.append("护栏B：在途地区分布缺少「%s」" % AF.REGION_LABELS.get(need, need))
        for need in ("us_west", "us_east", "us_central"):
            it = avg_regions.get(need)
            if not it or it.get("average_unit_price") is None:
                f_bad.append("护栏B：平均运费三地区中「%s」为空（卡片③不可用）"
                             % AF.REGION_LABELS.get(need, need))
    else:
        print("  B 跳过：复算模块不可用")

    if f_bad:
        print("  [F] 护栏异常 %d 处：" % len(f_bad))
        for x in f_bad:
            print("     - %s" % x)
        sync_bad.extend([("real", x) for x in f_bad])
    else:
        print("  [F] 两条护栏均通过")

# ---------- 判定：系统异常 vs 待同步（2026-10-30 主管-小天裁决） ----------
    real_bad = [m for k, m in sync_bad if k == "real"]
    src_bad = [m for k, m in sync_bad if k == "src"]
    n_diff_rows = len(a3_rows)
    site_at = str((sysd.get("_meta") or {}).get("fetchedAt") or "")
    src_at = str(args.src_updated_at or "")
    site_older = False
    if site_at and src_at:
        try:
            site_older = (datetime.datetime.strptime(site_at[:19], "%Y-%m-%d %H:%M:%S")
                          < datetime.datetime.strptime(src_at[:19], "%Y-%m-%d %H:%M:%S"))
        except Exception:
            site_older = False
    print("\n[G 源站时点判定]")
    print("  站侧构建时间(_meta.fetchedAt) = %s | 源数据更新时间 = %s | 站侧更旧 = %s"
          % (site_at or "(未知)", src_at or "(未提供)", "是" if site_older else "否"))

    pending = False
    pend_reason = ""
    if real_bad:
        pend_reason = "存在真系统异常（页面算错 / 护栏不过），与时点差无关"
    elif n_diff_rows:
        if n_bwd or n_chg:
            pend_reason = ("存在反向差异 %d 处 / 同期变化 %d 处 → 站上有而源没有，属真回归"
                           % (n_bwd, n_chg))
        elif not src_at:
            pend_reason = "未提供源更新时间(--src-updated-at)，无法证明「源比站新」→ 按系统异常处理"
        elif site_older:
            pending = True
            pend_reason = ("站侧构建时间早于源更新时间，且全部 %d 行差异都是单向「站空→源有值」"
                           % n_diff_rows)
        else:
            pend_reason = "站侧构建时间不早于源更新时间（刷新时源数据已在，却没落上线）→ 真回归"
    elif src_bad:
        pend_reason = "派生层源站不一致但无行级差异线索 → 按系统异常处理"

    # 防掩盖：同一批差异连续两轮都判待同步 → 第二轮起按系统异常报
    sig = ""
    if a3_rows:
        sig = hashlib.sha1("\n".join(sorted(
            "%s|%s|%s" % (k, x[0], x[1]) for k, lst in a3_rows.items() for x in lst)
        ).encode("utf-8")).hexdigest()
    st = {"pending_sig": "", "pending_rounds": 0}
    if os.path.exists(args.state):
        try:
            st = json.load(io.open(args.state, encoding="utf-8"))
        except Exception:
            st = {"pending_sig": "", "pending_rounds": 0}
    rounds = 0
    if pending:
        rounds = (int(st.get("pending_rounds") or 0) + 1) if st.get("pending_sig") == sig else 1
        if rounds >= 2:
            real_bad.append("连续 %d 轮抽检都判「待同步」（同一批差异未消），刷新链路可能没跑或没生效" % rounds)
            pending = False
            pend_reason = "连续两轮待同步 → 升级为系统异常"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if rounds:
        st = {"pending_sig": sig, "pending_rounds": rounds, "updatedAt": now_str}
    else:
        st = {"pending_sig": "", "pending_rounds": 0, "updatedAt": now_str}
    try:
        with io.open(args.state, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False)
    except Exception:
        pass

    if pending:
        sys_ex = 0
        pend_rows = n_diff_rows
    else:
        sys_ex = len(real_bad) + len(src_bad)
        pend_rows = 0

    print("\n结论：系统异常 %d 处 | 待同步 %d 行 | 源数据质量缺口 %d 类"
          % (sys_ex, pend_rows, len(quality)))
    if DERIVED:
        print("   派生字段 %s：源侧（共享盘）无对应值，比对必不一致 → 差异 %d 处只报不判"
              % ("、".join(sorted(DERIVED)), len(derived_diff)))
        for _k, m in derived_diff[:5]:
            print("     - %s" % m)
    if DEGRADED:
        print("   ⚠ 本次回源降级（用快照，快照时间=%s）：以下字段本次未独立回源，与站侧同源、不可独立核验 →"
              % (args.degraded_snapshot_at or "(未知)"))
        print("     · %s" % ("、".join(sorted(UNVERIF)) or "(未列出)"))
        print("     未独立核验的差异 %d 处（不计系统异常、不参与待同步方向判定）" % len(unverif))
        for _k, m in unverif[:8]:
            print("     - %s" % m)
    if pending:
        print("   待同步 %d 行（源比站新，等下一次刷新覆盖）：%s" % (pend_rows, pend_reason))
        shown = 0
        for k, lst in a3_rows.items():
            for label, kind, a, b in lst:
                if shown >= 2:
                    break
                print("   例：%s | %s | 站=%s → 源=%s" % (k, label, b, a))
                shown += 1
        return 0
    if sys_ex:
        for s in (real_bad + src_bad)[:10]:
            print("   异常：%s" % s)
        if pend_reason and n_diff_rows:
            print("   判定依据：%s" % pend_reason)
        return 2
    print("同步链路无差异（抽检主表 %d 条 + SKU 表 %d 条，字段全一致）" % (len(picks), len(picks)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
