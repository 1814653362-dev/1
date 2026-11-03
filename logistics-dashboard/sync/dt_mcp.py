# -*- coding: utf-8 -*-
"""钉钉 AI 表格（官方 dingtalk-mcp）Python 调用客户端 —— 复用 stdio 握手。

运行时路径**自动发现**（不写死本机路径，计划任务里也能跑）：
    DINGTALK_TOOLS_DIR  运行时根目录（默认从本文件位置往上找 <activeDataDir>/tools）
    DINGTALK_NODE       node 可执行文件（默认 <tools>/node-*/node.exe）
    DINGTALK_MCP_CLI    dingtalk-mcp 的 dist/cli.js（默认 <tools>/dingtalk-mcp/node_modules/…）
    DINGTALK_ENV_FILE   凭据 .env（默认 <tools>/dingtalk-mcp/.env）
    DINGTALK_OPERATOR_ID / DINGTALK_BASE_ID  钉钉 unionId / AI 表格 baseId
"""
import glob, json, os, subprocess, sys, threading, time

sys.stdout.reconfigure(encoding="utf-8")


def _tools_dir():
    env = os.environ.get("DINGTALK_TOOLS_DIR")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for up in range(1, 7):
        p = here
        for _ in range(up):
            p = os.path.dirname(p)
        cand = os.path.join(p, "tools")
        if os.path.isdir(cand):
            return cand
    return os.path.join(here, "tools")


TOOLS = _tools_dir()


def _find_node():
    env = os.environ.get("DINGTALK_NODE")
    if env:
        return env
    hits = sorted(glob.glob(os.path.join(TOOLS, "node-*", "node.exe")))
    return hits[0] if hits else "node"


def _find_cli():
    env = os.environ.get("DINGTALK_MCP_CLI")
    if env:
        return env
    hits = sorted(glob.glob(os.path.join(TOOLS, "dingtalk-mcp", "node_modules",
                                         "dingtalk-mcp", "dist", "cli.js")))
    return hits[0] if hits else ""


def _env_file():
    return os.environ.get("DINGTALK_ENV_FILE",
                           os.path.join(TOOLS, "dingtalk-mcp", ".env"))


NODE = _find_node()
CLI = _find_cli()

OPERATOR = os.environ.get("DINGTALK_OPERATOR_ID", "")   # 操作人 unionId（必填）
BASE = os.environ.get("DINGTALK_BASE_ID", "")            # AI 表格 baseId（必填）
# 各数据表 id 也走环境变量：主表 DINGTALK_SHEET_ID，其余按需加 DINGTALK_SHEET_ID_2…
SHEETS = {}


def _creds():
    """从 .env 读凭据（不在代码里硬编码）。"""
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(NODE) + os.pathsep + env.get("PATH", "")
    env.setdefault("ACTIVE_PROFILES", "dingtalk-notable,dingtalk-contacts")
    f = _env_file()
    if f and os.path.exists(f):
        for line in io_lines(f):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())
    return env


def io_lines(path):
    import io
    return io.open(path, encoding="utf-8", errors="replace").read().splitlines()


class DingTable:
    def __init__(self, operator=OPERATOR, base=BASE):
        self.operator = operator
        self.base = base
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

    # ---- 便捷方法 ----
    def sheets(self):
        r = self.call("getNotableAllSheets", {"operatorId": self.operator, "baseId": self.base})
        return r.get("value") if isinstance(r, dict) else r

    def fields(self, sheet):
        r = self.call("getNotableAllFields", {"operatorId": self.operator, "baseId": self.base,
                                              "sheetIdOrName": sheet})
        return r.get("value") if isinstance(r, dict) else r

    def records(self, sheet, max_results=100, timeout=90):
        """分页拉全部记录。"""
        rows, token = [], None
        for _ in range(60):
            args = {"operatorId": self.operator, "baseId": self.base, "sheetIdOrName": sheet,
                    "maxResults": max_results}
            if token:
                args["nextToken"] = token
            r = self.call("listNotableRecords", args, timeout=timeout)
            if not isinstance(r, dict):
                return rows, r
            rs = r.get("records") or []
            rows.extend(rs)
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
                          "sheetIdOrName": sheet, "recordIds": list(record_ids)}, timeout=180)

    def close(self):
        try:
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass
