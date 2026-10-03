#!/bin/zsh
# Run CXBoards.app's built-in self-test against the live server, on a throwaway board
# that is deleted (and purged from the trash) afterwards. Exit 0 only if every check passed.
#   scripts/selftest-app.sh [path/to/CXBoards.app]   (default: /Applications/CXBoards.app)
set -euo pipefail
APP=${1:-/Applications/CXBoards.app}
API=http://127.0.0.1:4870
H=(-H 'Content-Type: application/json' -H 'X-CXBoards: 1')
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# A real file on disk to drop, the way Finder would hand it over.
python3 - "$WORK/selftest-bounce.wav" <<'PY'
import sys, wave
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\0\0" * 800)
PY

BOARD=$(curl -sf -X POST $API/api/boards $H -d '{"title":"CXBoards app self-test"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
set +e
"$APP/Contents/MacOS/CXBoards" --selftest "$BOARD" "$WORK/selftest-bounce.wav"
CODE=$?
set -e
TRASH=$(curl -sf -X DELETE $API/api/boards/$BOARD -H 'X-CXBoards: 1' | python3 -c 'import json,sys; print(json.load(sys.stdin)["trash_id"])')
curl -sf -X DELETE $API/api/trash/$TRASH -H 'X-CXBoards: 1' >/dev/null
[[ $CODE == 0 ]] && echo "✓ CXBoards.app self-test passed" || echo "✗ CXBoards.app self-test failed" >&2
exit $CODE
