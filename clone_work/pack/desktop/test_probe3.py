# -*- coding: utf-8 -*-
"""桌面壳探针 v3：结果写入文件，避免缓冲丢失。"""
import json
import os
import time

import webview

URL = "https://www.workbuddy.cn/space/d/EQgDGVxmB0oON8dSFfAax9"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_result.json")


def dump(data):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())


def probe(win):
    R = {}
    time.sleep(12)
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
        dump(R)  # 每步落盘，异常也能留证
    dump(R)
    try:
        win.destroy()
    except Exception:  # noqa: BLE001
        pass


dump({"stage": "before_create"})
win = webview.create_window("probe3", URL, width=1200, height=820)
dump({"stage": "created"})
webview.start(probe, win, debug=False, private_mode=False)
dump({"stage": "start_returned"})
