# -*- coding: utf-8 -*-
"""② SKU成本统计：在「按地区拆分 / 按船型拆分」表右侧加「发货日期」列（2026-11-03 小丁提）。

起因：小丁反馈 ② 卡片结果表右边空着，"出了问题我定位不到是哪批的货"——
     原来只有 地区/记录数/单件运费，看不出这批货是哪天发的。

改动（全部只在 ② 的引擎与渲染层，不动其他模块）：
  1) 新增全局辅助：shipMd(日期→M.D)、shipDateList(去重倒序)、shipDateDetail(日期→FBA+件数)
  2) engineSkuCost：byRegion / byShip 每项补 ship_dates（日期清单）+ ship_detail（悬停明细）
  3) shipments 每条补 ship_date
  4) 渲染：两张拆分表各加一列「发货日期」；价格缺失告警表也加一列「发货日期」
幂等：重复执行字节不变（已打过补丁会输出 already）。
"""
import io, os, re, sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(WS, "shandi-v5", "index.html")
html = io.open(IDX, encoding="utf-8", newline="").read()
norm = html.replace("\r\n", "\n")

HELPERS = '''/* ---- 发货日期工具（2026-11-03：② 拆分表右侧要能看到发货日期，便于定位是哪批货） ---- */
function shipMd(d) {
  var s = String(d || "").trim();
  if (s.length >= 10 && s.charAt(4) === "-") {
    return String(parseInt(s.slice(5, 7), 10)) + "." + String(parseInt(s.slice(8, 10), 10));
  }
  return s;
}
function shipDateList(rows) {
  var seen = {}, out = [];
  (rows || []).forEach(function (r) {
    var d = String(r.ship_date || "").trim();
    if (!d || seen[d]) return;
    seen[d] = 1; out.push(d);
  });
  out.sort(function (a, b) { return a < b ? 1 : (a > b ? -1 : 0); });
  var res = [], last = "";
  out.forEach(function (d) {
    var m = shipMd(d);
    if (m === last) return;
    last = m; res.push(m);
  });
  return res;
}
function shipDateDetail(rows) {
  var by = {}, keys = [];
  (rows || []).forEach(function (r) {
    var d = String(r.ship_date || "").trim();
    if (!d) return;
    if (!by[d]) { by[d] = { qty: 0, fba: [] }; keys.push(d); }
    by[d].qty += Number(r.quantity || 0);
    var f = String(r.fba || "").split("&")[0];
    if (f && by[d].fba.indexOf(f) < 0) by[d].fba.push(f);
  });
  keys.sort(function (a, b) { return a < b ? 1 : (a > b ? -1 : 0); });
  return keys.map(function (k) {
    return shipMd(k) + "：" + (by[k].fba.join("、") || "—") + "（" + by[k].qty + "件）";
  }).join("；");
}
function shipDatesText(list) {
  if (!list || !list.length) return "—";
  var s = list.slice(0, 6).join("、");
  if (list.length > 6) s += " 等" + list.length + "个";
  return s;
}
'''

