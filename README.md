# 跨境电商物流看板（Logistics Dashboard）

一个面向跨境电商物流 / 货代场景的运费、时效与货件状态看板，数据来自领星 ERP 的 FBA 货件接口，经过口径归并后展示。

本仓库包含两部分：

- **看板前端**（`dashboard/v134.html`）：一个 WorkBuddy 智能页，实时读取资料库并渲染图表。
- **领星同步后台**（`sync/`）：一组脚本，把领星 FBA 货件状态同步进看板数据库，作为每周自动任务运行。

---

## 两种用法

### 方式 A：直接嵌入（零部署，推荐）

看板已经发布为一个公开只读页面。任何人拿到链接就能看，你（数据拥有者）在资料库里改了数据，对方刷新即可看到最新结果。

嵌入到你自己的系统（iframe）：

```html
<iframe
  src="https://workbuddy.link/p/AG1ZyVlXPs4H1z2VaUaWsB"
  width="100%"
  height="900"
  frameborder="0"
  style="border:0;">
</iframe>
```

> 链接由数据拥有者提供。只要拥有者保持页面发布状态，嵌入方无需任何配置。

**数据同步原理**：看板页面关联到资料库的数据表，页面在 WorkBuddy 运行环境内实时读取。拥有者修改资料库（无论是手动改，还是每周自动从领星同步），嵌入方刷新页面即是最新数据，不需要把数据推到任何地方。

### 方式 B：fork 后用你自己的数据自建一套

如果你想用自己的领星账号和资料库搭一套独立的看板：

1. 在领星开放平台申请 App ID / Secret。

2. 在 WorkBuddy 资料库建立「新版发货记录」和「SKU 批次明细」两张表，记下数据库 ID。

3. 复制 `.env.example` 为 `.env`，填入上面的凭据与数据库 ID（或直接 `export` 环境变量）。

4. 运行同步脚本，把领星货件状态同步进你的资料库：

   ```bash
   # 先取得 WorkBuddy 的 op_token（在 WorkBuddy 里执行 connect_open_platform）
   printf '%s' "<op_token>" | bash sync/lx_auto_sync.sh --dry   # 试跑，只输出待更新
   printf '%s' "<op_token>" | bash sync/lx_auto_sync.sh        # 正式写库
   ```

5. 把 `dashboard/v134.html` 导入你自己的资料库，并把其中的 `DATABASE_ID` 改成你自己的数据库 ID，然后「发布为网站」得到你自己的链接，再按方式 A 嵌入。

> 注意：`v134.html` 是 WorkBuddy 智能页，依赖 WorkBuddy 运行环境（`window.__SMART_PAGE__`），不能直接当作普通静态网页放到任意服务器运行。它必须发布在 WorkBuddy 资料库内。

---

## 环境变量说明（`.env.example`）

| 变量                            | 用途                        |
| ----------------------------- | ------------------------- |
| `LX_APP_ID` / `LX_APP_SECRET` | 领星开放平台凭据，用于调用 FBA 货件接口    |
| `MAIN_DB`                     | 看板主表「新版发货记录」的资料库数据库 ID    |
| `SKU_DB`                      | 「SKU 批次明细」数据库 ID，用于限定对碰范围 |
| `PY` / `NODE`                 | 可选，覆盖默认 Python / Node 路径  |

---

## 数据口径（重要）

- **地区归并**：主表备注列有 6 个细分地区（美西 / 美中 / 美中北 / 美中南 / 美东 / 美东南），计算时按三大区归并：美中北、美中南 → 美中；美东南 → 美东；美西、美东不变。
- **货件状态判定**：`RECEIVING` / `CLOSED` / `DELIVERED` 判定为到仓，其余（`SHIPPED` / `IN_TRANSIT` / `WORKING` / `READY_TO_SHIP` / `UNCONFIRMED` / `CHECKED_IN`）判定为在途。
