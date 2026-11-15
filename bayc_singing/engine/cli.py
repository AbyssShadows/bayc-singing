"""Make a character sing. The one command behind the Blender panel, and the one to give an agent.

  blender -b character.blend --python <add-on>/engine/cli.py -- --song SONG [options]

  --song      a song file (.json), a MIDI melody (.mid/.midi/.kar), or the name of an included
              song (bored_ape_boat, jungle_groove, fart_cancan, jingle_bells)
  --lyrics    lyrics for a MIDI melody (text, or a .txt file); without any he scats
  --midi-track N   which MIDI track holds the melody (default: found automatically)
  --voice     male | female | child                        (default male)
  --mode      sing | both | farts   (sing, sing + farts, farts only; default sing)
  --transpose auto | <semitones>    (auto: moves the tune by octaves into the voice's range)
  --no-bend   no bend-over section in a song with farts
  --look      xray | textured   (xray: wireframe with his organs built inside; default xray)
  --render    also render the video (otherwise just build the scene)
  --engine    eevee | cycles        (textured look only; cycles = slower, path traced)
  --floppy    jiggle looseness, 0.5 (stiff) .. 2 (very floppy)    (default 1)
  --profile   character profile (auto, bayc, jnkyz, mixamo_arkit, ...)  (default auto)
  --out       output folder (default: BAYC_Sing_Output next to the .blend)
  --check     only check the character and the song (fast); builds nothing
  --cfg       JSON overrides for the engine's CFG (see engine/bayc_sing.py)

Nothing is saved over the opened .blend: the build is saved as a new file in the output folder.
Lines starting with "BAYC:" are the ones that matter (Blender prints plenty of other noise);
everything is also in <run folder>/build.log, and the outcome in <run folder>/result.json.
"""
import argparse
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import bpy  # noqa: E402

LOG = []
RUN = {}
ORGANS = {"XR_folds": "vocal folds", "XR_throat": "throat", "XR_trachea": "windpipe", "XR_lungs": "lungs",
          "XR_gut": "stomach and gut", "XR_gas": "gas bubbles", "XR_exit": "exit"}


def say(msg):
    LOG.append(msg)
    print("BAYC: " + msg, flush=True)


def platform_dir():
    m = platform.machine().lower()
    if sys.platform.startswith("win"):
        return "windows-x64"
    if sys.platform == "darwin":
        return "macos-arm64" if m in ("arm64", "aarch64") else "macos-x64"
    return "linux-arm64" if m in ("arm64", "aarch64") else "linux-x64"


def find_chimera(explicit=None):
    exe = "chimera.exe" if sys.platform.startswith("win") else "chimera"
    for c in (explicit, os.environ.get("BAYC_CHIMERA"), os.path.join(ROOT, "bin", platform_dir(), exe), shutil.which("chimera")):
        if c and os.path.isfile(c):
            return c
    raise RuntimeError(f"the voice synth isn't installed for {platform_dir()}: build it with chimera-patch/build_chimera "
                       f"(see the README) or point --chimera / BAYC_CHIMERA at it")


def find_song(s):
    for c in (s, os.path.join(ROOT, "songs", s), os.path.join(ROOT, "songs", s + ".json")):
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    have = ", ".join(sorted(os.path.splitext(f)[0] for f in os.listdir(os.path.join(ROOT, "songs")) if f.endswith(".json")))
    raise RuntimeError(f"song not found: {s} (included songs: {have})")


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()[:40] or "song"


