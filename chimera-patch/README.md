# The voice synth: chimera-vocal-synth plus a small patch

The singing voice comes from **chimera-vocal-synth** by Jameson Hodge
(https://github.com/jamesondh/chimera-vocal-synth, MIT license). This folder holds the two small
additions this project needs on top of it:

| file | what it does |
| --- | --- |
| `blender.rs` | a new `chimera render blender` command: the same WAV as `render notes`, plus `<out>.track.json` (mouth, tongue and throat movements at 200 Hz) and `<out>.geom.json` (the airway shape at 30 fps) that the animation follows |
| `main.rs.patch` | registers the command, and lets a standalone copy of the binary find its dictionary in a `data/` folder next to itself |

They apply to upstream commit `eed4a5ff2695ad151df2210d012b2a4ab584f099`. The sound engine itself is
not changed.

**Windows** users don't need any of this: the add-on ships a ready-built `chimera.exe` in
`ape_synth/bin/windows-x64/`.

## macOS and Linux: build it once (about 5 minutes)

1. Install Rust from https://rustup.rs and git.
2. In this folder, run:

   ```sh
   sh build_chimera.sh
   ```

   It clones chimera at the pinned commit, applies the patch, builds it, and copies the binary and
   its dictionary into `../ape_synth/bin/<platform>/`, where the add-on looks for it.
3. Make the add-on zip again (`python tools/make_zip.py`) and install that, or point the add-on's
   preferences at the binary (Edit > Preferences > Add-ons > Ape Synth > Voice synth).

## Windows: rebuild it yourself (optional)

```powershell
powershell -ExecutionPolicy Bypass -File build_chimera.ps1
```
