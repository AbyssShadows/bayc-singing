"""BAYC Singing: make your 3D ape (or another character with a profile) sing and fart any song.

The panel lives in the 3D Viewport's sidebar (press N, tab "BAYC Sing"). It never changes your
file: "Make it" runs the build in a second, background Blender on your saved .blend and saves
the result as a new .blend (and video) in the output folder, so Blender stays usable meanwhile.
The work itself is engine/cli.py, which you (or an AI agent) can also run from a terminal.
"""
import json
import os
import queue
import subprocess
import sys
import threading

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ADDON_DIR, "engine")
SONGS = os.path.join(ADDON_DIR, "songs")
PROFILES = os.path.join(ADDON_DIR, "profiles")
REPO_URL = "https://github.com/AbyssShadows/ape-synth"

JOB = {"proc": None, "queue": None, "status": "", "progress": None, "result": None, "error": None,
       "lines": [], "check": [], "check_ok": None, "anatomy": ""}
_ENUM_CACHE = {}


# ------------------------------------------------------------------------------------------------
# settings (saved with the .blend)
# ------------------------------------------------------------------------------------------------
def _song_items(self, context):
    items = []
    for f in sorted(os.listdir(SONGS)) if os.path.isdir(SONGS) else []:
        if f.endswith(".json"):
            try:
                with open(os.path.join(SONGS, f), encoding="utf-8") as fh:
                    d = json.load(fh)
                title = d.get("title", f[:-5])
                extra = " (+ farts)" if "farts" in d else ""
            except Exception:
                title, extra = f[:-5], ""
            items.append((f[:-5], title[:60] + extra, os.path.join("songs", f)))
    _ENUM_CACHE["songs"] = items or [("none", "(no songs found)", "")]
    return _ENUM_CACHE["songs"]


def _profile_items(self, context):
    items = [("auto", "Auto-detect", "Pick the profile that matches the scene best")]
    for f in sorted(os.listdir(PROFILES)) if os.path.isdir(PROFILES) else []:
        if f.endswith(".json"):
            try:
                with open(os.path.join(PROFILES, f), encoding="utf-8") as fh:
                    d = json.load(fh)
                items.append((d["id"], d.get("name", d["id"]), d.get("status", "")))
            except Exception:
                pass
    _ENUM_CACHE["profiles"] = items
    return _ENUM_CACHE["profiles"]


class BAYCSING_Settings(bpy.types.PropertyGroup):
    source: EnumProperty(name="Song from", items=[
        ("INCLUDED", "Included song", "One of the songs that come with the add-on"),
        ("FILE", "My file", "A song file (.json) or a MIDI melody (.mid, .midi, .kar)")], default="INCLUDED")
    song: EnumProperty(name="Song", items=_song_items)
    song_file: StringProperty(name="File", subtype='FILE_PATH',
                              description="A song file (.json) or a MIDI melody (.mid/.midi/.kar)")
    lyrics: StringProperty(name="Lyrics", description="Lyrics for a MIDI melody (or a path to a .txt file). "
                           "Empty: the file's own karaoke lyrics, or he scats 'doo bee doo'")
    midi_track: IntProperty(name="MIDI track", default=-1, min=-1, max=64,
                            description="Which track of the MIDI file holds the melody (-1 = find it)")
    voice: EnumProperty(name="Voice", items=[("male", "Male", ""), ("female", "Female", ""), ("child", "Child", "")])
    mode: EnumProperty(name="Mode", items=[
        ("sing", "Sing", "He sings the song"),
        ("both", "Sing + Farts", "He sings and farts (the song's own fart part, or one fart in every gap)"),
        ("farts", "Farts Only", "He farts the tune and doesn't sing")], default="sing")
    bend: BoolProperty(name="Bend over", default=True, description="A deep bend-over section in a song with farts")
    transpose_auto: BoolProperty(name="Auto key", default=True,
                                 description="Move the tune by octaves into the voice's range")
    transpose: IntProperty(name="Transpose", default=0, min=-36, max=36, description="Semitones")
    look: EnumProperty(name="Look", default="xray", items=[
        ("xray", "X-ray", "Glowing wireframe with his organs built inside: vocal folds, throat, lungs and (with farts) the gut"),
        ("textured", "Textured", "Your character as it is, with its own materials and lights")])
    render: BoolProperty(name="Render video", default=False, description="Also render the MP4 (takes a while)")
    engine: EnumProperty(name="Engine", items=[("eevee", "EEVEE (fast)", ""), ("cycles", "Cycles (best, slow)", "")])
    floppy: FloatProperty(name="Floppiness", default=1.0, min=0.5, max=2.0,
                          description="How loose the ragdoll jiggle is (1 = default)")
    profile: EnumProperty(name="Character", items=_profile_items)
    out_dir: StringProperty(name="Output", subtype='DIR_PATH', default="//BAYC_Sing_Output",
                            description="Where the new .blend, audio and video go (// = next to your .blend)")


