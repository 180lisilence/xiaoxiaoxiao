# -*- coding: utf-8 -*-
"""
小笑肖 v4.0.2 —— 后端服务

一个可独立运行、也可被启动器内嵌调用的 HTTP 服务：
  · 数据存本机 SQLite
  · 监听 0.0.0.0，手机可通过局域网直连
  · 所有写操作带 source（pc/phone/web）与 updated_at，支持双端同步
  · 软删除 + 变更日志，支持增量拉取

接口（与 v3 保持向后兼容，页面无需改动）：
    POST /api/query       读整表
    POST /api/add         新增
    POST /api/update      修改
    POST /api/delete      删除（软删）
    POST /api/upload      上传封面
    GET  /api/export      全库导出
    POST /api/import      全库导入

v4 新增：
    GET  /api/health      健康检查 + 版本 + 配对状态
    GET  /api/changes     增量拉取 since=<ts>
    POST /api/sync        批量推送本地变更（手机离线队列）
    GET  /api/devices     已连接设备
    GET  /api/ping        极轻量探测，供手机判断可达
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = "4.0.2"

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

DEFAULT_PORT = 8731


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def resource_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def app_home() -> str:
    """程序自己唯一的可写根目录 —— 永远落在 exe 所在的那块盘上。

    为什么不再用 %LOCALAPPDATA%：
        操作者指定了唯一可写的工作目录（E 盘那个文件夹），程序往系统盘写
        数据属于越界。所以改成程序自己目录下的 _data：
            · 绿色便携 —— 整个文件夹拷走就能换机器，不用重装
            · exe 在哪个盘，数据就在哪个盘，绝不在 C 盘留残留

    查找顺序（三步，都能预期）：
        1. exe 同目录已有 _data        → 直接用（最直接的便携形态）
        2. 上一级目录已有 _data        → 用它（启动器和工作台各占一个子目录、
                                        共用一份数据的布局）
        3. 都没有                      → 在 exe 同目录新建 _data

    环境变量 XIAOXIAOXIAO_HOME 可以整体覆盖（迁移到独立服务器、跑测试时用）。
    """
    env = (os.environ.get("XIAOXIAOXIAO_HOME") or "").strip()
    if env:
        return os.path.abspath(env)
    if getattr(sys, "frozen", False):
        here = os.path.dirname(os.path.abspath(sys.executable))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, "_data")
    if os.path.isdir(local):
        return local
    parent = os.path.join(os.path.dirname(here), "_data")
    if os.path.isdir(parent):
        return parent
    return local


def data_dir() -> str:
    path = app_home()
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "uploads"), exist_ok=True)
    return path


DATA_DIR = data_dir()
DB_PATH = os.path.join(DATA_DIR, "data.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
CONFIG_PATH = os.path.join(DATA_DIR, "server.json")


def _web_dir() -> str:
    return os.path.join(resource_root(), WEB_DIR_NAME)


# --------------------------------------------------------------------------
# 配置（配对状态、端口）
# --------------------------------------------------------------------------
_config_lock = threading.Lock()


def load_config() -> dict:
    with _config_lock:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                return cfg
        except Exception:  # noqa: BLE001
            pass
        return {}


def save_config(cfg: dict) -> None:
    with _config_lock:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)


def get_pair_hash() -> str:
    return str(load_config().get("key_hash") or "")


# --------------------------------------------------------------------------
# 本机会话私钥
# --------------------------------------------------------------------------
# 为什么需要「本机会话私钥」：
#   4.0.2 起所有 /api/* 都要带 X-Pair-Key。工作台页面在浏览器里跑，
#   它必须能拿到这把私钥，否则整个页面都是空的。
#
# 之前的问题：私钥只存在进程内存里（set_local_key），
#   启动器一关、或工作台自己拉起后端，内存就是空的 → 页面永远 401。
#   可如果直接存明文，又违背了「明文未落盘」的承诺。
#
# 现在的做法：DPAPI 加密后落盘（key_sealed 字段）。
#   · 磁盘上只有密文，且绑定「本机 + 当前 Windows 用户」，拷走也解不开；
#   · 后端启动时自己 unseal 回内存，页面照常拿得到 key；
#   · 内存里仍有一份，命中就不重复解密。
_LOCAL_KEY = ""
_local_key_lock = threading.Lock()
_SEAL_FIELD = "key_sealed"


def set_local_key(raw_key: str, persist: bool = True) -> None:
    """设置本机会话私钥。

    persist=True 时同时用 DPAPI 加密写入 server.json 的 key_sealed 字段，
    使得后端重启后仍能把私钥交还给本机页面。
    """
    global _LOCAL_KEY
    raw = str(raw_key or "").strip()
    with _local_key_lock:
        _LOCAL_KEY = raw
    if not persist:
        return
    try:
        import _dpapi
        sealed = _dpapi.seal(raw) if raw else ""
    except Exception:  # noqa: BLE001
        sealed = ""
    cfg = load_config()
    if sealed:
        cfg[_SEAL_FIELD] = sealed
    else:
        cfg.pop(_SEAL_FIELD, None)
    save_config(cfg)


def local_key() -> str:
    """取本机会话私钥：优先内存，其次从 DPAPI 密文恢复。"""
    with _local_key_lock:
        if _LOCAL_KEY:
            return _LOCAL_KEY
    # 内存空 → 尝试从磁盘密文恢复（后端被工作台单独拉起时走这条）
    cfg = load_config()
    sealed = cfg.get(_SEAL_FIELD) or ""
    if not sealed:
        return ""
    try:
        import _dpapi
        raw = _dpapi.unseal(sealed)
    except Exception:  # noqa: BLE001
        raw = ""
    if not raw:
        return ""
    # 解出来的必须和库里的哈希对得上，否则说明配置被改过/被拷过
    if not hmac.compare_digest(_key_digest(raw), get_pair_hash()):
        return ""
    with _local_key_lock:
        globals()["_LOCAL_KEY"] = raw
    return raw


def _is_loopback(addr: str) -> bool:
    a = str(addr or "").strip()
    return a in ("127.0.0.1", "::1", "localhost") or a.startswith("127.")


# 反向代理/隧道会加上的转发头。
# 为什么必须查这些：
#   /api/session 是靠「只允许本机访问」来保护的（它直接吐出私钥）。
#   但内网穿透（Cloudflare Tunnel、frp、ngrok…）都是在**本机**起一个客户端，
#   由那个客户端把公网流量回源到 127.0.0.1。
#   于是服务端看到的 client_address 永远是 127.0.0.1 ——
#   公网上的任何人都会被认成「本机」，直接把私钥读走。
#
#   只要请求带任何一个转发头，就说明它不是本机浏览器直连，
#   一律按「外部请求」处理。
PROXY_HEADERS = (
    "CF-Connecting-IP",
    "X-Forwarded-For",
    "X-Forwarded-Host",
    "X-Real-IP",
    "Forwarded",
    "X-Original-Forwarded-For",
    "True-Client-IP",
    "CDN-Loop",
)


def has_proxy_headers(headers) -> bool:
    """请求里有没有反向代理留下的痕迹。"""
    if headers is None:
        return False
    for name in PROXY_HEADERS:
        try:
            if headers.get(name):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def set_pair_hash(h: str, raw_key: str = "") -> None:
    cfg = load_config()
    cfg["key_hash"] = h
    cfg["paired_at"] = datetime.now().isoformat(timespec="seconds")
    save_config(cfg)
    if raw_key:
        set_local_key(raw_key)


def is_paired() -> bool:
    return bool(get_pair_hash())


def _key_digest(raw_key: str) -> str:
    return hashlib.sha256(str(raw_key or "").strip().encode("utf-8")).hexdigest()


def verify_key(raw_key: str) -> bool:
    """校验私钥。

    两条约束：
    1. 未配对（库里没有 key_hash）时一律 False —— 不能让「没设私钥」等于「谁都能进」。
    2. 用 hmac.compare_digest 而不是 ==：== 会在第一个不同字节处返回，
       理论上能靠响应时间分布逐字节猜哈希。
    """
    stored = get_pair_hash()
    if not stored:
        return False
    raw = str(raw_key or "").strip()
    if not raw:
        return False
    return hmac.compare_digest(_key_digest(raw), stored)


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
    conn.row_factory = sqlite3.Row
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS records(
    id TEXT PRIMARY KEY,
    db_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'pc',
    device_name TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_kind ON records(kind);
CREATE INDEX IF NOT EXISTS idx_upd ON records(updated_at);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS devices(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    last_ip TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS changelog(
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    op TEXT NOT NULL,
    at INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'pc'
);
"""


