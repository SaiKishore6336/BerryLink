#!/usr/bin/env bash
# Run Android unit tests, build the debug APK, and publish it to dist/.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"

if [[ ! -d "$ANDROID_HOME" ]]; then
    echo "Android SDK not found at $ANDROID_HOME." >&2
    echo "Set ANDROID_HOME to the SDK directory and retry." >&2
    exit 1
fi
if [[ ! -x "$ROOT/android/gradlew" ]]; then
    echo "The Gradle wrapper is missing or not executable: android/gradlew" >&2
    exit 1
fi

"$ROOT/android/gradlew" -p "$ROOT/android" \
    :app:testDebugUnitTest :app:assembleDebug --console=plain

APK="$ROOT/android/app/build/outputs/apk/debug/app-debug.apk"
if [[ ! -f "$APK" ]]; then
    echo "The build finished without producing app-debug.apk." >&2
    exit 1
fi

mkdir -p "$ROOT/dist"
install -m 0644 "$APK" "$ROOT/dist/app-debug.apk"
(
    cd "$ROOT/dist"
    sha256sum app-debug.apk > app-debug.apk.sha256
)
echo "APK:      $ROOT/dist/app-debug.apk"
echo "Checksum: $ROOT/dist/app-debug.apk.sha256"
