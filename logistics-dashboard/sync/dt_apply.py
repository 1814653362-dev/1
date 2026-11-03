# -*- coding: utf-8 -*-
"""把公盘 Excel 的新数据写入钉钉「发货记录」表。

用法：
  python dt_apply.py            # 只算方案，不写
  python dt_apply.py --apply    # 真写入（新增 + 更新），写完自动复核

规则：
  · 事实源 = 共享盘 发货记录.xlsx（data/shipments_share.xlsx）
  · 只同步本年月份（dt_sync.CURRENT_YEAR_MONTHS = 1~10月）；去年（11/12月 tab）不碰
  · 只写 Excel 有的字段；Excel 没有的字段不动钉钉现值
  · Excel 单元格是 #N/A（公式错误）→ 跳过该字段，不写
  · number 类型字段只写能解析成数字的值，非数字（如 "25/26"）跳过并报告
  · 钉钉里有、Excel 没有的历史残行 → 不删，只报告
"""
import collections, io, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dt_mcp import DingTable, SHEETS
from dt_sync import build_target, diff, NUM_FIELDS, build_excel_rows
import dt_sync
from read_xlsx import read_xlsx

sys.stdout.reconfigure(encoding="utf-8")
APPLY = "--apply" in sys.argv
BATCH = 40


def is_num(v):
    try:
        float(str(v).strip())
        return True
    except (TypeError, ValueError):
        return False


def main():
    target, rows, sheet1 = build_target(read_xlsx)
    all_rows, _ = build_excel_rows(read_xlsx, months=None)
    skipped = [r for r in all_rows if r.get("_月份") not in dt_sync.CURRENT_YEAR_MONTHS]
    print("=== 本年范围 ===")
    print("同步月份:", "、".join(sorted(dt_sync.CURRENT_YEAR_MONTHS)))
    print("跳过(去年/不在范围)行数:", len(skipped),
          "| 涉及 tab:", sorted({r.get("_tab") for r in skipped}))

    dt = DingTable()
    try:
        dt_rows, _ = dt.records(sheet, max_results=100)
        missing, changed, same, extra, dt_map = diff(target, dt_rows)

        print("=== 方案 ===")
        print("Excel 目标行 %d | 钉钉现有 %d" % (len(target), len(dt_rows)))
        print("待新增 %d | 待更新 %d | 已一致 %d | 钉钉多出 %d" %
              (len(missing), len(changed), same, len(extra)))

        # number 字段里的非数字值 → 跳过
        skipped = []
        inserts = []
        for k, f in missing:
            rec = {}
            for fld, val in f.items():
                if fld in NUM_FIELDS and not is_num(val):
                    skipped.append((k, fld, val))
                    continue
                rec[fld] = val
            inserts.append({"fields": rec})
        updates = []
        for k, rid, diffs, f in changed:
            rec = {}
            for fld, (ov, nv) in diffs.items():
                if fld in NUM_FIELDS and not is_num(nv):
                    skipped.append((k, fld, nv))
                    continue
                rec[fld] = nv
            if rec:
                updates.append({"id": rid, "fields": rec})

        print("可写入：新增 %d 条 / 更新 %d 条" % (len(inserts), len(updates)))
        if skipped:
            print("跳过(number 字段非数字) %d 处:" % len(skipped))
            for k, fld, v in skipped:
                print("   ", str(k), fld, repr(v))

        if not APPLY:
            print("\n[dry-run] 未写入。加 --apply 执行。")
            return

        # ---- 写入新增 ----
        print("\n=== 写入新增 ===")
        done = 0
        for i in range(0, len(inserts), BATCH):
            chunk = inserts[i:i + BATCH]
            r = dt.insert(sheet, chunk)
            ok = not (isinstance(r, dict) and (r.get("code") or r.get("errcode") or r.get("_error")))
            print("  批 %d: %d 条 -> %s" % (i // BATCH + 1, len(chunk),
                                          "OK" if ok else json.dumps(r, ensure_ascii=False)[:300]))
            if ok:
                done += len(chunk)
        print("新增完成 %d 条" % done)

        # ---- 写入更新 ----
        print("\n=== 写入更新 ===")
        done = 0
        for i in range(0, len(updates), BATCH):
            chunk = updates[i:i + BATCH]
            r = dt.update(sheet, chunk)
            ok = not (isinstance(r, dict) and (r.get("code") or r.get("errcode") or r.get("_error")))
            print("  批 %d: %d 条 -> %s" % (i // BATCH + 1, len(chunk),
                                          "OK" if ok else json.dumps(r, ensure_ascii=False)[:400]))
            if ok:
                done += len(chunk)
        print("更新完成 %d 条" % done)

        # ---- 复核 ----
        print("\n=== 复核 ===")
        dt2_rows, _ = dt.records(sheet, max_results=100)
        m2, c2, s2, e2, _ = diff(target, dt2_rows)
        print("写入后：钉钉 %d 条 | 仍缺失 %d | 仍有差异 %d | 一致 %d | 多出 %d"
              % (len(dt2_rows), len(m2), len(c2), s2, len(e2)))
        print("DINGTALK_SYNC ok | 新增 %d | 更新 %d | 表内 %d 条 | 仍缺失 %d | 仍有差异 %d"
              % (len(inserts), len(updates), len(dt2_rows), len(m2), len(c2)))
        if c2:
            fc = collections.Counter()
            for k, rid, diffs, f in c2:
                for fld in diffs:
                    fc[fld] += 1
            print("残留差异字段:", dict(fc))
            for k, rid, diffs, f in c2[:10]:
                print("   ", str(k), diffs)
        if m2:
            for k, f in m2[:10]:
                print("    仍缺:", str(k), json.dumps(f, ensure_ascii=False)[:160])
    finally:
        dt.close()


if __name__ == "__main__":
    main()
