# -*- coding: utf-8 -*-
"""空运单独成一类，不与海运（快船/普船）混算（2026-11-03 小丁提）。

起因：SKU 2604021 在 2026-04-03 有一票空运（美东 / 美通 / 210 件 / 总运费 7606.06
     → 单件 ¥36.2193），主表规范化时「船型原文=空运」被判成了「普船」，
     于是 ② 卡片里这票空运被混进海运：
       · 按船型拆分的「普船」均价被拉高（¥5.82 → ¥14.86）
       · 按地区拆分的「美东」整行其实只有这票空运
       · 头条「SKU 单件运费」也把它混算了
     全表只有 3 票空运（2026-04-03 / 04-18，渠道列写着「空运」）。

本补丁两处改动：
  ① 数据层 build_records_from_share.py：ship_type_norm() 把「空运」单列一类
     （这样 ③ 卡片按 ship_type 分组时，空运自动自成桶、不再进「普船」列，
       时效拆分也因 r.ship_type !== '普船' 自动排除）
  ② 页面 index.html：
     · 引擎加 isAir()；② 卡片按船型拆分为 快船 / 普船 / 空运 三类
     · ② 卡片船型筛选下拉加「空运」；普船筛选不再含空运
     · ② 卡片头条单件运费改为「海运口径」，空运单独一行列出
     · ① 卡片普船拆分排除空运；全部在途 KPI 空运单独计数（>0 才显示）
     · ⑥ 批次面板船型列：空运显示「空运」而不是「普船」
幂等：重复执行字节不变。
"""
import io, os, re, sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(WS, "shandi-v5", "index.html")
BLD = os.path.join(WS, "build_records_from_share.py")

html = io.open(IDX, encoding="utf-8", newline="").read()
norm = html.replace("\r\n", "\n")

