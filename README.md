# 小笑肖 · 在线生活工作台

一个**自托管、双端同步**的本地生活工作台。把「今日概览 / 记账理财 / 习惯健康 / 减脂健身 / 日程统筹 / 待买清单 / 书影音收藏」七大模块收进一个 App，数据存你自己的电脑，不依赖任何第三方云服务。

- **安卓端**：纯 `tkinter`-free 原生壳 + WebView 桥接，数据存本机 SQLite，可离线使用。
- **电脑端**：一个轻量 HTTP 后端（SQLite 存储），你自己的电脑就是服务器，手机按需连上来同步。
- **安全模型**：每台设备一把 **36 位私钥**（前 10 位数字 + 后 26 位字母），所有写操作都带来源标记，软删除 + 变更日志支持增量拉取。

## 目录结构

```
xiaoxiaoxiao-workbench/
├── android/                    # 安卓端（免 Gradle 手工构建链）
│   ├── build.sh               # aapt2 → javac → d8 → 签名 → 对齐
│   ├── AndroidManifest.xml
│   ├── _pack_dex.py           # dex 以 STORE + 4 字节对齐打包（Android 12+ 必需）
│   ├── _check_apk_dex.py      # 对齐断言
│   ├── src/.../workbench/      # MainActivity / LocalDb / LocalBridge / PairStore / SyncEngine
│   ├── res/  assets/          # 界面资源 + 业务页面 index.html / seed.json
│   └── xiaoxiaoxiao-4.0.2.apk # 已构建好的安装包（可直接装）
└── server/                    # 电脑端同步后端
    ├── server.py              # HTTP 服务：/api/ping /api/sync /api/changes ...
    ├── launcher.py            # 桌面启动器（tkinter）：配对、启停、公网隧道
    ├── _dpapi.py              # Windows DPAPI 私钥保管（缺失时自动降级）
    ├── app.py                 # 另：联网阅读器壳（加载云端地址，与本机同步无关）
    ├── _web/index.html        # 电脑端网页界面
    └── 使用说明.md / 公网访问配置指南.md / 内网穿透配置指南.md
```

## 功能特性

- 七大生活模块，单 App 收纳，少切软件。
- 本地优先：断网照常记录，联网后自动补推离线队列。
- 双端同步：手机 ↔ 电脑，增量拉取，互不覆盖，每条记录带 `source`（pc / phone）与设备信息。
- 私钥鉴权：`X-Pair-Key` 头校验，私钥永不上网，只在首次配对时算一次哈希存本机。
- 可迁移：电脑地址可改，后端可跑在任意一台你控制的机器上；即开即用、即关即停（启动器 × 最小化而非常驻系统服务）。

## 安卓端构建

依赖：**JDK 21**（仅编译期，产出 Java 8 字节码）、**Android SDK build-tools 34.0.0**（`aapt2` / `d8` / `zipalign` / `apksigner`）、**Python 3**（跑 dex 打包脚本）。

```bash
cd android
bash build.sh          # 产物在 dist/小笑肖-4.0.2.apk
```

构建脚本会按需重新生成签名用的 `keystore.jks`（默认口令 `xiaoxiao2026`，可用环境变量 `XXV_KS_PASS` / `XXV_KS_FILE` / `XXV_KS_ALIAS` 覆盖）。**请勿把 `keystore.jks` 提交到仓库。**

环境变量覆盖：`JAVA_HOME_21`（JDK 路径）、`ANDROID_SDK`、`BUILD_TOOLS_VER`、`XXV_PY`（python 路径）。

## 电脑端同步后端

```bash
cd server
pip install -r requirements.txt   # 仅标准库 + tkinter（Windows 自带）；无第三方依赖
python launcher.py                # 图形启动器：首次粘贴手机 36 位私钥完成配对 → 启动服务
# 或仅起后端：  python server.py 8731
```

启动后启动器会显示手机要填的地址（局域网 `http://<电脑IP>:8731`，或勾选生成公网地址）。

## 配对与同步流程

1. 手机端「连接信息」页复制本机 36 位私钥。
2. 电脑端启动器粘贴该私钥 → 配对（仅此一次）。
3. 手机端填电脑地址 + 同一把私钥 → 双向同步开始。
4. 离线期间的记录会在联网后自动补推。

## 已知修复记录

- 后端 `/api/changes` 原先只支持 `GET`，而手机拉取走 `POST /api/changes?since=0` → 手机拉取 404、收不到电脑端数据。已在 `server.py::do_POST` 补上 `POST /api/changes` 分支（共用增量逻辑）。

## 许可

[MIT](LICENSE)。
