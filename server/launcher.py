# -*- coding: utf-8 -*-
"""
小笑肖 v4.0.2 —— 后端启动器

一个独立的小窗口程序，只干一件事：管后端。
    · 第一次打开：要你输入一次手机上的 36 位私钥，配对后记住
    · 以后打开：自动放行、自动起服务
    · 显示手机能连的地址、已连接设备、实时日志
    · 随时启停服务；点 × 默认最小化到任务栏，服务继续跑（不常驻系统服务、不开机自启）

配对是怎么校验的：
    你输入的私钥 → SHA-256 → 与本机保存的哈希比对。
    本机不存私钥明文，只存哈希；私钥本身永远留在手机上，不上网。
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import server as backend

APP_TITLE = "小笑肖 · 后端启动器"
VER = backend.VERSION

# ---------------------------------------------------------------- 保活协作标记
# 外层 启动.bat 负责「进程没了就拉起来」，但它有两个信息拿不到：
#   1. GUI 程序（windowed exe）在批处理里 start 之后拿不到退出码
#   2. 分不清「用户主动退出」和「崩了」
# 所以这里落两个文件跟 bat 对话：
#   launcher.pid   —— 当前进程号，bat 用它做 tasklist 精确判断（PID 是纯数字，
#                     绕开中文文件名在控制台的编码坑）
#   .clean_exit    —— 只有走正常关闭路径才会写，bat 见到它就不再重启
PID_FILE = os.path.join(backend.DATA_DIR, "launcher.pid")
CLEAN_EXIT_FILE = os.path.join(backend.DATA_DIR, ".clean_exit")
# 心跳文件：启动器每 2 秒往里写一个递增数字，外层 bat 采样两次比对。
# 为什么用心跳而不是让 bat 去 tasklist 查进程 —— 实测过：bat 里
#   tasklist /FI "PID eq xxx" | find "xxx"
# 会误判成「进程已退出」（tasklist 走管道时中文进程名乱码，find 匹配不上），
# 于是 bat 每 2 秒重启一次，几下就叠出好几个进程抢同一个端口。
# 纯文件读写不经过任何外部命令，没有编码问题。
HEARTBEAT_FILE = os.path.join(backend.DATA_DIR, "heartbeat")
HEARTBEAT_MS = 2_000

HEALTH_INTERVAL_MS = 10_000   # 后端多久探一次
HEALTH_MAX_FAIL = 3           # 连续几次无响应就判定后端死了

BG = "#F5F0E8"
CARD = "#FFFDF9"
INK = "#2C2A26"
MUTED = "#8A857B"
LINE = "#E2DACB"
OK = "#2F7A52"
WARN = "#B4761F"
BAD = "#B04A3E"
ACCENT = "#3D5A6C"


def _font(size=10, bold=False):
    family = "Microsoft YaHei UI"
    return (family, size, "bold" if bold else "normal")


# --------------------------------------------------------------------------
# 公网地址（Cloudflare 快速隧道）
# --------------------------------------------------------------------------
# 为什么用 cloudflared 而不是继续折腾 SakuraFrp：
#   · Sakura 内地节点跑明文 HTTP 会被合规拦截（回 501）
#   · 它的 TCP 隧道又不做 TLS 终结，HTTPS 也过不去
#   · 换非内地节点后实测节点能连、但流量转不下来
#   · HTTP 类型隧道要绑定域名，还要备案
#
#   cloudflared 的「快速隧道」一条命令就够，而且：
#     - 不需要注册账号
#     - 不需要域名
#     - 自动给 https://xxx.trycloudflare.com（真证书，手机端零警告）
#     - TLS 由 Cloudflare 边缘终结，回源用明文 HTTP，
#       所以不受「内地节点跑 HTTP」那类限制
#
#   代价：地址是随机的，重建一次变一次。所以界面上要能一键复制。

TUNNEL_URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")


class QuickTunnel:
    """管一个 cloudflared 快速隧道进程。"""

    def __init__(self, port: int, on_url, on_log):
        self.port = port
        self.on_url = on_url      # 回调：拿到地址（主线程安全由调用方保证）
        self.on_log = on_log      # 回调：写一行日志
        self.proc = None
        self.url = ""
        self._reader = None

    @staticmethod
    def find_binary() -> str:
        """找 cloudflared.exe：exe 同目录 → _cf → 上一级 _cf → PATH。"""
        if getattr(sys, "frozen", False):
            here = os.path.dirname(os.path.abspath(sys.executable))
        else:
            here = os.path.dirname(os.path.abspath(__file__))
        cands = [
            os.path.join(here, "cloudflared.exe"),
            os.path.join(here, "_cf", "cloudflared.exe"),
            os.path.join(os.path.dirname(here), "_cf", "cloudflared.exe"),
            os.path.join(os.path.dirname(here), "cloudflared.exe"),
        ]
        for p in cands:
            if os.path.isfile(p):
                return p
        return shutil.which("cloudflared") or ""

    def start(self) -> bool:
        if self.proc is not None:
            return True
        exe = self.find_binary()
        if not exe:
            self.on_log("没找到 cloudflared.exe，跳过公网地址")
            return False
        cmd = [exe, "tunnel", "--url", "http://127.0.0.1:%d" % self.port,
               "--no-autoupdate"]
        flags = 0
        if os.name == "nt":
            # CREATE_NO_WINDOW：别弹出黑框cmd
            flags = 0x08000000
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
                # cwd 指到 _data，不放 exe 目录：
                # cloudflared 会在 cwd 建一个空的 config.yml（内容就一个 {}），
                # 放在 启动器\ 里会跟 exe 混在一起，看着像垃圾文件。
                cwd=backend.DATA_DIR,
            )
        except Exception as exc:  # noqa: BLE001
            self.on_log("公网地址启动失败：%s" % exc)
            self.proc = None
            return False
        self.on_log("正在申请公网地址…")
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True

    def _read_loop(self):
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for raw in iter(proc.stdout.readline, b""):
            try:
                line = raw.decode("utf-8", "replace").rstrip()
            except Exception:  # noqa: BLE001
                continue
            if not line:
                continue
            if not self.url:
                m = TUNNEL_URL_RE.search(line)
                if m:
                    self.url = m.group(0)
                    self.on_url(self.url)
                    continue
            # 只把真正的错误往上抛，正常日志太吵
            low = line.lower()
            if " err " in low or "failed" in low or "unable" in low:
                self.on_log("隧道：" + line[-140:])

    def stop(self):
        proc = self.proc
        self.proc = None
        self.url = ""
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("620x740")
        self.minsize(560, 680)
        self.configure(bg=BG)

        self.httpd = None
        self.tunnel = None
        self.port = backend.DEFAULT_PORT
        self.logq: "queue.Queue[str]" = queue.Queue()
        self.cfg = backend.load_config()
        self._health_fail = 0

        self._build()
        self._pump_logs()
        self.after(200, self._after_start)
        self._announce_running()
        self.after(HEALTH_INTERVAL_MS, self._health_check)

    # ------------------------------------------------------------------
    # 保活：跟外层 启动.bat 的握手 + 后端心跳自愈
    # ------------------------------------------------------------------
    def _announce_running(self):
        """告诉外层 bat「我起来了」，并清掉上次留下的正常退出标记。"""
        try:
            with open(CLEAN_EXIT_FILE, "r", encoding="utf-8"):
                pass
            os.remove(CLEAN_EXIT_FILE)
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001
            pass
        try:
            with open(PID_FILE, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except Exception:  # noqa: BLE001
            pass
        self._beat_seq = 0
        self._beat()

    def _beat(self):
        """心跳：每 2 秒把递增数字写进 heartbeat，外层 bat 靠它判活。"""
        try:
            self._beat_seq = getattr(self, "_beat_seq", 0) + 1
            with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
                f.write("%d\n" % self._beat_seq)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.after(HEARTBEAT_MS, self._beat)
        except Exception:  # noqa: BLE001
            pass  # 窗口已销毁，定时器自然停

    def _mark_clean_exit(self):
        """正常退出时留痕，bat 见到就不重启；崩溃时不会执行到这里。"""
        try:
            with open(CLEAN_EXIT_FILE, "w", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:  # noqa: BLE001
            pass
        for p in (PID_FILE, HEARTBEAT_FILE):
            try:
                os.remove(p)
            except Exception:  # noqa: BLE001
                pass

    def _health_check(self):
        """后端心跳。窗口还开着但服务线程死了，手机就连不上 —— 这里自愈。

        为什么需要它：后端跑在启动器进程内的线程里，线程抛异常退出时
        进程不会退出，窗口看起来一切正常，实际上端口已经没人监听了。
        光靠外层 bat 保活救不了这种情况，必须在进程内部探。
        """
        try:
            if self.httpd is not None:
                if self._ping_backend():
                    if self._health_fail:
                        self._log("后端恢复响应（之前失败 %d 次）" % self._health_fail)
                    self._health_fail = 0
                else:
                    self._health_fail += 1
                    self._log("后端无响应 %d/%d" % (self._health_fail, HEALTH_MAX_FAIL))
                    if self._health_fail >= HEALTH_MAX_FAIL:
                        self._health_fail = 0
                        self._restart_backend()
        except Exception as exc:  # noqa: BLE001
            self._log("心跳自检异常：%s" % exc)
        finally:
            self.after(HEALTH_INTERVAL_MS, self._health_check)

    def _ping_backend(self) -> bool:
        scheme = "https" if bool(self.tls_var.get()) else "http"
        kw = {}
        if scheme == "https":
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kw["context"] = ctx
        try:
            with urllib.request.urlopen(
                "%s://127.0.0.1:%d/api/ping" % (scheme, self.port),
                timeout=2.5, **kw
            ) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            return False

    def _restart_backend(self):
        """把死掉的后端重新拉起来，端口沿用原来的。"""
        self._log("后端连续无响应，正在自动重启…")
        old = self.httpd
        self.httpd = None
        if old is not None:
            try:
                old.shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                old.server_close()
            except Exception:  # noqa: BLE001
                pass
        self.addr_var.set("—")
        self._set_pill("● 重启中", WARN)
        # shutdown 会等 serve_forever 收尾，给它一点时间再重绑端口
        self.after(800, self._auto_restart)

    def _auto_restart(self):
        """真正重绑端口。走 _start() 是为了复用它那套「端口被占就顺延」的逻辑。"""
        if not backend.is_paired():
            self._log("未配对，无法自动重启后端")
            self._set_pill("● 未配对", MUTED)
            return
        self._log("重新监听（端口沿用 %d）" % self.port)
        self._start()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 8))

        tk.Label(head, text="小笑肖 · 后端启动器", bg=BG, fg=INK,
                 font=_font(13, True)).pack(side="left")
        tk.Label(head, text="v" + VER, bg=BG, fg=MUTED,
                 font=_font(9)).pack(side="left", padx=(8, 0))

        self.pill = tk.Label(head, text="● 未启动", bg=BG, fg=MUTED, font=_font(9))
        self.pill.pack(side="right")

        # 配对区
        self.pair_box = tk.Frame(self, bg=CARD, highlightbackground=LINE,
                                 highlightthickness=1)
        self.pair_box.pack(fill="x", padx=18, pady=(0, 10))

        inner = tk.Frame(self.pair_box, bg=CARD)
        inner.pack(fill="x", padx=16, pady=14)

        tk.Label(inner, text="第一次使用：配一次对", bg=CARD, fg=INK,
                 font=_font(11, True)).pack(anchor="w")
        tk.Label(inner,
                 text="打开手机小笑肖 →「连接信息」页 → 复制那条 36 位私钥，粘到下面。\n"
                      "只需配一次，以后打开会自动放行。",
                 bg=CARD, fg=MUTED, font=_font(9), justify="left").pack(anchor="w", pady=(4, 10))

        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x")

        self.key_var = tk.StringVar()
        self.key_entry = tk.Entry(row, textvariable=self.key_var, font=("Consolas", 10),
                                  bg="#FFFFFF", fg=INK, relief="flat",
                                  highlightbackground=LINE, highlightthickness=1)
        self.key_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        self.key_entry.bind("<Return>", lambda e: self._do_pair())

        tk.Button(row, text="配对并启动", command=self._do_pair,
                  bg=ACCENT, fg="#FFFFFF", relief="flat", font=_font(9, True),
                  activebackground=ACCENT, activeforeground="#FFFFFF",
                  cursor="hand2", padx=14, pady=4).pack(side="left")

        self.pair_hint = tk.Label(inner, text="", bg=CARD, fg=BAD, font=_font(9))
        self.pair_hint.pack(anchor="w", pady=(8, 0))

        # 主区
        self.main_box = tk.Frame(self, bg=CARD, highlightbackground=LINE,
                                 highlightthickness=1)
        self.main_box.pack(fill="both", expand=True, padx=18, pady=(0, 10))

        m = tk.Frame(self.main_box, bg=CARD)
        m.pack(fill="both", expand=True, padx=16, pady=12)

        # 地址
        tk.Label(m, text="手机端填这个地址", bg=CARD, fg=MUTED,
                 font=_font(9)).pack(anchor="w")
        addr_row = tk.Frame(m, bg=CARD)
        addr_row.pack(fill="x", pady=(3, 10))
        self.addr_var = tk.StringVar(value="—")
        self.addr_label = tk.Label(addr_row, textvariable=self.addr_var, bg="#F1ECE2",
                                   fg=INK, font=("Consolas", 10), anchor="w",
                                   padx=9, pady=6)
        self.addr_label.pack(side="left", fill="x", expand=True)
        tk.Button(addr_row, text="复制", command=self._copy_addr,
                  bg=CARD, fg=ACCENT, relief="flat", font=_font(8),
                  cursor="hand2", padx=8).pack(side="left", padx=(6, 0))

        # 公网地址（不在同一 Wi-Fi 时用这个）
        pub_row = tk.Frame(m, bg=CARD)
        pub_row.pack(fill="x", pady=(0, 10))
        self.pub_var = tk.StringVar(value="公网地址：未启用")
        self.pub_label = tk.Label(pub_row, textvariable=self.pub_var, bg="#F1ECE2",
                                  fg=MUTED, font=("Consolas", 9), anchor="w",
                                  padx=9, pady=6)
        self.pub_label.pack(side="left", fill="x", expand=True)
        self.btn_pub_copy = tk.Button(pub_row, text="复制", command=self._copy_pub,
                                      bg=CARD, fg=ACCENT, relief="flat",
                                      font=_font(8), cursor="hand2", padx=8,
                                      state="disabled")
        self.btn_pub_copy.pack(side="left", padx=(6, 0))

        self.tunnel_var = tk.BooleanVar(
            value=bool(backend.load_config().get("tunnel_enabled")))
        self.chk_tunnel = tk.Checkbutton(
            m, text="生成公网地址（手机不在同一 Wi-Fi 时勾上）",
            variable=self.tunnel_var, command=self._on_tunnel_toggle,
            bg=CARD, fg=INK, activebackground=CARD, font=_font(9),
            cursor="hand2", anchor="w")
        self.chk_tunnel.pack(anchor="w", pady=(0, 8))

        # 设备
        dev_head = tk.Frame(m, bg=CARD)
        dev_head.pack(fill="x")
        tk.Label(dev_head, text="已连接设备", bg=CARD, fg=MUTED,
                 font=_font(9)).pack(side="left")
        self.dev_count = tk.Label(dev_head, text="0 台", bg=CARD, fg=MUTED,
                                  font=_font(9))
        self.dev_count.pack(side="right")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Dev.Treeview", background="#FFFFFF", fieldbackground="#FFFFFF",
                        foreground=INK, borderwidth=0, font=_font(9), rowheight=24)
        style.configure("Dev.Treeview.Heading", background="#F1ECE2", foreground=MUTED,
                        font=_font(8), borderwidth=0)
        style.layout("Dev.Treeview", [("Dev.Treeview.treearea", {"sticky": "nswe"})])

        self.tree = ttk.Treeview(m, columns=("name", "ip", "seen"), show="headings",
                                 height=3, style="Dev.Treeview")
        self.tree.heading("name", text="设备")
        self.tree.heading("ip", text="地址")
        self.tree.heading("seen", text="最近")
        self.tree.column("name", width=180, anchor="w")
        self.tree.column("ip", width=120, anchor="w")
        self.tree.column("seen", width=90, anchor="w")
        self.tree.pack(fill="x", pady=(3, 10))

        # 日志
        tk.Label(m, text="运行日志", bg=CARD, fg=MUTED,
                 font=_font(9)).pack(anchor="w")
        log_wrap = tk.Frame(m, bg=CARD)
        log_wrap.pack(fill="both", expand=True, pady=(3, 0))
        self.log_text = tk.Text(log_wrap, height=8, bg="#F1ECE2", fg="#4A463E",
                                relief="flat", font=("Consolas", 8),
                                wrap="none", state="disabled", padx=8, pady=6)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(log_wrap, command=self.log_text.yview, width=10)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set)

        # 按钮
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=18, pady=(0, 16))

        self.btn_start = tk.Button(btn_row, text="启动服务", command=self._start,
                                   bg=ACCENT, fg="#FFFFFF", relief="flat",
                                   font=_font(9, True), cursor="hand2", pady=5)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_stop = tk.Button(btn_row, text="停止服务", command=self._stop,
                                  bg="#E7E1D5", fg=INK, relief="flat",
                                  font=_font(9), cursor="hand2", pady=5)
        self.btn_stop.pack(side="left", fill="x", expand=True, padx=5)

        tk.Button(btn_row, text="重新配对", command=self._unpair,
                  bg="#E7E1D5", fg=INK, relief="flat", font=_font(9),
                  cursor="hand2", pady=5).pack(side="left", fill="x", expand=True, padx=(5, 0))

        # HTTPS 开关
        # 内网穿透（SakuraFrp 等）对内地 TCP 隧道跑明文 HTTP 有合规拦截，
        # 会直接回 501。开了这个开关后端自己持证书，隧道那头就能过检。
        tls_row = tk.Frame(self, bg=BG)
        tls_row.pack(fill="x", padx=18, pady=(0, 10))
        self.tls_var = tk.BooleanVar(
            value=bool(backend.load_config().get("use_tls")))
        self.chk_tls = tk.Checkbutton(
            tls_row, text="启用 HTTPS（内网穿透时打开；局域网直连可不打开）",
            variable=self.tls_var, command=self._on_tls_toggle,
            bg=BG, fg=INK, activebackground=BG, font=_font(9),
            cursor="hand2", anchor="w")
        self.chk_tls.pack(side="left")

        # 未配对时把主区藏起来
        if not backend.is_paired():
            self.main_box.pack_forget()
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            self.after(120, lambda: self.key_entry.focus_set())
        else:
            self.pair_box.pack_forget()

    # ------------------------------------------------------------------
    # 启动行为
    # ------------------------------------------------------------------
    def _after_start(self):
        if backend.is_paired():
            self._log("已配对 · 自动启动")
            self._start()

    # ------------------------------------------------------------------
    # 配对
    # ------------------------------------------------------------------
    def _do_pair(self):
        raw = self.key_var.get().strip().replace(" ", "").replace("-", "")
        if not raw:
            self._pair_fail("请先粘贴私钥")
            return
        if len(raw) != 36:
            self._pair_fail("私钥应为 36 位，当前 %d 位" % len(raw))
            return
        if not raw[:10].isdigit() or not raw[10:].isalpha():
            self._pair_fail("格式不对：前 10 位要数字，后 26 位要字母")
            return
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        # 明文不落盘（磁盘上只有 sha256），但要交给后端进程内存 ——
        # 工作台页面靠它调 /api/*，否则改造后所有接口都是 401。
        backend.set_pair_hash(h, raw)
        self.key_var.set("")
        self._pair_fail("")
        self.pair_box.pack_forget()
        self.main_box.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="normal")
        self._log("配对成功 · 私钥哈希已保存，明文未落盘")
        self._start()

    def _pair_fail(self, msg):
        self.pair_hint.configure(text=msg)

    def _unpair(self):
        if not messagebox.askyesno("重新配对",
                                   "清掉已保存的配对信息？\n\n"
                                   "清掉后服务会停止，需要重新输入手机上那把私钥。"):
            return
        self._stop()
        cfg = backend.load_config()
        cfg.pop("key_hash", None)
        cfg.pop("paired_at", None)
        cfg.pop("key_sealed", None)
        backend.save_config(cfg)
        backend.set_local_key("", persist=False)
        self.main_box.pack_forget()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self.pair_box.pack(fill="x", padx=18, pady=(0, 10))
        self._log("已清除配对 · 服务已停止")
        self._set_pill("● 未配对", MUTED)
        self.after(120, lambda: self.key_entry.focus_set())

    # ------------------------------------------------------------------
    # 服务控制
    # ------------------------------------------------------------------
    def _start(self):
        if self.httpd is not None:
            self._log("服务已在运行")
            return
        if not backend.is_paired():
            self._log("未配对，拒绝启动")
            return
        use_tls = bool(self.tls_var.get())
        try:
            self.httpd = backend.start(self.port, "0.0.0.0",
                                       log_sink=self._log, tls=use_tls)
        except OSError as exc:
            # 端口被占时往后顺延找一个可用的
            ok = False
            for p in range(self.port + 1, self.port + 20):
                try:
                    self.httpd = backend.start(p, "0.0.0.0",
                                               log_sink=self._log, tls=use_tls)
                    self.port = p
                    ok = True
                    break
                except OSError:
                    continue
            if not ok:
                messagebox.showerror(APP_TITLE, "端口都被占用，服务起不来。\n\n%s" % exc)
                return
        ip = backend.lan_ip()
        scheme = "https" if use_tls else "http"
        self.addr_var.set("%s:%d" % (ip, self.port))
        # 把端口写进配置，工作台主程序打开时按这个端口找后端
        cfg = backend.load_config()
        cfg["port"] = self.port
        cfg["use_tls"] = use_tls
        backend.save_config(cfg)
        self._set_pill("● 运行中", OK)
        self._log("监听 0.0.0.0:%d（%s）" % (self.port, scheme))
        self._log("局域网地址 %s://%s:%d" % (scheme, ip, self.port))
        self._log("数据库 %s" % backend.DB_PATH)
        if use_tls:
            self._log("HTTPS 已开启 · 证书 %s" % backend.CERT_FILE)
            self._log("自签证书手机首次访问会提示不安全，选择「继续」即可")
        self._refresh_devices()
        if bool(self.tunnel_var.get()):
            self._start_tunnel()
        else:
            self._set_pub("公网地址：未启用")

    def _on_tls_toggle(self):
        on = bool(self.tls_var.get())
        cfg = backend.load_config()
        cfg["use_tls"] = on
        backend.save_config(cfg)
        if self.httpd is not None:
            self._stop()
            self._log("已切换 HTTPS 设置，正在按新设置重启服务…")
            self.after(400, self._start)
        else:
            self._log("HTTPS %s" % ("已开启" if on else "已关闭"))

    def _stop(self):
        if self.httpd is None:
            self._log("服务未运行")
            return
        # 先断公网，再关后端：反过来的话隧道会短暂指向一个已关闭的端口
        self._stop_tunnel()
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:  # noqa: BLE001
            pass
        self.httpd = None
        self.addr_var.set("—")
        self._set_pill("● 已停止", MUTED)
        self._log("服务已停止")

    def _set_pill(self, text, color):
        self.pill.configure(text=text, fg=color)

    def _copy_addr(self):
        val = self.addr_var.get()
        if not val or val == "—":
            return
        self.clipboard_clear()
        self.clipboard_append(val)
        self._log("地址已复制到剪贴板")

    def _copy_pub(self):
        if self.tunnel is None or not self.tunnel.url:
            return
        self.clipboard_clear()
        self.clipboard_append(self.tunnel.url)
        self._log("公网地址已复制")

    # ------------------------------------------------------------------
    # 公网地址（Cloudflare 快速隧道）
    # ------------------------------------------------------------------
    def _set_pub(self, text, color=MUTED):
        self.pub_var.set(text)
        self.pub_label.configure(fg=color)

    def _on_tunnel_toggle(self):
        on = bool(self.tunnel_var.get())
        cfg = backend.load_config()
        cfg["tunnel_enabled"] = on
        backend.save_config(cfg)
        if not on:
            self._stop_tunnel()
            self._set_pub("公网地址：未启用")
            return
        if self.httpd is None:
            self._set_pub("公网地址：先启动服务")
            return
        self._start_tunnel()

    def _start_tunnel(self):
        if self.tunnel is not None and self.tunnel.proc is not None:
            return
        self._set_pub("公网地址：申请中…", WARN)

        def on_url(url):
            # 回调发生在读取线程，UI 操作必须回主线程
            self.after(0, lambda: self._tunnel_ready(url))

        self.tunnel = QuickTunnel(self.port, on_url, self._log)
        if not self.tunnel.start():
            self._set_pub("公网地址：缺少 cloudflared.exe", BAD)
            self.tunnel = None

    def _tunnel_ready(self, url):
        self._set_pub(url, OK)
        self.btn_pub_copy.configure(state="normal")
        self._log("公网地址已就绪：%s" % url)
        self._log("手机不在同一 Wi-Fi 时，填这个地址（要带 https://）")
        # 记到配置里：下次打开能显示上次的地址，也方便排查
        try:
            cfg = backend.load_config()
            cfg["tunnel_url"] = url
            backend.save_config(cfg)
        except Exception:  # noqa: BLE001
            pass

    def _stop_tunnel(self):
        if self.tunnel is not None:
            self.tunnel.stop()
            self.tunnel = None
        self.btn_pub_copy.configure(state="disabled")
        self._set_pub("公网地址：未启用")

    # ------------------------------------------------------------------
    # 设备与日志
    # ------------------------------------------------------------------
    def _refresh_devices(self):
        try:
            devs = backend.list_devices()
        except Exception:  # noqa: BLE001
            devs = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        now = int(time.time() * 1000)
        for d in devs[:20]:
            name = d.get("name") or d.get("platform") or "未知设备"
            ip = d.get("last_ip") or ""
            delta = max(0, now - int(d.get("last_seen") or now))
            if delta < 60_000:
                seen = "刚刚"
            elif delta < 3_600_000:
                seen = "%d 分钟前" % (delta // 60_000)
            elif delta < 86_400_000:
                seen = "%d 小时前" % (delta // 3_600_000)
            else:
                seen = "%d 天前" % (delta // 86_400_000)
            self.tree.insert("", "end", values=(name, ip, seen))
        self.dev_count.configure(text="%d 台" % len(devs))
        if self.httpd is not None:
            self.after(3000, self._refresh_devices)

    def _log(self, msg: str):
        stamp = time.strftime("%H:%M:%S")
        self.logq.put("%s  %s" % (stamp, msg))

    def _pump_logs(self):
        lines = []
        while True:
            try:
                lines.append(self.logq.get_nowait())
            except queue.Empty:
                break
        if lines:
            self.log_text.configure(state="normal")
            for ln in lines:
                self.log_text.insert("end", ln + "\n")
            # 只保留最近 500 行
            total = int(self.log_text.index("end-1c").split(".")[0])
            if total > 500:
                self.log_text.delete("1.0", "%d.0" % (total - 500))
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(400, self._pump_logs)

    # ------------------------------------------------------------------
    def on_close(self):
        """点窗口右上角 × 时的行为。

        以前是「窗口一关就停服务」，实测这会直接踢掉手机 ——
        配置里留着 tunnel_url，对应的隧道却是 530（隧道进程已死），
        原因就是关过一次窗口，或者手滑点了 ×。

        「即关即停」的本意是不要装成系统服务常驻、不要开机自启，
        不是「手滑点一下 × 就把手机踢下线」。所以改成三选一：
            是   → 最小化到任务栏，后端和隧道继续跑（双击任务栏图标回来）
            否   → 真的退出，服务全停
            取消 → 什么都不做
        """
        running = self.httpd is not None or self.tunnel is not None
        if not running:
            self.destroy()
            return
        ans = messagebox.askyesnocancel(
            APP_TITLE,
            "服务正在运行，手机正连着它。\n\n"
            "【是】最小化到任务栏 —— 手机继续连接\n"
            "【否】退出并停止服务 —— 手机立即断开\n"
            "【取消】什么都不做",
            icon="question",
            default="yes",
        )
        if ans is True:
            self.iconify()
            self._log("已最小化到任务栏，服务与隧道继续运行；双击任务栏图标可恢复窗口")
        elif ans is False:
            self._log("正在退出并停止服务…")
            self.destroy()
        else:
            self._log("已取消关闭")

    def destroy(self):
        # 真正退出时才停：不常驻系统服务、不装开机自启
        # 先落「正常退出」标记 —— 外层的 启动.bat 靠它区分「用户主动关的」
        # 和「进程崩了」，只有后者才会被重新拉起来。
        self._mark_clean_exit()
        # 隧道进程也要一起收掉，否则 cloudflared 会变孤儿继续占着那条隧道
        try:
            if self.tunnel is not None:
                self.tunnel.stop()
                self.tunnel = None
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.httpd is not None:
                self.httpd.shutdown()
                self.httpd.server_close()
                self.httpd = None
        except Exception:  # noqa: BLE001
            pass
        super().destroy()


def _pid_alive(pid: int) -> bool:
    """这个 PID 对应的进程还活着吗（Windows 上用它判断单实例）。

    不用 os.kill(pid, 0)：那是 POSIX 语义，Windows 上会真发信号。
    用 OpenProcess 探一下，拿到句柄就说明进程在。
    """
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name != "nt":
        return False
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:  # noqa: BLE001
        return False


def _running_instance_pid() -> int:
    """已经有实例在跑就返回它的 PID，否则 0。"""
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            pid = int((f.read() or "0").strip())
    except Exception:  # noqa: BLE001
        return 0
    return pid if _pid_alive(pid) else 0


def _warn(text: str):
    """不依赖 tkinter 的提示框（单实例判断要赶在任何窗口创建之前）。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, APP_TITLE, 0x40)
    except Exception:  # noqa: BLE001
        print(text)


def main() -> int:
    # 单实例：Windows 的 SO_REUSEADDR 允许重复绑定同一端口，第二个实例
    # bind 0.0.0.0:8731 也会「成功」。后果是两个进程同时监听、各起一条隧道、
    # 抢同一个 SQLite —— 用户双击两次 启动.bat 就会撞上这个。
    other = _running_instance_pid()
    if other:
        _warn("小笑肖启动器已经在运行了（PID %d）。\n\n"
              "不用再开一个：窗口可能被最小化到任务栏了，点任务栏图标就能恢复。\n"
              "如果确实要重开，先在启动器里点「停止服务」再退出。" % other)
        return 0
    app = Launcher()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
