<#
.SYNOPSIS
  Make a character sing from the command line: the same thing the Blender panel does.
  Prints only the lines that matter ("BAYC: ..."), so it is cheap for AI agents too.

.EXAMPLE
  .\tools\sing.ps1 -Blend "D:\apes\my_ape.blend" -Song bored_ape_boat
  .\tools\sing.ps1 -Blend my_ape.blend -Song fart_cancan -Mode both -Look xray -Render
  .\tools\sing.ps1 -Blend my_ape.blend -Song "C:\music\tune.mid" -Lyrics "hap-py birth-day to you" -Render
  .\tools\sing.ps1 -Blend my_ape.blend -Song my_song.json -Check        (fast: checks song + character only)
#>
param(
    [Parameter(Mandatory = $true)][string]$Blend,
    [Parameter(Mandatory = $true)][string]$Song,
    [string]$Lyrics = "",
    [ValidateSet("male", "female", "child")][string]$Voice = "male",
    [ValidateSet("sing", "both", "farts")][string]$Mode = "sing",
    [ValidateSet("xray", "textured")][string]$Look = "xray",
    [switch]$Render,
    [ValidateSet("eevee", "cycles")][string]$Engine = "eevee",
    [double]$Floppy = 1.0,
    [string]$Profile = "auto",
    [string]$Transpose = "auto",
    [string]$Out = "",
    [switch]$Check,
    [string]$Blender = ""
)
$ErrorActionPreference = "Stop"
$cli = Join-Path $PSScriptRoot "..\ape_synth\engine\cli.py"
if (-not $Blender) { $Blender = $env:BLENDER }
if (-not $Blender) { $c = Get-Command blender -ErrorAction SilentlyContinue; if ($c) { $Blender = $c.Source } }
if (-not $Blender) {
    $cands = @("C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe") +
             @(Get-ChildItem "C:\Program Files\Blender Foundation\Blender*\blender.exe" -ErrorAction SilentlyContinue |
               Sort-Object FullName -Descending | ForEach-Object { $_.FullName })
    $Blender = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Blender -or -not (Test-Path $Blender)) { throw "Blender not found: pass -Blender <path to blender.exe> or set `$env:BLENDER" }
if (-not (Test-Path -LiteralPath $Blend)) { throw "not found: $Blend" }
$a = @("--song", $Song, "--voice", $Voice, "--mode", $Mode, "--look", $Look, "--floppy", "$Floppy", "--profile", $Profile, "--transpose", $Transpose)
if ($Lyrics) { $a += @("--lyrics", $Lyrics) }
if ($Render) { $a += @("--render", "--engine", $Engine) }
if ($Out) { $a += @("--out", $Out) }
if ($Check) { $a += "--check" }
$ErrorActionPreference = "Continue"     # Blender's add-ons print harmless errors on stderr
& $Blender -b $Blend --python $cli -- @a 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match "^BAYC:" } | ForEach-Object { Write-Host $_ }
exit $LASTEXITCODE
