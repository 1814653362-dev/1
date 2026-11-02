# 杉迪供应链货流 · 物流看板

跨境电商物流 / 货代场景的**运费、时效、库龄与货件状态**看板。

| 目录 | 内容 |
|---|---|
| [`logistics-dashboard/`](logistics-dashboard/) | 看板本体：页面源码 + 领星抓取 / 数据构建 / 页面注入 / 每日刷新链路 |

---

## 这套系统是什么

一个单页看板（`logistics-dashboard/dashboard/index.html`），围绕「这批货发了多少钱、多久能到、到没到、仓里还剩多少」组织：

| 模块 | 做什么 |
|---|---|
| ① 单箱运费测算 | 输入外箱尺寸 / 箱规 / 时间范围，算每双运费（按地区 × 船型拆分） |
| ② SKU 成本统计 | 按 SKU / 款号查最近几个月的实际物流成本 |
| ③ 时间范围平均运费（按地区） | 美西 / 美中 / 美东 的单价与时效对比 |
| ④ 在途物流可视图 | 太平洋航线：出口港 → 航线 → 美国 FBA 仓点气泡（在途件数、地区） |
| ⑤ C 端物流成本统计 | 按月 / 批次汇总数量、货值、物流成本，并与去年同期对比 |
| ⑥ SKU 批次在途 | 批次（发货日期）维度的已发 / 入仓 / 到仓进度 |
| 仓库模块 | FBA 库存、五档库龄结构、库容占用剖面、款号级 13 周趋势 |

**数据链路**：`共享盘发货记录.xlsx` 是主表的**唯一事实源**，领星 ERP 提供库存 / 货件状态 / 采购单 / 出库明细；构建期把数据内嵌进 HTML，运行时零外部请求、零计算。

---

## 跑起来

完整说明见 [`logistics-dashboard/README.md`](logistics-dashboard/README.md)。

```powershell
# 一条命令：抓取 → 构建 → 注入 → 写资料库 → 发布 → 线上校验
powershell -NoProfile -ExecutionPolicy Bypass -File logistics-dashboard\sync\refresh_all.ps1
```

---

## 这个仓库里没有什么

- **不含任何凭据**：领星 App ID/Secret、资料库页面 ID 全部走环境变量，见 [`logistics-dashboard/.env.example`](logistics-dashboard/.env.example)。
- **不含真实业务数据**：`records.json` / `trend.json` / `sku_index.json` 等构建产物一律不入库（见 `.gitignore`），由脚本从共享盘与领星重新生成。
- **仓库里的 `dashboard/index.html` 是脱敏版**：页面代码完整，但内嵌的库存快照 / 周趋势 / 库龄矩阵 / 款号运营归属 / 成本快照 / 库存事件流都已置空，资料库 ID 换成占位符，平台注入的统计脚本已剔除。
  在本地跑一次上面的链路即可生成带数据的完整版。
- **不含平台侧发布脚本**：发布到 MiniMax 站点需要平台凭据，脚本不随仓库分发。

> 口径与业务规则由数据拥有者维护，fork 后请按你的实际业务校准。
