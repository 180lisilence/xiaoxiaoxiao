package com.xiaoxiaoxiao.workbench;

import android.webkit.JavascriptInterface;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * 页面与原生层之间的桥（v4）。
 *
 * 参数与返回值都是 JSON 字符串，签名刻意与桌面版 HTTP 接口保持一致，
 * 这样同一份 HTML 在两个平台都能跑。
 *
 * 注意：
 *  · Android 4.2+ 必须加 @JavascriptInterface 注解，否则方法不可见。
 *  · JS Bridge 调用跑在界面线程，联网必须挪到后台，否则会卡 UI。
 *  · d8 (R8 8.2.2) 对匿名内部类会内部崩溃，所以线程体一律用 static 嵌套类实现，
 *    不能写成 new Runnable() { ... } 的形式。
 */
public class LocalBridge {

    private final LocalDb db;
    private final PairStore pair;
    private final SyncEngine sync;

    public LocalBridge(LocalDb db, PairStore pair) {
        this.db = db;
        this.pair = pair;
        this.sync = new SyncEngine(pair);
    }

    // ---------- 数据 ----------
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

    /**
     * 清空数据。页面七个模块底部各有清空入口，电脑端走 POST /api/wipe，
     * 手机端必须能走这里 —— 之前 LocalDb.wipe 有实现但 Bridge 没暴露，
     * 手机端点清空直接报「不是函数」，等于这个功能在手机上完全失效。
     */
    @JavascriptInterface
    public String wipe(String json) {
        return db.wipe(json);
    }

    // ---------- 配对 ----------
    @JavascriptInterface
    public String key() {
        return pair.key();
    }

    @JavascriptInterface
    public String regenerateKey() {
        return pair.regenerateKey();
    }

    @JavascriptInterface
    public String pairInfo() {
        return pair.infoJson();
    }

    @JavascriptInterface
    public String savePair(String host) {
        return pair.savePair(host);
    }

    @JavascriptInterface
    public String deviceName() {
        return pair.deviceName();
    }

    @JavascriptInterface
    public void setDeviceName(String name) {
        pair.setDeviceName(name);
    }

    // ---------- 同步 ----------
    @JavascriptInterface
    public void enqueue(String opJson) {
        pair.enqueue(opJson);
    }

    @JavascriptInterface
    public int queueSize() {
        return pair.queueSize();
    }

    /** 只补推离线队列，不做全量对账。 */
    @JavascriptInterface
    public String flushQueue() {
        return runAsync(new FlushTask(pair), 12);
    }

    /** 补推队列 + 拉全量对账，一次做完。 */
    @JavascriptInterface
    public String syncNow() {
        return runAsync(new SyncTask(db, pair), 20);
    }

    /** 轻量探测：电脑是否可达、有没有待传。 */
    @JavascriptInterface
    public String ping() {
        return runAsync(new PingTask(pair), 6);
    }

    // ------------------------------------------------------------------
    // 后台执行骨架
    // ------------------------------------------------------------------
    /**
     * 在独立线程里跑一个 Task，等它出结果再返回给 JS。
     * 之所以做成 static 嵌套类而不是匿名类，是为了绕开 d8 的内部崩溃。
     */
    private static String runAsync(Task task, int timeoutSec) {
        CountDownLatch latch = new CountDownLatch(1);
        task.latch = latch;
        Thread t = new Thread(task);
        t.setDaemon(true);
        t.start();
        try {
            latch.await(timeoutSec, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        String out = task.result;
        return out == null ? "{\"ok\":false,\"why\":\"timeout\"}" : out;
    }

    /** 可在线程里执行的任务基类。 */
    static abstract class Task implements Runnable {
        CountDownLatch latch;
        volatile String result;

        void finish(String s) {
            result = s;
            if (latch != null) {
                latch.countDown();
            }
        }

        @Override
        public void run() {
            try {
                finish(work());
            } catch (Throwable t) {
                finish("{\"ok\":false,\"why\":\"internal\"}");
            }
        }

        abstract String work();
    }

    /** 只推队列。 */
    static final class FlushTask extends Task {
        private final PairStore pair;

        FlushTask(PairStore pair) {
            this.pair = pair;
        }

        @Override
        String work() {
            return new SyncEngine(pair).flushQueue().toString();
        }
    }

    /** 推队列 + 拉对账。 */
    static final class SyncTask extends Task {
        private final LocalDb db;
        private final PairStore pair;

        SyncTask(LocalDb db, PairStore pair) {
            this.db = db;
            this.pair = pair;
        }

        @Override
        String work() {
            SyncEngine engine = new SyncEngine(pair);
            JSONObject out = new JSONObject();
            try {
                boolean online = engine.reachable();
                out.put("online", online);
                if (!online) {
                    out.put("ok", false);
                    out.put("why", "连不上电脑");
                    out.put("queue", pair.queueSize());
                    return out.toString();
                }
                JSONObject pushed = engine.flushQueue();
                JSONObject pulled = engine.pullAll(db);
                out.put("ok", pulled.optBoolean("ok", false));
                out.put("pushed", pushed.optInt("done", 0));
                out.put("merged", pulled.optInt("merged", 0));
                out.put("queue", pair.queueSize());
            } catch (JSONException e) {
                try {
                    out.put("ok", false);
                } catch (JSONException ignored) {
                    // ignore
                }
            }
            return out.toString();
        }
    }

    /** 可达性探测。 */
    static final class PingTask extends Task {
        private final PairStore pair;

        PingTask(PairStore pair) {
            this.pair = pair;
        }

        @Override
        String work() {
            SyncEngine engine = new SyncEngine(pair);
            JSONObject o = new JSONObject();
            try {
                o.put("configured", engine.configured());
                o.put("queue", pair.queueSize());
                o.put("host", pair.baseUrl());
                o.put("online", engine.reachable());
                // reachable() 只回 true/false，连不上时用户看不到任何线索。
                // 这里补一次带原因的探测：把异常类型或 HTTP 状态码带回去，
                // 页面才能判断是「协议不对」「隧道没开」还是「端口错了」。
                if (!o.optBoolean("online", false)) {
                    o.put("why", engine.lastError());
                }
            } catch (JSONException ignored) {
                // ignore
            }
            return o.toString();
        }
    }
}
