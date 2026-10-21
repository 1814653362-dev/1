// 定向拉取：只查「SKU 批次明细」覆盖到的主表 FBA 货件号（shipment_id 精确匹配，逗号分隔分批）
// 用法: node fetch_lx_ship_targeted.js [db_records.json] [sku_records.json]
// 范围口径（2026-10-20 用户明确）：主表货件号 ∩ SKU 批次明细「货件单号」→ 只拉这些货件的状态
const https = require("https");
const fs = require("fs");
const LX = require("./lingxing_client.js");

const APP_ID = "process.env.LX_APP_ID", APP_SECRET = "process.env.LX_APP_SECRET", HOST = "openapi.lingxing.com";
const SIDS = "6574,13306,16907,13310,18538,13120";   // 主表涉及的 6 个店铺
const START = "2025-11-01", END = "2026-11-01";       // 按货件创建日期的宽窗口（覆盖主表 1–10 月）
const CHUNK = 50;                                    // 每批货件号数量（实测接口上限 75，取 50 保险）
const GAP = 1100;                                     // 令牌桶容量 1，串行 + 间隔

function getToken() {
  return new Promise(res => {
    const r = https.request({ method: "POST", hostname: HOST, path: "/api/auth-server/oauth/access-token", headers: { "Content-Type": "application/x-www-form-urlencoded" } }, p => {
      let b = ""; p.on("data", d => b += d);
      p.on("end", () => { try { const j = JSON.parse(b); res(j.code === "200" ? j.data.access_token : null); } catch (e) { res(null); } });
    });
    r.on("error", () => res(null));
    r.write("appId=" + encodeURIComponent(APP_ID) + "&appSecret=" + encodeURIComponent(APP_SECRET));
    r.end();
  });
}
function post(path, body, token) {
  return new Promise(res => {
    const data = JSON.stringify(body);
    const ts = Math.floor(Date.now() / 1000).toString();
    const sp = Object.assign({}, body, { access_token: token, app_key: APP_ID, timestamp: ts });
    const sign = LX.makeSign(sp, APP_ID, APP_SECRET);
    const qs = "access_token=" + encodeURIComponent(token) + "&app_key=" + encodeURIComponent(APP_ID) + "&timestamp=" + ts + "&sign=" + encodeURIComponent(sign);
    const r = https.request({ method: "POST", hostname: HOST, path: path + "?" + qs, headers: { "Content-Type": "application/json" }, timeout: 40000 }, p => {
      let b = ""; p.on("data", d => b += d);
      p.on("end", () => { try { res(JSON.parse(b)); } catch (e) { res({ raw: b.slice(0, 300) }); } });
    });
    r.on("error", e => res({ error: e.message }));
    r.on("timeout", () => { r.destroy(); res({ error: "timeout" }); });
    r.write(data); r.end();
  });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const dbFile = process.argv[2] || "db_records.json";
  const skuFile = process.argv[3] || "sku_records.json";
  const recs = JSON.parse(fs.readFileSync(dbFile, "utf8"));

  // SKU 批次明细的货件单号集合（对碰范围）
  const skuset = new Set();
  if (fs.existsSync(skuFile)) {
    JSON.parse(fs.readFileSync(skuFile, "utf8")).forEach(r => {
      String(r["货件单号"] || "").split("&").forEach(x => {
        const id = x.trim().toUpperCase();
        if (id) skuset.add(id);
      });
    });
  }

  // 主表货件号 ∩ SKU 明细货件号（按 & 拆开）
  const idset = new Set();
  recs.forEach(r => {
    String(r["FBA货件号"] || "").split("&").forEach(x => {
      const id = x.trim().toUpperCase();
      if (!id) return;
      if (skuset.size && !skuset.has(id)) return;   // 不在 SKU 明细范围内 → 不查
      if (/^FBA/i.test(id)) idset.add(id);
    });
  });
  const ids = [...idset];
  console.log("主表记录 %d 条 | SKU 明细货件号 %d 个 | 对碰范围内唯一亚马逊货件号 %d 个", recs.length, skuset.size, ids.length);
  if (!ids.length) { console.log("无可查货件号，退出"); return; }

  const token = await getToken();
  if (!token) { console.log("TOKEN FAIL"); return; }

  const found = new Map();
  let miss = 0, batches = 0;
  for (let i = 0; i < ids.length; i += CHUNK) {
    const chunk = ids.slice(i, i + CHUNK);
    const r = await post("/erp/sc/data/fba_report/shipmentList",
      { sid: SIDS, start_date: START, end_date: END, shipment_id: chunk.join(","), offset: 0, length: 1000 }, token);
    batches++;
    if (r.code !== 0) {
      console.log("  批次%d 失败 code=%s %s", batches, r.code, (r.message || r.raw || "").slice(0, 80));
    } else {
      const list = (r.data && r.data.list) || [];
      list.forEach(s => { if (s.shipment_id) found.set(String(s.shipment_id).trim(), s); });
      // 本批没返回的算未匹配
      chunk.forEach(id => { if (!found.has(id)) miss++; });
      console.log("  批次%d 请求%d个 返回%d条 累计命中%d", batches, chunk.length, list.length, found.size);
    }
    if (i + CHUNK < ids.length) await sleep(GAP);
  }

  const all = [...found.values()];
  fs.writeFileSync("lx_shipments.json", JSON.stringify(all));
  const st = {};
  all.forEach(s => { const k = s.shipment_status || "(空)"; st[k] = (st[k] || 0) + 1; });
  console.log("\n共 %d 批请求 | 命中 %d / 请求 %d | 未匹配 %d", batches, all.length, ids.length, miss);
  console.log("状态分布:", JSON.stringify(st));
})();