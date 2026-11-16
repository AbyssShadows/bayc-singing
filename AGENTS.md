# AGENTS.md: make a character sing (read only this file)

This repo is a Blender add-on that makes a rigged 3D character (a BAYC ape, Jnkyz, ...) sing and
fart songs. **Don't read the engine source to do a normal job.** Everything you need is here.
Each run prints only `BAYC: ...` lines; ignore all other output.

## Recipe 1: make the character sing a song

```powershell
# Windows (finds Blender itself; -Check first is cheap, about 5 s)
.\tools\sing.ps1 -Blend "<character.blend>" -Song <song> -Check
.\tools\sing.ps1 -Blend "<character.blend>" -Song <song> [-Mode sing|both|farts] [-Look xray|textured] [-Voice male|female|child] [-Render] [-Engine eevee|cycles]
```
```sh
# macOS / Linux (set BLENDER=/path/to/blender if it isn't found)
sh tools/sing.sh "<character.blend>" --song <song> --check
sh tools/sing.sh "<character.blend>" --song <song> [--mode sing|both|farts] [--look xray|textured] [--voice ...] [--render] [--engine eevee|cycles]
```

- `<character.blend>`: a saved .blend (BAYC ape, Jnkyz, ...). For an FBX, import it into an empty
  Blender scene and save it as a .blend first.
- `<song>`: an included name (`bored_ape_boat`, `jungle_groove`, `fart_cancan`, `jingle_bells`,
  `thunder_jeans`, `fart_styles_demo`, `template_do_re_mi`), a `.json` song file, or a `.mid`/`.midi`/`.kar` file
  (add `-Lyrics "words"` or `--lyrics "words"`; without lyrics he scats).
- Modes: `sing`, `both` (sing + farts; the song's own fart part or an automatic one), `farts`
  (the farts play the tune, no singing).
- Looks: `xray` (default) is a wireframe with his organs built inside him (vocal folds, throat,
  windpipe, lungs; the gut in fart songs); `textured` keeps his own materials. X-ray runs print
  `BAYC: anatomy built inside him: ...`; a `WARNING partly outside` line means the organs don't
  fit this character (tune the profile's `xray` values).
- Success ends with `BAYC: done {"blend": ..., "video": ...}`. The input .blend is never modified.
- Times: build about 15 s; render about 1–2 min per 30 s of song (EEVEE / X-ray); Cycles about 30–60 min.
  For long renders, run in the background and wait for the process to exit.
- Outputs: `<blend dir>/Ape_Synth_Output/<song>[_farts|_fartsonly][_xray]/` with `result.json`
  and `build.log`. Read `build.log` only on failure.

## Recipe 2: write a new song file

Write `songs/<name>.json` (anywhere is fine; pass its path):

```json
{"title": "Banana Boat", "bpm": 112,
 "lyrics": "I'm a bored ape on a big blue boat",
 "notes": [["C3",0.5],["D3",0.5],["E3",1],["G3",1],["E3",0.5],["D3",0.5],["C3",1],["D3",1],["C3",2]]}
```

Rules (the build enforces them):
- A note is `[pitch, beats]`. Pitch is a name like `C3`, `F#3`, `Bb2` (C4 = middle C = 60) or a
  MIDI number. `"rest"` is a pause.
- **Exactly one syllable per sounding note.** Write words normally (the synth splits them).
  ` ~ ` (a lone tilde) holds the previous vowel one more note. Hyphenate only made-up words.
- Range: male C3–C4 (default). Auto-transposition moves the tune by octaves for female/child.
- Optional: `"t0"` (lead-in seconds, default 0.5), `"vibrato"` (default 45), and a fart part:
  `"farts": {"notes": [[0, 4], ["C2", 2, "rip", 1.2], ...], "bend": [[startBeat, endBeat]]}`
  with styles `toot parp long rip squeak blart`, `[0, beats]` = gap, on the same beat grid as the vocals.
- Count syllables yourself first. Then run with `-Check`: a mismatch prints how the synth split
  the lyrics (`the lyrics have N syllables but the tune has M notes: ...`). Fix and re-check.
- **Copyright:** write original lyrics and melodies, or use public-domain ones. Don't reproduce
  copyrighted lyrics or melodies; a "cover" isn't free to post. Tell the user so if they ask for one.

## Recipe 3: the character is not ready

`-Check` prints the character report. An error names what's missing:
- *lacks bones*: the rig uses other names. Copy `ape_synth/profiles/mixamo_arkit.json` to a new
  profile, set `bone_prefix` / `rename_bones`, and pass `-Profile <id>`.
- *no face mesh / lacks the lip-sync shape keys*: map the character's names to `jawOpen
  mouthClose mouthFunnel mouthPucker` (plus `fff_M tth_M rrr_M sss_M ssh_M lntd_M gk_M eh_M` if
  present) with `rename_shape_keys`. The schema is in `ape_synth/profiles/README.md`.

## Errors and fixes

| BAYC: ERROR ... | fix |
| --- | --- |
| `the lyrics have N syllables but the tune has M notes` | add/remove notes, add `~`, or change words |
| `song not found` | use an included name or a correct path |
| `the voice synth isn't installed for <platform>` | macOS/Linux: `sh chimera-patch/build_chimera.sh` once |
| `this character can't sing yet` | see Recipe 3 |
| anything else | read the last 20 lines of `build.log` in the run folder |

## Don'ts
- Don't edit `ape_synth/engine/*` for a normal song job. Tuning goes in `--cfg '{"key": value}'`
  (keys are in `CFG` at the top of `engine/bayc_sing.py`; e.g. `jaw_gain`, `bounce_cm`, `bend_deg`).
- Don't save over the user's .blend, and don't delete their files. The build writes new files only.
