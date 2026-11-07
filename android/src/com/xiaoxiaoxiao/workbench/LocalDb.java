package com.xiaoxiaoxiao.workbench;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Iterator;
import java.util.UUID;

/**
 * 本地 SQLite 数据层（安卓独立版）。
 *
 * 与桌面版共用同一套表结构与数据格式：
 *   records(id, db_id, kind, data(JSON, 扁平字段), created_at, updated_at)
 *
 * 云端 databaseId → kind 的映射保持与页面里硬编码的常量一致，
 * 这样页面代码无需改动。
 */
public class LocalDb {

    private static final String DB_NAME = "xiaoxiaoxiao.db";
    private static final int DB_VER = 1;

    private static final String[] CLOUD_IDS = {
            "tHLWn2tjAvknVD3h5lyWG5",
            "BxxY8CTvCuWpMWgHJJGq9S",
            "cPZx8ssc03WAmKOwFhBcPx",
            "JNiZJHR3QXKBMNrmHc0nIj",
            "B2a4VCyYGokQUAqXRhAKVv",
            "ukf8VPIPQtBQN71qyrtu6x",
            "HEEB4feB120kc8nx8iSTxW",
    };
    private static final String[] KINDS = {
            "money", "habit", "plan", "fitness", "shopping", "media", "summary",
    };

    private final Context context;
    private Helper helper;

    public LocalDb(Context context) {
        this.context = context.getApplicationContext();
        this.helper = new Helper(this.context);
    }

    /** 云端 ID → 本地 kind；无法识别返回 null。 */
    public static String kindOf(String dbId) {
        if (dbId == null) {
            return null;
        }
        for (int i = 0; i < CLOUD_IDS.length; i++) {
            if (CLOUD_IDS[i].equals(dbId)) {
                return KINDS[i];
            }
        }
        return null;
    }

    public static String idOf(String kind) {
        for (int i = 0; i < KINDS.length; i++) {
            if (KINDS[i].equals(kind)) {
                return CLOUD_IDS[i];
            }
        }
        return null;
    }

    // ------------------------------------------------------------------
    // SQLiteOpenHelper
    // ------------------------------------------------------------------
    static final class Helper extends SQLiteOpenHelper {

        private final Context ctx;

        Helper(Context context) {
            super(context, DB_NAME, null, DB_VER);
            this.ctx = context;
        }

        @Override
        public void onCreate(SQLiteDatabase db) {
            db.execSQL("CREATE TABLE records("
                    + "id TEXT PRIMARY KEY,"
                    + "db_id TEXT NOT NULL,"
                    + "kind TEXT NOT NULL,"
                    + "data TEXT NOT NULL,"
                    + "created_at INTEGER NOT NULL,"
                    + "updated_at INTEGER NOT NULL)");
            db.execSQL("CREATE INDEX idx_kind ON records(kind)");
            db.execSQL("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)");
            seed(db);
        }

        @Override
        public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
            // 结构未变，保留数据
        }

        /** 首次建库：导入随包 seed.json。 */
        private void seed(SQLiteDatabase db) {
            String raw;
            try {
                raw = readAsset("seed.json");
            } catch (Exception e) {
                return;
            }
            if (raw == null || raw.length() == 0) {
                return;
            }
            long now = System.currentTimeMillis();
            try {
                JSONObject root = new JSONObject(raw);
                Iterator<String> keys = root.keys();
                while (keys.hasNext()) {
                    String kind = keys.next();
                    if (idOf(kind) == null) {
                        continue;
                    }
                    JSONArray rows = root.optJSONArray(kind);
                    if (rows == null) {
                        continue;
                    }
                    for (int i = 0; i < rows.length(); i++) {
                        JSONObject row = rows.optJSONObject(i);
                        if (row == null) {
                            continue;
                        }
                        row.remove("record_id");
                        normalizeDates(row);
                        db.execSQL(
                                "INSERT INTO records(id,db_id,kind,data,created_at,updated_at)"
                                        + " VALUES(?,?,?,?,?,?)",
                                new Object[]{
                                        newId(), idOf(kind), kind,
                                        row.toString(), now, now
                                });
                    }
                }
                db.execSQL("INSERT INTO meta(key,value) VALUES('seeded',?)",
                        new Object[]{String.valueOf(now)});
            } catch (JSONException ignored) {
                // 种子损坏则从空库开始
            }
        }

