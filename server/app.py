# -*- coding: utf-8 -*-
"""
小笑肖 v4.0.2 —— 电脑端主程序

打开就是一个窗口，显示你的生活工作台。
数据来自本机后端（由「小笑肖-启动器」起服务）；如果后端还没起，
程序会自己先把服务拉起来，让你不至于开不了。

用法：
    直接双击，或从启动器点「打开工作台」。
"""

from __future__ import annotations

import os
import socket
import sys
import time
import urllib.error
import urllib.request

APP_TITLE = "小笑肖 · 生活工作台"
ENTRY_FILE = "index.html"
WEB_DIR_NAME = "_web"
# 版本号不再独立硬编码：直接取后端的，避免「后端 4.0.2、主程序 4.0.1」
# 这种两边对不上的情况。真源只有 server.py 的 VERSION 一处。
import server as backend  # noqa: E402

VERSION = backend.VERSION


def resource_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def web_dir() -> str:
    return os.path.join(resource_root(), WEB_DIR_NAME)


def data_dir() -> str:
    """跟后端共用同一个可写目录（exe 同目录下的 _data），不另开一份。

    以前这里也自己算一遍 %LOCALAPPDATA%\\XiaoXiaoXiao，等于两处代码各写各的。
    现在统一由 server.app_home() 决定，工作台和启动器、后端三方看到的是
    同一个 DB 文件 —— 这也是「启动器起的后端、工作台能直接接管」的前提。
    """
    return backend.data_dir()


CONFIG_PATH = os.path.join(data_dir(), "server.json")


def read_port() -> int:
    """读启动器写下的端口；没写过就用默认的。"""
    try:
        import json

        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        p = int(cfg.get("port") or 0)
        if 1024 < p < 65535:
            return p
    except Exception:  # noqa: BLE001
        pass
    return 8731


def read_use_tls() -> bool:
    """启动器是否开了 HTTPS。工作台自己拉后端时要跟着用同一套协议。"""
    try:
        import json

        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return bool(cfg.get("use_tls"))
    except Exception:  # noqa: BLE001
        return False


def _ssl_ctx():
    """自签证书：本机连自己不用校验，否则 pywebview 会直接打不开。"""
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _port_in_use(port: int) -> bool:
    """端口上有没有人在听。

    为什么不用 bind 判断（踩过的坑）：
    Windows 的 SO_REUSEADDR 语义和 Linux 不同 —— 它允许**同一个端口被
    重复绑定**。而 socketserver 默认开着 allow_reuse_address，
    于是「后端正在 8731 监听」时，我们再去 bind 0.0.0.0:8731 居然也能成功，
    被判成「端口空闲」。后果是工作台以为没后端、又起一份，
    和启动器起的那份抢同一个数据库。

    所以只能真的去 connect。这台机器上连本机关闭端口不会立刻回 RST
    （connect_ex 返回 10035，SYN 无人应答），只能等超时 ——
    那就把超时压到 60ms：回环的 SYN-ACK 是内核立即回的，
    有服务时远小于这个值，没服务时最多浪费 60ms。
    """
    import socket as _socket

    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.settimeout(0.06)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


def probe(port: int, timeout=0.6) -> bool:
    """探活。先判端口有没有人听，再确认是不是我们的服务。

    以前的写法是「HTTP 试一次 0.6s + HTTPS 试一次 0.6s」，
    端口没开时两个都等满超时，单次 1.25 秒；ensure_backend 要扫
    6 个端口、还要扫两轮，光探测就 8.8 秒 —— 双击工作台半天没反应。
    """
    if not _port_in_use(port):
        return False
    for scheme in ("http", "https"):
        try:
            kw = {}
            if scheme == "https":
                kw["context"] = _ssl_ctx()
            with urllib.request.urlopen(
                f"{scheme}://127.0.0.1:{port}/api/ping", timeout=timeout, **kw
            ) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


def ensure_backend() -> int | None:
    """
    确保本机后端在跑。
    已经在跑 → 直接用它；没在跑 → 自己起一个（后台线程），用完随窗口关闭而停。
    返回可用端口；起不来返回 None。

    只起在 127.0.0.1 上，并且跟随启动器的 HTTPS 设置：
    手机要连的时候走的是「启动器」起的那份（0.0.0.0），
    工作台这份只服务本机窗口，不该占着对外端口。
    """
    import server as backend

    # 候选端口：配置里那个 + 默认那个，去重。
    # 启动器每次启动都会把实际端口写回配置，所以 cfg_port 基本就是真身，
    # 没必要一上来扫 6 个 —— 那 6 次 connect 在「端口没开」时都要等满
    # 60ms 超时，白等 0.4 秒。真起不来时下面的启动循环会继续顺延。
    cands = []
    for p in (read_port(), 8731):
        if p and p not in cands:
            cands.append(p)

    for p in cands:
        if probe(p):
            return p

    # 自己拉起来（本机回环，跟随 HTTPS 设置）
    use_tls = read_use_tls()
    for p in cands + [8732, 8733, 8734, 8735]:
        try:
            def _log(msg):
                pass

            httpd = backend.start(p, "127.0.0.1", log_sink=_log, tls=use_tls)
            GLOBAL_SERVER.append(httpd)
            for _ in range(60):
                if probe(p, 0.3):
                    return p
                time.sleep(0.05)
        except OSError:
            continue
    return None


