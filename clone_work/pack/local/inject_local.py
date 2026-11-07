# -*- coding: utf-8 -*-
"""生成双模页面：桌面走本地 HTTP API，安卓走 JS Bridge，共用同一份 HTML。"""
import io
import os

SRC = r"E:/gongxiangwenjianjia/xxx/clone_work/build/final.html"
OUT_DESKTOP = r"E:/gongxiangwenjianjia/xxx/clone_work/pack/local/_web/index.html"
OUT_ANDROID = r"E:/gongxiangwenjianjia/xxx/clone_work/pack/android/assets/index.html"

ADAPTER = """<script>
/* ===== 本地数据层适配（独立版·双模） =====
   页面其余代码完全沿用原有写法：window.__SMART_PAGE__.database.xxx(...)
   · 桌面端（Windows exe）：走本机 HTTP 服务 → SQLite
   · 安卓端（APK）：走 JS Bridge → 原生 SQLite
   不联网、不登录、不依赖任何第三方服务。 */
(function () {
  var native = window.AndroidLocal || null;
  var hasBridge = !!(native && typeof native.query === 'function');

  function viaBridge(method, opt) {
    return new Promise(function (resolve, reject) {
      try {
        var raw = native[method](JSON.stringify(opt || {}));
        var obj = JSON.parse(raw);
        if (obj && obj.error) reject(new Error(obj.error));
        else resolve(obj);
      } catch (e) {
        reject(e);
      }
    });
  }

  function viaHttp(path, opt) {
    return fetch(location.origin + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opt || {})
    }).then(function (res) {
      if (!res.ok) {
        return res.text().then(function (t) {
          throw new Error('本地服务返回 ' + res.status + '：' + (t || ''));
        });
      }
      return res.json();
    });
  }

  var impl;
  if (hasBridge) {
    impl = {
      query: function (o) { return viaBridge('query', o); },
      addRecord: function (o) { return viaBridge('add', o); },
      updateRecord: function (o) { return viaBridge('update', o); },
      deleteRecord: function (o) { return viaBridge('delete', o); },
      uploadImage: function (o) { return viaBridge('upload', o); }
    };
  } else {
    impl = {
      query: function (o) { return viaHttp('/api/query', o); },
      addRecord: function (o) { return viaHttp('/api/add', o); },
      updateRecord: function (o) { return viaHttp('/api/update', o); },
      deleteRecord: function (o) { return viaHttp('/api/delete', o); },
      uploadImage: function (o) { return viaHttp('/api/upload', o); }
    };
  }

  window.__SMART_PAGE__ = { database: impl };
})();
</script>
"""

OLD_SAFE_TAIL = """  if (low.indexOf('data:image/webp;base64,') === 0) return raw;
  return '';
}"""

NEW_SAFE_TAIL = """  if (low.indexOf('data:image/webp;base64,') === 0) return raw;
  /* 独立版本地图片：允许本机回环地址 */
  if (low.indexOf('http://127.0.0.1:') === 0) return raw;
  if (low.indexOf('http://localhost:') === 0) return raw;
  return '';
}"""


def build(target):
    with io.open(SRC, encoding="utf-8") as f:
        html = f.read()
    if "__SMART_PAGE__ = {" in html:
        raise SystemExit("源文件已含适配层，请从 build/final.html 重新生成")

    idx = html.find(">", html.find("<head"))
    if html.find("<head") < 0 or idx < 0:
        raise SystemExit("未找到 <head>")
    html = html[: idx + 1] + "\n" + ADAPTER + html[idx + 1 :]

    if OLD_SAFE_TAIL not in html:
        raise SystemExit("safeUrl 结构不符，需人工核对")
    html = html.replace(OLD_SAFE_TAIL, NEW_SAFE_TAIL, 1)

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with io.open(target, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    print("WROTE", target, len(html), "chars")


if __name__ == "__main__":
    build(OUT_DESKTOP)
    build(OUT_ANDROID)
