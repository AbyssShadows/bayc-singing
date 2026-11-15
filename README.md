# Ape Synth 🎤🍌

**Make your 3D Bored Ape sing any song and fart along to it, and see inside him while he does it, all in Blender.**

Pick a song (or drop in a MIDI file), pick a voice, choose *Sing*, *Sing + Farts* or *Farts Only*,
and press one button. You get a Blender scene of your ape singing, dancing and wobbling with his
insides on show, plus an MP4 with sound.

- **His insides, built for him.** The *X-ray* look (the default) turns your ape into a glowing
  wireframe and builds the anatomy inside him: a larynx with vibrating vocal folds, a throat that
  lights up with the sound, a windpipe, bronchi, and lungs that fill between lines. When he farts
  you also get his esophagus, stomach, intestines and colon, with gas bubbles travelling down to
  the exit. Every organ is measured from your ape's own neck, chest and belly, moves with his rig
  as he dances, and is checked to stay inside his skin. His own tongue, teeth and gums do the
  singing. A vocal-fold strobe, the pitch and the sung words run at the side of the frame, plus
  sound displays when he farts.
- **A real singing voice.** A physical model of a human airway sings the song. The mouth, tongue
  and jaw follow the same movements that made the sound, so the lip sync isn't guessed.
- **Goofy ragdoll physics.** A bobble head, floppy arms and hands, flapping ears, googly eyes and
  a hat that hops on the beat.
- **Farts that play the tune.** Toots, parps, rips and squeaks, pitched so they can play a melody.
  He bends over and shakes for the big ones.
- **Or keep him textured.** The *Textured* look is your ape as he is, with his own materials and
  green gas clouds when he farts. Render it with EEVEE or Cycles.
- **Your own music.** Use the included songs, write one in a few lines of text, import a MIDI
  melody (karaoke `.kar` files bring their lyrics), or ask an AI agent to write one.
- **Other characters.** Works with any ape built on the BAYC Advanced Skeleton rig. Jnkyz support
  is being prepared, and Mixamo-rigged characters are an experimental option.

