# 杉迪供应链货流 · 物流看板

面向跨境电商物流 / 货代场景的运费、时效、库龄与货件状态看板。数据来自**共享盘发货记录**（主表唯一事实源）与**领星 ERP**（库存 / 货件状态 / 采购单 / 出库明细），构建期内嵌进页面，运行时零外部请求。

本目录包含三部分：

- **看板前端**（`dashboard/index.html`）：单页看板，读取资料库并渲染全部模块。
- **数据链路**（`sync/`）：领星抓取 → 主表构建 → 页面注入 → 写资料库 → 发布 → 线上校验，一条 `refresh_all.ps1` 串起来。
- **口径与配置**：`.env.example`（凭据模板）、`.gitignore`。

> **仓库里的页面是脱敏版**：页面代码完整保留，但内嵌的库存快照 / 周趋势 / 库龄矩阵 / 款号运营归属 / 成本快照 / 库存事件流都已置空，资料库数据库 ID 换成 `REPLACE_WITH_DATABASE_ID`，平台注入的统计脚本与悬浮球已剔除。
> 本地跑一次 `refresh_all.ps1` 即会重新注入数据、生成可用的完整版。

---

## 环境变量

复制 `.env.example` 为 `.env` 并填写（`.env` 不入库），或直接 `export`：

| 变量 | 用途 |
|---|---|
| `LX_APP_ID` / `LX_APP_SECRET` | 领星开放平台凭据（抓库存 / 货件 / 采购单 / 分类账都用它） |
| `WB_PAGE_URL` | WorkBuddy「发布为网站」页面的资料库地址（发货记录主表写回与读取用） |
| `SHARE_XLSX` | 共享盘发货记录.xlsx 的路径（主表唯一事实源） |

> 脚本在凭据缺失时会直接报错退出，不会静默跑出空结果。

---

## 跑起来

### 一条命令（全链路）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File sync\refresh_all.ps1
```

依次执行：领星抓取（仓库/店铺/库存、本地仓商品清单、FBA 出库明细、库存分类账）→ 主表与索引构建 → 页面注入 → 写资料库 → 同步共享盘 → 重建主表 → 归档快照 → 周趋势计算 → 发布 → 线上校验。

日常定时任务跑的是 `sync\nightly_refresh.ps1`（夜间版，AsOf 取昨天；周末只更新库存快照，不动发货记录类数据）。

### 只想更新库存快照

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File sync\nightly_refresh.ps1
```

---

## 文件结构

```
logistics-dashboard/
├── dashboard/
│   ├── index.html                 看板单页源码（仓库内为脱敏版，无业务数据）
│   └── records.sample.json        records.json 的空壳样例，供本地起页面用
├── sync/
│   ├─ 领星抓取 ────────────────────────────────
│   │   ├── fetch_wh.ps1                  仓库/店铺/库存明细（FBA + 本地仓）
│   │   ├── fetch_products.ps1            本地仓商品清单
│   │   ├── fetch_ship.ps1                FBA 出库明细
│   │   ├── fetch_ledger.ps1              库存分类账
│   │   ├── lx_ledger.py                  分类账拉取器（按月缓存）
│   │   ├── lx_recv_time.py               货件 receiving_time → 到仓时刻
│   │   ├── fetch_purchase_orders.py      采购单（含采购单价、到货入库量）
│   │   ├─ 数据构建 ────────────────────────────────
│   │   ├── build_records_from_share.py   共享盘 → 主表 records.json（唯一事实源）
│   │   ├── build_wh_snapshot.py          本地仓/FBA 库存快照
│   │   ├── build_spu2.py / build_spu_local.py
│   │   ├── build_sku_index.py / build_fba_sku_index2.py
│   │   ├── build_vol_v5.py               库容占用体积口径
│   │   ├── build_age_spu.py              库龄 × 款号矩阵
│   │   ├── build_spu_owner.py            SPU → 运营归属
│   │   ├── build_sku_from_lx.py          SKU 明细（领星）
│   │   ├── build_trend.py                FBA 周趋势
│   │   ├─ 页面注入 ────────────────────────────────
│   │   ├── inject_wh_inplace.py          注入 __WH 库存数据
│   │   ├── patch_vol_v5.py               注入库容图
│   │   ├── patch_age_spu_fba.py          注入库龄矩阵
│   │   ├── patch_spu_owner.py            注入运营归属
│   │   ├── patch_fba_kpi_style.py        FBA 指标格样式
│   │   ├── patch_trend_ui.py             注入周趋势交互
│   │   ├── patch_sku_progress.py         到仓进度口径修正
│   │   ├── patch_window_scope.py         「最近N个月」窗口口径修正
│   ├─ 编排与同步 ────────────────────────────────
│   │   ├── refresh_all.ps1               全链路（上面那条命令）
│   │   ├── nightly_refresh.ps1           夜间定时版
│   │   ├── refresh_data.ps1              资料库读写
│   │   ├── sync_share_xlsx.ps1          同步共享盘发货记录
│   │   ├── sync_sku_batch_lx.ps1        SKU 批次明细同步
│   │   ├── unify_share_formats.ps1      共享盘各 tab 格式统一
│   │   ├── write_share_lx.ps1           领星值写回共享盘
│   │   ├── verify_page.py               线上校验
│   │   └─ 抽检 ────────────────────────────────
│   │       ├── audit_plan.py            抽检排期（工作日随机三晚）
│   │       ├── audit_logistics.py       物流数据抽检
│   │       └── audit_features.py        功能一致性核对
├── .env.example                  凭据模板
├── .gitignore
├── LICENSE
└── README.md
```

