package com.xiaoxiaoxiao.workbench;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.security.MessageDigest;
import java.security.SecureRandom;

/**
 * 配对信息本机存储。
 *
 * · 私钥：首次启动时在手机本地生成，格式固定为「10 位数字 + 26 位字母」共 36 位。
 *   存在 SharedPreferences，同时写入应用私有目录的 key.txt 便于备份。
 * · 电脑地址：你手动填一次（格式 192.168.1.37:8731），之后一直用它。
 *
 * 私钥不会被发送到网络上：启动器只在你第一次配对时收下它、算一次 SHA-256 存起来，
 * 之后靠「已配对」这个状态决定服务是否放行，手机连进来只凭地址。
 */
public final class PairStore {

    private static final String PREF = "xxv_pair";
    private static final String K_KEY = "key";
    private static final String K_HOST = "host";
    private static final String K_DEVICE_ID = "device_id";
    private static final String K_DEVICE_NAME = "device_name";

    private static final String DIGITS = "0123456789";
    private static final String LETTERS = "abcdefghijklmnopqrstuvwxyz";

    private final SharedPreferences sp;
    private final SecureRandom rnd = new SecureRandom();

    public PairStore(Context ctx) {
        this.sp = ctx.getApplicationContext()
                .getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    // ------------------------------------------------------------------
    // 私钥
    // ------------------------------------------------------------------
    /** 取本机私钥；不存在则生成一把固定保存下来。 */
    public synchronized String key() {
        String k = sp.getString(K_KEY, "");
        if (k != null && k.length() == 36) {
            return k;
        }
        String fresh = generateKey();
        sp.edit().putString(K_KEY, fresh).apply();
        return fresh;
    }

    /** 重新生成一把（旧的那把在启动器里就作废了，需要重新配对）。 */
    public synchronized String regenerateKey() {
        String fresh = generateKey();
        sp.edit().putString(K_KEY, fresh).apply();
        return fresh;
    }

    /** 10 位数字 + 26 位字母。 */
    private String generateKey() {
        StringBuilder sb = new StringBuilder(36);
        for (int i = 0; i < 10; i++) {
            sb.append(DIGITS.charAt(rnd.nextInt(DIGITS.length())));
        }
        for (int i = 0; i < 26; i++) {
            sb.append(LETTERS.charAt(rnd.nextInt(LETTERS.length())));
        }
        return sb.toString();
    }

    public static String sha256(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest(s.getBytes("UTF-8"));
            StringBuilder sb = new StringBuilder(d.length * 2);
            for (byte b : d) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    // ------------------------------------------------------------------
    // 服务器地址
    // ------------------------------------------------------------------
    /** 原始存储值（可能不带协议，老版本遗留）。 */
    public synchronized String host() {
        String h = sp.getString(K_HOST, "");
        return h == null ? "" : h.trim();
    }

    /**
     * 可直接用于 URL 的基址，一定带协议。
     * 老版本存的是 "1.2.3.4:8731"，这里补成 "http://1.2.3.4:8731"。
     */
    public synchronized String baseUrl() {
        String h = host();
        return h.length() == 0 ? "" : withScheme(h);
    }

    /**
     * 保存电脑地址。
     *
     * 必须**保留** http:// 或 https:// 前缀：内网穿透（Sakura Frp / 花生壳等）
     * 给的往往是 HTTPS 隧道（域名 + 443），这时协议就是协议，不能被抹掉。
     *
     * 以前这里无条件剥掉协议只留 host:port，而 SyncEngine 又无条件拼 http://，
     * 结果是「填了 https 地址、实际用 http 去连」，握手失败还看不出原因。
     *
     * 不写协议时默认补 http://（局域网直连场景）。
     */
    public synchronized void setHost(String host) {
        String h = host == null ? "" : host.trim();
        // 去掉尾斜杠（http://a.b:1/  和  http://a.b:1  等价）
        while (h.endsWith("/")) {
            h = h.substring(0, h.length() - 1);
        }
        if (h.length() > 0) {
            String low = h.toLowerCase();
            if (!low.startsWith("http://") && !low.startsWith("https://")) {
                h = "http://" + h;
            }
        }
        sp.edit().putString(K_HOST, h).apply();
    }

    /**
     * 历史遗留：老版本存的是不带协议的 host:port。
     * 取出来时补上 http://，避免升级后连不上。
     */
    private static String withScheme(String h) {
        String low = h.toLowerCase();
        if (low.startsWith("http://") || low.startsWith("https://")) {
            return h;
        }
        return "http://" + h;
    }

    public synchronized boolean hasHost() {
        return host().length() > 0;
    }

    // ------------------------------------------------------------------
    // 设备身份（启动器设备列表用）
    // ------------------------------------------------------------------
    public synchronized String deviceId() {
        String id = sp.getString(K_DEVICE_ID, "");
        if (id != null && id.length() > 0) {
            return id;
        }
        StringBuilder sb = new StringBuilder("h");
        for (int i = 0; i < 15; i++) {
            sb.append(LETTERS.charAt(rnd.nextInt(LETTERS.length())));
        }
        id = sb.toString();
        sp.edit().putString(K_DEVICE_ID, id).apply();
        return id;
    }

    public synchronized String deviceName() {
        String n = sp.getString(K_DEVICE_NAME, "");
        return n == null ? "" : n;
    }

    public synchronized void setDeviceName(String name) {
        sp.edit().putString(K_DEVICE_NAME, name == null ? "" : name.trim()).apply();
    }

    public synchronized void clearPair() {
        sp.edit().remove(K_KEY).remove(K_HOST).apply();
    }

    /** 供页面读取的全部配对信息。 */
    public synchronized String infoJson() {
        JSONObject o = new JSONObject();
        try {
            o.put("key", key());
            o.put("host", host());
            o.put("deviceId", deviceId());
            o.put("deviceName", deviceName());
        } catch (JSONException ignored) {
            // ignore
        }
        return o.toString();
    }

    public synchronized String savePair(String host) {
        setHost(host);
        return infoJson();
    }

    // ------------------------------------------------------------------
    // 待同步队列（离线期间攒下来的写操作）
    // ------------------------------------------------------------------
    private static final String K_QUEUE = "queue";

    public synchronized void enqueue(String opJson) {
        try {
            JSONArray arr = queueArray();
            arr.put(new JSONObject(opJson));
            sp.edit().putString(K_QUEUE, arr.toString()).apply();
        } catch (Exception ignored) {
            // ignore
        }
    }

    public synchronized String takeQueue() {
        return queueArray().toString();
    }

    public synchronized int queueSize() {
        return queueArray().length();
    }

    public synchronized void clearQueue() {
        sp.edit().putString(K_QUEUE, "[]").apply();
    }

    private JSONArray queueArray() {
        String raw = sp.getString(K_QUEUE, "[]");
        try {
            JSONArray a = new JSONArray(raw == null ? "[]" : raw);
            return a;
        } catch (JSONException e) {
            return new JSONArray();
        }
    }
}
