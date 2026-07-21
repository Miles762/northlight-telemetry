#!/bin/bash
# =============================================================================
# make-app-bundle.sh  ·  wrap the SwiftPM binary into a proper .app bundle
# =============================================================================
# The machine has Command Line Tools but not full Xcode, so we build with
# `swift build` and assemble the .app by hand. macOS grants Input Monitoring /
# Accessibility to a bundled app with a stable bundle id and the right usage
# strings, which a bare terminal binary does not reliably get -- so this bundle
# is what you actually run to capture keyboard/mouse counts.
#
# Usage:
#   swift build -c release
#   ./Scripts/make-app-bundle.sh
#   open ./NorthLightAgent.app
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG="${1:-release}"
BIN=".build/${CONFIG}/NorthLightAgent"
if [[ ! -x "$BIN" ]]; then
  echo "Binary not found at $BIN — run: swift build -c ${CONFIG}" >&2
  exit 1
fi

APP="NorthLightAgent.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/NorthLightAgent"

# Info.plist: this local take-home build shows a normal launch window for the
# explicit consent step. NS*UsageDescription strings are what macOS shows in the
# permission prompt -- they state plainly that we count input, never read it.
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>NorthLight Agent</string>
  <key>CFBundleDisplayName</key>     <string>NorthLight Agent</string>
  <key>CFBundleIdentifier</key>      <string>com.northlight.agent</string>
  <key>CFBundleVersion</key>         <string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleExecutable</key>      <string>NorthLightAgent</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>LSMinimumSystemVersion</key>  <string>13.0</string>
  <key>NSInputMonitoringUsageDescription</key>
    <string>NorthLight counts how often you use the keyboard and mouse to measure activity level. It never records which keys or characters you press.</string>
  <key>NSAppleEventsUsageDescription</key>
    <string>NorthLight reads only the name of the frontmost application to measure app switching. It never reads window titles, URLs, or screen contents.</string>
</dict>
</plist>
PLIST

# Ad-hoc codesign so the bundle has a stable identity for the TCC permission
# system (real distribution would use a Developer ID; ad-hoc is fine locally).
codesign --force --deep --sign - "$APP" 2>/dev/null \
  && echo "signed (ad-hoc)" || echo "codesign skipped (not fatal for local run)"

echo "Built $APP — run:  open ./$APP"