> ### Credits
> The singing voice is **[chimera-vocal-synth](https://github.com/jamesondh/chimera-vocal-synth)
> by Jameson Hodge** (MIT license), a physical-modeling voice synthesizer. This project bundles a
> build of it with one small added export command (see [`chimera-patch/`](chimera-patch/)). All the
> singing, and the mouth and throat movements, come from his work. Thank you, Jameson!
> Full credits and licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

## Contents

1. [What you need](#1-what-you-need)
2. [Install (2 minutes)](#2-install-2-minutes)
3. [Make him sing](#3-make-him-sing)
4. [Every option explained](#4-every-option-explained)
5. [Your own songs](#5-your-own-songs)
6. [Farts](#6-farts)
7. [What you get](#7-what-you-get)
8. [Other characters (Jnkyz, Mixamo, ...)](#8-other-characters-jnkyz-mixamo-)
9. [Using an AI agent (cheap on tokens)](#9-using-an-ai-agent-cheap-on-tokens)
10. [Command line](#10-command-line)
11. [Troubleshooting](#11-troubleshooting)
12. [Copyright and posting](#12-copyright-and-posting)
13. [How it works](#13-how-it-works)

---

## 1. What you need

- **Blender 5.2 or newer.** It's free from [blender.org](https://www.blender.org/download/) (or Steam).
- **Your ape as a `.blend` file**, rigged with the BAYC Advanced Skeleton rig and its face shape
  keys (`jawOpen`, `mouthFunnel`, ...). Not sure? The add-on's **Check my character** button tells you.
- **Windows** works out of the box. **macOS / Linux:** build the voice synth once (about 5
  minutes, see [`chimera-patch/README.md`](chimera-patch/README.md)).
- A GPU helps for rendering. Building the animation itself takes seconds on any machine.

## 2. Install (2 minutes)

1. Download **`ape_synth-<version>.zip`** from the
   [Releases page](https://github.com/AbyssShadows/ape-synth/releases/latest). Don't unzip it.
2. In Blender: **Edit > Preferences > Add-ons**. Click the **⌄** menu at the top right, choose
   **Install from Disk...**, and pick the zip.
3. Make sure **Ape Synth** is ticked.

> Downloaded the whole repository instead (Code > Download ZIP)? That zip won't install directly.
> Run `python tools/make_zip.py` to build the add-on zip in `dist/`, or zip the contents of the
> `ape_synth` folder yourself.

## 3. Make him sing

1. **Open your ape's `.blend`** and save it (the build reads the saved file).
2. In the 3D Viewport, press **N** to open the sidebar and click the **Ape Synth** tab.
3. **1. Character:** click **Check my character**. You should see *Ready to sing*. If not, read
   the lines it shows (see [Troubleshooting](#11-troubleshooting)).
4. **2. Song:** pick an included song, or switch to **My file** and choose a song file or a MIDI file.
5. **3. Performance:** pick the voice and the mode (**Sing**, **Sing + Farts**, **Farts Only**).
6. **4. Look and render:** keep **X-ray** to see his organs working inside him, or pick **Textured**
   for your ape as he is. Tick **Render video** if you want the MP4.
7. Click **Make him sing!**

The build runs in the background, so you can keep using Blender. The panel shows the progress.
When it says **Done**, click **Open scene** to see the result and press Play (Spacebar), or
**Play video** if you rendered one.

**Your file is never changed.** Every result is saved as a new `.blend` in the output folder
(by default `Ape_Synth_Output`, next to your file).

How long it takes on a good PC: the build is about 10–20 seconds. The video for a 30-second song
is about 1–2 minutes in EEVEE or the X-ray look, and about 30–60 minutes in Cycles.

## 4. Every option explained

| option | what it does |
| --- | --- |
| **Character** | Which profile describes your character. **Auto-detect** picks it for you. |
| **Song from** | **Included song**: the songs below. **My file**: your `.json` song or a `.mid` / `.midi` / `.kar` melody. |
| **Lyrics** *(MIDI only)* | The words to sing, or a path to a `.txt` file. Leave it empty to use the file's karaoke lyrics, or he scats "doo bee doo bah". |
| **MIDI track** *(MIDI only)* | Which track holds the melody. `-1` finds it automatically. |
| **Auto key / Transpose** | **Auto key** moves the tune by whole octaves into the chosen voice's range (best for MIDI files). Or untick it and set a number of semitones. |
| **Voice** | Male, female or child. |
| **Mode** | **Sing**: he sings. **Sing + Farts**: he sings and farts, using the song's own fart part or one fart in every gap of the vocal line plus a rip at the end. **Farts Only**: the farts play the tune, and he keeps his mouth shut and dances. |
| **Bend over** | In a song with farts: a deep bend-over with a butt shake in the middle of the song. |
| **Floppiness** | How loose the ragdoll jiggle is: 0.5 is stiff, 1 is the default, 2 is very floppy. |
| **Look** | **X-ray** (default): the glowing wireframe with his organs built inside him (larynx and vocal folds, throat, windpipe, lungs, and the gut when he farts), all measured from his body. The run ends by reporting that they sit inside him. **Textured**: your ape with his own materials and your scene's lights (a three-light studio is added if your scene has none). |
| **Render video** | Also render the MP4 with sound. Without it you get the scene only, to play or render yourself. |
| **Engine** | Textured look only. **EEVEE** is fast. **Cycles** is path traced, the best quality and much slower. Cycles renders frames first and resumes if stopped. |
| **Output** | Where results go. `//` means next to your `.blend`. |

## 5. Your own songs

### A. Write a song file (a few lines of text)

Copy `songs/template_do_re_mi.json` (inside the add-on folder, or in this repo under
`ape_synth/songs/`) and edit it:

```json
{
  "title": "My Ape Song",
  "bpm": 110,
  "lyrics": "I'm a bored ape and I love to sing ~",
  "notes": [["C3", 0.5], ["D3", 0.5], ["E3", 1], ["G3", 1], ["E3", 1],
            ["D3", 1], ["C3", 0.5], ["D3", 0.5], ["E3", 2], ["E3", 2]]
}
```

- Each note is `[pitch, beats]`. Pitch is a note name (`C3`, `F#3`, `Bb2`; `C4` is middle C) or a
  MIDI number (60 = C4). Use `"rest"` for a pause.
- The rule that matters: **one syllable per sung note.** Write words normally, because the synth
  splits them itself (*wonderful* is won-der-ful). A lone `~` holds the previous vowel over one
  more note (*sing ~* sings "sing" over two notes). Hyphens force splits in made-up words
  (*boo-ga-loo*).
- If the count is off, the build tells you exactly how the synth split your lyrics, for example
  `the lyrics have 11 syllables but the tune has 10 notes: I'm a bored ape and I real ly love to sing`.
- Good ranges: male C3–C4, female and child an octave higher. **Auto key** fixes the octave for you.
- Optional fields: `"t0"` (seconds of silence before the first note, default 0.5) and
  `"vibrato"` (default 45).

### B. Import a MIDI melody

Choose **My file** and pick the `.mid`. The add-on finds the melody track, turns chords into a
single line, and quantizes it to 1/16 notes.

- Karaoke **`.kar`** files bring their own lyrics, matched note by note.
- Otherwise type the **Lyrics**. If they don't fit the melody exactly, the add-on merges or splits
  notes until they do.
- With no lyrics at all, he scats.

### C. Ask an AI agent to write one

See [section 9](#9-using-an-ai-agent-cheap-on-tokens).

### Included songs (all free to post)

| song | what |
| --- | --- |
| `bored_ape_boat` | Original goofy tune, 104 bpm |
| `jungle_groove` | Original funk-pop, 118 bpm |
| `fart_cancan` | The Can-Can (Offenbach, 1858, public domain) with new lyrics and its own fart part with a bend-over |
| `jingle_bells` | Public-domain classic (1857) |
| `fart_styles_demo` | Every fart style in turn (farts only) |
| `template_do_re_mi` | The template to copy |

## 6. Farts

Pick **Sing + Farts** or **Farts Only**, and any song gets a fart part automatically. To write
your own, add a `"farts"` part to the song file. It uses the same beat grid as the vocal melody:

```json
"farts": {
  "notes": [[0, 4], ["G2", 1, "parp"], [0, 3], ["C2", 3, "rip", 1.15], ["G4", 0.5, "squeak"]],
  "bend": [[16, 24]]
}
```

- Each fart note is `[pitch, beats, style, loudness]`. Style and loudness are optional, and
  `[0, beats]` is a gap.
- **Styles:** `toot` (short), `parp` (a beat), `long`, `rip` (long and wet, slowing to single
  pops), `squeak` (high, chirps up), `blart` (low and messy).
- **Pitch:** C2–C3 is the tuba register, and C3–C4 carries a tune well.
- **`bend`:** the beats (counted from the first note) where he bends right over and shakes.
- Every toot is a butt pop, and big ones make his hat hop and his ears flap. In the textured look
  each fart puffs out a green gas cloud. In the X-ray look you see the gas bubble travel through
  his gut.

## 7. What you get

In the output folder, one subfolder per song, mode and look (for example
`Ape_Synth_Output/fart_cancan_farts_xray/`):

| file | what |
| --- | --- |
| `<your file>_<song>....blend` | The scene. Open it and press Play: the audio is in the sequencer. |
| `<song>_0001-NNNN.mp4` | The video (EEVEE and X-ray). |
| `<song>..._cycles_0001-NNNN.mp4` + `..._cycles_frames/` | The Cycles video, and the frames it was made from. Delete the frames once you're happy. |
| `<song>.wav`, `<song>.mix.wav` | The voice, and the voice plus farts. |
| `<song>.song.json` | The song exactly as sung: after transposing and fitting, with the fart part. |
| `build.log`, `result.json` | What happened, for troubleshooting. |

In the scene, everything is plain Blender data you can tweak:
- the actions `BAYC_Sing_Body` (all bones, baked) and `BAYC_Sing_Face` (shape keys)
- the camera `Sing_Cam`
- the extra jiggle bones `Hat_Jiggle`, `Ear_L` and `Ear_R`
- in fart songs, the gas clouds (`Fart_FX` collection) and `Stage_Turntable`. The turntable turns
  your backdrop and lights with the camera, so it always faces the backdrop.

## 8. Other characters (Jnkyz, Mixamo, ...)

The add-on reads small **profiles** (`ape_synth/profiles/*.json`). A profile says which bones,
meshes and shape keys do which job. It can also rename them, and those renames happen only in
the build's copy.

- **BAYC** (Advanced Skeleton rig): tested.
- **Jnkyz:** a draft profile is ready, assuming the same rig and face shapes. If **Check my
  character** reports something missing on your Jnkyz, open an issue with what it says.
- **Mixamo** bodies with ARKit / Oculus viseme faces: experimental. The build strips the
  `mixamorig:` prefix and maps the visemes. Hat and ear jiggle bones are off, because their
  placement depends on the character.

See [`ape_synth/profiles/README.md`](ape_synth/profiles/README.md) to write a profile for a
new character. It's one small JSON file.

## 9. Using an AI agent (cheap on tokens)

Agents (Claude Code, Codex, Cursor, ...) don't need to read the code. [`AGENTS.md`](AGENTS.md)
gives them everything in one short page: the commands, the song format, and fixes for common
errors. The command prints only a handful of `BAYC:` lines, so a whole song costs a few thousand
tokens.

Copy-paste prompt:

> Read AGENTS.md in this repo (nothing else). Write an original song about my ape eating bananas
> on a boat, about 30 seconds, upbeat, and make him sing it with farts in the X-ray look and
> render it. My ape is `D:\apes\my_ape.blend`.

## 10. Command line

The panel runs `ape_synth/engine/cli.py` inside a background Blender. You can run it yourself:

```powershell
# Windows: the helper finds Blender for you and prints only the important lines
.\tools\sing.ps1 -Blend "D:\apes\my_ape.blend" -Song bored_ape_boat
.\tools\sing.ps1 -Blend "D:\apes\my_ape.blend" -Song fart_cancan -Mode both -Look xray -Render
.\tools\sing.ps1 -Blend "D:\apes\my_ape.blend" -Song "D:\music\tune.mid" -Lyrics "happy birthday to you" -Mode farts -Render
.\tools\sing.ps1 -Blend "D:\apes\my_ape.blend" -Song my_song.json -Check     # 5 s: checks song + character
```

```sh
# macOS / Linux
sh tools/sing.sh ~/apes/my_ape.blend --song bored_ape_boat --mode both --render
```

Or call Blender directly:

```
blender -b my_ape.blend --python ape_synth/engine/cli.py -- --song SONG [--voice male|female|child]
        [--mode sing|both|farts] [--look xray|textured] [--render] [--engine eevee|cycles]
        [--lyrics TEXT] [--midi-track N] [--transpose auto|N] [--no-bend] [--floppy 1.0]
        [--profile auto|bayc|jnkyz|mixamo_arkit] [--out DIR] [--check] [--cfg JSON]
```

`--cfg` reaches every tuning value in `CFG` at the top of `engine/bayc_sing.py`, for example
`--cfg "{\"jaw_gain\": 1.8, \"bounce_cm\": 4}"`.

## 11. Troubleshooting

| you see | do this |
| --- | --- |
| You installed the earlier **BAYC Singing** (1.0.x) | Ape Synth replaces it. Remove the old one first: **Edit → Preferences → Add-ons → BAYC Singing → ⌄ → Uninstall**, restart Blender, then install Ape Synth. |
| *the armature lacks bones the dance needs* | Your rig uses other bone names. Pick or write a [profile](#8-other-characters-jnkyz-mixamo-) that renames them. |
| *no face mesh: none of his meshes has a 'jawOpen' shape key* | The face shape keys are missing, or named differently (add `rename_shape_keys` to a profile). |
| *the lyrics have N syllables but the tune has M notes* | Add or remove notes, use `~` to hold a vowel, or change the words. The message shows how the synth split them. |
| *the voice synth isn't installed for macos-...* | Build it once: [`chimera-patch/README.md`](chimera-patch/README.md). |
| The panel says Failed | Open the folder: `build.log` has the details. |
| The hat flies off / the ears don't move | Check the `jiggle swing` line in `build.log`. Lower **Floppiness**, or see the `JIGGLE` table in `engine/bayc_sing.py`. |
| Cycles render stopped | Click **Make him sing!** again with the same settings. It carries on from the last frame. |
| The X-ray anatomy sits wrong on a non-BAYC character | The X-ray look is fitted to the BAYC body. Use the textured look, or tune the profile's `xray` values. |

## 12. Copyright and posting

- **This tool:** MIT license. Use it for anything, including commercial videos of your own ape.
- **The voice:** chimera-vocal-synth by Jameson Hodge, MIT license. Please keep the credit when you
  share the tool.
- **Your ape:** BAYC is a Yuga Labs trademark, and this project isn't affiliated with Yuga Labs.
  Use characters you hold the rights to.
- **Songs:** the included ones are originals or public domain, so they're free to post.
  **A cover of a copyrighted song is still copyrighted**, even when a synth sings it with new
  sounds. Posting one can get your video muted or taken down. Use originals, tunes old enough to
  be public domain (in the US, published before 1931; elsewhere it depends on when the composer
  died), or songs you have a license for. The same goes for
  MIDI files and lyrics you import.

## 13. How it works

1. **Voice:** chimera simulates lungs, vocal folds and a vocal tract singing your notes and lyrics.
   Besides the WAV, it exports the jaw, lips, tongue and throat movements over time.
2. **Face:** those movements drive the face shape keys (jaw, lip closure, rounding, F/V, TH, R, S,
   SH, and the tongue tip and back). On top come the expressions: brows that follow the pitch,
   blinks, and cheek puffs.
3. **Dance:** a beat-synced dance on the rig. The feet stay planted, with knee bends, sway, head
   bobs and gestures. Fart songs add butt pops and the bend-over.
4. **Jiggle:** a spring-and-damper simulation on the loose parts (head, arms, hands, ears, eyes,
   hat), baked to keyframes so it renders anywhere.
5. **Farts:** a small source-filter synth (`engine/fartsynth.py`). A pulsing valve feeds a
   resonant tube, and the pulse rate is the pitch, so farts can play notes.
6. **Stage:** the audio as a sound strip, a camera move, the X-ray materials or gas clouds, and the
   render settings.

Project layout:

```
ape_synth/              the Blender add-on (this is what the release zip contains)
  __init__.py           the panel
  engine/cli.py         the one command that does everything
  engine/bayc_sing.py   face, dance, jiggle, stage, gas clouds
  engine/bayc_xray.py   the X-ray look
  engine/bayc_songs.py  song files, MIDI import, auto fart parts
  engine/bayc_rig.py    character profiles and detection
  engine/fartsynth.py   the fart synthesizer
  profiles/             character profiles
  songs/                included songs
  bin/                  the voice synth (chimera) and its licenses
  fonts/                the X-ray lettering (AVHershey, CC0)
chimera-patch/          the small addition to chimera, and scripts to build it
tools/                  sing.ps1 / sing.sh helpers, make_zip.py
AGENTS.md               the short guide for AI agents
```

Made for the BAYC community. Have fun, and keep it goofy. 🦍💨
