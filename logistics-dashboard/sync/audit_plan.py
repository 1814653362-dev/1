# -*- coding: utf-8 -*-
"""抽检排期：工作日随机三晚（唯一事实源，定时任务 sch_4f6460bfdf6e 的 prompt 与本文件同口径）。

规则（用户 2026-10-30 定：抽检是抽样，不是每晚都做，省 token）：
  1) 周末（周六/周日）不抽检 —— 直接跳过，不调接口、不发群消息。
  2) 每周在「周一~周五」里随机取 3 天作为本周抽检夜；随机种子 = ISO 年-周号
     （如 2026-44 → 种子 202644），所以同一周无论什么时候算，结果都一样。
  3) 一周内固定，中途不改；下周自动换一组。
  4) 计划文件 workspace/audit_plan.json，格式：{"2026-44": ["周一","周三","周五"]}

用法：
  python audit_plan.py                 # 问：今天是不是抽检夜
  python audit_plan.py --date 2026-10-30
  python audit_plan.py --show          # 打印本周计划明细
  python audit_plan.py --json          # 机器可读输出

输出（文本模式）：
  STATUS=AUDIT_NIGHT|WEEKEND|NOT_AUDIT_NIGHT
  WEEK=2026-44
  PLAN=周一,周三,周五
  REASON=...
退出码：0 正常（不管是不是抽检夜，判定本身成功）。
"""
import io
import json
import os
import random
import sys
import datetime

sys.stdout.reconfigure(encoding="utf-8")

WS = os.path.dirname(os.path.abspath(__file__))
PLAN_FILE = os.path.join(WS, "audit_plan.json")

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WORKDAYS = WEEKDAY_CN[:5]          # 只在周一~周五 里抽
NIGHTS_PER_WEEK = 3                # 每周抽检晚数
KEEP_WEEKS = 8                     # 计划文件只保留最近 N 周，避免无限增长


def week_key(d):
    """ISO 年-周号，如 2026-10-30 → '2026-44'。"""
    iso = d.isocalendar()
    return "%04d-%02d" % (iso[0], iso[1])


def seed_of(key):
    """种子 = ISO 年-周号（2026-44 → 202644），数字部分与连字符都进种子。"""
    return int(key.replace("-", ""))


def weekday_cn(d):
    return WEEKDAY_CN[d.weekday()]


def load_plan():
    if not os.path.exists(PLAN_FILE):
        return {}
    try:
        with io.open(PLAN_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_plan(plan):
    with io.open(PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2, sort_keys=True)


def prune(plan, keep_key):
    """只保留最近 KEEP_WEEKS 周（含本周），历史太久的丢掉。"""
    if len(plan) <= KEEP_WEEKS:
        return plan
    keys = sorted(plan.keys())
    # 保留本周 + 最近的 KEEP_WEEKS-1 个
    keep = set(keys[-(KEEP_WEEKS - 1):]) | {keep_key}
    return {k: v for k, v in plan.items() if k in keep}


def week_plan(key, create=True):
    """取本周抽检夜；没有就按种子生成并落盘（create=False 时不写文件）。"""
    plan = load_plan()
    if key in plan and plan[key]:
        return plan[key], plan, False
    days = random.Random(seed_of(key)).sample(WORKDAYS, NIGHTS_PER_WEEK)
    days.sort(key=lambda x: WORKDAYS.index(x))
    if create:
        plan[key] = days
        save_plan(prune(plan, key))
    return days, plan, True


def judge(d=None):
    """返回判定结果字典：
       status: AUDIT_NIGHT / NOT_AUDIT_NIGHT / WEEKEND
       is_audit_night: bool
       week / plan / reason
    """
    d = d or datetime.date.today()
    key = week_key(d)
    wd = weekday_cn(d)
    if d.weekday() >= 5:
        return {
            "status": "WEEKEND", "is_audit_night": False, "date": d.isoformat(),
            "week": key, "weekday": wd, "plan": [], "reason": "非工作日，未执行",
        }
    days, _, created = week_plan(key)
    if wd in days:
        return {
            "status": "AUDIT_NIGHT", "is_audit_night": True, "date": d.isoformat(),
            "week": key, "weekday": wd, "plan": days,
            "reason": "本周抽检夜 %s" % "、".join(days),
        }
    return {
        "status": "NOT_AUDIT_NIGHT", "is_audit_night": False, "date": d.isoformat(),
        "week": key, "weekday": wd, "plan": days,
        "reason": "非抽检夜，未执行（本周抽检夜：%s）" % "、".join(days),
    }


def main():
    args = sys.argv[1:]
    d = None
    show = False
    as_json = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--date" and i + 1 < len(args):
            d = datetime.date.fromisoformat(args[i + 1]); i += 2; continue
        if a == "--show":
            show = True; i += 1; continue
        if a == "--json":
            as_json = True; i += 1; continue
        i += 1

    res = judge(d)
    if show:
        res = dict(res)
        res["all_plans"] = load_plan()
    if as_json:
        print(json.dumps(res, ensure_ascii=False))
        return 0

    print("STATUS=%s" % res["status"])
    print("WEEK=%s" % res["week"])
    print("PLAN=%s" % ",".join(res["plan"]))
    print("REASON=%s" % res["reason"])
    if show:
        for k in sorted(res["all_plans"].keys()):
            print("  %s -> %s" % (k, "、".join(res["all_plans"][k])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