        private String readAsset(String name) throws IOException {
            InputStream in = null;
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            try {
                in = ctx.getAssets().open(name);
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                }
                return out.toString("UTF-8");
            } finally {
                if (in != null) {
                    try {
                        in.close();
                    } catch (IOException ignored) {
                        // ignore
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // 工具
    // ------------------------------------------------------------------
    private static String newId() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 24);
    }

    /** 日期字段统一成 YYYY-MM-DD。 */
    private static void normalizeDates(JSONObject row) {
        Iterator<String> it = row.keys();
        while (it.hasNext()) {
            String key = it.next();
            if (key == null || !key.contains("日期")) {
                continue;
            }
            String val = row.optString(key, "");
            if (val.length() >= 10 && val.charAt(4) == '-') {
                try {
                    row.put(key, val.substring(0, 10));
                } catch (JSONException ignored) {
                    // ignore
                }
            }
        }
    }

    /** {字段:{类型:值}} → {字段:值}，与桌面版 flatten 行为一致。 */
    private static JSONObject flatten(JSONObject props) {
        JSONObject out = new JSONObject();
        if (props == null) {
            return out;
        }
        Iterator<String> keys = props.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            Object raw = props.opt(key);
            try {
                if (raw instanceof JSONObject) {
                    JSONObject val = (JSONObject) raw;
                    if (val.has("image")) {
                        JSONObject img = val.optJSONObject("image");
                        out.put(key, img != null && img.has("images")
                                ? img.optJSONArray("images") : new JSONArray());
                    } else if (val.has("date")) {
                        out.put(key, normalizeDateStr(val.optString("date", "")));
                    } else if (val.has("select")) {
                        out.put(key, val.optString("select", ""));
                    } else if (val.has("multi_select")) {
                        out.put(key, val.optJSONArray("multi_select"));
                    } else if (val.has("checkbox")) {
                        out.put(key, val.optBoolean("checkbox", false));
                    } else if (val.has("currency")) {
                        out.put(key, val.optDouble("currency", 0));
                    } else if (val.has("number")) {
                        out.put(key, val.optDouble("number", 0));
                    } else if (val.has("text")) {
                        out.put(key, val.optString("text", ""));
                    } else if (val.has("url")) {
                        out.put(key, val.optString("url", ""));
                    } else if (val.has("email")) {
                        out.put(key, val.optString("email", ""));
                    } else if (val.has("phone_number")) {
                        out.put(key, val.optString("phone_number", ""));
                    } else {
                        Iterator<String> inner = val.keys();
                        out.put(key, inner.hasNext()
                                ? val.opt(inner.next()) : "");
                    }
                } else {
                    out.put(key, raw);
                }
            } catch (JSONException ignored) {
                // 跳过该字段
            }
        }
        return out;
    }

    private static String normalizeDateStr(String v) {
        if (v == null) {
            return "";
        }
        String s = v.trim();
        if (s.length() >= 10 && s.charAt(4) == '-') {
            return s.substring(0, 10);
        }
        return s;
    }