---

## 数据口径（重要）

- **主表唯一事实源**：`共享盘/物流部/发货记录.xlsx`，12 个月度 tab。脚本按 tab 推断年份（1~10 月 = 本年，11/12 月 = 上年）。**领星 receiving_time 会写回共享盘「送达时间」列**，系统侧不再二次回填，避免两个真相。
- **地区归并**：主表有 6 个细分地区（美西 / 美中 / 美中北 / 美中南 / 美东 / 美东南），计算时按三大区归并：美中北、美中南 → 美中；美东南 → 美东。
- **货件状态判定**：`RECEIVING` / `CLOSED` / `DELIVERED` 判定为到仓，其余（`SHIPPED` / `IN_TRANSIT` / `WORKING` / `READY_TO_SHIP` / `UNCONFIRMED` / `CHECKED_IN`）判定为在途。
- **「最近 N 个月」窗口**：按**真实发货日期**算；**没有发货日期的记录按月份 tab 推断年月**再判断是否落在窗口内（早期版本一律保留，会把去年的零星碎料算进窗口，把运费均值拉到几毛几分）。
- **窗口内查不到时回退**：② SKU 成本在窗口内查不到该 SKU 时，回退到它最近一次发货的月份，时间标签会标明实际用的月份。
- **价格未确认的货件整条排除**：主表「总运费」为空的货件不计运费也不计件数，会单独统计上报。
- **船型判定**：船型原文含「美森」「快船」「快线」= 快船，其余 = 普船；6 月之后主表船型列填的是渠道名，判定仍按原文包含关系走。
- **对碰范围**：只对碰 SKU 明细覆盖到的在途货件（主表 FBA 货件号与 SKU 明细「货件单号」有交集的行），历史货件不进对碰。

---

## 说明

- 本仓库不含任何私密凭据；真实密钥与页面 ID 已替换为环境变量占位。
- 看板的业务数据不随本仓库分发：`dashboard/index.html` 已脱敏（数据块置空、数据库 ID 占位、平台注入段剔除），构建产物（`records.json` 等）均在 `.gitignore` 中。本地跑一遍链路即可还原完整页面。
- `sync/build_wh_snapshot.py` 里的仓库 ID 与名称是示例值（`10001`~`10005`），按你自己领星的仓库改；`sync/` 里出现的店名、运营名等一律是占位。
- 发布到 MiniMax 站点所需的平台凭据与脚本不随仓库分发，请自行配置。
- 运费、时效口径由数据拥有者维护，fork 后请按你的实际业务校准。
