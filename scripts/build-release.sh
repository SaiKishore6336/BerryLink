#!/usr/bin/env bash
# Build the release-signed BerryLink APK.
#
# Requires (both gitignored, local only):
#   android/release-keystore.jks   private keystore
#   android/keystore.properties    storeFile/keyAlias/storePassword/keyPassword
#
# Output:
#   dist/app-release.apk + dist/app-release.apk.sha256
# The GitHub release asset should be uploaded as BerryLink-<version>.apk —
# one APK per release page; replace it, never stack.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
export ANDROID_SDK_ROOT="${ANDROID_HOME:-$ANDROID_SDK_ROOT}"

if [[ ! -d "$ANDROID_HOME" ]]; then
    echo "Android SDK not found at $ANDROID_HOME." >&2
    echo "Set ANDROID_HOME to the SDK directory and retry." >&2
    exit 1
fi
if [[ ! -x "$ROOT/android/gradlew" ]]; then
    echo "The Gradle wrapper is missing or not executable: android/gradlew" >&2
    exit 1
fi
if [[ ! -f "$ROOT/android/keystore.properties" || ! -f "$ROOT/android/release-keystore.jks" ]]; then
    echo "Release signing material is missing:" >&2
    echo "  need android/release-keystore.jks and android/keystore.properties" >&2
    echo "Create them locally; both are gitignored and must never be committed." >&2
    exit 1
fi

"$ROOT/android/gradlew" -p "$ROOT/android" \
    :app:testDebugUnitTest :app:assembleRelease --console=plain

APK="$ROOT/android/app/build/outputs/apk/release/app-release.apk"
if [[ ! -f "$APK" ]]; then
    echo "The build finished without producing app-release.apk" >&2
    exit 1
fi

mkdir -p "$ROOT/dist"
install -m 0644 "$APK" "$ROOT/dist/app-release.apk"
(
    cd "$ROOT/dist"
    sha256sum app-release.apk > app-release.apk.sha256
)

echo "Release APK:   $ROOT/dist/app-release.apk"
echo "Checksum file: $ROOT/dist/app-release.apk.sha256"

SIGNER="$(ls "$ANDROID_HOME"/build-tools/*/apksigner 2>/dev/null | sort -V | tail -1 || true)"
if [[ -n "${SIGNER:-}" ]]; then
    echo "Signature:"
    "$SIGNER" verify --print-certs "$ROOT/dist/app-release.apk" 2>/dev/null | grep -i "DN:\|SHA-256" | head -3
fi