    // ------------------------------------------------------------------
    // CRUD
    // ------------------------------------------------------------------
    public synchronized String query(String json) {
        JSONObject req = parse(json);
        String kind = kindOf(req.optString("databaseId", ""));
        if (kind == null) {
            return error("未知数据表");
        }
        JSONArray results = new JSONArray();
        Cursor c = null;
        try {
            c = helper.getReadableDatabase().rawQuery(
                    "SELECT id,data FROM records WHERE kind=? ORDER BY updated_at DESC",
                    new String[]{kind});
            while (c.moveToNext()) {
                String id = c.getString(0);
                String data = c.getString(1);
                JSONObject row;
                try {
                    row = new JSONObject(data);
                } catch (JSONException e) {
                    row = new JSONObject();
                }
                try {
                    row.put("record_id", id);
                } catch (JSONException ignored) {
                    // ignore
                }
                results.put(row);
            }
        } catch (Exception e) {
            return error("查询失败：" + e.getMessage());
        } finally {
            if (c != null) {
                c.close();
            }
        }
        JSONObject out = new JSONObject();
        try {
            out.put("results", results);
            out.put("hasMore", false);
            out.put("nextCursor", JSONObject.NULL);
        } catch (JSONException ignored) {
            // ignore
        }
        return out.toString();
    }

    public synchronized String add(String json) {
        JSONObject req = parse(json);
        String kind = kindOf(req.optString("databaseId", ""));
        if (kind == null) {
            return error("未知数据表");
        }
        JSONObject props = req.optJSONObject("properties");
        JSONObject flat = flatten(props);
        // v4：页面会带一个固定 id 进来，让本地库和电脑端用同一个 id，同步才对得上
        String id = req.optString("recordId", "");
        if (id == null || id.length() == 0) {
            id = newId();
        }
        long now = System.currentTimeMillis();
        try {
            helper.getWritableDatabase().execSQL(
                    "INSERT OR REPLACE INTO records(id,db_id,kind,data,created_at,updated_at)"
                            + " VALUES(?,?,?,?,?,?)",
                    new Object[]{id, idOf(kind), kind, flat.toString(), now, now});
        } catch (Exception e) {
            return error("写入失败：" + e.getMessage());
        }
        JSONObject out = new JSONObject();
        try {
            out.put("record_id", id);
            out.put("id", id);
        } catch (JSONException ignored) {
            // ignore
        }
        return out.toString();
    }

    public synchronized String update(String json) {
        JSONObject req = parse(json);
        String kind = kindOf(req.optString("databaseId", ""));
        String rid = req.optString("recordId", "");
        if (kind == null || rid.length() == 0) {
            return error("参数缺失");
        }
        JSONObject props = req.optJSONObject("properties");
        JSONObject flat = flatten(props);

        Cursor c = null;
        String existed = null;
        try {
            c = helper.getReadableDatabase().rawQuery(
                    "SELECT data FROM records WHERE id=? AND kind=?",
                    new String[]{rid, kind});
            if (c.moveToNext()) {
                existed = c.getString(0);
            }
        } finally {
            if (c != null) {
                c.close();
            }
        }
        if (existed == null) {
            return error("记录不存在");
        }
        JSONObject merged;
        try {
            merged = new JSONObject(existed);
        } catch (JSONException e) {
            merged = new JSONObject();
        }
        Iterator<String> keys = flat.keys();
        while (keys.hasNext()) {
            String k = keys.next();
            try {
                merged.put(k, flat.opt(k));
            } catch (JSONException ignored) {
                // ignore
            }
        }
        try {
            helper.getWritableDatabase().execSQL(
                    "UPDATE records SET data=?, updated_at=? WHERE id=?",
                    new Object[]{merged.toString(), System.currentTimeMillis(), rid});
        } catch (Exception e) {
            return error("更新失败：" + e.getMessage());
        }
        return ok();
    }

    public synchronized String delete(String json) {
        JSONObject req = parse(json);
        String kind = kindOf(req.optString("databaseId", ""));
        String rid = req.optString("recordId", "");
        if (kind == null || rid.length() == 0) {
            return error("参数缺失");
        }
        try {
            helper.getWritableDatabase().execSQL(
                    "DELETE FROM records WHERE id=? AND kind=?", new Object[]{rid, kind});
        } catch (Exception e) {
            return error("删除失败：" + e.getMessage());
        }
        return ok();
    }

