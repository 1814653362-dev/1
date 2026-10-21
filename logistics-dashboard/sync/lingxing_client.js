/* ============================================================
 * 领星 Open API 前端直连客户端（纯浏览器实现，无需后端）
 * - 签名算法：排序拼接 → MD5(大写) → AES-128-ECB(key=appId) → base64
 * - 调用方式：XHR（绕过看板内置的 mock fetch）
 * - 域名：https://openapi.lingxing.com
 * 仅在浏览器中访问时生效；node 仅用于离线校验。
 * ============================================================ */
(function (root) {
  "use strict";

  var LX = {};

  /* ---------- MD5（紧凑实现，public domain 风格） ---------- */
  function md5(s) {
    function add32(a, b) { return (a + b) & 0xffffffff; }
    function cmn(q, a, b, x, s, t) {
      a = add32(add32(a, q), add32(x, t));
      return add32((a << s) | (a >>> (32 - s)), b);
    }
    function ff(a, b, c, d, x, s, t) { return cmn((b & c) | (~b & d), a, b, x, s, t); }
    function gg(a, b, c, d, x, s, t) { return cmn((b & d) | (c & ~d), a, b, x, s, t); }
    function hh(a, b, c, d, x, s, t) { return cmn(b ^ c ^ d, a, b, x, s, t); }
    function ii(a, b, c, d, x, s, t) { return cmn(c ^ (b | ~d), a, b, x, s, t); }
    function md5cycle(x, k) {
      var a = x[0], b = x[1], c = x[2], d = x[3];
      a = ff(a, b, c, d, k[0], 7, -680876936); d = ff(d, a, b, c, k[1], 12, -389564586);
      c = ff(c, d, a, b, k[2], 17, 606105819); b = ff(b, c, d, a, k[3], 22, -1044525330);
      a = ff(a, b, c, d, k[4], 7, -176418897); d = ff(d, a, b, c, k[5], 12, 1200080426);
      c = ff(c, d, a, b, k[6], 17, -1473231341); b = ff(b, c, d, a, k[7], 22, -45705983);
      a = ff(a, b, c, d, k[8], 7, 1770035416); d = ff(d, a, b, c, k[9], 12, -1958414417);
      c = ff(c, d, a, b, k[10], 17, -42063); b = ff(b, c, d, a, k[11], 22, -1990404162);
      a = ff(a, b, c, d, k[12], 7, 1804603682); d = ff(d, a, b, c, k[13], 12, -40341101);
      c = ff(c, d, a, b, k[14], 17, -1502002290); b = ff(b, c, d, a, k[15], 22, 1236535329);
      a = gg(a, b, c, d, k[1], 5, -165796510); d = gg(d, a, b, c, k[6], 9, -1069501632);
      c = gg(c, d, a, b, k[11], 14, 643717713); b = gg(b, c, d, a, k[0], 20, -373897302);
      a = gg(a, b, c, d, k[5], 5, -701558691); d = gg(d, a, b, c, k[10], 9, 38016083);
      c = gg(c, d, a, b, k[15], 14, -660478335); b = gg(b, c, d, a, k[4], 20, -405537848);
      a = gg(a, b, c, d, k[9], 5, 568446438); d = gg(d, a, b, c, k[14], 9, -1019803690);
      c = gg(c, d, a, b, k[3], 14, -187363961); b = gg(b, c, d, a, k[8], 20, 1163531501);
      a = gg(a, b, c, d, k[13], 5, -1444681467); d = gg(d, a, b, c, k[2], 9, -51403784);
      c = gg(c, d, a, b, k[7], 14, 1735328473); b = gg(b, c, d, a, k[12], 20, -1926607734);
      a = hh(a, b, c, d, k[5], 4, -378558); d = hh(d, a, b, c, k[8], 11, -2022574463);
      c = hh(c, d, a, b, k[11], 16, 1839030562); b = hh(b, c, d, a, k[14], 23, -35309556);
      a = hh(a, b, c, d, k[1], 4, -1530992060); d = hh(d, a, b, c, k[4], 11, 1272893353);
      c = hh(c, d, a, b, k[7], 16, -155497632); b = hh(b, c, d, a, k[10], 23, -1094730640);
      a = hh(a, b, c, d, k[13], 4, 681279174); d = hh(d, a, b, c, k[0], 11, -358537222);
      c = hh(c, d, a, b, k[3], 16, -722521979); b = hh(b, c, d, a, k[6], 23, 76029189);
      a = hh(a, b, c, d, k[9], 4, -640364487); d = hh(d, a, b, c, k[12], 11, -421815835);
      c = hh(c, d, a, b, k[15], 16, 530742520); b = hh(b, c, d, a, k[2], 23, -995338651);
      a = ii(a, b, c, d, k[0], 6, -198630844); d = ii(d, a, b, c, k[7], 10, 1126891415);
      c = ii(c, d, a, b, k[14], 15, -1416354905); b = ii(b, c, d, a, k[5], 21, -57434055);
      a = ii(a, b, c, d, k[12], 6, 1700485571); d = ii(d, a, b, c, k[3], 10, -1894986606);
      c = ii(c, d, a, b, k[10], 15, -1051523); b = ii(b, c, d, a, k[1], 21, -2054922799);
      a = ii(a, b, c, d, k[8], 6, 1873313359); d = ii(d, a, b, c, k[15], 10, -30611744);
      c = ii(c, d, a, b, k[6], 15, -1560198380); b = ii(b, c, d, a, k[13], 21, 1309151649);
      a = ii(a, b, c, d, k[4], 6, -145523070); d = ii(d, a, b, c, k[11], 10, -1120210379);
      c = ii(c, d, a, b, k[2], 15, 718787259); b = ii(b, c, d, a, k[9], 21, -343485551);
      x[0] = add32(a, x[0]); x[1] = add32(b, x[1]); x[2] = add32(c, x[2]); x[3] = add32(d, x[3]);
    }
    function md5blk(s) {
      var md5blks = [], i;
      for (i = 0; i < 64; i += 4) {
        md5blks[i >> 2] = s.charCodeAt(i) + (s.charCodeAt(i + 1) << 8) + (s.charCodeAt(i + 2) << 16) + (s.charCodeAt(i + 3) << 24);
      }
      return md5blks;
    }
    function md5blk_array(a) {
      var md5blks = [], i;
      for (i = 0; i < 64; i += 4) {
        md5blks[i >> 2] = a[i] + (a[i + 1] << 8) + (a[i + 2] << 16) + (a[i + 3] << 24);
      }
      return md5blks;
    }
    function md51(s) {
      var n = s.length, state = [1732584193, -271733879, -1732584194, 271733878], i;
      for (i = 64; i <= n; i += 64) md5cycle(state, md5blk(s.substring(i - 64, i)));
      s = s.substring(64 * (n >> 6));
      var tail = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
      for (i = 0; i < s.length; i += 1) tail[i >> 2] |= s.charCodeAt(i) << ((i % 4) << 3);
      tail[i >> 2] |= 128 << ((i % 4) << 3);
      if (i > 55) { md5cycle(state, tail); for (i = 0; i < 16; i += 1) tail[i] = 0; }
      tail[14] = n * 8;
      md5cycle(state, tail);
      return state;
    }
    function rhex(n) {
      var hexch = "0123456789abcdef".split(""), r = "", j = 0;
      for (; j < 4; j += 1) { r += hexch[(n >> (j * 8 + 4)) & 15] + hexch[(n >> (j * 8)) & 15]; }
      return r;
    }
    return rhex(md51(s)[0]) + rhex(md51(s)[1]) + rhex(md51(s)[2]) + rhex(md51(s)[3]);
  }
  LX.md5 = md5;

  /* ---------- AES-128-ECB（标准 S-box + 正确密钥扩展，PKCS7 填充） ---------- */
  var SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16
  ];
  var XTIME = []; for (var t = 0; t < 256; t++) XTIME[t] = (t << 1) ^ (((t >> 7) & 1) * 283);

  // 密钥扩展：w 为 44 个 4 字节字（列主序，与 FIPS / OpenSSL 一致）
  function keyExpansion(key) {
    var w = [], j;
    for (j = 0; j < 4; j++) w.push([key[4 * j], key[4 * j + 1], key[4 * j + 2], key[4 * j + 3]]);
    var Rcon = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36];
    for (var i = 4; i < 44; i++) {
      var t = w[i - 1].slice();
      if (i % 4 === 0) {
        t = [t[1], t[2], t[3], t[0]];                                   // RotWord
        t = [SBOX[t[0]], SBOX[t[1]], SBOX[t[2]], SBOX[t[3]]];           // SubWord
        t[0] ^= Rcon[(i / 4) - 1];
      }
      w.push([w[i - 4][0] ^ t[0], w[i - 4][1] ^ t[1], w[i - 4][2] ^ t[2], w[i - 4][3] ^ t[3]]);
    }
    return w;
  }

  // AES-128-ECB：state 按列主序处理（字节 i -> state[i%4][floor(i/4)]），与 OpenSSL 字节序一致
  function aesEcbEncrypt(keyBytes16, plaintext) {
    var Nr = 10, w = keyExpansion(keyBytes16), out = [], blk, row, col;
    for (blk = 0; blk < plaintext.length; blk += 16) {
      var s = [];
      for (row = 0; row < 4; row++) { s[row] = []; for (col = 0; col < 4; col++) s[row][col] = plaintext[blk + col * 4 + row]; }
      for (row = 0; row < 4; row++) for (col = 0; col < 4; col++) s[row][col] ^= w[col][row]; // AddRoundKey(0)
      for (var rnd = 1; rnd <= Nr; rnd++) {
        for (row = 0; row < 4; row++) for (col = 0; col < 4; col++) s[row][col] = SBOX[s[row][col]]; // SubBytes
        for (row = 0; row < 4; row++) { var tmp = [s[row][0], s[row][1], s[row][2], s[row][3]]; for (col = 0; col < 4; col++) s[row][col] = tmp[(col + row) % 4]; } // ShiftRows
        if (rnd < Nr) {
          for (col = 0; col < 4; col++) {
            var a = s[0][col], b = s[1][col], c = s[2][col], d = s[3][col];
            s[0][col] = XTIME[a] ^ (XTIME[b] ^ b) ^ c ^ d;
            s[1][col] = a ^ XTIME[b] ^ (XTIME[c] ^ c) ^ d;
            s[2][col] = a ^ b ^ XTIME[c] ^ (XTIME[d] ^ d);
            s[3][col] = (XTIME[a] ^ a) ^ b ^ c ^ XTIME[d];
          }
        }
        for (row = 0; row < 4; row++) for (col = 0; col < 4; col++) s[row][col] ^= w[4 * rnd + col][row]; // AddRoundKey(rnd)
      }
      for (var i = 0; i < 16; i++) out.push(s[i % 4][(i / 4) | 0]);
    }
    return out;
  }
  LX.aesEcb = aesEcbEncrypt;

  /* ---------- 领星签名 ---------- */
  LX.makeSign = function (paramsObj, appId, appSecret) {
    var keys = Object.keys(paramsObj).filter(function (k) { return paramsObj[k] !== "" && paramsObj[k] !== null && paramsObj[k] !== undefined; });
    keys.sort();
    var raw = keys.map(function (k) { return k + "=" + paramsObj[k]; }).join("&");
    var m = md5(raw).toUpperCase();
    var keyB = []; for (var i = 0; i < 16; i++) keyB.push(appId.charCodeAt(i) & 255);
    var plain = []; for (i = 0; i < m.length; i++) plain.push(m.charCodeAt(i) & 255);
    // PKCS7 pad to multiple of 16
    var pad = 16 - (plain.length % 16); if (pad === 0) pad = 16;
    for (i = 0; i < pad; i++) plain.push(pad);
    var enc = aesEcbEncrypt(keyB, plain);
    // base64
    var bin = ""; for (i = 0; i < enc.length; i++) bin += String.fromCharCode(enc[i]);
    return btoa(bin);
  };

  /* ---------- 领星请求（XHR，绕过 mock fetch） ---------- */
  LX.BASE = "https://openapi.lingxing.com";

  LX.call = function (path, params, appId, appSecret) {
    return new Promise(function (resolve, reject) {
      var ts = Math.floor(Date.now() / 1000).toString();
      var sign = LX.makeSign(params, appId, appSecret);
      var q = "access_token=" + encodeURIComponent(params.access_token) +
              "&app_key=" + encodeURIComponent(appId) +
              "&timestamp=" + ts +
              "&sign=" + encodeURIComponent(sign);
      var url = LX.BASE + path + "?" + q;
      var xhr = new XMLHttpRequest();
      xhr.open("POST", url, true);
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
          try { resolve(JSON.parse(xhr.responseText)); }
          catch (e) { reject(new Error("解析失败: " + xhr.responseText)); }
        }
      };
      xhr.onerror = function () { reject(new Error("网络错误（可能被领星 IP 白名单拦截，或网络不通）")); };
      xhr.send(JSON.stringify(stripSignParams(params)));
    });
  };

  function stripSignParams(p) {
    var c = {}; Object.keys(p).forEach(function (k) { if (k !== "access_token" && k !== "app_key" && k !== "timestamp" && k !== "sign") c[k] = p[k]; });
    return c;
  }

  LX.getToken = function (appId, appSecret) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", LX.BASE + "/api/auth-server/oauth/access-token", true);
      xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
      xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
          try {
            var d = JSON.parse(xhr.responseText);
            if (d.code === "200" || d.code === 200) resolve(d.data.access_token);
            else reject(new Error("获取 token 失败: " + d.msg));
          } catch (e) { reject(new Error("解析 token 失败")); }
        }
      };
      xhr.onerror = function () { reject(new Error("网络错误（获取 token 失败）")); };
      xhr.send("appId=" + encodeURIComponent(appId) + "&appSecret=" + encodeURIComponent(appSecret));
    });
  };

  /* ---------- 拉取并映射为 window.__PLAN_BASE ---------- */
  LX.syncPlanBase = function (appId, appSecret, days) {
    days = days || 14;
    var end = new Date();
    var start = new Date(end.getTime() - (days - 1) * 86400000);
    function fmt(d) { return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()); }
    function pad2(n) { return (n < 10 ? "0" : "") + n; }
    var sd = fmt(start), ed = fmt(end);

    return LX.getToken(appId, appSecret).then(function (token) {
      // 1) 销量（按店铺·日）
      var salesParams = { start_date: sd, end_date: ed, data_type: "6", result_type: "1", date_unit: "4", page: 1, length: 50, access_token: token, app_key: appId, timestamp: Math.floor(Date.now() / 1000).toString() };
      return LX.call("/basicOpen/platformStatisticsV2/saleStat/pageList", salesParams, appId, appSecret).then(function (salesRes) {
        if (salesRes.code !== 0 && salesRes.code !== "0") throw new Error("销量接口错误: " + salesRes.msg);
        var shops = (salesRes.data || []).map(function (s) {
          var dc = s.date_collect || {};
          var total = 0; Object.keys(dc).forEach(function (k) { total += Number(dc[k]) || 0; });
          return { name: (s.store_name && s.store_name[0]) || ("sid:" + (s.sid && s.sid[0])), daily: dc, total: total };
        });
        var dateSet = {}; shops.forEach(function (s) { Object.keys(s.daily).forEach(function (k) { dateSet[k] = 1; }); });
        var dates = Object.keys(dateSet).sort();
        var salesTotal = shops.reduce(function (a, s) { return a + s.total; }, 0);

        // 2) FBA 库存（分页聚合，按店铺）
        return fetchFba(token, appId, appSecret).then(function (fba) {
          return {
            updatedAt: fmt(end),
            sales: { range: sd + " ~ " + ed, dates: dates, shops: shops, total: salesTotal },
            stock: fba,
            source: "领星 ERP 实时接口（" + fmt(end) + " 拉取）"
          };
        });
      });
    });
  };

  function fetchFba(token, appId, appSecret) {
    var COLS = ["FBA可售", "FBA实际在途", "FBA入库中", "FBA总库存", "AWD可用量(成本)"];
    var agg = {}; // name -> [可售, 在途, 入库中, 总库存, AWD]
    var TOTAL = [0, 0, 0, 0, 0];
    function addRow(r) {
      var name = r.seller_group_name || (r.name) || "未命名店铺";
      if (!agg[name]) agg[name] = [0, 0, 0, 0, 0];
      var v = agg[name];
      v[0] += Number(r.afn_fulfillable_quantity) || 0;
      v[1] += Number(r.afn_inbound_shipped_quantity) || 0;
      v[2] += Number(r.afn_inbound_receiving_quantity) || 0;
      v[3] += Number(r.total) || 0;
      // AWD 暂未在该接口出参，置 0（需另接 AWD 报表）
      for (var i = 0; i < 4; i++) TOTAL[i] += v[i];
    }
    function page(offset, length) {
      var p = { offset: offset, length: length, is_hide_zero_stock: "0", access_token: token, app_key: appId, timestamp: Math.floor(Date.now() / 1000).toString() };
      return LX.call("/basicOpen/openapi/storage/fbaWarehouseDetail", p, appId, appSecret).then(function (res) {
        if (res.code !== 0 && res.code !== "0") throw new Error("FBA接口错误: " + res.msg);
        (res.data || []).forEach(addRow);
        var total = res.total || 0;
        if (offset + length < total) return page(offset + length, length);
        return null;
      });
    }
    return page(0, 5000).then(function () {
      var rows = Object.keys(agg).map(function (n) { return { name: n, vals: agg[n] }; });
      return { asAt: fmt(new Date()), cols: COLS, rows: rows, totalRow: { name: "合计", vals: TOTAL }, note: "AWD可用量(成本) 该接口暂未返回，置 0；其余为领星 FBA 库存实时聚合（按 seller_group_name 汇总）" };
    });
  }

  if (typeof module !== "undefined" && module.exports) module.exports = LX;
  if (typeof window !== "undefined") window.LX = LX;
})(typeof window !== "undefined" ? window : this);
