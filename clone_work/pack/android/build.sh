#!/usr/bin/env bash
# 小笑肖 Android APK 构建脚本（独立版：本地 SQLite，免 Gradle）
set -euo pipefail

SDK="D:/Android/Sdk"
BT="$SDK/build-tools/34.0.0"
PLATFORM="$SDK/platforms/android-34/android.jar"
JAVA_HOME="D:/TOOL/21"
JAVAC="$JAVA_HOME/bin/javac.exe"

cd "$(dirname "$0")"

APP_NAME="小笑肖"
VER_NAME="3.0.0"
VER_CODE="3"
PKG="com.xiaoxiaoxiao.workbench"
SRC_DIR="src/com/xiaoxiaoxiao/workbench"

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
"$JAVAC" -encoding UTF-8 -source 8 -target 8 -nowarn \
  -classpath "$PLATFORM" \
  -d build/classes \
  build/gen/com/xiaoxiaoxiao/workbench/R.java \
  "$SRC_DIR/MainActivity.java" \
  "$SRC_DIR/LocalDb.java" \
  "$SRC_DIR/LocalBridge.java" 2>&1 | grep -v "^警告\|^注:" || true

echo "[5/8] d8 生成 dex"
"$BT/d8.bat" --min-api 23 --lib "$PLATFORM" --output build/dex \
  $(find build/classes -name "*.class")

echo "[6/8] 合并 dex + zipalign"
cp build/base.apk build/unaligned.apk
cp build/dex/classes.dex build/classes.dex
(cd build && "$BT/aapt.exe" add unaligned.apk classes.dex >/dev/null)
rm -f build/classes.dex
"$BT/zipalign.exe" -p -f 4 build/unaligned.apk build/aligned.apk

echo "[7/8] 签名"
if [ ! -f keystore.jks ]; then
  "$JAVA_HOME/bin/keytool.exe" -genkeypair -v \
    -keystore keystore.jks -storetype JKS \
    -alias xiaoxiaoxiao -keyalg RSA -keysize 2048 -validity 10950 \
    -storepass xiaoxiao2026 -keypass xiaoxiao2026 \
    -dname "CN=XiaoXiaoXiao, OU=Workbench, O=XiaoXiaoXiao, L=Beijing, ST=Beijing, C=CN" \
    >/dev/null 2>&1
fi
"$BT/apksigner.bat" sign \
  --ks keystore.jks --ks-key-alias xiaoxiaoxiao \
  --ks-pass pass:xiaoxiao2026 --key-pass pass:xiaoxiao2026 \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out "dist/${APP_NAME}-${VER_NAME}.apk" build/aligned.apk

echo "[8/8] 校验"
"$BT/apksigner.bat" verify "dist/${APP_NAME}-${VER_NAME}.apk" && echo "SIGN_OK"
ls -la "dist/"
"$BT/aapt.exe" list "dist/${APP_NAME}-${VER_NAME}.apk" 2>/dev/null || true
