#!/bin/sh
# Make a character sing from the command line (macOS / Linux): the same thing the Blender panel does.
# Prints only the lines that matter ("BAYC: ..."), so it is cheap for AI agents too.
#
#   sh tools/sing.sh my_ape.blend --song bored_ape_boat
#   sh tools/sing.sh my_ape.blend --song fart_cancan --mode both --look xray --render
#   sh tools/sing.sh my_ape.blend --song tune.mid --lyrics "hap-py birth-day to you" --render
#   sh tools/sing.sh my_ape.blend --song my_song.json --check
# Options are the ones of bayc_singing/engine/cli.py (see the README). Set BLENDER if Blender isn't found.
set -e
[ $# -ge 2 ] || { sed -n 2,9p "$0"; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
BLEND="$1"; shift
if [ -z "$BLENDER" ]; then
  if command -v blender >/dev/null 2>&1; then BLENDER=$(command -v blender)
  elif [ -x /Applications/Blender.app/Contents/MacOS/Blender ]; then BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
  else echo "Blender not found: set BLENDER=/path/to/blender"; exit 1; fi
fi
"$BLENDER" -b "$BLEND" --python "$HERE/../bayc_singing/engine/cli.py" -- "$@" 2>&1 | grep '^BAYC:' || true
