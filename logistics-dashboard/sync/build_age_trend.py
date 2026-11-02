# -*- coding: utf-8 -*-
"""build_age_trend.py —— 店级 13 周五段库龄结构（数据层）

输入：shandi-v5/trend.json（SPU × 13 周的 [可售, 总双数, 老库龄, 0-90, 91-180,
      181-270, 271-365, 365+]）、wh_raw/wh_snapshot.json（页面库龄条基准
      summary.age）、wh_raw/sellers.json（sid → 店名）
输出：data/age_trend_shop.json

口径说明：
  · bands  = 该店该周**全部 SPU 合计**的五段双数（0-90/91-180/181-270/271-365/365+）
  · old    = bands[3] + bands[4]（271 天以上）
  · oldPct = old / sum(bands) × 100，保留 1 位小数
  · total  = sum(bands)（堆叠柱子的总量 = 五段之和）
  · qty    = 该周该店 SPU 的「总双数」之和（trend 行 index 1），作参考
  · 某周没有任何有效 SPU 行 → bands/total/old/oldPct 全为 null（不插值、不补上期、不造数）

容错：每个 SPU 行逐条检查 —— 不是数组、长度不足 8、含非数值、整行 null，
      一律**跳过并计数**，绝不静默当 0 参与合计。

硬校验：每店最新一周的 bands 与页面库龄条 summary.age 逐段比较，
      结果写进输出文件的 meta.hardCheck。
"""
import io
import json
import os
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
TREND = os.path.join(BASE, "shandi-v5", "trend.json")
SNAP = os.path.join(BASE, "wh_raw", "wh_snapshot.json")
SELLERS = os.path.join(BASE, "wh_raw", "sellers.json")
OUT = os.path.join(BASE, "data", "age_trend_shop.json")

AGE_BANDS = ["0-90", "91-180", "181-270", "271-365", "365+"]
N_FIELDS = 8          # 可售/总双数/老库龄 + 5 段


