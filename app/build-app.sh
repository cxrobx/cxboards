#!/bin/zsh
# Build CXBoards.app and install it to /Applications.
#   app/build-app.sh               # build + install
#   app/build-app.sh --no-install  # build only (app/build/CXBoards.app)
#
# The app is a native window around the board server (LaunchAgent com.cx.cxboards.server);
# it bundles no server of its own. Signed with the keychain's Apple Development identity so
# macOS keeps any permission it grants across rebuilds; ad hoc when there is none.
set -euo pipefail
DIR=${0:A:h}
ROOT=${DIR:h}
BUILD="$DIR/build"
BUNDLE="$BUILD/CXBoards.app"
DEST="/Applications/CXBoards.app"

echo "→ Cleaning"
rm -rf "$BUILD"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"

echo "→ Compiling Swift"
swiftc -O -swift-version 5 -framework Cocoa -framework WebKit \
  "$DIR/CXBoards.swift" -o "$BUNDLE/Contents/MacOS/CXBoards" 2>&1 | tee "$BUILD/swiftc.log"
if grep -q "nearly matches" "$BUILD/swiftc.log"; then
  echo "A delegate method doesn't match WebKit's signature, so it would never be called." >&2
  exit 1
fi

echo "→ Icon"
ICONSET="$BUILD/AppIcon.iconset"
mkdir -p "$ICONSET"
SRC="$ROOT/assets/icon/candidate-2.png"
for s in 16 32 128 256 512; do
  sips -z $s $s "$SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUNDLE/Contents/Resources/AppIcon.icns"

echo "→ Bundle"
cp "$DIR/Info.plist" "$BUNDLE/Contents/Info.plist"
plutil -lint "$BUNDLE/Contents/Info.plist" >/dev/null

echo "→ Signing"
IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null | awk -F'"' '/Apple Development: /{print $2; exit}')"
if [[ -n "$IDENTITY" ]] && codesign --force --sign "$IDENTITY" "$BUNDLE" 2>/dev/null; then
  echo "  signed with $IDENTITY"
else
  codesign --force --sign - "$BUNDLE"
  echo "  signed ad hoc"
fi
codesign --verify --strict "$BUNDLE"

if [[ "${1:-}" == "--no-install" ]]; then
  echo "✓ Built $BUNDLE"
  exit 0
fi

echo "→ Installing to $DEST"
BACKUP="$BUILD/CXBoards.previous.app"
if pgrep -xq CXBoards; then
  osascript -e 'tell application "CXBoards" to quit' >/dev/null 2>&1 || true
  sleep 1
fi
[[ -e "$DEST" ]] && mv "$DEST" "$BACKUP"
if ! ditto "$BUNDLE" "$DEST"; then
  [[ -e "$BACKUP" ]] && mv "$BACKUP" "$DEST"
  echo "Install failed; the previous app was put back." >&2
  exit 1
fi
rm -rf "$BACKUP"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST" >/dev/null 2>&1 || true
echo "✓ Installed $DEST — open it from Spotlight, Launchpad or Alfred as “CXBoards”, or: open -a CXBoards"
