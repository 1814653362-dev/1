# -*- coding: utf-8 -*-
"""build_sku_from_lx.py —— 用领星 SKU 明细（shipmentList 的 item_list）重建 SKU 备货明细。

背景（2026-11-02 用户/主管派活）：
  站点的 SKU 备货明细现在取自 WorkBuddy 资料库「SKU备货明细」表（周级更新，且发布页可能下线）。
  领星 shipmentList 返回的 item_list 就是「SKU × 货件」级明细，字段含 sku / quantity_shipped，
  是更新更及时的来源。本脚本用它重建一份 SKU 明细，与 WorkBuddy 那份做对比。

口径（照主管-主管核实的事实，别自创）：
  · join 键 = 主表 records.json 的「FBA货件号」。**只有主表有的货件才进**（领星有、主表没有的不进）。
  · FBA 货件号判据（团队记忆 fba.shipment-id-rule）：FBA + 9 位大写字母数字（共 12 位）；
    非 FBA 形态（RVSDGF-/RVG21468-/RVZJSD-/STAR-/「TR仓发」）不进 FBA 口径；
    混合行（FBA19X&RVSDGF-1）按 id 级剔除而非整行弃。
  · 「已发货」= 领星 quantity_shipped。
  · 品名三级取源：① shandi-v5/sku_index.json ② shandi-v5/fba_sku_index.json
    ③ 领星商品接口（本地仓商品 local_products.json / FBA 仓库存明细 fba_inventory.json）。
    ①② 实测都没有品名字段，所以实际命中的是 ③。取不到就留空并写明，绝不瞎编。

输出：data/sku_from_lx.json
  {"_meta": {...}, "sku": [ {货件单号, SKU, 已发货, 品名, _id, ...}, ... ]}
  行结构与 WorkBuddy SKU 表一致（SKU/品名/已发货/货件单号/_id），便于直接对比。

用法：
  python build_sku_from_lx.py [--lx lx_raw/shipments.json] [--records shandi-v5/records.json]
                              [--out data/sku_from_lx.json] [--report]
"""
import argparse
import collections
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
FBA_RE = re.compile(r"^FBA[A-Z0-9]{9}$")


def nk(v):
    return str(v or "").strip()


