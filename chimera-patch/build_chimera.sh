#!/bin/sh
# Build chimera-vocal-synth (Jameson Hodge, MIT) with this project's patch, for macOS or Linux.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
COMMIT=eed4a5ff2695ad151df2210d012b2a4ab584f099
WORK="$HERE/build"
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PLAT=macos-arm64 ;;
  Darwin-*) PLAT=macos-x64 ;;
  Linux-aarch64|Linux-arm64) PLAT=linux-arm64 ;;
  *) PLAT=linux-x64 ;;
esac
command -v cargo >/dev/null || { echo "Install Rust first: https://rustup.rs"; exit 1; }
rm -rf "$WORK"
git clone https://github.com/jamesondh/chimera-vocal-synth.git "$WORK"
cd "$WORK"
git checkout -q $COMMIT
cp "$HERE/blender.rs" crates/chimera-cli/src/blender.rs
git apply --ignore-whitespace "$HERE/main.rs.patch"
# keep local paths (user name, folders) out of the binary
RUSTFLAGS="--remap-path-prefix=${CARGO_HOME:-$HOME/.cargo}=/cargo --remap-path-prefix=$WORK=/chimera" \
  cargo build --release -p chimera-cli
OUT="$HERE/../ape_synth/bin/$PLAT"
mkdir -p "$OUT/data"
cp target/release/chimera "$OUT/chimera"
cp public/data/cmudict.txt.gz "$OUT/data/"
echo "done: $OUT/chimera"
