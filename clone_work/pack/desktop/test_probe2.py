# -*- coding: utf-8 -*-
"""桌面壳探针 v2：用 start(func) 官方回调通道抓取页面真实状态。"""
import json
import time

import webview

URL = "https://www.workbuddy.cn/space/d/EQgDGVxmB0oON8dSFfAax9"
R = {}


def probe(win):
    time.sleep(14)
    for key, js in [
        ("href", "location.href"),
        ("title", "document.title"),
        ("sdk_type", "typeof window.__SMART_PAGE__"),
        ("iframe_count", "document.querySelectorAll('iframe').length"),
        ("iframe_src", "(document.querySelector('iframe')||{}).src||''"),
        ("body_len", "document.body?document.body.innerText.length:-1"),
        ("body_text", "document.body?document.body.innerText.slice(0,700):''"),
    ]:
        try:
            R[key] = win.evaluate_js(js)
        except Exception as exc:  # noqa: BLE001
            R[key] = "ERR:" + repr(exc)[:120]
    print("PROBE2 " + json.dumps(R, ensure_ascii=False))
    try:
        win.destroy()
    except Exception:  # noqa: BLE001
        pass


win = webview.create_window("probe2", URL, width=1200, height=820)
webview.start(probe, win, debug=False, private_mode=False)
print("PROBE2_DONE")
