import traceback, webview
try:
    webview.create_window("mini", "https://www.workbuddy.cn/space/d/EQgDGVxmB0oON8dSFfAax9", width=1000, height=700)
    webview.start(debug=False, private_mode=False)
    print("START_OK")
except Exception:
    traceback.print_exc()