class BAYCSING_Prefs(bpy.types.AddonPreferences):
    bl_idname = __package__
    chimera_path: StringProperty(name="Voice synth (chimera)", subtype='FILE_PATH',
                                 description="Only if you built chimera yourself (macOS/Linux); Windows uses the bundled one")

    def draw(self, context):
        self.layout.prop(self, "chimera_path")
        self.layout.operator("wm.url_open", text="Help (README)", icon='HELP').url = REPO_URL


# ------------------------------------------------------------------------------------------------
# operators
# ------------------------------------------------------------------------------------------------
def _engine_import():
    if ENGINE not in sys.path:
        sys.path.insert(0, ENGINE)
    import importlib
    import bayc_rig
    import bayc_sing
    importlib.reload(bayc_sing)
    importlib.reload(bayc_rig)
    return bayc_rig


def _redraw():
    wm = bpy.context.window_manager
    for w in wm.windows:
        for area in w.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class BAYCSING_OT_check(bpy.types.Operator):
    bl_idname = "bayc_sing.check"
    bl_label = "Check my character"
    bl_description = "See which bones, meshes and face shapes the add-on finds (changes nothing)"

    def execute(self, context):
        try:
            rig = _engine_import()
            rep, *_ = rig.analyse(context.scene.bayc_sing.profile)
            JOB["check"], JOB["check_ok"] = rig.report_lines(rep), rep["ok"]
        except Exception as e:
            JOB["check"], JOB["check_ok"] = [f"ERROR: {e}"], False
        return {'FINISHED'}


def _poll_job():
    q = JOB["queue"]
    while q is not None and not q.empty():
        line = q.get_nowait()
        JOB["lines"] = (JOB["lines"] + [line])[-6:]
        if line.startswith("frame "):
            try:
                a, b = line.split()[1].split("/")
                JOB["progress"] = (int(a), int(b))
                JOB["status"] = f"Rendering frame {a} of {b}"
            except ValueError:
                pass
        elif line.startswith("ERROR"):
            JOB["error"] = line[6:]
            JOB["status"] = "Failed"
        elif line.startswith("done "):
            try:
                JOB["result"] = json.loads(line[5:])
            except ValueError:
                pass
        elif line.startswith("step "):
            JOB["status"] = line.split(":", 1)[1].strip().capitalize()
        elif line.startswith(("anatomy", "WARNING")):
            JOB["anatomy"] = line
        elif line.startswith("saved "):
            JOB["result"] = dict(JOB["result"] or {}, blend=line[6:])
    proc = JOB["proc"]
    _redraw()
    if proc is not None and proc.poll() is not None and (q is None or q.empty()):
        if proc.returncode == 0:
            JOB["status"] = "Done"
        elif not JOB["error"]:
            JOB["error"] = f"the build stopped (exit code {proc.returncode})"
            JOB["status"] = "Failed"
        JOB["proc"] = None
        _redraw()
        return None
    return 0.5


def _reader(proc, q):
    for raw in proc.stdout:
        if raw.startswith("BAYC: "):
            q.put(raw[6:].rstrip())
    proc.stdout.close()


