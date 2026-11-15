# Build chimera-vocal-synth (Jameson Hodge, MIT) with this project's patch, for Windows.
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$commit = "eed4a5ff2695ad151df2210d012b2a4ab584f099"
$work = Join-Path $here "build"
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "Install Rust first: https://rustup.rs" }
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
git clone https://github.com/jamesondh/chimera-vocal-synth.git $work
Push-Location $work
git checkout -q $commit
Copy-Item (Join-Path $here "blender.rs") "crates\chimera-cli\src\blender.rs"
git apply --ignore-whitespace (Join-Path $here "main.rs.patch")
# keep local paths (user name, folders) out of the binary
$cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $HOME ".cargo" }
$env:RUSTFLAGS = "--remap-path-prefix=$cargoHome=C:\cargo --remap-path-prefix=$work=C:\chimera"
cargo build --release -p chimera-cli
$out = Join-Path $here "..\bayc_singing\bin\windows-x64"
New-Item -ItemType Directory -Force (Join-Path $out "data") | Out-Null
Copy-Item "target\release\chimera.exe" $out
Copy-Item "public\data\cmudict.txt.gz" (Join-Path $out "data")
Pop-Location
Write-Host "done: $out\chimera.exe"
