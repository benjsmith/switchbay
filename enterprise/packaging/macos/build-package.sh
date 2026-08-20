#!/bin/bash
# Build an unsigned macOS .pkg from a staged payload.
# Company: codesign --sign "Developer ID" --options runtime --entitlements
# entitlements.plist every dylib, then notarize. CI leaves notarize=false.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)
PAYLOAD=${1:-"$ROOT/dist/switchbay-enterprise-darwin-arm64"}
OUT=${2:-"$ROOT/dist/SwitchBay.pkg"}
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

INSTALL="$STAGING/Library/Application Support/SwitchBay"
mkdir -p "$INSTALL"
rsync -a --delete "$PAYLOAD/" "$INSTALL/"

cc -O2 -o "$STAGING/SwitchBay" "$ROOT/enterprise/packaging/macos/switchbay-stub.c"
mkdir -p "$STAGING/Applications/Switch Bay.app/Contents/MacOS"
mv "$STAGING/SwitchBay" "$STAGING/Applications/Switch Bay.app/Contents/MacOS/SwitchBay"
cat > "$STAGING/Applications/Switch Bay.app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>com.switchbay.app</string>
  <key>CFBundleName</key><string>Switch Bay</string>
  <key>CFBundleExecutable</key><string>SwitchBay</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
</dict>
</plist>
PLIST

pkgbuild --root "$STAGING" --identifier com.switchbay.pkg --version 0.9.16 \
  --install-location / "$OUT"
echo "unsigned pkg: $OUT"
echo "sign+notarize on the company bake machine (not CI)."
