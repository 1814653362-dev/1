# -*- coding: utf-8 -*-
"""领星货件状态：判定规则与覆盖主表「货件状态」。

数据来源口径（小丁 2026-10-30 亲口纠正，以此为准）：
  · SKU 批次明细 / 主表「货件状态」= 抓**领星 API 的货件状态**维护的
    （shipmentList 的 shipment_status，shipment_id = 主表「FBA货件号」本体）。
    不是共享盘发货记录、也不是 WorkBuddy 对账推算。
  · 「预估到仓时间」才是我方推算的（发货日期 + 15 + landDays[地区]），
    页面每次打开实时重算 —— 本模块**只管领星状态抓对，不碰推算逻辑**。

判定规则照抄 ex/1-main/logistics-dashboard/sync/lx_sync_status.py：
  到仓 = RECEIVING / CLOSED / DELIVERED，其余在途；
  终止态 CANCELLED / DELETED / ABANDONED / ERROR 不写只报；
  领星在途但 gmt_modified 超 60 天 = 陈旧，不写只报。

对碰范围：主表发货日期 ≥ TRANSIT_CUTOFF（页面 computeAllTransit 用的同一个 cutoff）。
"""
import datetime
import io
import json
import os
import re

# ---- 判定常量（与参考实现保持一致）----
ARRIVED = {"RECEIVING", "CLOSED", "DELIVERED"}
INTRANSIT = {"SHIPPED", "IN_TRANSIT", "WORKING", "READY_TO_SHIP", "UNCONFIRMED", "CHECKED_IN"}
TERMINAL = {"CANCELLED", "DELETED", "ABANDONED", "ERROR"}
RANK = {"RECEIVING": 1, "CLOSED": 2, "DELIVERED": 3}
# 在途态取值优先级（同行多个货件号时取最靠前者）
IPRI = ["IN_TRANSIT", "SHIPPED", "CHECKED_IN", "WORKING", "READY_TO_SHIP", "UNCONFIRMED"]
STALE_DAYS = 60          # 领星侧 gmt_modified 超过该天数视为陈旧，在途值不可信 → 不写

DEFAULT_CUTOFF = "2026-07-01"


def norm(s):
    return (s or "").strip().upper()


def split_ids(s):
    """主表「FBA货件号」可能是 'A&B' 拼箱，按 & 拆成单个货件号。"""
    return [x.strip().upper() for x in str(s or "").split("&") if x.strip()]


def load_lx(path):
    """读领星 shipmentList 快照 → (状态表, 最后修改时间表)。"""
    lxmap, lxmod = {}, {}
    if not path or not os.path.exists(path):
        return lxmap, lxmod
    with io.open(path, encoding="utf-8") as f:
        rows = json.load(f)
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or []
    for s in rows or []:
        sid = norm(s.get("shipment_id"))
        if not sid:
            continue
        lxmap[sid] = norm(s.get("shipment_status"))
        m = str(s.get("gmt_modified") or "").strip()
        if m:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                try:
                    lxmod[sid] = datetime.datetime.strptime(m[:19], fmt)
                    break
                except ValueError:
                    continue
    return lxmap, lxmod


def decide(main_status, lx_statuses, lx_mods=None):
    """返回 (action, value, reason)；action ∈ write/skip/terminal/nomatch/stale。

    与参考实现 lx_sync_status.decide 同口径：
      领星到仓 → 主表非到仓的一律写领星到仓值；主表已到仓则保持（同级不细化）
      领星在途 → 主表已到仓也照写领星在途值（允许降级）；主表在途则刷新为领星原值
      领星终止态 → 不写，仅报告
      领星在途但陈旧（超 60 天未更新）→ 不写，仅报告
    """
    ls = [s for s in lx_statuses if s]
    if not ls:
        return ("nomatch", None, "领星未匹配")
    ms = norm(main_status)
    arrived = [s for s in ls if s in ARRIVED]
    intransit = [s for s in ls if s in INTRANSIT]
    terminal = [s for s in ls if s in TERMINAL]

    if terminal and not arrived and not intransit:
        return ("terminal", None, "领星=%s(终止态,不自动改)" % ",".join(terminal))

    if arrived:
        best = max(arrived, key=lambda s: RANK.get(s, 0))
        if not ms:
            return ("write", best, "主表空 → 领星到仓 %s" % best)
        if ms in ARRIVED:
            if RANK.get(best, 0) > RANK.get(ms, 0):
                return ("write", best, "到仓升级 %s→%s" % (ms, best))
            return ("skip", None, "同属到仓，保持主表 %s（领星 %s）" % (ms, best))
        return ("write", best, "主表非到仓(%s) → 领星到仓 %s" % (ms, best))

    if intransit:
        pick = next((s for s in IPRI if s in intransit), intransit[0])
        mods = [m for m in (lx_mods or []) if m]
        if mods:
            newest = max(mods)
            age = (datetime.datetime.now() - newest).days
            if age > STALE_DAYS:
                return ("stale", None, "领星在途=%s 但最后更新 %s（已 %d 天未更新，不写）"
                        % (pick, newest.strftime("%Y-%m-%d"), age))
        if not ms:
            return ("write", pick, "主表空 → 领星在途 %s" % pick)
        if ms == pick:
            return ("skip", None, "与领星一致(%s)" % ms)
        if ms in ARRIVED:
            return ("write", pick, "主表已到仓(%s) → 降级为领星在途 %s" % (ms, pick))
        return ("write", pick, "在途刷新 %s→%s" % (ms, pick))

    return ("nomatch", None, "未知状态 %s" % ",".join(ls))


def page_cutoff(page_html=None):
    """取页面 computeAllTransit 的 TRANSIT_CUTOFF（取不到用默认值）。"""
    if page_html and os.path.exists(page_html):
        try:
            with io.open(page_html, encoding="utf-8") as f:
                src = f.read()
            m = re.search(r"var\s+TRANSIT_CUTOFF\s*=\s*[\"']([^\"']+)[\"']", src)
            if m:
                return m.group(1)
        except Exception:
            pass
    return DEFAULT_CUTOFF


def resolve_record(record, lxmap, lxmod, cutoff=DEFAULT_CUTOFF):
    """对一条主表记录做领星对碰。

    返回 dict：{action, old, new, reason, in_scope, matched}
      action ∈ write / skip / terminal / stale / nomatch / out_of_scope
    """
    ship = str(record.get("发货日期") or "")[:10]
    ids = split_ids(record.get("FBA货件号"))
    res = {"action": "nomatch", "old": record.get("货件状态") or "",
           "new": None, "reason": "", "in_scope": True, "matched": 0}
    if not ids:
        res["action"] = "nomatch"
        res["reason"] = "无货件号"
        return res
    if cutoff and ship < cutoff:
        res["action"] = "out_of_scope"
        res["reason"] = "发货日期 %s 早于 cutoff %s，不对碰" % (ship or "-", cutoff)
        return res
    lss = [lxmap.get(i) for i in ids]
    mods = [lxmod.get(i) for i in ids]
    lss = [x for x in lss if x]
    res["matched"] = len(lss)
    if not lss:
        res["reason"] = "领星未匹配到这 %d 个货件号" % len(ids)
        return res
    action, value, reason = decide(record.get("货件状态"), lss, mods)
    res["action"] = action
    res["new"] = value
    res["reason"] = reason
    return res
