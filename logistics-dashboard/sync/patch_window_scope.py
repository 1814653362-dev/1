# -*- coding: utf-8 -*-
"""修 ①②③ 卡片「最近N个月」的口径缺陷（2026-11-02 小丁指出：头程单价 1 块/几毛明显不可能）。

根因：`monthRangeFilter` 对**没有发货日期的记录一律保留**（`if (!d) return true`）。
     主表里有 46 条无发货日期的记录，全部在 11月/12月 tab（实为 2025-11/2025-12），
     它们是零星小额碎料，被算进「最近3个月」后把加权均值拉到几毛几分：
       2212121 → ¥1.85、230421 → ¥0、8392 → ¥0.54、BF2 → ¥0
修法：无发货日期时**按月份 tab 推断发货年月**（1~10月=本年、11/12月=上年，与
     build_records_from_share.py 的 ym_of 同口径）再判断是否落在窗口内。

同时给 ② SKU 成本加回退：窗口内查不到该 SKU 时，回退到它**最近一次发货的月份**，
     并在时间标签上标出实际用的月份（成本不会突变；否则这些款号在②里直接"查不到"）。
"""
import io, os, re, sys

WS = r"D:\丁志浩minimax\.minimax\sessions\mvs_932857ad8b1748649104e680ab004996\workspace"
IDX = os.path.join(WS, "shandi-v5", "index.html")
html = io.open(IDX, encoding="utf-8").read()

# ---------- 改动 1：monthRangeFilter ----------
OLD1 = """  function monthRangeFilter(recs, months) {
    var now = new Date();
    var ny = now.getFullYear(), nm = now.getMonth() + 1;
    return recs.filter(function (r) {
      var d = parseDate(r.ship_date);
      if (!d) return true;
      var diff = (ny - d.getFullYear()) * 12 + (nm - (d.getMonth() + 1));
      return diff >= 0 && diff < months;
    });
  }"""

NEW1 = """  function monthRangeFilter(recs, months) {
    var now = new Date();
    var ny = now.getFullYear(), nm = now.getMonth() + 1;
    return recs.filter(function (r) {
      var d = parseDate(r.ship_date);
      if (!d) {
        /* 无发货日期 → 按月份 tab 推断发货年月（1~10月=本年、11/12月=上年，与
           build_records_from_share.py 的 ym_of 同口径）。
           原来这里 return true（一律保留），把去年 11-12 月的零星小额碎料也算进了
           「最近N个月」，运费均值被拉到几毛几分（2026-11-02 小丁指出头程 1 块不合理）。 */
        var mm = monthKey(r.source_sheet);
        if (mm == null) return false;
        var yy = mm >= 11 ? ny - 1 : ny;
        var diff0 = (ny - yy) * 12 + (nm - mm);
        return diff0 >= 0 && diff0 < months;
      }
      var diff = (ny - d.getFullYear()) * 12 + (nm - (d.getMonth() + 1));
      return diff >= 0 && diff < months;
    });
  }"""

# ---------- 改动 2：engineSkuCost 匹配链抽函数 + 回退 ----------
OLD2 = """    var tokens = splitSkus(body.sku).map(normSku).filter(function (x) { return x; });
    var matched = [], mode = "none";
    if (tokens.length > 1) {
      matched = timeRecs.filter(function (r) {
        var tk = recTokens(r);
        return tokens.every(function (t) { return tk.indexOf(t) >= 0; });
      });
      if (matched.length) mode = "mixed";
      else {
        matched = timeRecs.filter(function (r) {
          var tk = recTokens(r);
          return tokens.some(function (t) { return tk.indexOf(t) >= 0; });
        });
        if (matched.length) mode = "mixed_union";
      }
    }
    if (!matched.length && tokens.length) {
      matched = timeRecs.filter(function (r) { return recTokens(r).indexOf(tokens[0]) >= 0; });
      if (matched.length) mode = "exact";
    }
    if (!matched.length && tokens.length) {
      matched = timeRecs.filter(function (r) {
        var tk = recTokens(r);
        return tk.some(function (t) { return t.indexOf(tokens[0]) >= 0 || tokens[0].indexOf(t) >= 0; });
      });
      if (matched.length) mode = "fuzzy";
    }
"""