def load(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def num(v):
    """只接受有限数值；None/空串/布尔/NaN/inf 一律判为无效"""
    if v is None or isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return float(v)


def row_bands(row):
    """从一行 SPU 数据里取五段；行不合法返回 None（调用方计数跳过）"""
    if not isinstance(row, (list, tuple)) or len(row) < N_FIELDS:
        return None
    b = []
    for i in range(3, N_FIELDS):
        v = num(row[i])
        if v is None:
            return None
        b.append(v)
    return b


def main():
    trend = load(TREND)
    snap = load(SNAP)
    sellers = load(SELLERS)

    names = {}
    for s in (sellers.get("data") or []):
        names[str(s.get("sid"))] = s.get("name") or str(s.get("sid"))
    bars = {}
    for s in (snap.get("fba", {}).get("shops") or []):
        summ = s.get("summary") or {}
        bars[str(s.get("sid"))] = [num(x) for x in (summ.get("age") or [])]

    shops_out = []
    meta_shops = {}
    union_weeks = set()

    for sid in sorted(trend.keys(), key=lambda x: (len(str(x)), str(x))):
        sh = trend[sid] or {}
        weeks = sorted(sh.get("weeks") or [])
        union_weeks.update(weeks)
        spu_map = sh.get("spu") or {}

        # 每店每周的累加器
        agg = {w: {"bands": [0.0] * 5, "qty": 0.0, "n": 0} for w in weeks}
        skipped = {"null_row": 0, "bad_len": 0, "bad_num": 0}
        n_spu_used = 0
        n_spu_all = 0

        for spu in sorted(spu_map.keys()):
            rows = spu_map[spu]
            n_spu_all += 1
            if isinstance(rows, list):
                seq = list(rows)
            elif isinstance(rows, dict):
                seq = [rows.get(w) for w in weeks]
            else:
                skipped["bad_len"] += 1
                continue
            if len(seq) != len(weeks):
                # 长度对不上：逐周按 key 取；对齐不了就整条跳过并计数
                skipped["bad_len"] += 1
                if not isinstance(rows, dict):
                    continue
            used = False
            for w, row in zip(weeks, seq):
                if row is None:
                    skipped["null_row"] += 1
                    continue
                b = row_bands(row)
                if b is None:
                    if isinstance(row, (list, tuple)):
                        skipped["bad_len"] += 1
                    else:
                        skipped["bad_num"] += 1
                    continue
                a = agg[w]
                for i in range(5):
                    a["bands"][i] += b[i]
                a["qty"] += num(row[1]) or 0.0
                a["n"] += 1
                used = True
            if used:
                n_spu_used += 1

        series = []
        weeks_with_data = 0
        weeks_with_stock = 0
        for w in weeks:
            a = agg[w]
            if a["n"] == 0:
                series.append({"d": w, "bands": None, "total": None,
                               "old": None, "oldPct": None, "qty": None,
                               "spuCount": 0})
                continue
            weeks_with_data += 1
            bands = [round(x, 1) for x in a["bands"]]
            bsum = sum(bands)
            old = round(bands[3] + bands[4], 1)
            if bsum > 0:
                weeks_with_stock += 1
            series.append({
                "d": w,
                "bands": bands,
                "total": round(bsum, 1),
                "old": old,
                "oldPct": round(old / bsum * 100, 1) if bsum > 0 else None,
                "qty": round(a["qty"], 1),
                "spuCount": a["n"],
            })

        # 硬校验：最新周 bands vs 页面库龄条 summary.age
        check = {"sid": sid, "latestWeek": weeks[-1] if weeks else None,
                 "trend": None, "bar": bars.get(sid), "diff": None, "ok": None}
        if weeks and sid in bars and bars[sid] and len(bars[sid]) == 5:
            last = series[-1]
            tv = last["bands"]
            bv = bars[sid]
            if tv:
                diff = [round(tv[i] - bv[i], 2) for i in range(5)]
                check["trend"] = tv
                check["diff"] = diff
                check["ok"] = all(abs(x) < 0.51 for x in diff)

        shops_out.append({
            "sid": sid,
            "name": names.get(sid, sid),
            "weeks": weeks,
            "series": series,
        })
        meta_shops[sid] = {
            "name": names.get(sid, sid),
            "spuTotal": n_spu_all,
            "spuUsed": n_spu_used,
            "weeks": len(weeks),
            "weeksWithData": weeks_with_data,
            "weeksWithStock": weeks_with_stock,
            "skippedRows": skipped,
            "latestWeek": weeks[-1] if weeks else None,
            "oldPctFirst": next((r["oldPct"] for r in series if r["oldPct"] is not None), None),
            "oldPctLast": next((r["oldPct"] for r in reversed(series) if r["oldPct"] is not None), None),
            "hardCheck": check,
        }

    all_weeks = sorted(union_weeks)
    out = {
        "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": {
            "trend": "shandi-v5/trend.json",
            "ageBar": "wh_raw/wh_snapshot.json (fba.shops[].summary.age)",
            "sellers": "wh_raw/sellers.json",
        },
        "ageBands": AGE_BANDS,
        "weeks": all_weeks,
        "shops": shops_out,
        "shopsMeta": meta_shops,
    }
    d = os.path.dirname(OUT)
    if not os.path.isdir(d):
        os.makedirs(d)
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=1))

    # ---- 控制台摘要 ----
    print("写入 %s（%.1f KB）" % (OUT, os.path.getsize(OUT) / 1024.0))
    print("总周数 %d，店数 %d" % (len(all_weeks), len(shops_out)))
    ok_all = True
    for sid, m in meta_shops.items():
        c = m["hardCheck"]
        ok = c["ok"]
        ok_all = ok_all and bool(ok)
        print("  %-16s sid=%-6s 周 %d（有效 %d / 有货 %d）SPU %d/%d 跳过 %s 老库龄占比 %s→%s 校验 %s"
              % (m["name"], sid, m["weeks"], m["weeksWithData"], m["weeksWithStock"],
                 m["spuUsed"], m["spuTotal"], m["skippedRows"],
                 m["oldPctFirst"], m["oldPctLast"],
                 ("OK " + str(c["diff"])) if ok else "!! " + str(c["diff"])))
    print("硬校验全部通过：", ok_all)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
