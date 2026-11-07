# 小笑肖 · 在线生活工作台（v0.0.1）

> 本仓库的 **第一个发布版本（v0.0.1）**。项目定位：一个自托管的双端（安卓 + 电脑）生活管理工作台，
> 把「今日概览 / 记账理财 / 习惯健康 / 减脂健身 / 日程统筹 / 待买清单 / 书影音收藏」七大模块收进一个 App。

版本历史见仓库的 Git Tag：**`v0.0.1`**（本版本）与 **`v0.2.1`**（后续重组版本）。
最新版请切换到 `v0.2.1` 标签或 `main` 分支。

---

## 本版本（v0.0.1）包含什么

这是项目的早期源码快照，目录结构以 `clone_work/` 为核心：

```
clone_work/
├── build/          # 网页端工作台（HTML + JS + 注入脚本 + 构建工具 + JSON 数据）
│   ├── final.html / xiaoxiaoxiao.html / online.html / reader.html   # 各形态页面
│   ├── inject.js / check_fields.js / extract_meta.js / _check.js    # 前端构建/校验脚本
│   ├── *.py         # 字段抽取、注入、schema 合并等构建辅助
│   └── *.json       # 各模块业务数据（fit / habit / media / money / plan / shop ...）
├── csv/  csv7/     # 模块数据导出（fitness / habit / media / money / plan / shopping / summary）
├── src/            # life-all-in-one.html 整合页面
└── pack/           # 三端打包源码（不含构建产物）
    ├── android/    # 安卓端：AndroidManifest.xml / assets / res / build.sh / src(Java)
    ├── desktop/    # 电脑端（pywebview）：app.py / mini.py / setup.iss / _web / 小笑肖.spec
    └── local/      # 本地服务形态：app.py / inject_local.py / seed.json / setup.iss / _web
```

### 已排除的内容（未提交）
- `pack/*/build/`、`pack/*/dist/`、`pack/*/dist_installer/` 等 **PyInstaller 构建产物**（.exe/.pkg/.pyz 等，共约 176MB）。
- 签名密钥 `*.jks` / `*.keystore`（私钥不应入仓）。
- 运行日志 `run.log` / `errors.log` 等临时文件。

---

## 如何运行（本版本）

- **网页端**：直接用浏览器打开 `clone_work/build/xiaoxiaoxiao.html` 或 `online.html` 预览。
- **安卓端**：进入 `clone_work/pack/android/`，按 `build.sh` 重新构建 APK（需 JDK 21 + Android build-tools）。
- **电脑端**：进入 `clone_work/pack/desktop/` 或 `local/`，用 Python 运行 `app.py`（需先 `pip install` 相关依赖）。

> 本版本是早期结构，打包形态分散在 `desktop/` 与 `local/` 两处；
> 在 `v0.2.1` 中已统一为 `android/` + `server/` 的清晰结构，建议新用户直接看 `v0.2.1`。

---

## 许可证

本仓库源码仅供个人使用与学习。详见各版本中的 LICENSE 文件。