def backend_scheme(port: int) -> str:
    """这个端口到底是 HTTP 还是 HTTPS —— 探一下就知道，比读配置可靠。"""
    try:
        with urllib.request.urlopen(
            f"https://127.0.0.1:{port}/api/ping", timeout=0.6,
            context=_ssl_ctx(),
        ) as r:
            if r.status == 200:
                return "https"
    except Exception:  # noqa: BLE001
        pass
    return "http"


GLOBAL_SERVER = []


def show_error(message: str) -> None:
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
        show_error(f"缺少 WebView 组件：{exc}")
        return 2

    entry = os.path.join(web_dir(), ENTRY_FILE)
    if not os.path.isfile(entry):
        show_error(f"缺少页面资源：{entry}")
        return 3

    port = ensure_backend()
    if not port:
        show_error(
            "本机后端没能启动。\n\n"
            "请先打开「小笑肖-启动器」，配对后再打开工作台。"
        )
        return 4

    url = f"{backend_scheme(port)}://127.0.0.1:{port}/{ENTRY_FILE}"

    # 自检：不建窗口，验证页面与接口是否正常
    if os.environ.get("XXV_SELFTEST") == "1":
        lines = []

        def _log(m):
            lines.append(str(m))

        # 自检统一出口：协议跟着实际后端走，HTTPS 时用宽容的 SSL 上下文，
        # 否则自签证书会让自检自己崩在 CERTIFICATE_VERIFY_FAILED。
        def _open(path, headers=None):
            kw = {"timeout": 8}
            if headers:
                req = urllib.request.Request(path, headers=headers)
            else:
                req = path
            if str(path).startswith("https://"):
                kw["context"] = _ssl_ctx()
            return urllib.request.urlopen(req, **kw)

        try:
            import json as _json

            # 1) 未配对时接口必须 401（这条先测，因为下面要写数据库）
            auth_blocked = False
            try:
                _open(url.replace(ENTRY_FILE, "api/health"))
            except urllib.error.HTTPError as he:
                auth_blocked = (he.code == 401)
            _log(f"auth_guard: {auth_blocked} (expect True)")

            # 2) 从 /api/session 取本机会话私钥 —— 工作台页面走的就是这条路
            key = ""
            try:
                with _open(url.replace(ENTRY_FILE, "api/session")) as r:
                    sess = _json.loads(r.read().decode())
                key = sess.get("key") or ""
            except urllib.error.HTTPError as he:
                _log(f"session: HTTP {he.code}（未配对时 409 属于正常）")
            _log(f"session_key_len: {len(key)}")

            hdr = {"Content-Type": "application/json"}
            if key:
                hdr["X-Pair-Key"] = key

            # 3) 带私钥问 health
            try:
                with _open(url.replace(ENTRY_FILE, "api/health"), hdr) as r:
                    _log(f"health: {r.status} {r.read().decode()[:200]}")
            except urllib.error.HTTPError as he:
                _log(f"health: HTTP {he.code}")

            # 4) 静态页面必须免鉴权可开
            with _open(url) as r:
                body = r.read()
                text = body.decode("utf-8", errors="replace")
            _log(f"page: {r.status} bytes={len(body)}")
            _log(f"adapter: {'__XXV_SOURCE__' in text}")
            _log(f"has_session_api: {'/api/session' in text}")
            _log(f"has_wipe_ui: {'page-wipe-btn' in text}")
            _log(f"charset_in_1024: {b'charset' in body[:1024]}")

            # 5) 带私钥查数据。未配对时这里 401 是**正确行为**，不算失败。
            qreq = urllib.request.Request(
                url.replace(ENTRY_FILE, "api/query"),
                data=_json.dumps(
                    {"databaseId": "tHLWn2tjAvknVD3h5lyWG5", "pageSize": 200}
                ).encode(),
                method="POST",
                headers=hdr,
            )
            qkw = {"timeout": 8}
            if url.startswith("https://"):
                qkw["context"] = _ssl_ctx()
            try:
                with urllib.request.urlopen(qreq, **qkw) as r:
                    data = _json.loads(r.read().decode())
                rows = data.get("results", [])
                _log(f"money_rows: {len(rows)}")
                if rows:
                    _log(f"sample_keys: {sorted(rows[0].keys())}")
            except urllib.error.HTTPError as he:
                if he.code == 401 and not key:
                    _log("money_rows: 未配对，接口按规则拒绝（正常）")
                else:
                    raise
            _log("SELFTEST_DONE")
        except Exception as exc:  # noqa: BLE001
            _log(f"SELFTEST_FAIL: {exc!r}")
        finally:
            try:
                with open(os.path.join(data_dir(), "selftest_v4.log"), "w",
                          encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except Exception:  # noqa: BLE001
                pass
            for s in GLOBAL_SERVER:
                try:
                    s.shutdown()
                except Exception:  # noqa: BLE001
                    pass
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
        # storage_path 必须显式指到 _data 下：WebView2 默认会在系统盘建
        # profile 和缓存目录（%LOCALAPPDATA%\\...\\EBWebView）。操作者要求程序
        # 只在自己的工作目录里落文件，所以这里把内核缓存也一起挪进来。
        webview.start(debug=False, private_mode=True,
                      storage_path=os.path.join(data_dir(), "WebView2"))
    except Exception as exc:  # noqa: BLE001
        show_error(f"启动窗口失败：{exc}")
        return 5
    finally:
        for s in GLOBAL_SERVER:
            try:
                s.shutdown()
                s.server_close()
            except Exception:  # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
