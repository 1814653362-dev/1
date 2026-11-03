# -*- coding: utf-8 -*-
"""领星库存分类账（日维度）拉取器 —— 只保留需要的字段，按月缓存。

用途：为「库龄 × 款号」矩阵提供**历史趋势**数据源。
分类账每天给每 SKU 的期初/期末仓库余额 + 入库/出库流水，
由此可重建任意历史时点的在库数量（SELLABLE 可售 / 全部状态总库存）。

签名口径照抄 fetch_ledger.ps1：
  raw = 按 key 升序拼 "k=v&k=v"（sellerIds 是 JSON 数组字符串）
  sign = base64( AES-128-ECB-PKCS7( MD5_upper(raw), key=app_id ) )
  URL query = access_token / app_key / timestamp / sign

落盘：wh_raw/ledger_cache/YYYY-MM.json（按月缓存，重跑只补新月份）
"""
import base64
import datetime
import hashlib
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
APP_ID = os.environ.get("LX_APP_ID", "")
APP_SECRET = os.environ.get("LX_APP_SECRET", "")
if not APP_ID or not APP_SECRET:
    raise SystemExit("缺少领星凭据：请设置环境变量 LX_APP_ID / LX_APP_SECRET（见 .env.example）")
API = "https://openapi.lingxing.com"
EP = "/cost/center/ods/summary/query"
# 领星店铺 ID（sellerId）列表：从环境变量读取，逗号分隔。
# 取不到时退化为占位值（脚本仍可运行，但接口查询会返回空）——按自己账号填 .env。
SELLERS = [s.strip() for s in os.environ.get(
    "LX_SELLER_IDS", "SELLER_ID_PLACEHOLDER,SELLER_ID_PLACEHOLDER,SELLER_ID_PLACEHOLDER,"
                     "SELLER_ID_PLACEHOLDER,SELLER_ID_PLACEHOLDER,SELLER_ID_PLACEHOLDER").split(",")
           if s.strip()]
CACHE = os.path.join(BASE, "wh_raw", "ledger_cache")

# 每条记录保留的字段（顺序固定）—— 左边是缓存字段名，右边是接口原始字段名
FIELDS = [("start", "startingWarehouseBalance"), ("end", "endingWareHouseBalance"),
          ("receipts", "receipts"), ("cShip", "customerShipments"),
          ("cRet", "customerReturns"), ("vRet", "vendorReturns"), ("found", "found"),
          ("disposed", "disposed"), ("damaged", "damaged"), ("lost", "lost"),
          ("transfer", "warehouseTransferInOrOut")]
FIELD_KEYS = [k for k, _ in FIELDS]


def _md5_upper(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest().upper()


def _aes_ecb_b64(plain, key):
    pad = padding.PKCS7(128).padder()
    data = pad.update(plain.encode("utf-8")) + pad.finalize()
    c = Cipher(algorithms.AES(key.encode("utf-8")), modes.ECB()).encryptor()
    return base64.b64encode(c.update(data) + c.finalize()).decode("ascii")


def get_token():
    body = urllib.parse.urlencode({"appId": APP_ID, "appSecret": APP_SECRET})
    req = urllib.request.Request(
        API + "/api/auth-server/oauth/access-token", data=body.encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))["data"]["access_token"]


def call(token, params, tries=4):
    ts = str(int(time.time()))
    sp = {"sellerIds": json.dumps(SELLERS, separators=(",", ":"))}
    sp.update(params)
    sp["access_token"] = token
    sp["app_key"] = APP_ID
    sp["timestamp"] = ts
    raw = "&".join("%s=%s" % (k, sp[k]) for k in sorted(sp.keys()))
    sign = _aes_ecb_b64(_md5_upper(raw), APP_ID)
    qs = urllib.parse.urlencode({
        "access_token": token, "app_key": APP_ID,
        "timestamp": ts, "sign": sign})
    data = json.dumps({"sellerIds": SELLERS, **params},
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + EP + "?" + qs, data=data,
                                 headers={"Content-Type": "application/json"})
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.loads(r.read().decode("utf-8"))
            if str(out.get("code")) == "103":
                time.sleep(3 * (i + 1))
                last = "rate-limited"
                continue
            return out
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
            time.sleep(3 * (i + 1))
    raise RuntimeError("接口连续失败: %s" % last)