class BAYCSING_OT_make(bpy.types.Operator):
    bl_idname = "bayc_sing.make"
    bl_label = "Make it"
    bl_description = "Build the song on your character in a background Blender (your file is not changed)"

    def execute(self, context):
        s = context.scene.bayc_sing
        if JOB["proc"] is not None:
            self.report({'WARNING'}, "A build is already running")
            return {'CANCELLED'}
        if not bpy.data.filepath:
            self.report({'ERROR'}, "Save your .blend first (the build reads the saved file)")
            return {'CANCELLED'}
        if bpy.data.is_dirty:
            # panel settings travel as arguments; only edits to the character itself need a save
            self.report({'WARNING'}, "Building from your last saved file: save first (Ctrl+S) if you changed the character")
        song =s.song if s.source == 'INCLUDED' else bpy.path.abspath(s.song_file)
        if not song or song == "none" or (s.source == 'FILE' and not os.path.isfile(song)):
            self.report({'ERROR'}, "Pick a song")
            return {'CANCELLED'}
        args = ["--song", song, "--voice", s.voice, "--mode", s.mode, "--look", s.look,
                "--floppy", f"{s.floppy:.2f}", "--profile", s.profile, "--out", bpy.path.abspath(s.out_dir),
                "--transpose", "auto" if s.transpose_auto else str(s.transpose)]
        if s.source == 'FILE' and s.lyrics.strip():
            args += ["--lyrics", bpy.path.abspath(s.lyrics) if s.lyrics.lower().endswith(".txt") else s.lyrics]
        if s.source == 'FILE' and s.midi_track >= 0:
            args += ["--midi-track", str(s.midi_track)]
        if not s.bend:
            args.append("--no-bend")
        if s.render:
            args += ["--render", "--engine", s.engine if s.look == "textured" else "eevee"]
        entry = context.preferences.addons.get(__package__)
        prefs = entry.preferences if entry else None
        if prefs and prefs.chimera_path:
            args += ["--chimera", bpy.path.abspath(prefs.chimera_path)]
        cmd = [bpy.app.binary_path, "-b", bpy.data.filepath, "--python", os.path.join(ENGINE, "cli.py"), "--"] + args
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
        q = queue.Queue()
        threading.Thread(target=_reader, args=(proc, q), daemon=True).start()
        JOB.update(proc=proc, queue=q, status="Starting", progress=None, result=None, error=None, lines=[], anatomy="")
        if not bpy.app.timers.is_registered(_poll_job):
            bpy.app.timers.register(_poll_job, first_interval=0.5)
        return {'FINISHED'}


class BAYCSING_OT_cancel(bpy.types.Operator):
    bl_idname = "bayc_sing.cancel"
    bl_label = "Stop"
    bl_description = "Stop the running build (a Cycles render resumes where it stopped next time)"

    def execute(self, context):
        if JOB["proc"] is not None:
            JOB["proc"].terminate()
            JOB["error"], JOB["status"] = "stopped", "Stopped"
        return {'FINISHED'}


class BAYCSING_OT_open(bpy.types.Operator):
    bl_idname = "bayc_sing.open"
    bl_label = "Open"
    what: StringProperty()

    def execute(self, context):
        res = JOB["result"] or {}
        path = res.get(self.what) if self.what in ("blend", "video") else None
        if self.what == "folder":
            path = os.path.dirname(res.get("blend") or "") or bpy.path.abspath(context.scene.bayc_sing.out_dir)
        if not path or not os.path.exists(path):
            self.report({'ERROR'}, "Nothing to open yet")
            return {'CANCELLED'}
        if self.what == "blend":
            if bpy.data.is_dirty:
                self.report({'ERROR'}, "Save or discard your changes first")
                return {'CANCELLED'}
            bpy.ops.wm.open_mainfile(filepath=path)
        else:
            bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}