def init_db() -> None:
    with _connect() as conn:
        for stmt in SCHEMA.split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)
        # 老库升级：补列
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(records)")}
        for name, ddl in (
            ("deleted", "ALTER TABLE records ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0"),
            ("source", "ALTER TABLE records ADD COLUMN source TEXT NOT NULL DEFAULT 'pc'"),
            ("device_name", "ALTER TABLE records ADD COLUMN device_name TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in cols:
                conn.execute(ddl)
        row = conn.execute("SELECT value FROM meta WHERE key='seeded'").fetchone()
        if row is None:
            _seed(conn)
            conn.execute(
                "INSERT INTO meta(key,value) VALUES('seeded',?)",
                (datetime.now().isoformat(timespec="seconds"),),
            )
        else:
            # 用户主动清空过数据就不再补种子，否则一清空、下次启动又全灌回来
            cleared = conn.execute(
                "SELECT value FROM meta WHERE key='user_cleared'").fetchone()
            if cleared is None:
                # 老库可能只导入了部分表（早期版本中断过），补上缺的那些
                _seed_missing(conn)
        row = conn.execute("SELECT value FROM meta WHERE key='created'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key,value) VALUES('created',?)",
                (datetime.now().isoformat(timespec="seconds"),),
            )
        conn.commit()


def _seed_missing(conn) -> None:
    """按表补齐：某张表一条都没有就重新导入该表的种子。"""
    path = os.path.join(resource_root(), "seed.json")
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
        if kind not in KIND_TO_ID or not isinstance(rows, list) or not rows:
            continue
        have = conn.execute(
            "SELECT COUNT(*) AS n FROM records WHERE kind=?", (kind,)
        ).fetchone()["n"]
        if have and have > 0:
            continue
        db_id = KIND_TO_ID[kind]
        for row in rows:
            if not isinstance(row, dict):
                continue
            row = {
                k: (_norm_date(v) if ("日期" in k and isinstance(v, str)) else v)
                for k, v in row.items()
            }
            conn.execute(
                "INSERT INTO records(id,db_id,kind,data,created_at,updated_at,deleted,source,device_name)"
                " VALUES(?,?,?,?,?,?,0,'pc','')",
                (uuid.uuid4().hex[:24], db_id, kind,
                 json.dumps(row, ensure_ascii=False), now, now),
            )
    conn.commit()


def _seed(conn) -> None:
    path = os.path.join(resource_root(), "seed.json")
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
            row = {
                k: (_norm_date(v) if ("日期" in k and isinstance(v, str)) else v)
                for k, v in row.items()
            }
            rid = uuid.uuid4().hex[:24]
            conn.execute(
                "INSERT INTO records(id,db_id,kind,data,created_at,updated_at,deleted,source,device_name)"
                " VALUES(?,?,?,?,?,?,0,'pc','')",
                (rid, db_id, kind, json.dumps(row, ensure_ascii=False), now, now),
            )
    conn.commit()


def _row_to_item(row) -> dict:
    try:
        item = json.loads(row["data"])
    except Exception:  # noqa: BLE001
        item = {}
    if not isinstance(item, dict):
        item = {}
    item["record_id"] = row["id"]
    item["_source"] = row["source"] or "pc"
    item["_device"] = row["device_name"] or ""
    item["_updated_at"] = row["updated_at"]
    return item


def rows_of(kind: str) -> list:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id,data,source,device_name,updated_at FROM records"
            " WHERE kind=? AND deleted=0 ORDER BY updated_at DESC",
            (kind,),
        )
        return [_row_to_item(r) for r in cur.fetchall()]


def _log_change(conn, rid: str, kind: str, op: str, source: str) -> None:
    conn.execute(
        "INSERT INTO changelog(record_id,kind,op,at,source) VALUES(?,?,?,?,?)",
        (rid, kind, op, int(time.time() * 1000), source),
    )


def add_record(kind: str, properties: dict, source: str = "pc",
               device: str = "", rid: str | None = None,
               ts: int | None = None) -> str:
    db_id = KIND_TO_ID[kind]
    rid = rid or uuid.uuid4().hex[:24]
    flat = _flatten(properties)
    now = int(ts or time.time() * 1000)
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO records"
            "(id,db_id,kind,data,created_at,updated_at,deleted,source,device_name)"
            " VALUES(?,?,?,?,?,?,0,?,?)",
            (rid, db_id, kind, json.dumps(flat, ensure_ascii=False), now, now,
             source, device),
        )
        _log_change(conn, rid, kind, "add", source)
        conn.commit()
    return rid