def month_days(y, m):
    d = datetime.date(y, m, 1)
    nxt = datetime.date(y + (m == 12), (m % 12) + 1, 1)
    out = []
    while d < nxt:
        out.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return out


def fetch_month(token, y, m, asof=None):
    """拉一个月日维度（全 disposition），边拉边聚合成 day -> {key: [fields]}"""
    agg = {}
    off = 0
    total = None
    days = month_days(y, m)
    start = days[0]
    end = days[-1]
    if asof and asof < end:
        end = asof
    while True:
        p = {"queryType": 2, "startDate": start,
             "endDate": end, "offset": off, "length": 1000}
        r = call(token, p)
        if str(r.get("code")) != "1":
            raise RuntimeError("月 %04d-%02d offset %d params=%s resp=%s"
                               % (y, m, off, p, json.dumps(r, ensure_ascii=False)[:400]))
        recs = (r.get("data") or {}).get("records") or []
        total = (r.get("data") or {}).get("total", 0)
        for x in recs:
            d = str(x.get("date") or "")
            if not d:
                continue
            key = "%s|%s|%s" % (x.get("msku") or "", x.get("disposition") or "",
                                x.get("location") or "")
            vals = [x.get(raw) for _, raw in FIELDS]
            slot = agg.setdefault(d, {})
            if key in slot:
                old = slot[key]
                slot[key] = [a + (b or 0) if isinstance(a, (int, float)) and isinstance(b, (int, float))
                             else b for a, b in zip(old, vals)]
            else:
                slot[key] = vals
        off += len(recs)
        if not recs or off >= total:
            break
        time.sleep(0.15)
    print("   %04d-%02d  原始 %s 条 -> 聚合 %d 天" % (y, m, total, len(agg)))
    return {"month": "%04d-%02d" % (y, m), "days": agg}


def main():
    asof = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    months = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    d0 = datetime.date.fromisoformat(asof)
    # 窗口：asof 往前 months 个月（当月只拉到 asof）
    want = []
    y, m = d0.year, d0.month
    for _ in range(months):
        want.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    want.reverse()

    if not os.path.isdir(CACHE):
        os.makedirs(CACHE)
    token = get_token()
    merged = {}
    for (y, m) in want:
        mp = os.path.join(CACHE, "%04d-%02d.json" % (y, m))
        cur_month = (y, m) == (d0.year, d0.month)
        if os.path.exists(mp):
            old = json.load(io.open(mp, encoding="utf-8"))
            # 当月缓存可能不完整（上次跑得早），重拉；历史月直接用
            if not cur_month:
                merged.update(old.get("days") or {})
                print("   %04d-%02d  用缓存" % (y, m))
                continue
        days = month_days(y, m)
        obj = fetch_month(token, y, m, asof if cur_month else None)
        json.dump(obj, io.open(mp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        merged.update(obj.get("days") or {})
    # 合并缓存里**所有**月份（窗口往前滚时历史不能被截断）
    for fn in sorted(os.listdir(CACHE)):
        if not fn.endswith(".json"):
            continue
        obj = json.load(io.open(os.path.join(CACHE, fn), encoding="utf-8"))
        merged.update(obj.get("days") or {})

    out = os.path.join(BASE, "wh_raw", "ledger_events.json")
    json.dump({"asOf": asof, "days": merged},
              io.open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    n = sum(len(v) for v in merged.values())
    print("合并 %d 天 / %d 条 -> %s (%.1f KB)" % (len(merged), n, out, os.path.getsize(out) / 1024))


if __name__ == "__main__":
    main()