PAIRS = [
    # 1) 辅助函数插到 ② 渲染层之前（全局声明，引擎侧也能调用）
    (
        "// SKU 物流成本测算：输入 SKU → 汇总运费总和与件数 → 推算单件运费",
        HELPERS + "// SKU 物流成本测算：输入 SKU → 汇总运费总和与件数 → 推算单件运费",
        "辅助函数",
    ),
    # 2) byRegion 补 ship_dates / ship_detail
    (
        """      a.region = reg; a.region_label = REGION_LABELS[reg];
      byRegion.push(a);""",
        """      a.region = reg; a.region_label = REGION_LABELS[reg];
      a.ship_dates = shipDateList(sub);
      a.ship_detail = shipDateDetail(sub);
      byRegion.push(a);""",
        "byRegion",
    ),
    # 3) byShip 补 ship_dates / ship_detail
    (
        """      a.ship_type = st;
      byShip.push(a);""",
        """      a.ship_type = st;
      a.ship_dates = shipDateList(sub);
      a.ship_detail = shipDateDetail(sub);
      byShip.push(a);""",
        "byShip",
    ),
    # 4) shipments 每条补 ship_date
    (
        """        ship_type: isFast(r.ship_type) ? "快船" : "普船",
        quantity: Number(r.quantity || 0), box_count: Number(r.box_count || 0),""",
        """        ship_type: isFast(r.ship_type) ? "快船" : "普船",
        ship_date: r.ship_date || "",
        quantity: Number(r.quantity || 0), box_count: Number(r.box_count || 0),""",
        "shipments",
    ),
    # 5) 按地区拆分：加「发货日期」列
    (
        """        <th>地区<\\/th><th>记录数<\\/th><th>单件运费(元/件)<\\/th>
      <\\/tr>`;
      for (const it of data.by_region) {
        const pp = it.per_unit_freight == null ? "—" : `¥${it.per_unit_freight.toFixed(4)}`;
        html += `<tr>
          <td class="region-${it.region}">${it.region_label}<\\/td>
          <td>${it.record_count}<\\/td>
          <td><b>${pp}<\\/b><\\/td>
        <\\/tr>`;""",
        """        <th>地区<\\/th><th>记录数<\\/th><th>单件运费(元/件)<\\/th><th>发货日期<\\/th>
      <\\/tr>`;
      for (const it of data.by_region) {
        const pp = it.per_unit_freight == null ? "—" : `¥${it.per_unit_freight.toFixed(4)}`;
        html += `<tr>
          <td class="region-${it.region}">${it.region_label}<\\/td>
          <td>${it.record_count}<\\/td>
          <td><b>${pp}<\\/b><\\/td>
          <td title="${String(it.ship_detail || "").replace(/"/g, "&quot;")}">${shipDatesText(it.ship_dates)}<\\/td>
        <\\/tr>`;""",
        "按地区拆分表",
    ),
    # 6) 按船型拆分：加「发货日期」列
    (
        """        <th>船型<\\/th><th>记录数<\\/th><th>单件运费(元/件)<\\/th>
      <\\/tr>`;
      for (const it of data.by_ship_type) {
        const pp = it.per_unit_freight == null ? "—" : `¥${it.per_unit_freight.toFixed(4)}`;
        html += `<tr>
          <td>${it.ship_type}<\\/td>
          <td>${it.record_count}<\\/td>
          <td><b>${pp}<\\/b><\\/td>
        <\\/tr>`;""",
        """        <th>船型<\\/th><th>记录数<\\/th><th>单件运费(元/件)<\\/th><th>发货日期<\\/th>
      <\\/tr>`;
      for (const it of data.by_ship_type) {
        const pp = it.per_unit_freight == null ? "—" : `¥${it.per_unit_freight.toFixed(4)}`;
        html += `<tr>
          <td>${it.ship_type}<\\/td>
          <td>${it.record_count}<\\/td>
          <td><b>${pp}<\\/b><\\/td>
          <td title="${String(it.ship_detail || "").replace(/"/g, "&quot;")}">${shipDatesText(it.ship_dates)}<\\/td>
        <\\/tr>`;""",
        "按船型拆分表",
    ),
    # 7) 价格缺失告警表：加「发货日期」列
    (
        """<th>月份<\\/th><th>仓点<\\/th><th>进仓编号<\\/th><th>FBA货件号<\\/th><th>件数<\\/th><th>缺失费用项<\\/th>""",
        """<th>月份<\\/th><th>发货日期<\\/th><th>仓点<\\/th><th>进仓编号<\\/th><th>FBA货件号<\\/th><th>件数<\\/th><th>缺失费用项<\\/th>""",
        "告警表表头",
    ),
    (
        """${un.map(s => `<tr><td>${s.source_sheet || "—"}<\\/td><td><code>${s.warehouse_code}<\\/code><\\/td>""",
        """${un.map(s => `<tr><td>${s.source_sheet || "—"}<\\/td><td>${shipMd(s.ship_date) || "—"}<\\/td><td><code>${s.warehouse_code}<\\/code><\\/td>""",
        "告警表行",
    ),
]

changed = []
for old, new, tag in PAIRS:
    if new in norm:
        changed.append(tag + ":already")
        continue
    if old not in norm:
        print("MISS:", tag)
        sys.exit(1)
    norm = norm.replace(old, new, 1)
    changed.append(tag + ":replaced")

out = re.sub(r"(?<!\r)\n", "\r\n", norm)
io.open(IDX, "w", encoding="utf-8", newline="").write(out)
b = open(IDX, "rb").read()
print("patched:", ", ".join(changed))
print("bytes %d | crlf %d | lf-only %d" % (len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n")))
t = io.open(IDX, encoding="utf-8").read()
print("发货日期列:", t.count("<th>发货日期<\\/th>"), "处")
print("shipDateList 调用:", t.count("shipDateList(sub)"), "处")
print("ship_date 字段:", t.count("ship_date: r.ship_date"), "处")