PAIRS = [
    # ① 引擎：isAir 辅助
    ('  function isFast(st) { return (st || "").indexOf("快") >= 0; }',
     '  function isFast(st) { return (st || "").indexOf("快") >= 0; }\n'
     '  /* 空运单独一类（2026-11-03 小丁：空运不能跟海运混算） */\n'
     '  function isAir(st) { return (st || "").indexOf("空运") >= 0; }',
     "isAir 辅助", 1),

    # ② ① 单箱运费：普船拆分排除空运
    ('      ["快船", "普船"].forEach(function (st) {\n'
     '        var sub2 = sub.filter(function (r) {\n'
     '          return st === "快船" ? isFast(r.ship_type) : !isFast(r.ship_type);\n'
     '        });',
     '      ["快船", "普船"].forEach(function (st) {\n'
     '        var sub2 = sub.filter(function (r) {\n'
     '          if (st === "快船") return isFast(r.ship_type);\n'
     '          return !isFast(r.ship_type) && !isAir(r.ship_type);\n'
     '        });',
     "① 卡片普船拆分", 1),

    # ③ 船型筛选分支（两处 timeRecs + 一处 fb）
    ('    if (body.ship_type === "快船") timeRecs = timeRecs.filter(function (r) { return isFast(r.ship_type); });\n'
     '    else if (body.ship_type === "普船") timeRecs = timeRecs.filter(function (r) { return !isFast(r.ship_type); });',
     '    if (body.ship_type === "快船") timeRecs = timeRecs.filter(function (r) { return isFast(r.ship_type); });\n'
     '    else if (body.ship_type === "空运") timeRecs = timeRecs.filter(function (r) { return isAir(r.ship_type); });\n'
     '    else if (body.ship_type === "普船") timeRecs = timeRecs.filter(function (r) { return !isFast(r.ship_type) && !isAir(r.ship_type); });',
     "船型筛选分支", 2),

    ('        if (body.ship_type === "快船") fb = fb.filter(function (r) { return isFast(r.ship_type); });\n'
     '        else if (body.ship_type === "普船") fb = fb.filter(function (r) { return !isFast(r.ship_type); });',
     '        if (body.ship_type === "快船") fb = fb.filter(function (r) { return isFast(r.ship_type); });\n'
     '        else if (body.ship_type === "空运") fb = fb.filter(function (r) { return isAir(r.ship_type); });\n'
     '        else if (body.ship_type === "普船") fb = fb.filter(function (r) { return !isFast(r.ship_type) && !isAir(r.ship_type); });',
     "回退月份船型筛选", 1),

    # ④ 引擎：海运/空运分开聚合
    ('    var agg = skuAggregate(matched);\n\n    var byRegion = [];',
     '    var agg = skuAggregate(matched);\n'
     '    /* 空运单独算：头条与船型拆分都不能把空运混进海运（2026-11-03 小丁） */\n'
     '    var airRows = matched.filter(function (r) { return isAir(r.ship_type); });\n'
     '    var seaRows = matched.filter(function (r) { return !isAir(r.ship_type); });\n'
     '    var seaAgg = skuAggregate(seaRows);\n'
     '    var airAgg = skuAggregate(airRows);\n\n'
     '    var byRegion = [];',
     "海运/空运聚合", 1),

    # ⑤ ② 按船型拆分：三类
    ('    ["快船", "普船"].forEach(function (st) {\n'
     '      var sub = matched.filter(function (r) { return st === "快船" ? isFast(r.ship_type) : !isFast(r.ship_type); });',
     '    ["快船", "普船", "空运"].forEach(function (st) {\n'
     '      var sub = matched.filter(function (r) {\n'
     '        if (st === "空运") return isAir(r.ship_type);\n'
     '        if (st === "快船") return isFast(r.ship_type);\n'
     '        return !isFast(r.ship_type) && !isAir(r.ship_type);\n'
     '      });',
     "② 按船型拆分三类", 1),

    # ⑥ shipments 船型三分
    ('        ship_type: isFast(r.ship_type) ? "快船" : "普船",',
     '        ship_type: isAir(r.ship_type) ? "空运" : (isFast(r.ship_type) ? "快船" : "普船"),',
     "shipments 船型", 1),

    # ⑦ 返回值：海运/空运单件运费
    ('      total_freight: agg.total_freight, per_unit_freight: agg.per_unit_freight,\n'
     '      by_region: byRegion, by_ship_type: byShip, shipments: shipments,',
     '      total_freight: agg.total_freight, per_unit_freight: agg.per_unit_freight,\n'
     '      sea_per_unit_freight: seaAgg.per_unit_freight,\n'
     '      sea_record_count: seaAgg.record_count, sea_quantity: seaAgg.total_quantity,\n'
     '      air_per_unit_freight: airAgg.per_unit_freight,\n'
     '      air_record_count: airAgg.record_count, air_quantity: airAgg.total_quantity,\n'
     '      by_region: byRegion, by_ship_type: byShip, shipments: shipments,',
     "返回值海运/空运", 1),

    # ⑧ ② 船型筛选下拉：加空运
    ('              <option data-page-node-id="bZzMbLjizCjWvw4OeV04Ia" value="普船"><!--pnid:f18BZecjThEBlCYdLyO1Sp-->普船</option>',
     '              <option data-page-node-id="bZzMbLjizCjWvw4OeV04Ia" value="普船"><!--pnid:f18BZecjThEBlCYdLyO1Sp-->普船</option>\n'
     '              <option data-page-node-id="dtShipAir2026" value="空运"><!--pnid:dtShipAir2026-->空运</option>',
     "船型下拉加空运", 1),

    # ⑨ 头条：海运口径 + 空运单独一行
    ('    const pu = data.per_unit_freight == null\n'
     '      ? `<span class="placeholder">无件数<\\/span>`\n'
     '      : `<b>¥${data.per_unit_freight.toFixed(4)}<\\/b> /件`;',
     '    /* 头条单件运费 = 海运口径（快船+普船）；空运单独一行，不混算 */\n'
     '    const puVal = (data.sea_per_unit_freight == null) ? data.per_unit_freight : data.sea_per_unit_freight;\n'
     '    const pu = puVal == null\n'
     '      ? `<span class="placeholder">无件数<\\/span>`\n'
     '      : `<b>¥${puVal.toFixed(4)}<\\/b> /件`;',
     "头条海运口径", 1),

    ('    html += `<div class="sku-headline">SKU 单件运费 ≈ ${pu}<\\/div>`;',
     '    html += `<div class="sku-headline">SKU 单件运费 ≈ ${pu}<\\/div>`;\n'
     '    if (data.air_record_count > 0) {\n'
     '      const apu = data.air_per_unit_freight == null\n'
     '        ? `<span class="placeholder">无件数<\\/span>`\n'
     '        : `<b>¥${data.air_per_unit_freight.toFixed(4)}<\\/b> /件`;\n'
     '      html += `<div class="sku-headline sku-headline-air">空运单件运费 ≈ ${apu}（${data.air_record_count} 票 · ${data.air_quantity} 件）<\\/div>`;\n'
     '    }',
     "头条空运行", 1),

    # ⑩ 全部在途：isAirText 辅助
    ('  var EXPRESS_KEYS = ["美森", "快船", "快线"];\n'
     '  function isExpress(rec) {',
     '  var EXPRESS_KEYS = ["美森", "快船", "快线"];\n'
     '  /* 空运（2026-11-03 小丁）：原文含「空运」的单独一类，不与海运混算 */\n'
     '  function isAirText(rec) {\n'
     '    var raw = String((rec && rec.channel) || (rec && rec.ship_type) || "");\n'
     '    return raw.indexOf("空运") >= 0;\n'
     '  }\n'
     '  function isExpress(rec) {',
     "isAirText 辅助", 1),

    # ⑪ 全部在途：空运单独计数
    ('    var ship = { "快船": 0, "普船": 0 };',
     '    var ship = { "快船": 0, "普船": 0, "空运": 0 };',
     "在途船型计数", 1),

    ('      ship[(r.ship_type || "").indexOf("快") >= 0 ? "快船" : "普船"]++;',
     '      ship[isAirText(r) ? "空运" : ((r.ship_type || "").indexOf("快") >= 0 ? "快船" : "普船")]++;',
     "在途船型分类", 1),

    ("    + cell('普船', d.ship[\"普船\"], '', 'ground', '票')",
     "    + cell('普船', d.ship[\"普船\"], '', 'ground', '票')\n"
     "    + (d.ship[\"空运\"] ? cell('空运', d.ship[\"空运\"], '', 'air', '票') : '')",
     "在途KPI空运格", 1),

    # ⑫ ⑥ 批次面板：船型三分
    ('        express: isExpress(rs[0]),',
     '        express: isExpress(rs[0]),\n        air: isAirText(rs[0]),',
     "批次 fbaMeta", 1),

    ('      l.shipType = l.meta.express ? "快船" : "普船";',
     '      l.shipType = l.meta.air ? "空运" : (l.meta.express ? "快船" : "普船");',
     "批次船型显示", 1),

    ('|| { recs: [], express: false, ship: null, deliver: null, region: "unknown", stage: "unmatched", delivery_window: null };',
     '|| { recs: [], express: false, air: false, ship: null, deliver: null, region: "unknown", stage: "unmatched", delivery_window: null };',
     "批次 meta 兜底", 1),
]