def load_json(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def is_fba_id(s):
    """FBA 货件号 = FBA + 9 位大写字母数字（共 12 位）。混合行按 id 级拆开判断。"""
    return bool(FBA_RE.match(nk(s)))


def split_mixed(s):
    """'FBA19X&RVSDGF-1' → ['FBA19X','RVSDGF-1']；非混合返回单元素。"""
    parts = [p.strip() for p in nk(s).split("&") if p.strip()]
    return parts or [nk(s)]


def load_name_maps(sku_index_path, fba_index_path, local_products_path, fba_inventory_path):
    """品名来源：① sku_index ② fba_sku_index ③ 领星商品接口产物。
    返回 (name_map, source_stats) —— source_stats 记录每级来源命中多少条。"""
    name_map = {}
    stats = collections.OrderedDict()

    def put(k, v, src):
        k = nk(k)
        if not k or not v:
            return
        if k in name_map:          # 先到的优先，不覆盖
            return
        name_map[k] = v
        stats[src] = stats.get(src, 0) + 1

    # ① sku_index.json
    if os.path.exists(sku_index_path):
        d = load_json(sku_index_path)
        rows = d.get("skus") if isinstance(d, dict) else d
        n = 0
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    put(r.get("SKU") or r.get("sku"), r.get("品名"), "sku_index.json")
                else:
                    put(r, None, "sku_index.json")
        stats["sku_index.json"] = n = len([k for k, v in name_map.items()])

    # ② fba_sku_index.json
    if os.path.exists(fba_index_path):
        d = load_json(fba_index_path)
        n = 0
        if isinstance(d, dict):
            sku_shops = d.get("skuShops") or {}
            for sid, blk in (sku_shops.items() if isinstance(sku_shops, dict) else []):
                skus = (blk or {}).get("skus") if isinstance(blk, dict) else None
                if isinstance(skus, list):
                    for s in skus:
                        if isinstance(s, dict):
                            put(s.get("SKU") or s.get("sku"), s.get("品名"), "fba_sku_index.json")
                            n += 1
        stats["fba_sku_index.json"] = n

    # ③ 领星商品接口产物
    if os.path.exists(local_products_path):
        d = load_json(local_products_path)
        n = 0
        for r in (d.get("rows") or []):
            put(r.get("sku"), r.get("product_name"), "领星 local_products")
            n += 1
        stats["领星 local_products"] = n
    if os.path.exists(fba_inventory_path):
        d = load_json(fba_inventory_path)
        n = 0
        for r in (d.get("rows") or []):
            put(r.get("seller_sku"), r.get("product_name"), "领星 fba_inventory")
            n += 1
        stats["领星 fba_inventory"] = n

    return name_map, stats


def build(args):
    lx = load_json(args.lx)
    rec = load_json(args.records)
    main = rec.get("main") or []
    wb_sku = rec.get("sku") or []

    # ---- 主表货件号 → 该货件的月份（用于按月统计）----
    main_fba = {}
    for r in main:
        for pid in split_mixed(r.get("FBA货件号")):
            if is_fba_id(pid):
                main_fba.setdefault(pid, []).append(r)
    print("主表 FBA 货件号（去重、剔非 FBA 形态）: %d 个" % len(main_fba))

    # ---- 领星 item 展开 ----
    lx_rows = []
    lx_ship_seen = set()
    for s in lx:
        sid = nk(s.get("shipment_id"))
        if not sid:
            continue
        for it in (s.get("item_list") or []):
            lx_rows.append({
                "货件单号": sid,
                "SKU": nk(it.get("sku")),
                "已发货": it.get("quantity_shipped"),
                "_id": it.get("id"),
                "_asin": it.get("asin"),
                "_fnsku": it.get("fnsku"),
                "_msku": it.get("msku"),
                "_shipment_status": s.get("shipment_status"),
                "_in_main": sid in main_fba,
            })
        lx_ship_seen.add(sid)
    print("领星货件 %d 个 | item_list 展开 %d 行 | 其中主表有的货件的行 %d"
          % (len(lx_ship_seen), len(lx_rows), len([r for r in lx_rows if r["_in_main"]])))

    # ---- 只保留主表有的货件 ----
    rows = [r for r in lx_rows if r["_in_main"]]
    rows.sort(key=lambda r: (r["货件单号"], r["SKU"]))

    # ---- 品名 ----
    name_map, name_stats = load_name_maps(
        args.sku_index, args.fba_sku_index, args.local_products, args.fba_inventory)
    print("品名来源命中：" + "，".join("%s %d 条" % (k, v) for k, v in name_stats.items()))
    n_named = 0
    for r in rows:
        nm = name_map.get(r["SKU"], "")
        if not nm:
            # 兜底：去掉末尾尺码段再找一次（有些库按「款-色-码-尺码」建，商品表按「款-色-码」建）
            base = "-".join(r["SKU"].split("-")[:-1]) if "-" in r["SKU"] else r["SKU"]
            nm = name_map.get(base, "")
        r["品名"] = nm
        if nm:
            n_named += 1
    print("品名覆盖: %d / %d 行" % (n_named, len(rows)))

    out = {
        "_meta": {
            "generatedAt": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "领星 shipmentList item_list（以主表 FBA货件号 join）",
            "lxSnapshot": os.path.relpath(args.lx, BASE),
            "lxSnapshotMtime": __import__("datetime").datetime.fromtimestamp(
                os.path.getmtime(args.lx)).strftime("%Y-%m-%d %H:%M:%S"),
            "recordsSnapshot": os.path.relpath(args.records, BASE),
            "mainFbaCount": len(main_fba),
            "lxShipmentCount": len(lx_ship_seen),
            "rows": len(rows),
            "namedRows": n_named,
            "nameSources": dict(name_stats),
        },
        "sku": rows,
    }
    outdir = os.path.dirname(args.out)
    if outdir and not os.path.exists(outdir):
        os.makedirs(outdir)
    with io.open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print("写出 %s (%d bytes)" % (args.out, os.path.getsize(args.out)))

    if args.report:
        report(rows, wb_sku, main_fba)
    return 0


def month_of(recs):
    """取该货件在主表里的发货月份（多行取最多的那个）"""
    c = collections.Counter()
    for r in recs:
        d = nk(r.get("发货日期"))
        if len(d) >= 7:
            c[d[:7]] += 1
        else:
            c[nk(r.get("月份")) or "(未知)"] += 1
    return c.most_common(1)[0][0] if c else "(未知)"


def report(rows, wb_sku, main_fba):
    """与 WorkBuddy SKU 明细逐条对比，出 5 项数字。"""
    lx_key = {}
    for r in rows:
        k = (r["货件单号"], r["SKU"])
        lx_key[k] = lx_key.get(k, 0) + (r["已发货"] or 0)

    wb_key = {}
    wb_non_fba = []
    for r in wb_sku:
        sid = nk(r.get("货件单号"))
        sku = nk(r.get("SKU"))
        if not sid or not sku:
            continue
        if not is_fba_id(sid):
            wb_non_fba.append((sid, sku, r.get("已发货") or 0))
            continue            # 非 FBA 形态不进 FBA 口径
        wb_key[(sid, sku)] = wb_key.get((sid, sku), 0) + (r.get("已发货") or 0)
    if wb_non_fba:
        print("（WorkBuddy SKU 表里非 FBA 形态的货件 %d 行，已按 FBA 口径剔除，不参与对比：%s）"
              % (len(wb_non_fba), "、".join(sorted(set(s[0] for s in wb_non_fba)))))

    both = set(lx_key) & set(wb_key)
    same = [k for k in both if lx_key[k] == wb_key[k]]
    diff = [(k, lx_key[k], wb_key[k]) for k in both if lx_key[k] != wb_key[k]]
    only_lx = set(lx_key) - set(wb_key)
    only_wb = set(wb_key) - set(lx_key)

    print("\n=== SKU 明细对比：领星 vs WorkBuddy ===")
    print("领星（主表货件内）：%d 条 (货件,SKU) | 已发货合计 %d 双"
          % (len(lx_key), sum(lx_key.values())))
    print("WorkBuddy（FBA 货件口径）：%d 条 | 已发货合计 %d 双"
          % (len(wb_key), sum(wb_key.values())))
    print("① 两边都有且数量一致：%d 条" % len(same))
    print("② 两边都有但数量不一致：%d 条（合计差 %d 双）"
          % (len(diff), sum(abs(a - b) for _, a, b in diff)))
    for k, a, b in sorted(diff, key=lambda x: -abs(x[1] - x[2]))[:10]:
        print("     %s | %s：领星 %s 双 / WB %s 双（差 %+d）" % (k[0], k[1], a, b, a - b))
    print("③ 只在领星有：%d 条（合计 %d 双）" % (len(only_lx), sum(lx_key[k] for k in only_lx)))
    print("④ 只在 WorkBuddy 有：%d 条（合计 %d 双）" % (len(only_wb), sum(wb_key[k] for k in only_wb)))

    # ⑤ 按月数量差异（按主表发货月份归集）
    print("⑤ 按月数量差异（按主表发货月份）：")
    per_month = collections.defaultdict(lambda: {"lx": 0, "wb": 0, "lx_k": 0, "wb_k": 0})
    for sid, sku in lx_key:
        m = month_of(main_fba.get(sid, []))
        per_month[m]["lx"] += lx_key[(sid, sku)]
        per_month[m]["lx_k"] += 1
    for sid, sku in wb_key:
        m = month_of(main_fba.get(sid, []))
        per_month[m]["wb"] += wb_key[(sid, sku)]
        per_month[m]["wb_k"] += 1
    print("     月份    领星双数  WB双数    差      领星条数  WB条数")
    for m in sorted(per_month):
        d = per_month[m]
        if m in ("2026-09", "2026-10"):
            print("     %s  %8d %8d %+7d %9d %7d"
                  % (m, d["lx"], d["wb"], d["lx"] - d["wb"], d["lx_k"], d["wb_k"]))
    print("     （9/10 月之外的小计：领星 %d 双 / WB %d 双）"
          % (sum(d["lx"] for m, d in per_month.items() if m not in ("2026-09", "2026-10")),
             sum(d["wb"] for m, d in per_month.items() if m not in ("2026-09", "2026-10"))))

    # ---- 覆盖率与「只在领星有」的成因 ----
    lx_ships = set(sid for sid, _ in lx_key)
    wb_ships = set(sid for sid, _ in wb_key)
    print("\n--- 覆盖率与成因 ---")
    print("SKU 明细覆盖的货件数：领星 %d 个 / WB %d 个 | 交集 %d | WB 完全没记 SKU 明细的货件 %d 个"
          % (len(lx_ships), len(wb_ships), len(lx_ships & wb_ships), len(lx_ships - wb_ships)))
    only_lx_ships = lx_ships - wb_ships
    only_lx_qty = sum(lx_key[k] for k in only_lx)
    only_lx_rows = len(only_lx)
    shared_ships = lx_ships & wb_ships
    shared_only_rows = len([k for k in only_lx if k[0] in shared_ships])
    print("「只在领星有」%d 条中：来自 WB 完全没记录的货件 %d 条（%d 双）；"
          "来自双方都有但 SKU 粒度/数量不同的货件 %d 条"
          % (only_lx_rows, len(only_lx), only_lx_qty, shared_only_rows))
    # 只在领星的货件按月份分布
    cnt = collections.Counter()
    for sid in only_lx_ships:
        cnt[month_of(main_fba.get(sid, []))] += 1
    top = ", ".join("%s %d 个" % (m, c) for m, c in sorted(cnt.items()))
    print("WB 未记录的领星货件按月分布：%s" % top)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lx", default=os.path.join(BASE, "lx_raw", "shipments.json"))
    ap.add_argument("--records", default=os.path.join(BASE, "shandi-v5", "records.json"))
    ap.add_argument("--out", default=os.path.join(BASE, "data", "sku_from_lx.json"))
    ap.add_argument("--sku-index", default=os.path.join(BASE, "shandi-v5", "sku_index.json"))
    ap.add_argument("--fba-sku-index", default=os.path.join(BASE, "shandi-v5", "fba_sku_index.json"))
    ap.add_argument("--local-products", default=os.path.join(BASE, "wh_raw", "local_products.json"))
    ap.add_argument("--fba-inventory", default=os.path.join(BASE, "wh_raw", "fba_inventory.json"))
    ap.add_argument("--report", action="store_true", help="同时打印与 WorkBuddy 的对比报告")
    args = ap.parse_args()
    return build(args)


if __name__ == "__main__":
    sys.exit(main())
