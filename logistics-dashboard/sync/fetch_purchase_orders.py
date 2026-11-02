# -*- coding: utf-8 -*-
"""拉领星采购单列表（purchaseOrderList）并落盘。
用于「最近3批已到货采购单的采购单价」。

接口：POST /erp/sc/routing/data/local_inventory/purchaseOrderList
参数：start_date/end_date（必填，双闭区间）、search_field_time(create_time)、
      order_sn[]、custom_order_sn[]、purchase_type、offset、length(≤500)
返回：data[] 采购单，含 status_shipped(1未到货/2部分到货/3全部到货)、
      item_list[]（sku/msku/spu/spu_name/price 含税单价/quantity_real/
      quantity_entry 到货入库量/quantity_receive 待到货量/first_receive_time…）
"""
import base64, hashlib, io, json, os, sys, time, urllib.parse, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE = os.path.dirname(os.path.abspath(__file__))
APP_ID = os.environ.get("LX_APP_ID", "")
APP_SECRET = os.environ.get("LX_APP_SECRET", "")
if not APP_ID or not APP_SECRET:
    raise SystemExit("缺少领星凭据：请设置环境变量 LX_APP_ID / LX_APP_SECRET（见 .env.example）")
API = "https://openapi.lingxing.com"
EP = "/erp/sc/routing/data/local_inventory/purchaseOrderList"
OUT = os.path.join(BASE, "wh_raw", "purchase_orders.json")

MONTHS_BACK = int(sys.argv[1]) if len(sys.argv) > 1 else 9


def _md5_upper(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest().upper()


def _aes_ecb_b64(plain, key):
    pad = padding.PKCS7(128).padder()
    data = pad.update(plain.encode("utf-8")) + pad.finalize()
    c = Cipher(algorithms.AES(key.encode("utf-8")), modes.ECB()).encryptor()
    return base64.b64encode(c.update(data) + c.finalize()).decode("ascii")


def get_token():
    body = urllib.parse.urlencode({"appId": APP_ID, "appSecret": APP_SECRET})
    req = urllib.request.Request(API + "/api/auth-server/oauth/access-token", data=body.encode("utf-8"),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))["data"]["access_token"]


def call(token, params, tries=4):
    ts = str(int(time.time()))
    sp = dict(params)
    sp["access_token"] = token
    sp["app_key"] = APP_ID
    sp["timestamp"] = ts
    raw = "&".join("%s=%s" % (k, sp[k]) for k in sorted(sp.keys()))
    sign = _aes_ecb_b64(_md5_upper(raw), APP_ID)
    qs = urllib.parse.urlencode({"access_token": token, "app_key": APP_ID, "timestamp": ts, "sign": sign})
    data = json.dumps(params, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + EP + "?" + qs, data=data, headers={"Content-Type": "application/json"})
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
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


tok = get_token()
print("token OK")

import datetime
today = datetime.date.today()
start = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
for _ in range(MONTHS_BACK - 1):
    start = (start - datetime.timedelta(days=1)).replace(day=1)
end = today
print("窗口: %s ~ %s (create_time)" % (start, end))

allrows = []
total = None
offset = 0
while True:
    r = call(tok, {"search_field_time": "create_time",
                   "start_date": start.isoformat(), "end_date": end.isoformat(),
                   "offset": offset, "length": 500})
    if str(r.get("code")) not in ("0", "0.0"):
        print("ERR", r.get("code"), r.get("message"))
        raise SystemExit(1)
    if total is None:
        total = r.get("total")
        print("total =", total)
    rows = r.get("data") or []
    if not rows:
        break
    allrows.extend(rows)
    print("  fetched", len(allrows))
    if total is not None and len(allrows) >= total:
        break
    offset = len(allrows)
    if len(allrows) > 40000:
        break
    time.sleep(0.3)

print("rows =", len(allrows))
if allrows:
    print("keys =", ",".join(sorted(allrows[0].keys())))
    it = (allrows[0].get("item_list") or [{}])[0]
    print("item keys =", ",".join(sorted(it.keys())))
    print("sample =", json.dumps(allrows[0], ensure_ascii=False)[:1200])

io.open(OUT, "w", encoding="utf-8", newline="").write(json.dumps(allrows, ensure_ascii=False))
print("saved ->", OUT, os.path.getsize(OUT), "bytes")