changed = []
for old, new, tag, cnt in PAIRS:
    if new in norm:
        changed.append(tag + ":already")
        continue
    found = norm.count(old)
    if found != cnt:
        print("MISS:", tag, "期望 %d 处，实际 %d 处" % (cnt, found))
        sys.exit(1)
    norm = norm.replace(old, new)
    changed.append(tag + ":replaced(%d)" % found)

out = re.sub(r"(?<!\r)\n", "\r\n", norm)
io.open(IDX, "w", encoding="utf-8", newline="").write(out)
b = open(IDX, "rb").read()
print("patched:", ", ".join(changed))
print("index.html bytes %d | crlf %d | lf-only %d" % (len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n")))
t = io.open(IDX, encoding="utf-8").read()
print("isAir:", t.count("function isAir("), "| isAirText:", t.count("function isAirText("),
      "| 空运选项:", t.count('value="空运"'), "| air_record_count:", t.count("air_record_count"))

# ---------- 数据层：ship_type_norm 加空运 ----------
bld = io.open(BLD, encoding="utf-8", newline="").read()
bn = bld.replace("\r\n", "\n")
OLD_N = '''def ship_type_norm(raw):
    s = str(raw or "")
    if ("美森" in s) or ("快船" in s) or ("快线" in s):
        return "快船"
    return "普船"'''
NEW_N = '''def ship_type_norm(raw):
    s = str(raw or "")
    if "空运" in s:
        # 2026-11-03 小丁：空运单独一类，不能跟海运（普船/快船）混算
        return "空运"
    if ("美森" in s) or ("快船" in s) or ("快线" in s):
        return "快船"
    return "普船"'''
if NEW_N in bn:
    print("build_records_from_share.py: already")
elif OLD_N not in bn:
    print("MISS: ship_type_norm")
    sys.exit(1)
else:
    bn = bn.replace(OLD_N, NEW_N, 1)
    bo = re.sub(r"(?<!\r)\n", "\r\n", bn)
    io.open(BLD, "w", encoding="utf-8", newline="").write(bo)
    bb = open(BLD, "rb").read()
    print("build_records_from_share.py: replaced | bytes %d | crlf %d | lf-only %d"
          % (len(bb), bb.count(b"\r\n"), bb.count(b"\n") - bb.count(b"\r\n")))
