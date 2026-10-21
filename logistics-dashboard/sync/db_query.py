#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分页拉取看板数据库记录（含 record_id），输出 JSON。"""
import argparse, json, sys
from pathlib import Path

LIB = Path(r"C:/Users/1/.workbuddy/plugins/marketplaces/workbuddy-builtin/skills/library")
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(LIB / "database"))
import _common  # noqa: E402
from _common import HttpError, error_exit, http_request, unwrap_data  # noqa: E402

_PATH = "/space/api/agent/v1/query-database"

ap = argparse.ArgumentParser()
ap.add_argument("--database-id", required=True)
ap.add_argument("--page-size", type=int, default=100)
ap.add_argument("--out", default="")
a = ap.parse_args()

token = _common.acquire_token()
records, cursor, pages = [], "", 0
while True:
    body = {"databaseId": a.database_id, "pageSize": a.page_size}
    if cursor:
        body["startCursor"] = cursor
    try:
        data = unwrap_data(http_request("POST", _common.build_url(_PATH), token, body=body, timeout=20.0))
    except HttpError as e:
        error_exit("查询失败: %s" % e)
    res = data.get("results") or []
    records.extend(res)
    pages += 1
    cursor = data.get("nextCursor") or ""
    if not data.get("hasMore") or not cursor or pages > 60:
        break

print("records=%d pages=%d" % (len(records), pages), file=sys.stderr)
if records:
    print("sample_keys=%s" % sorted(records[0].keys()), file=sys.stderr)
    print("sample=%s" % json.dumps(records[0], ensure_ascii=False)[:600], file=sys.stderr)
out = a.out or "db_records.json"
Path(out).write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
print("WROTE %s (%d records)" % (out, len(records)), file=sys.stderr)