def update_record(kind: str, rid: str, properties: dict, source: str = "pc",
                  device: str = "", ts: int | None = None) -> bool:
    flat = _flatten(properties)
    now = int(ts or time.time() * 1000)
    with _connect() as conn:
        row = conn.execute(
            "SELECT data,updated_at,deleted FROM records WHERE id=? AND kind=?",
            (rid, kind),
        ).fetchone()
        if not row:
            return False
        # 后写覆盖先写：本地已有更新的版本则忽略这次的旧变更
        if ts is not None and now < int(row["updated_at"]):
            return False
        if int(row["deleted"] or 0) == 1:
            return False
        try:
            cur = json.loads(row["data"])
        except Exception:  # noqa: BLE001
            cur = {}
        if not isinstance(cur, dict):
            cur = {}
        cur.update(flat)
        conn.execute(
            "UPDATE records SET data=?, updated_at=?, source=?, device_name=?"
            " WHERE id=?",
            (json.dumps(cur, ensure_ascii=False), now,
             source or "pc", device or "", rid),
        )
        _log_change(conn, rid, kind, "update", source)
        conn.commit()
    return True


def delete_record(kind: str, rid: str, source: str = "pc",
                  device: str = "", ts: int | None = None) -> bool:
    now = int(ts or time.time() * 1000)
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE records SET deleted=1, updated_at=?, source=?, device_name=?"
            " WHERE id=? AND kind=? AND deleted=0",
            (now, source or "pc", device or "", rid, kind),
        )
        ok = cur.rowcount > 0
        if ok:
            _log_change(conn, rid, kind, "delete", source)
        conn.commit()
        return ok


