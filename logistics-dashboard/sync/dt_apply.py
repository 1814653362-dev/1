# -*- coding: utf-8 -*-
"""把公盘 Excel 的新数据写入钉钉「发货记录」表（仓库版：凭据/标识全走环境变量）。

用法：
  python dt_apply.py            # 只算方案，不写
  python dt_apply.py --apply    # 真写入（新增 + 更新），写完自动复核

环境变量：
  DINGTALK_NODE / DINGTALK_MCP_CLI / DINGTALK_BASE_ID / DINGTALK_OPERATOR_ID / DINGTALK_SHEET_ID
  SHARE_XLSX_LOCAL（公盘 Excel 本地副本，默认 data/shipments_share.xlsx）

规则：
  · 事实源 = 公盘发货记录 Excel
  · 只同步本年月份（dt_sync.CURRENT_YEAR_MONTHS）
  · 只写 Excel 有的字段；Excel 没有的字段不动现值
  · Excel 单元格是 #N/A（公式错误）→ 跳过该字段
  · number 类型字段只写能解析成数字的值
  · 钉钉里有、Excel 没有的历史残行 → 不删，只报告
"""
import collections, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dt_mcp import DingTable
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
    sheet = os.environ.get("DINGTALK_SHEET_ID", "")
    try:
        dt_rows, _ = dt.records(sheet, max_results=100)
        missing, changed, same, extra, dt_map = diff(target, dt_rows)
        print("=== 方案 ===")
        print("Excel 目标行 %d | 钉钉现有 %d" % (len(target), len(dt_rows)))
        print("待新增 %d | 待更新 %d | 已一致 %d | 钉钉多出 %d"
              % (len(missing), len(changed), same, len(extra)))

        skipped_cells = []
        inserts = []
        for k, f in missing:
            rec = {}
            for fld, val in f.items():
                if fld in NUM_FIELDS and not is_num(val):
                    skipped_cells.append((k, fld, val))
                    continue
                rec[fld] = val
            inserts.append({"fields": rec})
        updates = []
        for k, rid, diffs, f in changed:
            rec = {}
            for fld, (ov, nv) in diffs.items():
                if fld in NUM_FIELDS and not is_num(nv):
                    skipped_cells.append((k, fld, nv))
                    continue
                rec[fld] = nv
            if rec:
                updates.append({"id": rid, "fields": rec})

        print("可写入：新增 %d 条 / 更新 %d 条" % (len(inserts), len(updates)))
        if skipped_cells:
            print("跳过(number 字段非数字) %d 处" % len(skipped_cells))
        if not APPLY:
            print("\n[dry-run] 未写入。加 --apply 执行。")
            return

        print("\n=== 写入新增 ===")
        done = 0
        for i in range(0, len(inserts), BATCH):
            chunk = inserts[i:i + BATCH]
            r = dt.insert(sheet, chunk)
            ok = not (isinstance(r, (dict, str)) and ("Error" in str(r) or r.get("code")))
            print("  批 %d: %d 条 -> %s" % (i // BATCH + 1, len(chunk), "OK" if ok else str(r)[:200]))
            if ok:
                done += len(chunk)
        print("新增完成 %d 条" % done)

        print("\n=== 写入更新 ===")
        done = 0
        for i in range(0, len(updates), BATCH):
            chunk = updates[i:i + BATCH]
            r = dt.update(sheet, chunk)
            ok = not (isinstance(r, (dict, str)) and ("Error" in str(r) or r.get("code")))
            print("  批 %d: %d 条 -> %s" % (i // BATCH + 1, len(chunk), "OK" if ok else str(r)[:200]))
            if ok:
                done += len(chunk)
        print("更新完成 %d 条" % done)

        print("\n=== 复核 ===")
        dt2, _ = dt.records(sheet, max_results=100)
        m2, c2, s2, e2, _ = diff(target, dt2)
        print("写入后：%d 条 | 仍缺失 %d | 仍有差异 %d | 一致 %d | 多出 %d"
              % (len(dt2), len(m2), len(c2), s2, len(e2)))
        if c2:
            fc = collections.Counter()
            for k, rid, diffs, f in c2:
                for fld in diffs:
                    fc[fld] += 1
            print("残留差异字段:", dict(fc))
    finally:
        dt.close()


if __name__ == "__main__":
    main()
