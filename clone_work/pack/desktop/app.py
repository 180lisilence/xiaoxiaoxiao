# -*- coding: utf-8 -*-
"""
小笑肖 —— 在线生活工作台（Windows 桌面端 v2）

v2 变更（关键）：
  页面不再内嵌。桌面端直接加载「资料库阅读器」地址。

为什么必须这样做：
  页面用的 window.__SMART_PAGE__.database SDK 是一个 postMessage 排队代理，
  真实实现必须由父窗口（资料库 iframe sandbox）注入。inject.js 源码开头会检测
  window.self === window.top，若页面被顶层直接打开，会 document.write 安全提示
  并 window.stop() 清空内容。因此桌面壳必须是「打开阅读器」，而不是「打开页面文件」。

数据流向：
  WebView2 → workbuddy.cn 阅读器（父窗口）→ iframe 加载页面 → 注入 database SDK
  → 读写 7 张云端 CSV 表。本地不保存任何业务数据。

登录态：
  private_mode=False 启用持久化 profile，用户首次登录后 cookie 保留。
"""

from __future__ import annotations

import os
import sys

APP_TITLE = "小笑肖 · 在线生活工作台"

# 资料库阅读器地址（父窗口，负责注入 database SDK）
READER_URL = "https://www.workbuddy.cn/space/d/EQgDGVxmB0oON8dSFfAax9"

WINDOW_W = 1220
WINDOW_H = 840
MIN_W = 900
MIN_H = 640


def _show_fallback_window(message: str) -> None:
    """WebView2 不可用时的兜底提示（Tkinter，标准库自带）。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, message)
        root.destroy()
    except Exception:  # noqa: BLE001 - 连 Tk 都没有就只打印
        print(message)


def _data_dir() -> str:
    """持久化目录：放在 %LOCALAPPDATA%，保存 WebView2 profile（登录态）。"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "XiaoXiaoXiao", "WebView2")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:  # noqa: BLE001
        return ""
    return path


def main() -> int:
    try:
        import webview  # 延迟导入，便于给出更友好的错误
    except Exception as exc:  # noqa: BLE001
        _show_fallback_window(
            "缺少 WebView 运行组件，无法启动。\n"
            "请安装 Microsoft Edge WebView2 Runtime 后重试。\n\n"
            f"详细信息：{exc}"
        )
        return 2

    storage = _data_dir()
    if storage:
        try:
            webview.settings["storage_path"] = storage
        except Exception:  # noqa: BLE001 - 老版本无此设置项
            pass

    try:
        webview.create_window(
            APP_TITLE,
            READER_URL,
            width=WINDOW_W,
            height=WINDOW_H,
            min_size=(MIN_W, MIN_H),
            text_select=True,
            confirm_close=False,
            zoomable=True,
        )
        # private_mode=False → 保留 cookie / 登录态
        webview.start(debug=False, private_mode=False)
    except Exception as exc:  # noqa: BLE001
        _show_fallback_window(
            "启动窗口失败。\n\n"
            f"详细信息：{exc}\n\n"
            "可先用浏览器打开下面的地址，确认网络与登录正常：\n"
            f"{READER_URL}"
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