def changes_since(ts: int) -> dict:
    """增量拉取：返回所有 updated_at > ts 的记录（含已删除）。"""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id,kind,data,created_at,updated_at,deleted,source,device_name"
            " FROM records WHERE updated_at > ? ORDER BY updated_at ASC LIMIT 5000",
            (int(ts),),
        )
        items = []
        for r in cur.fetchall():
            item = _row_to_item(r)
            item["_kind"] = r["kind"]
            item["_deleted"] = bool(r["deleted"])
            items.append(item)
        head = conn.execute(
            "SELECT COALESCE(MAX(updated_at),0) AS m FROM records"
        ).fetchone()["m"]
    return {"changes": items, "cursor": int(head), "count": len(items)}


def touch_device(dev_id: str, name: str, platform: str, ip: str) -> None:
    if not dev_id:
        return
    now = int(time.time() * 1000)
    with _connect() as conn:
        row = conn.execute("SELECT id FROM devices WHERE id=?", (dev_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE devices SET name=?,platform=?,last_seen=?,last_ip=? WHERE id=?",
                (name or "", platform or "", now, ip or "", dev_id),
            )
        else:
            conn.execute(
                "INSERT INTO devices(id,name,platform,first_seen,last_seen,last_ip)"
                " VALUES(?,?,?,?,?,?)",
                (dev_id, name or "", platform or "", now, now, ip or ""),
            )
        conn.commit()


WIPE_ALL_SCOPE = "all"


def wipe_all(kind: str = "", require_kind: bool = True) -> dict:
    """清空业务数据，并记住「用户主动清空过」。

    kind 为 "all" -> 清全部业务表；传具体 kind（money/habit/plan/...）-> 只清那一张表。

    **require_kind=True（默认，也是 HTTP 接口的行为）时，空 kind 一律拒绝。**
    原因：以前空 kind 等于「清全部」，于是 `POST /api/wipe {}` 一条空 body
    就能把整库抹掉 —— 前端任何一个漏传 kind 的 fetch 都会变成清库指令。
    现在必须显式写 `{"kind":"all"}` 才清全部，写空了就报错、什么也不动。
    启动器内部（用户点了「清空全部」）显式传 require_kind=False 走全清。

    清 records / changelog，**不清 devices**：
    devices 是「谁连过我」的连接记录，不是业务数据。把它一起清掉会让
    启动器（读 server.json 的 paired_at）说「已配对」、工作台（读 devices 表）
    说「没有手机连接」，两边对不上。清空数据不该把已配对的设备也抹掉。

    不写 user_cleared 标记的话，下次启动 _seed_missing() 会把示例数据全灌回来 ——
    用户清完一重启发现数据又在了，等于没清。
    单表清空时更要写：否则那一次重启就把它补齐了。

    私钥哈希、created 时间同样不动：清了之后手机还得连得上。
    """
    kind = (kind or "").strip()
    if not kind:
        if require_kind:
            return {
                "ok": False,
                "error": "必须指定要清空的表；清全部请传 kind=all",
            }
        kind = WIPE_ALL_SCOPE
    if kind != WIPE_ALL_SCOPE and kind not in KIND_TO_ID:
        return {"ok": False, "error": "未知数据表: " + kind}
    if kind == WIPE_ALL_SCOPE:
        kind = ""

    with _connect() as conn:
        before = {}
        for t in ("records", "devices", "changelog"):
            try:
                before[t] = conn.execute(
                    'SELECT COUNT(*) AS n FROM "%s"' % t).fetchone()["n"]
            except Exception:  # noqa: BLE001
                before[t] = -1

        if kind:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM records WHERE kind=?", (kind,)
            ).fetchone()
            before["scoped"] = {"kind": kind, "records": row["n"]}
            conn.execute("DELETE FROM records WHERE kind=?", (kind,))
        else:
            conn.execute("DELETE FROM records")
        conn.execute("DELETE FROM changelog")
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('user_cleared',?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        conn.commit()
    return {"ok": True, "wiped": True, "kind": kind or "all", "before": before}


def list_devices() -> list:
    """列设备。

    按 (name, platform) 归并：同一台手机重装 App 后 deviceId 会变，
    表里会多出一行，界面上就会看到同一台设备重复出现几次。
    这里只保留每台设备最近一次在线的那条，顺带累加首见时间。
    """
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id,name,platform,first_seen,last_seen,last_ip FROM devices"
            " ORDER BY last_seen DESC"
        )
        rows = [dict(r) for r in cur.fetchall()]

    merged: dict = {}
    order = []
    for r in rows:
        key = (r.get("name") or "", r.get("platform") or "")
        if key not in merged:
            merged[key] = dict(r)
            order.append(key)
        else:
            keep = merged[key]
            # 首见取更早，最近在线取更晚（rows 已按 last_seen 倒序，
            # 先到的那条就是最新的，这里只补 first_seen）
            if r.get("first_seen") and r["first_seen"] < keep.get("first_seen", 0):
                keep["first_seen"] = r["first_seen"]
    return [merged[k] for k in order]


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


