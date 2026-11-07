# -*- coding: utf-8 -*-
"""本地后端 API 实测：启动服务并跑完整增删改查。"""
import json
import time
import urllib.request

import app as backend

backend._init_db()
holder = {}
httpd = backend._start_server(holder)
for _ in range(100):
    if holder.get("port"):
        break
    time.sleep(0.02)
BASE = f"http://127.0.0.1:{holder['port']}"
print("BASE", BASE)
print("DB", backend.DB_PATH)


def call(path, body=None, method="POST"):
    data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


print("\n=== health ===")
print(call("/api/health", method="GET"))

MONEY = "tHLWn2tjAvknVD3h5lyWG5"

print("\n=== query money ===")
q = call("/api/query", {"databaseId": MONEY, "pageSize": 200})
print("rows:", len(q["results"]), "hasMore:", q["hasMore"])
print("sample:", json.dumps(q["results"][0], ensure_ascii=False)[:200])

print("\n=== add ===")
new_id = call(
    "/api/add",
    {
        "databaseId": MONEY,
        "properties": {
            "日期": {"date": "2026-10-25"},
            "分类": {"text": "测试"},
            "金额": {"currency": 12.5},
            "备注": {"text": "API 自测"},
            "收支方向": {"select": "支出"},
        },
    },
)
print(new_id)

print("\n=== verify add ===")
q2 = call("/api/query", {"databaseId": MONEY})
hit = [r for r in q2["results"] if r["record_id"] == new_id["record_id"]]
print("found:", len(hit), json.dumps(hit[0], ensure_ascii=False) if hit else None)

print("\n=== update ===")
print(call("/api/update", {
    "databaseId": MONEY,
    "recordId": new_id["record_id"],
    "properties": {"金额": {"currency": 99.9}, "备注": {"text": "已改"}},
}))
q3 = call("/api/query", {"databaseId": MONEY})
hit = [r for r in q3["results"] if r["record_id"] == new_id["record_id"]]
print("after update:", json.dumps(hit[0], ensure_ascii=False) if hit else None)

print("\n=== delete ===")
print(call("/api/delete", {"databaseId": MONEY, "recordId": new_id["record_id"]}))
q4 = call("/api/query", {"databaseId": MONEY})
print("rows after delete:", len(q4["results"]))

print("\n=== all tables ===")
for kind, dbid in backend.KIND_TO_ID.items():
    r = call("/api/query", {"databaseId": dbid})
    print(f"  {kind:9s} {len(r['results']):3d}")

print("\n=== export ===")
exp = call("/api/export", method="GET")
print("tables:", {k: len(v) for k, v in exp["tables"].items()})

print("\n=== upload ===")
png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
       "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
up = call("/api/upload", {"data": png, "contentType": "image/png", "fileName": "t.png"})
print(up)

httpd.shutdown()
print("\nDONE")