    /**
     * v4：把电脑端拉回来的记录写进本地库（对账用）。
     * 带进来的 updated_at 若比本地还旧就跳过，保证「后写覆盖先写」。
     */
    public synchronized String mergeRemote(String json) {
        JSONObject req = parse(json);
        JSONArray rows = req.optJSONArray("rows");
        if (rows == null) {
            return error("rows 非法");
        }
        int ok = 0, skip = 0;
        SQLiteDatabase db = helper.getWritableDatabase();
        for (int i = 0; i < rows.length(); i++) {
            JSONObject r = rows.optJSONObject(i);
            if (r == null) {
                continue;
            }
            String kind = r.optString("kind", "");
            String dbId = r.optString("db_id", "");
            if (idOf(kind) == null) {
                kind = kindOf(dbId);
            }
            if (kind == null) {
                skip++;
                continue;
            }
            String id = r.optString("record_id", "");
            if (id.length() == 0) {
                skip++;
                continue;
            }
            long remoteUpd = r.optLong("updated_at", 0);
            long remoteCreate = r.optLong("created_at", remoteUpd);
            boolean deleted = r.optBoolean("deleted", false);

            // 读一下本地这条现有的 updated_at
            long localUpd = -1;
            Cursor c = null;
            try {
                c = db.rawQuery("SELECT updated_at FROM records WHERE id=?",
                        new String[]{id});
                if (c.moveToNext()) {
                    localUpd = c.getLong(0);
                }
            } finally {
                if (c != null) {
                    c.close();
                }
            }
            if (localUpd >= 0 && remoteUpd <= localUpd) {
                skip++;
                continue;
            }

            JSONObject data = r.optJSONObject("data");
            String dataStr = data == null ? "{}" : data.toString();
            try {
                if (deleted) {
                    db.execSQL("DELETE FROM records WHERE id=?", new Object[]{id});
                } else {
                    db.execSQL(
                            "INSERT OR REPLACE INTO records(id,db_id,kind,data,created_at,updated_at)"
                                    + " VALUES(?,?,?,?,?,?)",
                            new Object[]{id, idOf(kind), kind, dataStr, remoteCreate, remoteUpd});
                }
                ok++;
            } catch (Exception e) {
                skip++;
            }
        }
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("merged", ok);
            out.put("skipped", skip);
        } catch (JSONException ignored) {
            // ignore
        }
        return out.toString();
    }

    /** v4：把本地所有记录按「电脑端需要的样子」导出，供推送与对账。 */
    public synchronized String dumpForSync(String json) {
        JSONObject req = parse(json);
        long since = req.optLong("since", 0);
        JSONArray rows = new JSONArray();
        SQLiteDatabase db = helper.getReadableDatabase();
        Cursor c = null;
        try {
            c = db.rawQuery(
                    "SELECT id,db_id,kind,data,created_at,updated_at FROM records"
                            + " WHERE updated_at > ? ORDER BY updated_at ASC",
                    new String[]{String.valueOf(since)});
            while (c.moveToNext()) {
                JSONObject o = new JSONObject();
                try {
                    o.put("record_id", c.getString(0));
                    o.put("db_id", c.getString(1));
                    o.put("kind", c.getString(2));
                    String d = c.getString(3);
                    o.put("data", new JSONObject(d == null ? "{}" : d));
                    o.put("created_at", c.getLong(4));
                    o.put("updated_at", c.getLong(5));
                } catch (JSONException ignored) {
                    // 跳过坏行
                    continue;
                }
                rows.put(o);
            }
        } catch (Exception e) {
            return error("导出失败：" + e.getMessage());
        } finally {
            if (c != null) {
                c.close();
            }
        }
        JSONObject out = new JSONObject();
        try {
            out.put("rows", rows);
        } catch (JSONException ignored) {
            // ignore
        }
        return out.toString();
    }

    /**
     * 清空本地库。
     *
     * json: {"kind":"money"} 只清一张表；{"kind":"all"} 或空 = 清全部。
     * 返回 {"ok":true,"kind":"...","before":N} / {"ok":false,"error":"..."}
     *
     * 以前只认「清全部」，但前端七个页面各有单表清空入口，
     * 传 money 进来也会把整库抹掉 —— 那是数据事故，不是功能。
     */
    public synchronized String wipe(String json) {
        JSONObject req = parse(json);
        String kind = req.optString("kind", "").trim();
        if (kind.length() == 0) {
            kind = "all";
        }
        if (!"all".equals(kind) && !isKnownKind(kind)) {
            return error("未知数据表: " + kind);
        }
        SQLiteDatabase wdb;
        try {
            wdb = helper.getWritableDatabase();
        } catch (Exception e) {
            return error("清空失败：" + e.getMessage());
        }
        int before;
        try {
            Cursor c = null;
            try {
                if ("all".equals(kind)) {
                    c = wdb.rawQuery("SELECT COUNT(*) FROM records", null);
                } else {
                    c = wdb.rawQuery("SELECT COUNT(*) FROM records WHERE kind=?",
                            new String[]{kind});
                }
                before = c.moveToFirst() ? c.getInt(0) : 0;
            } finally {
                if (c != null) {
                    c.close();
                }
            }
            if ("all".equals(kind)) {
                wdb.execSQL("DELETE FROM records");
            } else {
                wdb.execSQL("DELETE FROM records WHERE kind=?", new Object[]{kind});
            }
        } catch (Exception e) {
            return error("清空失败：" + e.getMessage());
        }
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("wiped", true);
            out.put("kind", kind);
            out.put("before", before);
        } catch (JSONException ignored) {
            // ignore
        }
        return out.toString();
    }

    private static boolean isKnownKind(String kind) {
        for (String k : KINDS) {
            if (k.equals(kind)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 封面图片：直接转成 data URL 返回。
     * 页面 safeUrl 已放行 data:image/*，无需本地文件存储。
     */
    public synchronized String upload(String json) {
        JSONObject req = parse(json);
        String data = req.optString("data", "");
        String ctype = req.optString("contentType", "image/png");
        if (data.length() == 0) {
            return error("缺少图片数据");
        }
        if (ctype.length() == 0) {
            ctype = "image/png";
        }
        String url = "data:" + ctype + ";base64," + data;
        JSONObject out = new JSONObject();
        try {
            out.put("url", url);
        } catch (JSONException ignored) {
            // ignore
        }
        return out.toString();
    }

    /** 导出全库，用于备份/迁移。 */
    public synchronized String exportAll() {
        JSONObject tables = new JSONObject();
        for (String kind : KINDS) {
            JSONArray rows = new JSONArray();
            Cursor c = null;
            try {
                c = helper.getReadableDatabase().rawQuery(
                        "SELECT id,data FROM records WHERE kind=?", new String[]{kind});
                while (c.moveToNext()) {
                    try {
                        JSONObject row = new JSONObject(c.getString(1));
                        row.put("record_id", c.getString(0));
                        rows.put(row);
                    } catch (JSONException ignored) {
                        // ignore
                    }
                }
            } finally {
                if (c != null) {
                    c.close();
                }
            }
            try {
                tables.put(kind, rows);
            } catch (JSONException ignored) {
                // ignore
            }
        }
        JSONObject out = new JSONObject();
        try {
            out.put("tables", tables);
            out.put("version", 1);
        } catch (JSONException ignored) {
            // ignore
        }
        return out.toString();
    }

    // ------------------------------------------------------------------
    private static JSONObject parse(String json) {
        try {
            JSONObject o = new JSONObject(json == null ? "{}" : json);
            return o;
        } catch (JSONException e) {
            return new JSONObject();
        }
    }

    private static String error(String msg) {
        JSONObject o = new JSONObject();
        try {
            o.put("error", msg);
        } catch (JSONException ignored) {
            // ignore
        }
        return o.toString();
    }

    private static String ok() {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", true);
        } catch (JSONException ignored) {
            // ignore
        }
        return o.toString();
    }
}