def save_upload(data_b64: str, content_type: str, file_name: str, base_url: str) -> str:
    raw = base64.b64decode(data_b64)
    ext = _EXT_BY_TYPE.get((content_type or "").lower(), "")
    if not ext:
        ext = os.path.splitext(file_name or "")[1].lower() or ".bin"
    name = uuid.uuid4().hex[:16] + ext
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(raw)
    return f"{base_url}/uploads/{name}"


def lan_ip() -> str:
    """取当前局域网 IP；取不到回环时返回 127.0.0.1。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class ApiHandler(BaseHTTPRequestHandler):
    server_version = "XiaoXiaoXiao/" + VERSION

    def log_message(self, fmt, *args):  # noqa: D401 - 由启动器接管日志
        msg = fmt % args if args else fmt
        try:
            if LOG_SINK is not None:
                LOG_SINK(f"{self.client_address[0]} {msg}")
        except Exception:  # noqa: BLE001
            pass

    # ---------- 工具 ----------
    def _cors_origin(self) -> str:
        """只允许本机 / 局域网来源的页面跨域调接口。

        原来一律回 `*`，等于任何网站都能在用户浏览器里直接 fetch
        这台机器的 /api/query 把数据读走 —— 加上没鉴权就是完全没有门槛。
        现在按 Origin 白名单回显，不在白名单就不发 CORS 头
        （同源请求本来就不需要它，浏览器照常工作）。
        """
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return ""
        try:
            u = urlparse(origin)
        except Exception:  # noqa: BLE001
            return ""
        host = (u.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return origin
        # 局域网/本机 IP：只认本机自己的地址
        try:
            if host and host == lan_ip().lower():
                return origin
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Pair-Key")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
        return ID_TO_KIND.get(db_id)

    def _src(self, payload):
        s = str(payload.get("source") or "pc").strip().lower()
        return s if s in ("pc", "phone", "web") else "pc"

    # ---------- 鉴权 ----------
    def _presented_key(self) -> str:
        """从请求里取私钥：优先请求头 X-Pair-Key，其次 ?key=。"""
        k = (self.headers.get("X-Pair-Key") or "").strip()
        if k:
            return k
        try:
            q = parse_qs(urlparse(self.path).query)
            return (q.get("key") or [""])[0].strip()
        except Exception:  # noqa: BLE001
            return ""

    def _authed(self) -> bool:
        return verify_key(self._presented_key())

    def _guard(self, path: str) -> bool:
        """返回 True 表示放行。未鉴权时已写好 401 响应，调用方直接 return。

        **只管 /api/ 开头的接口**，静态资源一律放行：
        工作台页面本身不含任何业务数据（数据全靠页面里带私钥的 fetch 取），
        锁页面既保护不了数据，只会让人打不开工作台。

        白名单只有 /api/ping —— 手机端启动时靠它探测「电脑在不在」，
        此时它还没拿到私钥，必须能问。ping 只回版本号，不泄露任何数据。
        /api/health 以前无鉴权且回 db 路径 + 局域网 IP，属于白送信息，
        现在必须带私钥，且不再回这两个字段。
        """
        if not path.startswith("/api/"):
            return True
        if path == "/api/ping":
            return True
        if self._authed():
            return True
        self._json(
            {"ok": False, "error": "unauthorized", "hint": "需要 X-Pair-Key 请求头或 ?key="},
            401,
        )
        return False

    def do_OPTIONS(self):  # noqa: N802
        self._json({"ok": True})

    # ---------- 路由 ----------
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        query = {}
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k] = v

        if path == "/api/ping":
            self._json({"ok": True, "v": VERSION})
            return

        if path == "/api/session":
            # 只给「就运行在这台电脑上」的页面发私钥（工作台 exe 用 pywebview
            # 加载 http://127.0.0.1:port/index.html，源 IP 一定是 127.0.0.1）。
            # 手机或局域网其他机器来问，一律 403：它们的私钥本来就在自己身上，
            # 没有理由向服务端索取。
            #
            # 注意 client_address 不可单独信任：内网穿透是在本机跑一个客户端
            # 把公网流量回源到 127.0.0.1，源 IP 看起来和本机浏览器一模一样。
            # 所以只要带了转发头，就一定是从公网绕进来的，直接拒。
            if has_proxy_headers(self.headers):
                self._err("forbidden", 403)
                return
            if not _is_loopback(self.client_address[0]):
                self._err("forbidden", 403)
                return
            k = local_key()
            if not k:
                self._err("尚未配对", 409)
                return
            self._json({"ok": True, "key": k, "version": VERSION})
            return

        # 以下全部需要私钥
        if not self._guard(path):
            return

        if path == "/api/health":
            self._json(
                {
                    "ok": True,
                    "version": VERSION,
                    "paired": is_paired(),
                    "port": int(self.server.server_address[1]),
                }
            )
            return

        if path == "/api/changes":
            try:
                since = int(query.get("since") or 0)
            except ValueError:
                since = 0
            self._json(changes_since(since))
            return

        if path == "/api/devices":
            self._json({"devices": list_devices()})
            return

        if path == "/api/wipe":
            # GET 不再能清库。以前 GET /api/wipe 直接清全部 —— 浏览器地址栏
            # 敲一下、页面里一个 <img src>、预取都能触发，太离谱。
            self._err("清空请用 POST 并带 {\"kind\":\"all\"}", 405)
            return

        if path == "/api/export":
            out = {k: rows_of(k) for k in KIND_TO_ID}
            self._json(
                {
                    "exported_at": datetime.now().isoformat(timespec="seconds"),
                    "version": 4,
                    "tables": out,
                }
            )
            return

        # ---------- 静态资源（不含数据，免鉴权） ----------
        # 必须在 _guard 之前返回：工作台页面本体要能加载，页面里的 fetch
        # 才是带私钥的那一方。锁住页面并不能保护数据，只会让人打不开。
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
        raw_path = self.path
        path = raw_path.split("?")[0]
        query = {}
        if "?" in raw_path:
            for part in raw_path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k] = v

        # 先鉴权再读 body：未鉴权的请求不该让我们解析 32MB
        if path != "/api/ping" and not self._guard(path):
            return

        payload = self._body()

        # 手机每次请求都报一次身份，用于启动器的设备列表
        dev_id = str(payload.get("deviceId") or "")
        if dev_id:
            touch_device(
                dev_id,
                str(payload.get("deviceName") or ""),
                str(payload.get("devicePlatform") or ""),
                self.client_address[0],
            )

        if path == "/api/ping":
            self._json({"ok": True, "v": VERSION})
            return

        if path == "/api/changes":
            # 手机端 pullAll 走 POST（body 带设备身份，用于设备列表），
            # 与 GET 共用同一份增量逻辑；since 从查询串取。
            try:
                since = int(query.get("since") or 0)
            except ValueError:
                since = 0
            self._json(changes_since(since))
            return

        if path == "/api/wipe":
            # 必须显式给 kind：{"kind":"money"} 清一张表，{"kind":"all"} 清全部。
            # 空 kind 一律拒绝，绝不默认清全部（P1-5）。
            confirm = payload.get("confirm")
            kind_req = str(payload.get("kind") or "").strip()
            if kind_req == WIPE_ALL_SCOPE and confirm is not True:
                self._err("清空全部需要 confirm=true")
                return
            res = wipe_all(kind_req)
            self._json(res, 200 if res.get("ok") else 400)
            return

        if path == "/api/query":
            kind = self._kind(payload)
            if not kind:
                self._err("未知数据表")
                return
            self._json({"results": rows_of(kind), "hasMore": False, "nextCursor": None})
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
            rid = add_record(
                kind, props,
                source=self._src(payload),
                device=str(payload.get("deviceName") or ""),
                rid=str(payload.get("recordId") or "") or None,
                ts=payload.get("ts"),
            )
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
            ok = update_record(
                kind, rid, props,
                source=self._src(payload),
                device=str(payload.get("deviceName") or ""),
                ts=payload.get("ts"),
            )
            self._json({"ok": ok})
            return

        if path == "/api/delete":
            kind = self._kind(payload)
            rid = str(payload.get("recordId") or "").strip()
            if not kind or not rid:
                self._err("参数缺失")
                return
            ok = delete_record(
                kind, rid,
                source=self._src(payload),
                device=str(payload.get("deviceName") or ""),
                ts=payload.get("ts"),
            )
            self._json({"ok": ok})
            return

        if path == "/api/sync":
            # 手机离线队列批量补推
            ops = payload.get("ops")
            if not isinstance(ops, list):
                self._err("ops 非法")
                return
            done, failed = 0, []
            for op in ops:
                if not isinstance(op, dict):
                    continue
                kind = ID_TO_KIND.get(str(op.get("databaseId") or ""))
                if not kind:
                    failed.append({"op": op, "why": "未知表"})
                    continue
                action = str(op.get("action") or "")
                rid = str(op.get("recordId") or "") or uuid.uuid4().hex[:24]
                src = self._src(op)
                dev = str(op.get("deviceName") or "")
                ts = op.get("ts")
                try:
                    if action == "add":
                        add_record(kind, op.get("properties") or {}, src, dev, rid, ts)
                    elif action == "update":
                        update_record(kind, rid, op.get("properties") or {}, src, dev, ts)
                    elif action == "delete":
                        delete_record(kind, rid, src, dev, ts)
                    else:
                        failed.append({"op": op, "why": "未知动作"})
                        continue
                    done += 1
                except Exception as exc:  # noqa: BLE001
                    failed.append({"op": op, "why": str(exc)})
            self._json({"ok": True, "done": done, "failed": failed})
            return

        if path == "/api/upload":
            data = str(payload.get("data") or "")
            if not data:
                self._err("缺少图片数据")
                return
            url = save_upload(
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
                            "INSERT INTO records"
                            "(id,db_id,kind,data,created_at,updated_at,deleted,source,device_name)"
                            " VALUES(?,?,?,?,?,?,0,'pc','')",
                            (rid, db_id, kind, json.dumps(row, ensure_ascii=False), now, now),
                        )
                        count += 1
                conn.commit()
            self._json({"ok": True, "imported": count})
            return

        self._err("not found", 404)


LOG_SINK = None


class FastHTTPServer(ThreadingHTTPServer):
    """跳过 socket.getfqdn() 的 HTTPServer。

    为什么必须这么做：
    Python 标准库 HTTPServer.server_bind() 里有这一行 ——

        self.server_name = socket.getfqdn(host)

    它会对绑定地址做一次**反向 DNS 查询**。绑 127.0.0.1 时瞬间返回，
    但绑 0.0.0.0 时实测要 19.5 秒（等 DNS 超时）：
        0.0.0.0   -> 19.492s
        127.0.0.1 ->  0.001s

    而启动器恰恰绑的是 0.0.0.0（手机要连）。这 19.5 秒发生在主线程，
    窗口刚画出来就冻住，用户看到的就是「打开瞬间很卡、点不动」。
    工作台绑 127.0.0.1 所以不卡 —— 这也解释了为什么只有启动器卡。

    server_name / server_port 只用于默认错误页和 CGI 变量，本服务不用。
    直接写成绑定地址，省掉这次查询。
    """

    def server_bind(self):
        # 绕过 HTTPServer.server_bind，只做 TCPServer 该做的事
        import socketserver

        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host or "localhost")
        self.server_port = int(port)


# --------------------------------------------------------------------------
# TLS（内网穿透必需）
# --------------------------------------------------------------------------
# 为什么后端自己要能上 HTTPS：
#   SakuraFrp 等穿透服务对 HTTP 隧道有合规拦截 —— 节点看到明文 HTTP 请求
#   会直接回 501「您正试图使用 HTTP 协议访问此隧道」，要求隧道所有者
#   自己在 Web 服务器里开 HTTPS，或者用它的「自动 HTTPS」。
#   而「自动 HTTPS」只对 HTTP 类型隧道有效，TCP 隧道它没法终结 TLS
#   （TLS 是端到端的，中间节点没有证书就握手不了）。
#   所以要么换 HTTP 隧道 + 自动 HTTPS，要么后端自己持证书。
#   这里做后者：后端能直接监听 TLS，任何穿透方式都能用。
#
# 证书从哪来：
#   · 有正式证书（域名 + Let's Encrypt 等）→ 配置 cert_file / key_file 直接用
#   · 没有 → 自动生成自签证书。自签证书浏览器会警告、Android 的
#     WebView 默认也会拒绝，所以手机端要走「信任本证书」那一步，
#     或者用 HTTP 隧道（见 README）。

CERT_FILE = os.path.join(DATA_DIR, "server.crt")
KEY_FILE = os.path.join(DATA_DIR, "server.key")


def _ensure_selfsigned(cert_path: str, key_path: str) -> bool:
    """没有证书就生成一张自签的（仅本机使用）。

    不引入 cryptography / OpenSSL 依赖 —— 用 Windows 自带的
    certreq 太重、Linux 上不一定有 openssl 命令。
    这里直接用 Python 标准库拼一张最小可用的 X.509 v3 证书：
    实际做法是调用 openssl 命令，找不到就返回 False，
    由调用方决定降级成 HTTP。
    """
    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        return True
    try:
        import shutil
        import subprocess

        openssl = shutil.which("openssl")
        if not openssl:
            return False
        os.makedirs(os.path.dirname(cert_path), exist_ok=True)
        subprocess.run(
            [
                openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", key_path, "-out", cert_path,
                "-days", "3650",
                "-subj", "/CN=xiaoxiaoxiao.local/O=XiaoXiaoXiao",
                "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _wrap_tls(httpd, cert_path: str, key_path: str):
    import ssl

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    return httpd


def start(port: int = DEFAULT_PORT, host: str = "127.0.0.1",
          log_sink=None, tls: bool = False,
          cert_file: str = "", key_file: str = "") -> ThreadingHTTPServer:
    """启动服务并返回 server 对象。调用方负责 shutdown()。

    host 默认 127.0.0.1（原来的 0.0.0.0 会把工作台连同数据库
    暴露给同一 Wi-Fi 下所有设备）。要手机连过来时，启动器自己显式传 0.0.0.0，
    并且那里已经有私钥把关。

    tls=True 时监听 HTTPS。cert_file / key_file 不传就用数据目录下的
    server.crt / server.key；两个都没有就尝试自动生成自签证书，
    生成不了则退回 HTTP（并写日志说明原因）。
    """
    global LOG_SINK
    if log_sink is not None:
        LOG_SINK = log_sink
    init_db()
    httpd = FastHTTPServer((host, port), ApiHandler)

    if tls:
        cf = cert_file or CERT_FILE
        kf = key_file or KEY_FILE
        if not (os.path.isfile(cf) and os.path.isfile(kf)):
            ok = _ensure_selfsigned(cf, kf)
            if not ok:
                if LOG_SINK:
                    LOG_SINK(
                        "TLS: 没有证书，本机也没有 openssl，先按 HTTP 启动。"
                        "要用 HTTPS 请把 server.crt / server.key 放进 %s" % DATA_DIR
                    )
                tls = False
        if tls:
            try:
                httpd = _wrap_tls(httpd, cf, kf)
                if LOG_SINK:
                    LOG_SINK("TLS: 已启用 HTTPS（证书 %s）" % cf)
            except Exception as exc:  # noqa: BLE001
                if LOG_SINK:
                    LOG_SINK("TLS: 证书加载失败（%s），退回 HTTP" % exc)
                tls = False

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def make_key() -> str:
    """生成 10 位数字 + 26 位字母的私钥（手机端首次启动用同一算法）。"""
    digits = "".join(secrets.choice("0123456789") for _ in range(10))
    letters = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(26))
    return digits + letters


if __name__ == "__main__":
    p = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            p = int(sys.argv[1])
        except ValueError:
            pass
    srv = start(p, log_sink=lambda m: print(m, flush=True))
    print(f"listening on http://{lan_ip()}:{p}", flush=True)
    print(f"data: {DB_PATH}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()
