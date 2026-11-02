# -*- coding: utf-8 -*-
"""修复 ⑥ SKU批次在途 的「到仓进度」恒为 0。

根因（2026-11-02 上午数据源切换时引入）：
    build() 里把过滤写成「按行过滤」——
        skuRows = skuRows.filter(l => l.meta && l.meta.ship && !lineArrived(l));
    已入仓的行被整行剔掉 → sumArrived() 永远算出 0 →
    底部「到仓进度」条恒为空、单元格「入仓 N」恒为 0。

修法：改成「批次级过滤」——
    行全部保留，只把「整批都已入仓」的批次（连同它的行）剔掉。
    还在途的批次保留它已入仓的行，入仓数 / 到仓进度才算得出来；
    月份卡片、批次列、导出全部自动跟着修好（都吃同一个 skuRows）。
"""
import io, os, re, sys

WS = r"D:\丁志浩minimax\.minimax\sessions\mvs_932857ad8b1748649104e680ab004996\workspace"
IDX = os.path.join(WS, "shandi-v5", "index.html")

OLD = """    /* 2026-11-02 小丁定：放开原来的「最近3个月」窗口，改成「只显示还在途的货件」。
       · 已入仓的老批次（5-8 月那 34,233 双）不再出现在月度卡片/批次表里；
       · 还没入仓的老批次照样显示 —— 3 个月窗口会把它们误伤掉；
       · 1-4 月更早批次领星里没有，不补齐（不影响在途口径）。
       入仓判定同 lineArrived()：货件状态=入仓，或已有送达日期（送达日期即实际到仓）。 */
    var before = skuRows.length;
    skuRows = skuRows.filter(function (l) {
      return l.meta && l.meta.ship && !lineArrived(l);
    });
    console.log("[sku] 只显示还在途的货件:", before, "->", skuRows.length);"""

NEW = """    /* 2026-11-02 小丁定：放开原来的「最近3个月」窗口，改成「只显示还在途的批次」。
       · 整批都已入仓的老批次（5-8 月那 34,233 双）不再出现在月度卡片/批次表里；
       · 还没入仓的老批次照样显示 —— 3 个月窗口会把它们误伤掉；
       · 1-4 月更早批次领星里没有，不补齐（不影响在途口径）。
       入仓判定同 lineArrived()：货件状态=入仓，或已有送达日期（送达日期即实际到仓）。

       ⚠ 2026-11-02 补回「到仓进度」：上午那版是按「行」过滤（!lineArrived(l)），
       把已入仓的行整行剔掉了 —— 入仓行没了，sumArrived() 永远算出 0，
       底部「到仓进度」条恒为空、单元格「入仓 N」恒为 0。
       现在改成**批次级过滤**：行全部保留，只把「整批都已入仓」的批次（连它的行）剔掉。
       还在途的批次保留它已入仓的行 → 入仓数 / 到仓进度才算得出来；
       月份卡片、批次列、CSV/Excel 导出都吃同一个 skuRows，会一起修好。 */
    var before = skuRows.length;
    skuRows = skuRows.filter(function (l) { return l.meta && l.meta.ship; });
    /* 过滤粒度 = **月份**，不是批次。
       批次级过滤会把「月内已全部入仓的批次」也剔掉 → 9 月的 09-05 那批 2,712 双不见了，
       合计 17,910 和实际发货 20,597 对不上（小丁 2026-11-02 提出）。
       改成：整月都没有在途货件的月份（5-8 月那 34,233 双）不出现；
       月份一旦出现，它里面所有批次（含已全部入仓的）都保留 ——
       入仓数 / 到仓进度才算得出来，月度合计也和实际发货对得上。 */
    var _transitMonth = {};
    skuRows.forEach(function (l) {
      if (!lineArrived(l)) _transitMonth[l.meta.ship.slice(0, 7)] = 1;
    });
    skuRows = skuRows.filter(function (l) { return !!_transitMonth[l.meta.ship.slice(0, 7)]; });
    console.log("[sku] 只显示还有在途货件的月份:", before, "->", skuRows.length);"""

html = io.open(IDX, encoding="utf-8").read()
if NEW in html:
    print("already patched")
else:
    assert OLD in html, "未找到待替换块（build() 里的行级过滤）"
    html = html.replace(OLD, NEW, 1)
    html = re.sub(r"(?<!\r)\n", "\r\n", html)
    io.open(IDX, "w", encoding="utf-8", newline="").write(html)
    print("patched: 到仓进度（行级过滤 → 批次级过滤）")

b = open(IDX, "rb").read()
print("bytes %d | crlf %d | lf-only %d" % (len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n")))
t = io.open(IDX, encoding="utf-8").read()
print("残留行级过滤:", t.count("l.meta.ship && !lineArrived(l)"))
print("批次级过滤:", t.count("_transitBatch"))
