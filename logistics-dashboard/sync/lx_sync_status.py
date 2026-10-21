#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按领星 FBA 货件状态同步看板数据库「货件状态」。

对碰范围（2026-10-20 用户明确）：只对碰 **SKU 批次明细** 覆盖到的在途货件。
  - 主表行的 FBA 货件号（按 & 拆分）只要有一个出现在「SKU批次明细」库的「货件单号」里，
    该行进入对碰范围；不在范围内的行一律不读不写。
  - 这样 1/2 月等历史货件（SKU 明细未覆盖）完全不会被碰。

判定（用户口径）：RECEIVING / CLOSED / DELIVERED = 到仓，其余 = 在途。
写入策略「领星为准，允许降级」：
  - 领星判到仓 → 主表非到仓的一律写领星到仓值；主表已到仓则保持（CLOSED/RECEIVING/DELIVERED 同属到仓，不做同级细化）
  - 领星判在途 → 主表已到仓也照写领星在途值（允许降级）；主表在途则刷新为领星原值
  - 领星终止态(CANCELLED/DELETED/ABANDONED/ERROR) → 不写库，仅报告
  - 领星在途但 gmt_modified 超过 60 天未更新 → 视为陈旧数据，不写，仅报告
默认 dry-run，加 --apply 才写库。
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path

ARRIVED = {"RECEIVING", "CLOSED", "DELIVERED"}
INTRANSIT = {"SHIPPED", "IN_TRANSIT", "WORKING", "READY_TO_SHIP", "UNCONFIRMED", "CHECKED_IN"}
TERMINAL = {"CANCELLED", "DELETED", "ABANDONED", "ERROR"}
RANK = {"RECEIVING": 1, "CLOSED": 2, "DELIVERED": 3}
# 在途态取值优先级（同行多个货件号时取最靠前者）
IPRI = ["IN_TRANSIT", "SHIPPED", "CHECKED_IN", "WORKING", "READY_TO_SHIP", "UNCONFIRMED"]
STALE_DAYS = 60   # 领星侧 gmt_modified 超过该天数视为陈旧，在途值不可信 → 不写


def norm(s):
    return (s or "").strip().upper()


def split_ids(s):
    return [x.strip().upper() for x in str(s or "").split("&") if x.strip()]


def sku_fba_set(sku_path):
    """从 SKU 批次明细库记录里取出全部货件单号（按 & 拆分）"""
    rows = json.loads(Path(sku_path).read_text(encoding="utf-8"))
    out = set()
    for r in rows:
        out.update(split_ids(r.get("货件单号")))
    return out


