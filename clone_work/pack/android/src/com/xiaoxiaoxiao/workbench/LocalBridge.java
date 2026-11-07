package com.xiaoxiaoxiao.workbench;

import android.webkit.JavascriptInterface;

/**
 * 页面与原生 SQLite 之间的桥。
 *
 * 页面的适配层会通过 window.AndroidLocal.query(...) 等调用这些方法，
 * 参数与返回值都是 JSON 字符串。方法签名刻意与桌面版 HTTP 接口保持一致，
 * 这样同一份 HTML 在两个平台都能跑。
 *
 * 注意：Android 4.2+ 必须加 @JavascriptInterface 注解，否则方法不可见。
 */
public class LocalBridge {

    private final LocalDb db;

    public LocalBridge(LocalDb db) {
        this.db = db;
    }

    @JavascriptInterface
    public String query(String json) {
        return db.query(json);
    }

    @JavascriptInterface
    public String add(String json) {
        return db.add(json);
    }

    @JavascriptInterface
    public String update(String json) {
        return db.update(json);
    }

    @JavascriptInterface
    public String delete(String json) {
        return db.delete(json);
    }

    @JavascriptInterface
    public String upload(String json) {
        return db.upload(json);
    }

    @JavascriptInterface
    public String exportAll() {
        return db.exportAll();
    }
}