def sing_voice(chimera, song_json, stem, voice):
    r = subprocess.run([chimera, "render", "blender", song_json, stem, voice], capture_output=True, text=True)
    msg = (r.stderr or r.stdout).strip()
    return r.returncode == 0, msg


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="cli.py", description="Make a character sing")
    ap.add_argument("--song", required=True)
    ap.add_argument("--lyrics")
    ap.add_argument("--midi-track", type=int)
    ap.add_argument("--voice", choices=("male", "female", "child"), default="male")
    ap.add_argument("--mode", choices=("sing", "both", "farts"), default="sing")
    ap.add_argument("--transpose", default="auto")
    ap.add_argument("--no-bend", action="store_true")
    ap.add_argument("--look", choices=("xray", "textured"), default="xray")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--engine", choices=("eevee", "cycles"), default="eevee")
    ap.add_argument("--floppy", type=float, default=1.0)
    ap.add_argument("--profile", default="auto")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--cfg")
    ap.add_argument("--chimera")
    a = ap.parse_args(argv)

    import bayc_rig as rig
    import bayc_songs as songtools
    if not bpy.data.filepath:
        raise RuntimeError("open your character's .blend: blender -b character.blend --python cli.py -- ...")
    chimera = find_chimera(a.chimera)
    song_path = find_song(a.song)
    song, info = songtools.load_song(song_path, a.lyrics, a.midi_track)
    song, info2 = songtools.prepare(song, a.mode, a.voice, a.transpose, not a.no_bend)
    for line in info + info2:
        say(line)
    say("song: " + songtools.summary(song))

    # the character
    rep, *_ = rig.analyse(a.profile)
    for line in rig.report_lines(rep):
        say(line)
    if not rep["ok"]:
        raise RuntimeError("this character can't sing yet (see the errors above)")

    # the syllables: they must match the notes; a MIDI melody bends to fit its words
    syl = songtools.syllables(chimera, song["lyrics"])
    n = len(songtools.sounding(song["notes"]))
    if len(syl) != n:
        if os.path.splitext(song_path)[1].lower() in (".mid", ".midi", ".kar"):
            song["notes"] = songtools.fit_notes(song["notes"], len(syl))
            if a.mode == "farts":
                song["farts"]["notes"] = songtools.fart_cover(song)["notes"]
            say(f"fitted the melody to the words: {n} notes -> {len(syl)} (one per syllable)")
        else:
            raise RuntimeError(f"the lyrics have {len(syl)} syllables but the tune has {n} notes: "
                               f"{' '.join(syl)}. Add or remove notes, split words with '-', or add '~' to hold a vowel")
    if a.check:
        say("check OK: ready to build")
        return {"ok": True, "check": True}

    blend = bpy.data.filepath
    out_root = os.path.abspath(a.out or os.path.join(os.path.dirname(blend), "BAYC_Sing_Output"))
    title = slug(os.path.splitext(os.path.basename(song_path))[0])
    tag = {"sing": "", "both": "_farts", "farts": "_fartsonly"}[a.mode] + ("_xray" if a.look == "xray" else "")
    run = os.path.join(out_root, title + tag)
    os.makedirs(run, exist_ok=True)
    RUN["dir"] = run
    song_json = os.path.join(run, title + ".song.json")
    with open(song_json, "w", encoding="utf-8") as fh:
        json.dump(song, fh, indent=1)
    stem = os.path.join(run, title)

    say("step 1/3: singing the voice")
    ok, msg = sing_voice(chimera, song_json, stem, a.voice)
    if not ok:
        raise RuntimeError("the voice synth failed: " + msg)
    farts = None
    if song.get("farts"):
        import fartsynth
        farts = fartsynth.build(song_json, stem, voice_path=stem + ".wav", voice_gain=0.0 if a.mode == "farts" else 1.0,
                                log=lambda s: LOG.append(s))
        say(f"farts: {len(farts['events'])} of them")
    audio = farts["mix"] if farts else stem + ".wav"

    say("step 2/3: animating (face, dance, jiggle)")
    import bayc_sing
    cfg = {"profile": a.profile, "vocals": a.mode != "farts", "output": run + os.sep,
           "engine": "cycles" if (a.engine == "cycles" and a.look == "textured") else "eevee",
           "stiffness_scale": 1.0 / max(0.25, a.floppy)}
    if a.cfg:
        cfg.update(json.loads(a.cfg))
    log = bayc_sing.build(stem + ".track.json", audio, title=title, cfg_over=cfg, farts=farts, fart_fx=a.look == "textured")
    LOG.extend(log)
    sc = bpy.context.scene
    if a.look == "xray":
        import bayc_xray
        xlog = bayc_xray.apply(stem + ".geom.json", stem + ".track.json", os.path.join(run, "xray_cache"),
                               cfg_over={"voice": a.mode != "farts"}, farts=farts, voice_wav=stem + ".wav")
        LOG.extend("xray: " + x for x in xlog)
        built, poke = [], []
        for x in xlog:
            m = re.match(r"inside check (\S+): (\d+)/(\d+)", x)
            if m:
                (poke if m.group(2) != m.group(3) else built).append(ORGANS.get(m.group(1), m.group(1)))
        if built or poke:
            say("anatomy built inside him: " + ", ".join(built + poke))
        if poke:
            say("WARNING partly outside the body: " + ", ".join(poke) +
                " (see build.log; the profile's \"xray\" values can move them)")
        sc.render.filepath = os.path.join(run, title + "_xray_")
    pose = bpy.data.actions.get("Pose")
    if pose:
        pose.use_fake_user = True
    out_blend = os.path.join(run, f"{os.path.splitext(os.path.basename(blend))[0]}_{title}{tag}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out_blend, relative_remap=True)
    say(f"saved {out_blend}")
    result = {"ok": True, "blend": out_blend, "run_dir": run, "audio": audio, "frames": sc.frame_end, "video": None}

    if a.render:
        say(f"step 3/3: rendering {sc.frame_end} frames ({sc.render.engine.replace('BLENDER_', '').lower()})")
        if sc.render.engine == 'CYCLES':
            bayc_sing.cycles_gpu(log=lambda s: LOG.append(s))

        def progress(scene, *_):
            say(f"frame {scene.frame_current}/{scene.frame_end}")
        bpy.app.handlers.render_post.append(progress)
        t0 = time.time()
        bpy.ops.render.render(animation=True)
        bpy.app.handlers.render_post.remove(progress)
        if sc.render.engine == 'CYCLES':
            result["video"] = bayc_sing.encode_frames(sc, audio, title + tag + "_cycles", log=lambda s: LOG.append(s))
        else:
            vids = sorted(glob.glob(bpy.path.abspath(sc.render.filepath) + "*.mp4"), key=os.path.getmtime)
            result["video"] = vids[-1] if vids else None
        say(f"rendered in {(time.time() - t0) / 60:.1f} min: {result['video']}")
    else:
        say("step 3/3: skipped rendering (open the .blend and press Play, or run again with --render)")
    return result


if __name__ == "__main__":
    res, code = {"ok": False}, 0
    try:
        res = main()
    except Exception as e:
        code = 1
        res = {"ok": False, "error": str(e)}
        LOG.append(traceback.format_exc())
        print("BAYC: ERROR " + str(e), flush=True)
    run = res.get("run_dir") or RUN.get("dir")
    if run:
        with open(os.path.join(run, "build.log"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(LOG) + "\n")
        with open(os.path.join(run, "result.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
    if res.get("ok") and not res.get("check"):
        print("BAYC: done " + json.dumps({k: res[k] for k in ("blend", "video") if res.get(k)}), flush=True)
    sys.stdout.flush()
    sys.exit(code)