def decide(main_status, lx_statuses, lx_mods=None):
    """返回 (action, value, reason)；action ∈ write/skip/terminal/nomatch/stale"""
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
            age = (datetime.now() - newest).days
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="db_records.json")
    ap.add_argument("--lx", default="lx_shipments.json")
    ap.add_argument("--sku", default="sku_records.json", help="SKU批次明细库导出，用于限定对碰范围")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default="lx_sync_plan.json")
    a = ap.parse_args()

    recs = json.loads(Path(a.db).read_text(encoding="utf-8"))
    lx = json.loads(Path(a.lx).read_text(encoding="utf-8"))
    skufb = sku_fba_set(a.sku) if Path(a.sku).exists() else set()

    lxmap, lxmod = {}, {}
    for s in lx:
        sid = str(s.get("shipment_id") or "").strip().upper()
        if not sid:
            continue
        lxmap[sid] = norm(s.get("shipment_status"))
        m = str(s.get("gmt_modified") or "").strip()
        if m:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    lxmod[sid] = datetime.strptime(m[:19], fmt)
                    break
                except ValueError:
                    continue

    plan, terminals, nomatch, stale, multi = [], [], [], [], []
    skipped_scope = 0
    stat = {}
    for r in recs:
        ids = split_ids(r.get("FBA货件号"))
        if not ids:
            continue
        # 范围限定：必须命中 SKU 批次明细的货件号
        if not any(i in skufb for i in ids):
            skipped_scope += 1
            continue
        if len(ids) > 1:
            multi.append(r.get("_id"))
        lss = [lxmap.get(i) for i in ids]
        mods = [lxmod.get(i) for i in ids]
        lss = [x for x in lss if x]
        if not lss:
            nomatch.append({"_id": r.get("_id"), "fba": r.get("FBA货件号"), "月份": r.get("月份")})
            continue
        action, value, reason = decide(r.get("货件状态"), lss, mods)
        stat[action] = stat.get(action, 0) + 1
        if action == "write":
            plan.append({"_id": r.get("_id"), "月份": r.get("月份"), "fba": r.get("FBA货件号"),
                         "old": r.get("货件状态") or "", "new": value, "reason": reason,
                         "进仓编号": r.get("进仓编号")})
        elif action == "terminal":
            terminals.append({"_id": r.get("_id"), "月份": r.get("月份"), "fba": r.get("FBA货件号"),
                              "主表": r.get("货件状态"), "领星": ",".join(sorted(set(lss)))})
        elif action == "stale":
            stale.append({"_id": r.get("_id"), "月份": r.get("月份"), "fba": r.get("FBA货件号"),
                          "主表": r.get("货件状态"), "原因": reason})

    by_month = {}
    for p in plan:
        by_month.setdefault(p["月份"], 0)
        by_month[p["月份"]] += 1

    in_scope = len(recs) - skipped_scope
    print("===== 领星状态同步 · %s =====" % ("DRY-RUN（未写库）" if not a.apply else "APPLY"))
    print("主表总记录 %d | 对碰范围内(SKU明细覆盖) %d | 范围外跳过 %d" % (len(recs), in_scope, skipped_scope))
    print("待更新 %d | 未匹配 %d | 终止态 %d | 陈旧不写 %d | 多FBA号行 %d"
          % (len(plan), len(nomatch), len(terminals), len(stale), len(multi)))
    print("动作统计:", json.dumps(stat, ensure_ascii=False))
    print("按月待更新:", json.dumps(by_month, ensure_ascii=False))
    if plan:
        print("\n--- 待更新明细 ---")
        for p in plan:
            print("  [%s] %s  %s → %s   (%s)  %s" % (p["月份"], str(p["fba"])[:40], p["old"] or "(空)",
                                                    p["new"], p["reason"], p["进仓编号"] or ""))
    if stale:
        print("\n--- 领星陈旧（不写）--- %d 条" % len(stale))
        for t in stale[:10]:
            print("  [%s] %s  主表=%s  %s" % (t["月份"], str(t["fba"])[:40], t["主表"] or "(空)", t["原因"]))
    if terminals:
        print("\n--- 领星终止态（不写）--- %d 条" % len(terminals))
        for t in terminals[:8]:
            print("  [%s] %s  主表=%s 领星=%s" % (t["月份"], str(t["fba"])[:40], t["主表"] or "(空)", t["领星"]))
    if nomatch:
        print("\n--- 领星未匹配（范围内）--- %d 条" % len(nomatch))
        for t in nomatch[:8]:
            print("  [%s] %s" % (t["月份"], str(t["fba"])[:40]))

    Path(a.out).write_text(json.dumps(
        {"plan": plan, "terminals": terminals, "nomatch": nomatch, "stale": stale,
         "scope": {"total": len(recs), "in_scope": in_scope, "skipped": skipped_scope}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n计划已写入 %s" % a.out)

    if a.apply and plan:
        print("\n>>> 写库中...")
        import subprocess
        LIB = Path(r"C:/Users/1/.workbuddy/plugins/marketplaces/workbuddy-builtin/skills/library")
        token = sys.stdin.read() if not sys.stdin.isatty() else ""
        if not token.strip():
            print("缺少 token：请用管道把 token 传给本脚本")
            sys.exit(2)
        done, failed = 0, 0
        for i in range(0, len(plan), 100):
            chunk = plan[i:i + 100]
            payload = {"database_id": "YOUR_MAIN_DATABASE_ID",
                       "records": [{"record_id": c["_id"], "properties": {"货件状态": {"text": c["new"]}}} for c in chunk]}
            cmd = [sys.executable, str(LIB / "database" / "batch_update_database_records.py"),
                   "--token-stdin", "--stdin"]
            stdin_data = token.strip() + "\n" + json.dumps(payload, ensure_ascii=False)
            r = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True, encoding="utf-8")
            out = (r.stdout or "").strip()
            bad = '"error"' in out or r.returncode != 0
            if bad:
                failed += len(chunk)
                print("  批次 %d-%d 失败: %s" % (i + 1, i + len(chunk), (out or r.stderr).strip()[:200]))
            else:
                done += len(chunk)
                print("  批次 %d-%d 成功 (%d 条)" % (i + 1, i + len(chunk), len(chunk)))
        print(">>> 实际成功 %d 条 / 失败 %d 条 / 计划 %d 条" % (done, failed, len(plan)))
        if failed:
            sys.exit(3)


if __name__ == "__main__":
    main()