NEW2 = """    var tokens = splitSkus(body.sku).map(normSku).filter(function (x) { return x; });
    /* 匹配链：多 SKU → mixed / mixed_union；单 SKU → exact → fuzzy */
    function matchSku(recs) {
      var hit = [], md = "none";
      if (tokens.length > 1) {
        hit = recs.filter(function (r) {
          var tk = recTokens(r);
          return tokens.every(function (t) { return tk.indexOf(t) >= 0; });
        });
        if (hit.length) md = "mixed";
        else {
          hit = recs.filter(function (r) {
            var tk = recTokens(r);
            return tokens.some(function (t) { return tk.indexOf(t) >= 0; });
          });
          if (hit.length) md = "mixed_union";
        }
      }
      if (!hit.length && tokens.length) {
        hit = recs.filter(function (r) { return recTokens(r).indexOf(tokens[0]) >= 0; });
        if (hit.length) md = "exact";
      }
      if (!hit.length && tokens.length) {
        hit = recs.filter(function (r) {
          var tk = recTokens(r);
          return tk.some(function (t) { return t.indexOf(tokens[0]) >= 0 || tokens[0].indexOf(t) >= 0; });
        });
        if (hit.length) md = "fuzzy";
      }
      return { matched: hit, mode: md };
    }
    var _m = matchSku(timeRecs);
    var matched = _m.matched, mode = _m.mode;
    /* 时间窗口内查不到 → 回退到该 SKU 最近一次发货的月份（成本不会突变）。
       2026-11-02 小丁要求「头程单价」必须是有意义的数，不能因为最近3个月没发货就空着。 */
    if (!matched.length && tokens.length && !body.target_month) {
      var latestYm = null;
      all.forEach(function (r) {
        var d = parseDate(r.ship_date);
        if (!d) return;
        var tk = recTokens(r);
        if (!tokens.some(function (t) { return tk.indexOf(t) >= 0; })) return;
        var ym = d.getFullYear() + "-" + (d.getMonth() + 1);
        if (!latestYm || ym > latestYm) latestYm = ym;
      });
      if (latestYm) {
        var fb = all.filter(function (r) {
          var d = parseDate(r.ship_date);
          if (!d) return false;
          return (d.getFullYear() + "-" + (d.getMonth() + 1)) === latestYm;
        });
        if (body.ship_type === "快船") fb = fb.filter(function (r) { return isFast(r.ship_type); });
        else if (body.ship_type === "普船") fb = fb.filter(function (r) { return !isFast(r.ship_type); });
        var _m2 = matchSku(fb);
        if (_m2.matched.length) {
          matched = _m2.matched;
          mode = _m2.mode;
          targetLabel = targetLabel + "（无发货，回退 " + latestYm + "）";
        }
      }
    }
"""

changed = []
for old, new, tag in ((OLD1, NEW1, "monthRangeFilter窗口口径"),
                      (OLD2, NEW2, "engineSkuCost回退")):
    if new in html:
        changed.append(tag + ":already")
        continue
    if old not in html:
        print("MISS:", tag)
        sys.exit(1)
    html = html.replace(old, new, 1)
    changed.append(tag + ":replaced")

html = re.sub(r"(?<!\r)\n", "\r\n", html)
io.open(IDX, "w", encoding="utf-8", newline="").write(html)
b = open(IDX, "rb").read()
print("patched:", ", ".join(changed))
print("bytes %d | crlf %d | lf-only %d" % (len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n")))
t = io.open(IDX, encoding="utf-8").read()
print("monthRangeFilter 修正:", "按月份 tab 推断发货年月" in t)
print("engineSkuCost 回退:", "无发货，回退" in t)
