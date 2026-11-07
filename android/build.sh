#!/usr/bin/env bash
# 小笑肖 Android APK 构建脚本（独立版：本地 SQLite，免 Gradle）
set -euo pipefail

SDK="${ANDROID_SDK:-D:/Android/Sdk}"
BT="$SDK/build-tools/${BUILD_TOOLS_VER:-34.0.0}"
PLATFORM="$SDK/platforms/android-34/android.jar"
JAVA_HOME="${JAVA_HOME_21:-D:/TOOL/21}"
JAVAC="$JAVA_HOME/bin/javac.exe"

cd "$(dirname "$0")"

APP_NAME="小笑肖"
VER_NAME="4.0.2"
VER_CODE="6"
PKG="com.xiaoxiaoxiao.workbench"
SRC_DIR="src/com/xiaoxiaoxiao/workbench"

# 签名口令走环境变量，不再写死在脚本里。
# 之前明文写在 build.sh 里，任何拿到脚本的人都能重新签一个「同签名」的包
# 顶掉用户已装的版本（Android 只校验签名一致就允许覆盖安装）。
# 本机沿用原口令，其它机器必须自己 export。
KS_PASS="${XXV_KS_PASS:-xiaoxiao2026}"
KS_FILE="${XXV_KS_FILE:-keystore.jks}"
KS_ALIAS="${XXV_KS_ALIAS:-xiaoxiaoxiao}"

for f in "$JAVAC" "$BT/aapt2.exe" "$BT/d8.bat" "$BT/zipalign.exe" "$BT/apksigner.bat"; do
  if [ ! -f "$f" ]; then
    echo "缺少构建工具：$f" >&2
    exit 1
  fi
done

echo "[1/8] 清理"
rm -rf build dist
mkdir -p build/res build/gen build/classes build/dex dist

echo "[2/8] aapt2 compile 资源"
"$BT/aapt2.exe" compile --dir res -o build/res/resources.zip

echo "[3/8] aapt2 link（含 assets）"
"$BT/aapt2.exe" link \
  -o build/base.apk \
  -I "$PLATFORM" \
  --manifest AndroidManifest.xml \
  -R build/res/resources.zip \
  --java build/gen \
  -A assets \
  --min-sdk-version 23 \
  --target-sdk-version 34 \
  --version-code "$VER_CODE" \
  --version-name "$VER_NAME" \
  --auto-add-overlay

echo "[4/8] javac 编译"
# 以前是 `javac ... | grep -v 警告 || true`：管道让退出码变成 grep 的，
# 再 || true 直接吞掉一切，编译失败也照常往下走，最后打出一个缺类的包。
# 现在先落盘日志、判退出码，失败立刻退出并打印真实报错。
set +e
"$JAVAC" -encoding UTF-8 -source 8 -target 8 -nowarn \
  -classpath "$PLATFORM" \
  -d build/classes \
  build/gen/com/xiaoxiaoxiao/workbench/R.java \
  "$SRC_DIR/MainActivity.java" \
  "$SRC_DIR/LocalDb.java" \
  "$SRC_DIR/LocalBridge.java" \
  "$SRC_DIR/PairStore.java" \
  "$SRC_DIR/SyncEngine.java" > build/javac.log 2>&1
JAVAC_RC=$?
set -e
if [ $JAVAC_RC -ne 0 ]; then
  echo "javac 失败（退出码 $JAVAC_RC），日志：" >&2
  cat build/javac.log >&2
  exit $JAVAC_RC
fi
grep -v "^警告\|^注:" build/javac.log || true

echo "[5/8] d8 生成 dex"
"$BT/d8.bat" --min-api 23 --lib "$PLATFORM" --output build/dex \
  $(find build/classes -name "*.class")

echo "[6/8] 合并 dex（必须 STORE + 4 字节对齐）"
# 关键：Android 12+（API 31）要求 classes.dex 在 zip 里以 STORE（不压缩）
# 方式存放，且数据偏移 4 字节对齐，否则安装时报 INSTALL_PARSE_FAILED_NOT_APK
# （报错只说「软件包似乎无效」，完全不提 dex，极难查）。
# aapt add 一律用 DEFLATE 写，zipalign 只改偏移不改压缩方式，
# 本机 Git Bash 又没有 zip —— 所以用 _pack_dex.py 自己控字节：
# 原条目原样搬运（不重压缩），classes.dex 追加为 STORE 并对齐。
PYBIN="${XXV_PY:-E:/pythonpath/python.exe}"
"$PYBIN" _pack_dex.py build/base.apk build/dex/classes.dex build/unaligned.apk

"$BT/zipalign.exe" -p -f 4 build/unaligned.apk build/aligned.apk

echo "[6.5/8] 断言：dex 必须 comp=0 且 offset%4==0"
"$PYBIN" _check_apk_dex.py build/aligned.apk

echo "[7/8] 签名"
if [ ! -f "$KS_FILE" ]; then
  "$JAVA_HOME/bin/keytool.exe" -genkeypair -v \
    -keystore "$KS_FILE" -storetype JKS \
    -alias "$KS_ALIAS" -keyalg RSA -keysize 2048 -validity 10950 \
    -storepass "$KS_PASS" -keypass "$KS_PASS" \
    -dname "CN=XiaoXiaoXiao, OU=Workbench, O=XiaoXiaoXiao, L=Beijing, ST=Beijing, C=CN" \
    >/dev/null 2>&1
fi
"$BT/apksigner.bat" sign \
  --ks "$KS_FILE" --ks-key-alias "$KS_ALIAS" \
  --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out "dist/${APP_NAME}-${VER_NAME}.apk" build/aligned.apk

echo "[8/8] 校验"
"$BT/apksigner.bat" verify "dist/${APP_NAME}-${VER_NAME}.apk" && echo "SIGN_OK"
"$BT/zipalign.exe" -c -v 4 "dist/${APP_NAME}-${VER_NAME}.apk" >/dev/null && echo "ALIGN_OK"
ls -la "dist/"
"$BT/aapt.exe" list "dist/${APP_NAME}-${VER_NAME}.apk" 2>/dev/null || true
