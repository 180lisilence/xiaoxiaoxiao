package com.xiaoxiaoxiao.workbench;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.Charset;

/**
 * 手机 → 电脑后端的同步通道。
 *
 * 设计要点：
 * · 只在「界面要刷新」和「队列有东西要补推」时联网，不常驻轮询。
 * · 网络调用一律放到后台线程，界面线程不阻塞。
 * · 服务器地址来自 PairStore，你只填一次。
 */
public final class SyncEngine {

    private static final Charset UTF8 = Charset.forName("UTF-8");
    private static final int TIMEOUT_MS = 4000;

    private final PairStore pair;

    /** 最近一次探测/请求的失败原因，供界面上给用户看。 */
    private volatile String lastError = "";

    public SyncEngine(PairStore pair) {
        this.pair = pair;
    }

    /** 最近一次失败原因（空串表示没失败过）。 */
    public String lastError() {
        return lastError == null ? "" : lastError;
    }

    /** 是否配置过地址。 */
    public boolean configured() {
        return pair.hasHost();
    }

    /** 极轻量探测：连得上就 true。 */
    public boolean reachable() {
        if (!configured()) {
            lastError = "还没填电脑地址";
            return false;
        }
        try {
            JSONObject o = get("/api/ping");
            boolean ok = o != null && o.optBoolean("ok", false);
            if (ok) {
                lastError = "";
            } else if (o == null) {
                if (lastError.length() == 0) {
                    lastError = "没有响应（服务端未返回内容）";
                }
            } else {
                lastError = "返回内容不是预期的 ping 响应";
            }
            return ok;
        } catch (Exception e) {
            // 把异常类名也带上：UnknownHostException = 域名解析不了（隧道地址打错），
            // SSLHandshakeException = https 地址却用了 http（或反之），
            // ConnectException = 端口不通（隧道没启动 / 防火墙拦）。
            lastError = describe(e);
            return false;
        }
    }

    /** 把异常翻译成一句人能看懂的话。 */
    private static String describe(Exception e) {
        String cls = e.getClass().getSimpleName();
        String msg = e.getMessage() == null ? "" : e.getMessage();
        if (cls.contains("UnknownHost")) {
            return "域名解析不了（" + msg + "）—— 地址拼错了，或穿透隧道域名不对";
        }
        if (cls.contains("SSLHandshake") || cls.contains("SSLException")
                || cls.contains("Certificate")) {
            return "TLS 握手失败（" + msg + "）—— HTTPS 地址和协议对不上，检查是否漏了 https://";
        }
        if (cls.contains("ConnectException")) {
            return "连不上端口（" + msg + "）—— 隧道没启动、端口填错，或被防火墙拦住";
        }
        if (cls.contains("SocketTimeout")) {
            return "连接超时（" + msg + "）—— 网络不通，或穿透线路太慢";
        }
        if (cls.contains("CleartextHTTP")) {
            return "明文 HTTP 被系统拦截 —— 需要改用 https 地址";
        }
        return cls + (msg.length() > 0 ? "：" + msg : "");
    }

    /** 把队列里的写操作一次性推上去；成功才清队列。 */
    public JSONObject flushQueue() {
        JSONObject out = new JSONObject();
        try {
            if (!configured()) {
                out.put("ok", false);
                out.put("why", "未设置电脑地址");
                return out;
            }
            JSONArray ops = new JSONArray(pair.takeQueue());
            if (ops.length() == 0) {
                out.put("ok", true);
                out.put("done", 0);
                return out;
            }
            JSONObject req = new JSONObject();
            req.put("ops", ops);
            req.put("deviceId", pair.deviceId());
            req.put("deviceName", pair.deviceName());
            req.put("devicePlatform", "android");
            JSONObject res = post("/api/sync", req);
            if (res != null && res.optBoolean("ok", false)) {
                pair.clearQueue();
            } else {
                // 有失败项就不清队列，下次重试
                out.put("ok", false);
                out.put("why", "服务端拒绝了部分操作");
                return res == null ? out : res;
            }
            return res == null ? out : res;
        } catch (Exception e) {
            try {
                out.put("ok", false);
                out.put("why", String.valueOf(e.getMessage()));
            } catch (JSONException ignored) {
                // ignore
            }
            return out;
        }
    }

