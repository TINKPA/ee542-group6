#!/usr/bin/env bash
# EE542 Lab 9 Part 2: build the TWA, boot an emulator, and open the chat app in it
# without exposing the server: the device's localhost:8000 is reverse-forwarded
# to the Mac, and Chrome is told to skip Digital Asset Links verification for
# that one origin (Google's documented debug path; needs a userdebug image such
# as google_apis, whose Chrome reads /data/local/tmp/chrome-command-line).
#   ./run_emulator.sh            (chat backend must already run on :8000)
# assetlinks.json (frontend/.well-known) carries this APK's real SHA-256, so a
# real HTTPS deployment verifies without the flag.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
ADB="$ANDROID_HOME/platform-tools/adb"
AVD="${AVD:-ee542_api34}"
PKG=edu.usc.ee542.group6.f1compass

[ -f local.properties ] || echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew -q assembleDebug
APK=app/build/outputs/apk/debug/app-debug.apk
echo "APK signer: $("$ANDROID_HOME"/build-tools/*/apksigner verify --print-certs "$APK" | grep -m1 SHA-256)"

if ! "$ADB" get-state >/dev/null 2>&1; then
  "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" list avd -c | grep -qx "$AVD" ||
    echo no | "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" create avd -n "$AVD" \
      -k "system-images;android-34;google_apis;arm64-v8a" -d pixel_7
  nohup "$ANDROID_HOME/emulator/emulator" -avd "$AVD" -no-snapshot -no-boot-anim >/dev/null 2>&1 &
  "$ADB" wait-for-device
  until [ "$("$ADB" shell getprop sys.boot_completed | tr -d '\r')" = 1 ]; do sleep 2; done
fi

"$ADB" reverse tcp:8000 tcp:8000
"$ADB" shell 'echo "_ --disable-fre --no-default-browser-check --no-first-run --disable-digital-asset-link-verification-for-url=\"http://localhost:8000\"" > /data/local/tmp/chrome-command-line'
"$ADB" shell am set-debug-app --persistent com.android.chrome
"$ADB" install -r "$APK"
# Launch like the home-screen icon does (an `am start` right after force-stopping
# Chrome tends to bounce back to the launcher).
"$ADB" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null
echo "launched $PKG; logcat should show: Verification skipped for http://localhost:8000"
