# -*- coding: utf-8 -*-
"""就地替换 shandi-v5/index.html 里的 window.__WH 数据（不改页面结构、不动 CRLF）"""
import io, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(BASE, "shandi-v5", "index.html")
SNAP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "wh_raw", "wh_snapshot.json")

html = io.open(IDX, encoding="utf-8", newline="").read()
snap = io.open(SNAP, encoding="utf-8").read().strip()

key = "window.__WH = "
i = html.find(key)
if i < 0:
    raise SystemExit("找不到 window.__WH")
start = i + len(key)
depth, in_str, esc = 0, False, False
j = start
while j < len(html):
    c = html[j]
    if in_str:
        if esc:
            esc = False
        elif c == "\\":
            esc = True
        elif c == '"':
            in_str = False
    else:
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
    j += 1
old = html[start:j + 1]
old_obj = json.loads(old)
new_obj = json.loads(snap)
out = html[:start] + snap + html[j + 1:]
io.open(IDX, "w", encoding="utf-8", newline="").write(out)
b = open(IDX, "rb").read()
print("__WH updatedAt: %s -> %s" % (old_obj.get("updatedAt"), new_obj.get("updatedAt")))
print("index.html bytes %d | crlf %d | lf-only %d" % (len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n")))