    /** 从电脑端拉全量，合并进本地库。 */
    public JSONObject pullAll(LocalDb db) {
        JSONObject out = new JSONObject();
        try {
            JSONObject req = new JSONObject();
            req.put("deviceId", pair.deviceId());
            req.put("deviceName", pair.deviceName());
            req.put("devicePlatform", "android");
            JSONObject res = post("/api/changes", req, "?since=0");
            if (res == null) {
                out.put("ok", false);
                out.put("why", "无响应");
                return out;
            }
            JSONArray changes = res.optJSONArray("changes");
            if (changes == null) {
                out.put("ok", true);
                out.put("merged", 0);
                return out;
            }
            JSONArray rows = new JSONArray();
            for (int i = 0; i < changes.length(); i++) {
                JSONObject ch = changes.optJSONObject(i);
                if (ch == null) {
                    continue;
                }
                JSONObject row = new JSONObject();
                row.put("record_id", ch.optString("record_id", ""));
                row.put("kind", ch.optString("_kind", ""));
                row.put("updated_at", ch.optLong("_updated_at", 0));
                row.put("created_at", ch.optLong("_updated_at", 0));
                row.put("deleted", ch.optBoolean("_deleted", false));
                // 去掉下划线开头的元信息，剩下的是业务字段
                JSONObject data = new JSONObject();
                java.util.Iterator<String> it = ch.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    if (k.startsWith("_") || "record_id".equals(k)) {
                        continue;
                    }
                    data.put(k, ch.opt(k));
                }
                row.put("data", data);
                rows.put(row);
            }
            JSONObject mergeReq = new JSONObject();
            mergeReq.put("rows", rows);
            String merged = db.mergeRemote(mergeReq.toString());
            return new JSONObject(merged);
        } catch (Exception e) {
            try {
                out.put("ok", false);
                out.put("why", String.valueOf(e.getMessage()));
            } catch (JSONException ignored) {
                // ignore
            }
            return out;
        }
    }

    // ------------------------------------------------------------------
    // HTTP 底层
    // ------------------------------------------------------------------
    /**
     * 请求基址。
     *
     * 这里**不再自己判断协议**：以前写成
     *   if (h.startsWith("http://") || h.startsWith("https://")) return h;
     *   return "http://" + h;
     * 但 setHost() 早把协议剥掉了，所以那个 if 永远为假，
     * 结果无论用户填 https 还是 http，最终都用 http 去连 ——
     * 内网穿透的 HTTPS 隧道（域名 + 443）必然握手失败。
     * 现在协议由 PairStore 负责保存与补全，这里直接拿成品。
     */
    private String base() {
        String h = pair.baseUrl();
        // 兜底：极端情况下（老数据异常）仍有空值
        return h.length() == 0 ? "" : h;
    }

    /**
     * 后端 4.0.2 起所有 /api/*（除 ping）都必须带私钥。
     * 手机端本地就能读到自己的私钥，直接挂在请求头上。
     */
    private String pairKey() {
        try {
            return pair.key();
        } catch (Exception e) {
            return "";
        }
    }

    private JSONObject get(String path) throws Exception {
        HttpURLConnection conn = null;
        try {
            URL u = new URL(base() + path);
            conn = (HttpURLConnection) u.openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(TIMEOUT_MS);
            conn.setReadTimeout(TIMEOUT_MS);
            conn.setRequestProperty("Accept", "application/json");
            String k = pairKey();
            if (k != null && k.length() > 0) {
                conn.setRequestProperty("X-Pair-Key", k);
            }
            int code = conn.getResponseCode();
            if (code != 200) {
                lastError = "服务端返回 HTTP " + code
                        + (code == 401 ? "（私钥不对或没带上）" : "");
                return null;
            }
            return new JSONObject(readAll(conn.getInputStream()));
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private JSONObject post(String path, JSONObject body) throws Exception {
        return post(path, body, "");
    }

    private JSONObject post(String path, JSONObject body, String query) throws Exception {
        HttpURLConnection conn = null;
        try {
            URL u = new URL(base() + path + query);
            conn = (HttpURLConnection) u.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(TIMEOUT_MS);
            conn.setReadTimeout(TIMEOUT_MS * 2);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            String k = pairKey();
            if (k != null && k.length() > 0) {
                conn.setRequestProperty("X-Pair-Key", k);
            }
            byte[] raw = body.toString().getBytes(UTF8);
            conn.setFixedLengthStreamingMode(raw.length);
            OutputStream os = conn.getOutputStream();
            os.write(raw);
            os.flush();
            os.close();
            int code = conn.getResponseCode();
            if (code != 200) {
                lastError = "服务端返回 HTTP " + code
                        + (code == 401 ? "（私钥不对或没带上）" : "");
                return null;
            }
            return new JSONObject(readAll(conn.getInputStream()));
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private static String readAll(InputStream in) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
        }
        in.close();
        return out.toString("UTF-8");
    }
}