# ------------------------------------------------------------------------------------------------
# the panel
# ------------------------------------------------------------------------------------------------
class BAYCSING_PT_panel(bpy.types.Panel):
    bl_label = "BAYC Sing"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BAYC Sing"

    def draw(self, context):
        s = context.scene.bayc_sing
        L = self.layout
        box = L.box()
        box.label(text="1. Character", icon='ARMATURE_DATA')
        box.prop(s, "profile")
        box.operator("bayc_sing.check", icon='VIEWZOOM')
        for line in JOB["check"]:
            icon = 'ERROR' if line.startswith("ERROR") else 'INFO' if line.startswith("Note") else \
                'CHECKMARK' if line.startswith("Ready") else 'BLANK1'
            box.label(text=line, icon=icon)

        box = L.box()
        box.label(text="2. Song", icon='SOUND')
        box.row().prop(s, "source", expand=True)
        if s.source == 'INCLUDED':
            box.prop(s, "song", text="")
        else:
            box.prop(s, "song_file")
            if s.song_file.lower().endswith((".mid", ".midi", ".kar")):
                box.prop(s, "lyrics")
                box.prop(s, "midi_track")
        row = box.row(align=True)
        row.prop(s, "transpose_auto")
        sub = row.row()
        sub.enabled = not s.transpose_auto
        sub.prop(s, "transpose")

        box = L.box()
        box.label(text="3. Performance", icon='OUTLINER_OB_ARMATURE')
        box.row().prop(s, "voice", expand=True)
        box.prop(s, "mode", text="")
        row = box.row()
        row.enabled = s.mode != "sing"
        row.prop(s, "bend")
        box.prop(s, "floppy", slider=True)

        box = L.box()
        box.label(text="4. Look and render", icon='RENDER_ANIMATION')
        box.row().prop(s, "look", expand=True)
        box.prop(s, "render")
        row = box.row()
        row.enabled = s.render and s.look == "textured"
        row.prop(s, "engine", text="")
        box.prop(s, "out_dir")

        running = JOB["proc"] is not None
        col = L.column()
        col.scale_y = 1.6
        if running:
            col.operator("bayc_sing.cancel", icon='CANCEL')
        else:
            col.operator("bayc_sing.make", text="Make him sing!", icon='PLAY_SOUND')
        if JOB["status"]:
            box = L.box()
            p = JOB["progress"]
            if running and p and p[1]:
                box.progress(factor=p[0] / p[1], text=JOB["status"])
            else:
                box.label(text=JOB["status"], icon='ERROR' if JOB["error"] else ('TIME' if running else 'CHECKMARK'))
            if JOB["error"]:
                for chunk in _wrap(JOB["error"], 46):
                    box.label(text=chunk)
            elif running and JOB["lines"]:
                box.label(text=JOB["lines"][-1][:60])
            if not running and JOB["anatomy"] and not JOB["error"]:
                for chunk in _wrap(JOB["anatomy"], 46):
                    box.label(text=chunk)
            res = JOB["result"] or {}
            if not running and res:
                row = box.row(align=True)
                if res.get("blend"):
                    row.operator("bayc_sing.open", text="Open scene", icon='FILE_BLEND').what = "blend"
                if res.get("video"):
                    row.operator("bayc_sing.open", text="Play video", icon='PLAY').what = "video"
                row.operator("bayc_sing.open", text="Folder", icon='FILE_FOLDER').what = "folder"
        L.operator("wm.url_open", text="Help", icon='HELP').url = REPO_URL


def _wrap(text, n):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + [cur] if cur else lines


CLASSES = (BAYCSING_Settings, BAYCSING_Prefs, BAYCSING_OT_check, BAYCSING_OT_make, BAYCSING_OT_cancel,
           BAYCSING_OT_open, BAYCSING_PT_panel)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.bayc_sing = PointerProperty(type=BAYCSING_Settings)


def unregister():
    if JOB["proc"] is not None:
        JOB["proc"].terminate()
    if bpy.app.timers.is_registered(_poll_job):
        bpy.app.timers.unregister(_poll_job)
    del bpy.types.Scene.bayc_sing
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
