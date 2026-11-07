# -*- coding: utf-8 -*-
"""桌面壳取数探针：真实启动 WebView，抓取页面加载状态与数据渲染结果。"""
import json
import threading
import time

import webview

URL = "https://www.workbuddy.cn/space/d/EQgDGVxmB0oON8dSFfAax9"
RESULT = {}


def probe(win):
    time.sleep(15)
    try:
        RESULT["href"] = win.evaluate_js("location.href")
        RESULT["title"] = win.evaluate_js("document.title")
        RESULT["has_sdk"] = win.evaluate_js("typeof window.__SMART_PAGE__")
        RESULT["body_len"] = win.evaluate_js("document.body ? document.body.innerText.length : -1")
        RESULT["text"] = win.evaluate_js(
            "document.body ? document.body.innerText.slice(0,900) : ''"
        )
        RESULT["iframes"] = win.evaluate_js("document.querySelectorAll('iframe').length")
        RESULT["iframe_src"] = win.evaluate_js(
            "(document.querySelector('iframe')||{}).src || ''"
        )
    except Exception as exc:  # noqa: BLE001
        RESULT["error"] = repr(exc)
    finally:
        try:
            win.destroy()
        except Exception:  # noqa: BLE001
            pass


win = webview.create_window("probe", URL, width=1200, height=820)
threading.Thread(target=probe, args=(win,), daemon=True).start()
webview.start(debug=False, private_mode=False)

print("PROBE_RESULT " + json.dumps(RESULT, ensure_ascii=False))
