# -*- coding: utf-8 -*-
"""钉钉 AI 表格（Notable）MCP 客户端 —— stdio 握手 + 工具调用封装。

依赖官方 npm 包 dingtalk-mcp：
    npx -y dingtalk-mcp@latest
本脚本负责以 stdio 方式拉起它，并把工具返回值（result.content[0].text 里的 JSON 字符串）解析成 dict。

环境变量：
    DINGTALK_NODE        node 可执行文件路径（默认 "node"）
    DINGTALK_MCP_CLI     dingtalk-mcp 的 dist/cli.js 路径
    DINGTALK_CLIENT_ID   钉钉应用 Client ID
    DINGTALK_CLIENT_SECRET 钉钉应用 Client Secret
    DINGTALK_ENV_FILE    .env 文件路径（可选）
    DINGTALK_BASE_ID     AI 表格 baseId
    DINGTALK_OPERATOR_ID 操作人 unionId
    DINGTALK_SHEET_ID    数据表 id
"""
import json, os, subprocess, sys, threading, time

sys.stdout.reconfigure(encoding="utf-8")

NODE = os.environ.get("DINGTALK_NODE", "node")
CLI = os.environ.get("DINGTALK_MCP_CLI", "")

OPERATOR = os.environ.get("DINGTALK_OPERATOR_ID", "")
BASE = os.environ.get("DINGTALK_BASE_ID", "")
SHEET_ID = os.environ.get("DINGTALK_SHEET_ID", "")


def _creds():
    env = dict(os.environ)
    env.setdefault("ACTIVE_PROFILES", "dingtalk-notable,dingtalk-contacts")
    f = os.environ.get("DINGTALK_ENV_FILE", "")
    if f and os.path.exists(f):
        for line in io.open(f, encoding="utf-8", errors="replace").read().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())
    return env


class DingTable:
    def __init__(self, operator=None, base=None):
        self.operator = operator or OPERATOR
        self.base = base or BASE
        if not self.operator or not self.base:
            raise RuntimeError("缺少 DINGTALK_OPERATOR_ID / DINGTALK_BASE_ID 环境变量")
        self.p = subprocess.Popen([NODE, CLI], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=_creds(), text=True, encoding="utf-8", bufsize=1)
        self.out = []
        threading.Thread(target=self._pump, args=(self.p.stdout, self.out), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.p.stderr, []), daemon=True).start()
        self._id = 0
        self._send({"jsonrpc": "2.0", "id": self._next(), "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "dt_client", "version": "1.0"}}})
        time.sleep(2.5)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    @staticmethod
    def _pump(stream, sink):
        for line in stream:
            sink.append(line.rstrip())

    def _next(self):
        self._id += 1
        return self._id

    def _send(self, o):
        self.p.stdin.write(json.dumps(o, ensure_ascii=False) + "\n")
        self.p.stdin.flush()

    def _wait(self, want, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            for l in list(self.out):
                try:
                    j = json.loads(l)
                except Exception:
                    continue
                if j.get("id") == want:
                    return j
            time.sleep(0.3)
        return None

    def call(self, name, args, timeout=60):
        i = self._next()
        self._send({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                    "params": {"name": name, "arguments": args}})
        r = self._wait(i, timeout)
        if not r:
            return {"_error": "timeout"}
        try:
            t = r["result"]["content"][0]["text"]
        except Exception:
            return r
        try:
            return json.loads(t)
        except Exception:
            return t

    def sheets(self):
        r = self.call("getNotableAllSheets", {"operatorId": self.operator, "baseId": self.base})
        return r.get("value") if isinstance(r, dict) else r

    def fields(self, sheet):
        r = self.call("getNotableAllFields", {"operatorId": self.operator, "baseId": self.base,
                                              "sheetIdOrName": sheet})
        return r.get("value") if isinstance(r, dict) else r

    def records(self, sheet, max_results=100, timeout=90):
        rows, token = [], None
        for _ in range(60):
            args = {"operatorId": self.operator, "baseId": self.base, "sheetIdOrName": sheet,
                    "maxResults": max_results}
            if token:
                args["nextToken"] = token
            r = self.call("listNotableRecords", args, timeout=timeout)
            if not isinstance(r, dict):
                return rows, r
            rows.extend(r.get("records") or [])
            token = r.get("nextToken")
            if not r.get("hasMore") or not token:
                break
        return rows, None

    def insert(self, sheet, records):
        return self.call("insertNotableRecords",
                         {"operatorId": self.operator, "baseId": self.base,
                          "sheetIdOrName": sheet, "records": records}, timeout=180)

    def update(self, sheet, records):
        return self.call("updateNotableRecords",
                         {"operatorId": self.operator, "baseId": self.base,
                          "sheetIdOrName": sheet, "records": records}, timeout=180)

    def delete(self, sheet, record_ids):
        return self.call("deleteNotableRecords",
                         {"operatorId": self.operator, "baseId": self.base,
                          "sheetIdOrName": sheet, "recordIds": record_ids}, timeout=180)

    def close(self):
        try:
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass
