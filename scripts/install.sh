#!/bin/zsh
# Build the UI, (re)install the LaunchAgent, and wait for the server to answer.
# Safe to re-run after any change: it rebuilds and restarts.
set -euo pipefail
repo=${0:A:h:h}
label=com.cx.cxboards.server
plist=~/Library/LaunchAgents/$label.plist

cd $repo/web && npm run build --silent
cp $repo/deploy/$label.plist $plist
launchctl bootout gui/$(id -u)/$label 2>/dev/null || true
launchctl bootstrap gui/$(id -u) $plist
for _ in {1..30}; do
  curl -sf http://127.0.0.1:4870/api/health >/dev/null && { echo "CXBoards is up: http://127.0.0.1:4870"; exit 0; }
  sleep 0.5
done
echo "CXBoards didn't answer; see ~/Library/Logs/cxboards.log" >&2
exit 1
