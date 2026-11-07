# -*- coding: utf-8 -*-
"""
小笑肖 —— 在线生活工作台（独立版）

完全独立运行：不登录、不联网、不依赖任何第三方账号或云服务。
数据存在本机 SQLite 数据库：
    %LOCALAPPDATA%\\XiaoXiaoXiao\\data.db
封面图片存在：
    %LOCALAPPDATA%\\XiaoXiaoXiao\\uploads\\

提供给页面的接口，签名与页面原有调用完全一致：
    POST /api/query   {databaseId, pageSize, startCursor}
    POST /api/add     {databaseId, properties}
    POST /api/update  {databaseId, recordId, properties}
    POST /api/delete  {databaseId, recordId}
    POST /api/upload  {data(base64), contentType, fileName}
    GET  /api/export  全库导出 JSON
    POST /api/import  全库导入 JSON
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_TITLE = "小笑肖 · 生活工作台"
ENTRY_FILE = "index.html"
WEB_DIR_NAME = "_web"

# 云端表 ID → 本地 kind。页面里硬编码的是这些 ID，保持一一对应。
ID_TO_KIND = {
    "tHLWn2tjAvknVD3h5lyWG5": "money",
    "BxxY8CTvCuWpMWgHJJGq9S": "habit",
    "cPZx8ssc03WAmKOwFhBcPx": "plan",
    "JNiZJHR3QXKBMNrmHc0nIj": "fitness",
    "B2a4VCyYGokQUAqXRhAKVv": "shopping",
    "ukf8VPIPQtBQN71qyrtu6x": "media",
    "HEEB4feB120kc8nx8iSTxW": "summary",
}
KIND_TO_ID = {v: k for k, v in ID_TO_KIND.items()}


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def _resource_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _web_dir() -> str:
    return os.path.join(_resource_root(), WEB_DIR_NAME)


def _data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "XiaoXiaoXiao")
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "uploads"), exist_ok=True)
    return path


DATA_DIR = _data_dir()
DB_PATH = os.path.join(DATA_DIR, "data.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")


# --------------------------------------------------------------------------
# 类型规整
# --------------------------------------------------------------------------
def _num(v):
    try:
        if v is None or v == "":
            return 0
        return float(v)
    except (TypeError, ValueError):
        return 0


def _norm_date(v):
    """统一成 YYYY-MM-DD；无法识别时原样返回字符串。"""
    if not v:
        return ""
    s = str(v).strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def _flatten(props):
    """{字段: {类型: 值}} → {字段: 值}，供页面直接读取。"""
    out = {}
    if not isinstance(props, dict):
        return out
    for key, val in props.items():
        if isinstance(val, dict):
            if "image" in val:
                inner = val.get("image") or {}
                out[key] = inner.get("images") or []
            elif "date" in val:
                out[key] = _norm_date(val.get("date"))
            elif "select" in val:
                out[key] = val.get("select") or ""
            elif "multi_select" in val:
                out[key] = val.get("multi_select") or []
            elif "checkbox" in val:
                out[key] = bool(val.get("checkbox"))
            elif "currency" in val:
                out[key] = _num(val.get("currency"))
            elif "number" in val:
                out[key] = _num(val.get("number"))
            elif "text" in val:
                out[key] = val.get("text") or ""
            elif "url" in val:
                out[key] = val.get("url") or ""
            elif "email" in val:
                out[key] = val.get("email") or ""
            elif "phone_number" in val:
                out[key] = val.get("phone_number") or ""
            else:
                out[key] = next(iter(val.values())) if val else ""
        else:
            out[key] = val
    return out


# --------------------------------------------------------------------------
# 数据库
# --------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records(
                id TEXT PRIMARY KEY,
                db_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kind ON records(kind)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)"
        )
        row = conn.execute(
            "SELECT value FROM meta WHERE key='seeded'"
        ).fetchone()
        if row is None:
            _seed(conn)
            conn.execute(
                "INSERT INTO meta(key,value) VALUES('seeded',?)",
                (datetime.now().isoformat(timespec="seconds"),),
            )
            conn.commit()
        row = conn.execute(
            "SELECT value FROM meta WHERE key='created'"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key,value) VALUES('created',?)",
                (datetime.now().isoformat(timespec="seconds"),),
            )
            conn.commit()


def _seed(conn: sqlite3.Connection) -> None:
    """首次运行：导入随包附带的种子数据（若有）。"""
    path = os.path.join(_resource_root(), "seed.json")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            seed = json.load(f)
    except Exception:  # noqa: BLE001
        return
    if not isinstance(seed, dict):
        return
    now = int(time.time() * 1000)
    for kind, rows in seed.items():
        if kind not in KIND_TO_ID or not isinstance(rows, list):
            continue
        db_id = KIND_TO_ID[kind]
        for row in rows:
            if not isinstance(row, dict):
                continue
            # 日期字段统一成 YYYY-MM-DD，避免新旧数据格式混杂
            row = {
                k: (_norm_date(v) if ("日期" in k and isinstance(v, str)) else v)
                for k, v in row.items()
            }
            rid = uuid.uuid4().hex[:24]
            conn.execute(
                "INSERT INTO records(id,db_id,kind,data,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?)",
                (rid, db_id, kind, json.dumps(row, ensure_ascii=False), now, now),
            )
    conn.commit()


def _rows(kind: str):
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id,data FROM records WHERE kind=? ORDER BY updated_at DESC",
            (kind,),
        )
        out = []
        for rid, data in cur.fetchall():
            try:
                item = json.loads(data)
            except Exception:  # noqa: BLE001
                item = {}
            item["record_id"] = rid
            out.append(item)
        return out


def _add(kind: str, properties: dict) -> str:
    db_id = KIND_TO_ID[kind]
    rid = uuid.uuid4().hex[:24]
    flat = _flatten(properties)
    now = int(time.time() * 1000)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO records(id,db_id,kind,data,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (rid, db_id, kind, json.dumps(flat, ensure_ascii=False), now, now),
        )
        conn.commit()
    return rid


def _update(kind: str, record_id: str, properties: dict) -> bool:
    flat = _flatten(properties)
    now = int(time.time() * 1000)
    with _connect() as conn:
        row = conn.execute(
            "SELECT data FROM records WHERE id=? AND kind=?", (record_id, kind)
        ).fetchone()
        if not row:
            return False
        try:
            cur = json.loads(row[0])
        except Exception:  # noqa: BLE001
            cur = {}
        if not isinstance(cur, dict):
            cur = {}
        cur.update(flat)
        conn.execute(
            "UPDATE records SET data=?, updated_at=? WHERE id=?",
            (json.dumps(cur, ensure_ascii=False), now, record_id),
        )
        conn.commit()
    return True


def _delete(kind: str, record_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM records WHERE id=? AND kind=?", (record_id, kind)
        )
        conn.commit()
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# 上传
# --------------------------------------------------------------------------
_EXT_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _save_upload(data_b64: str, content_type: str, file_name: str, base_url: str) -> str:
    raw = base64.b64decode(data_b64)
    ext = _EXT_BY_TYPE.get((content_type or "").lower(), "")
    if not ext:
        ext = os.path.splitext(file_name or "")[1].lower() or ".bin"
    name = uuid.uuid4().hex[:16] + ext
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(raw)
    return f"{base_url}/uploads/{name}"


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class ApiHandler(BaseHTTPRequestHandler):
    server_version = "XiaoXiaoXiao/2.0"

    def log_message(self, fmt, *args):  # noqa: D401 - 静默
        return

    # ---------- 工具 ----------
    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, status=400):
        self._json({"error": msg}, status)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > 32 * 1024 * 1024:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _base_url(self):
        host = self.headers.get("Host") or "127.0.0.1"
        return f"http://{host}"

    def _kind(self, payload):
        db_id = str(payload.get("databaseId") or "").strip()
        kind = ID_TO_KIND.get(db_id)
        if not kind:
            return None
        return kind

    # ---------- 路由 ----------
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]

        if path == "/api/health":
            self._json({"ok": True, "db": DB_PATH})
            return

        if path == "/api/export":
            out = {k: _rows(k) for k in KIND_TO_ID}
            self._json(
                {
                    "exported_at": datetime.now().isoformat(timespec="seconds"),
                    "version": 1,
                    "tables": out,
                }
            )
            return

        if path.startswith("/uploads/"):
            name = os.path.basename(path)
            fp = os.path.join(UPLOAD_DIR, name)
            if not os.path.isfile(fp):
                self._err("not found", 404)
                return
            ext = os.path.splitext(name)[1].lower()
            ctype = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }.get(ext, "application/octet-stream")
            with open(fp, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)
            return

        # 静态文件
        rel = path.lstrip("/") or ENTRY_FILE
        rel = os.path.normpath(rel).replace("\\", "/")
        if rel.startswith("..") or rel.startswith("/"):
            self._err("bad path", 400)
            return
        fp = os.path.join(_web_dir(), rel)
        if not os.path.isfile(fp):
            fp = os.path.join(_web_dir(), ENTRY_FILE)
            if not os.path.isfile(fp):
                self._err("not found", 404)
                return
        ext = os.path.splitext(fp)[1].lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }.get(ext, "application/octet-stream")
        with open(fp, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        payload = self._body()

        if path == "/api/query":
            kind = self._kind(payload)
            if not kind:
                self._err("未知数据表")
                return
            rows = _rows(kind)
            self._json({"results": rows, "hasMore": False, "nextCursor": None})
            return

        if path == "/api/add":
            kind = self._kind(payload)
            if not kind:
                self._err("未知数据表")
                return
            props = payload.get("properties")
            if not isinstance(props, dict):
                self._err("properties 非法")
                return
            rid = _add(kind, props)
            self._json({"record_id": rid, "id": rid})
            return

        if path == "/api/update":
            kind = self._kind(payload)
            rid = str(payload.get("recordId") or "").strip()
            props = payload.get("properties")
            if not kind or not rid:
                self._err("参数缺失")
                return
            if not isinstance(props, dict):
                self._err("properties 非法")
                return
            ok = _update(kind, rid, props)
            self._json({"ok": ok})
            return

        if path == "/api/delete":
            kind = self._kind(payload)
            rid = str(payload.get("recordId") or "").strip()
            if not kind or not rid:
                self._err("参数缺失")
                return
            ok = _delete(kind, rid)
            self._json({"ok": ok})
            return

        if path == "/api/upload":
            data = str(payload.get("data") or "")
            if not data:
                self._err("缺少图片数据")
                return
            url = _save_upload(
                data,
                str(payload.get("contentType") or ""),
                str(payload.get("fileName") or ""),
                self._base_url(),
            )
            self._json({"url": url})
            return

        if path == "/api/import":
            tables = payload.get("tables")
            if not isinstance(tables, dict):
                self._err("tables 非法")
                return
            count = 0
            with _connect() as conn:
                conn.execute("DELETE FROM records")
                now = int(time.time() * 1000)
                for kind, rows in tables.items():
                    if kind not in KIND_TO_ID or not isinstance(rows, list):
                        continue
                    db_id = KIND_TO_ID[kind]
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        row = {k: v for k, v in row.items() if k != "record_id"}
                        rid = uuid.uuid4().hex[:24]
                        conn.execute(
                            "INSERT INTO records(id,db_id,kind,data,created_at,updated_at)"
                            " VALUES(?,?,?,?,?,?)",
                            (
                                rid,
                                db_id,
                                kind,
                                json.dumps(row, ensure_ascii=False),
                                now,
                                now,
                            ),
                        )
                        count += 1
                conn.commit()
            self._json({"ok": True, "imported": count})
            return

        self._err("not found", 404)


def _start_server(holder: dict) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
    holder["port"] = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _show_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, message)
        root.destroy()
    except Exception:  # noqa: BLE001
        print(message)


def main() -> int:
    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        _show_error(f"缺少 WebView 组件：{exc}")
        return 2

    try:
        _init_db()
    except Exception as exc:  # noqa: BLE001
        _show_error(f"数据库初始化失败：\n{DB_PATH}\n\n{exc}")
        return 4

    entry = os.path.join(_web_dir(), ENTRY_FILE)
    if not os.path.isfile(entry):
        _show_error(f"缺少页面资源：{entry}")
        return 3

    holder: dict = {}
    httpd = _start_server(holder)
    for _ in range(100):
        if holder.get("port"):
            break
        time.sleep(0.01)

    port = holder["port"]
    url = f"http://127.0.0.1:{port}/{ENTRY_FILE}"

    # 自检模式：不建窗口，只验证资源完整、页面可加载、API 可读
    if os.environ.get("XXV_SELFTEST") == "1":
        import urllib.request

        log_path = os.path.join(DATA_DIR, "selftest.log")
        lines = []

        def _log(msg):
            lines.append(str(msg))

        def _get(path):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
                return r.status, r.read()

        try:
            st, body = _get("/api/health")
            _log(f"health: {st} {body.decode('utf-8')[:150]}")
            st, body = _get(f"/{ENTRY_FILE}")
            text = body.decode("utf-8", errors="replace")
            _log(f"page: {st} bytes={len(body)}")
            _log(f"adapter: {'本地数据层适配' in text}")
            _log(f"safeUrl_local: {'http://127.0.0.1:' in text}")
            _log(f"has_bridge_branch: {'AndroidLocal' in text}")
            import json as _json

            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/query",
                data=_json.dumps(
                    {"databaseId": "tHLWn2tjAvknVD3h5lyWG5", "pageSize": 200}
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = _json.loads(r.read().decode("utf-8"))
            _log(f"money_rows: {len(data.get('results', []))}")
            rows = data.get("results", [])
            if rows:
                _log(f"sample_keys: {sorted(rows[0].keys())}")
            _log("SELFTEST_DONE")
        except Exception as exc:  # noqa: BLE001
            _log(f"SELFTEST_FAIL: {exc!r}")
        finally:
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except Exception:  # noqa: BLE001
                pass
            httpd.shutdown()
        return 0

    try:
        webview.create_window(
            APP_TITLE,
            url,
            width=1240,
            height=860,
            min_size=(900, 640),
            text_select=True,
            confirm_close=False,
            zoomable=True,
        )
        webview.start(debug=False, private_mode=True)
    except Exception as exc:  # noqa: BLE001
        _show_error(f"启动窗口失败：{exc}")
        return 5
    finally:
        try:
            httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
