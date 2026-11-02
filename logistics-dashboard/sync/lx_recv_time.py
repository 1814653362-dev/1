# -*- coding: utf-8 -*-
"""lx_recv_time —— 从领星 shipmentList 快照落盘「货件号 → 仓库接收时间」映射。

背景（2026-11-02 小丁提、主管定）：
  领星货件状态转 RECEIVING 时会记时间 = `receiving_time`（仓库开始接收时刻），
  这就是真正的「货件被 FBA 仓库接收的时间」，用来回填主表「送达日期」列。
  ⚠ 不要用 `gmt_modified`（「更新时间」列）：它会被后续任何编辑刷新，且比 receiving_time 晚约 1 天。

落盘文件：data/lx_recv_time.json
  {"_meta": {...}, "map": {"FBA19XXXX": {receiving_time, closed_time, gmt_modified, shipment_status}}}

用法：
  python lx_recv_time.py --lx lx_raw/shipments.json --out data/lx_recv_time.json
"""
import datetime
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))


def nk(s):
    return str(s or "").strip()


def build_map(shipments_path):
    """读领星 shipmentList 快照 → {shipment_id: {receiving_time, closed_time, gmt_modified, shipment_status}}"""
    m = {}
    with io.open(shipments_path, encoding="utf-8") as fh:
        rows = json.load(fh)
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or []
    for s in rows or []:
        sid = nk(s.get("shipment_id"))
        if not sid:
            continue
        m[sid] = {
            "receiving_time": nk(s.get("receiving_time")),
            "closed_time": nk(s.get("closed_time")),
            "gmt_modified": nk(s.get("gmt_modified")),
            "shipment_status": nk(s.get("shipment_status")),
        }
    return m


def load_map(path):
    """读映射文件 → (map, meta)。文件不存在返回 ({}, {})。"""
    if not path or not os.path.exists(path):
        return {}, {}
    with io.open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    return (d.get("map") or {}), (d.get("_meta") or {})


def recv_date(raw):
    """receiving_time 原值 → YYYY-MM-DD（取日期部分）。取不到返回 ""。"""
    s = nk(raw)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return ""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--lx", default=os.path.join(BASE, "lx_raw", "shipments.json"))
    ap.add_argument("--out", default=os.path.join(BASE, "data", "lx_recv_time.json"))
    args = ap.parse_args()

    if not os.path.exists(args.lx):
        print("领星快照不存在：%s" % args.lx)
        return 1
    m = build_map(args.lx)
    n_rt = len([1 for v in m.values() if v["receiving_time"]])
    out = {
        "_meta": {
            "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": os.path.relpath(args.lx, BASE),
            "sourceMtime": datetime.datetime.fromtimestamp(
                os.path.getmtime(args.lx)).strftime("%Y-%m-%d %H:%M:%S"),
            "shipments": len(m),
            "withReceivingTime": n_rt,
            "field": "receiving_time（仓库开始接收时刻）；不用 gmt_modified（会被后续编辑刷新）",
        },
        "map": m,
    }
    d = os.path.dirname(args.out)
    if d and not os.path.exists(d):
        os.makedirs(d)
    tmp = args.out + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    os.replace(tmp, args.out)
    print("落盘 %s：%d 个货件，其中 %d 个有 receiving_time" % (args.out, len(m), n_rt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
