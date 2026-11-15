"""bayc_sing.py: make a character (a BAYC ape, or any rig a profile describes) sing a chimera-vocal-synth song.

Pipeline (run inside Blender; see build()):
  1. Track        load <song>.track.json from `chimera render blender` (articulators, telemetry,
                  phones and notes at 200 Hz) and resample it to the scene fps.
  2. Face         articulators -> ARKit / Advanced-Skeleton shape keys (jaw, lip closure, rounding,
                  spread, labiodental, tongue), a port of the synth's own Expression model (cheek
                  puff, brows from pitch, eyes that close on long high notes, blinks, beat nods) and
                  goofy layers (flappy jaw spring, brow bounces, nostril flare on inhales).
                  One action, one KEY slot, shared by the head and mouth meshes.
  3. Performance  a beat-synced dance on the base 'Pose': hip bounce with knee bend (analytic leg
                  IK, feet planted), sway, spine wiggle, head bob, inhale shrugs, arm gestures, a
                  big arms-up finale and a ragdoll flop at the end.
  4. Jiggle       a spring/damper sim on bone tails (bobble head, floppy arms and hands, googly eyes,
                  floppy ears, a hopping hat), baked to keyframes, so it renders anywhere.
  5. Stage        the WAV as a sound strip, a singing camera, render settings (EEVEE, MP4 + AAC).

Everything that is tunable lives in CFG. Frame f (starting at 1) shows time t = (f - 1) / fps.
"""
import bpy
import json
import math
import os
import random
import numpy as np
from mathutils import Matrix, Quaternion, Vector

# --------------------------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------------------------
CFG = {
    # the character: found by rig.resolve() from a profile in ../profiles/ ("auto" picks the best match)
    "profile": "auto",
    "armature": None, "head_mesh": None, "mouth_mesh": None, "hat_mesh": None,
    "skin_mesh": None, "clothes_mesh": None, "eyes_mesh": None,
    "vocals": True,               # False: he doesn't sing (a farts-only song); his mouth stays shut
    "fps": 30,
    "tail_seconds": 2.0,          # extra frames after the audio so the wobble can settle
    "seed": 7,
    # mouth
    "jaw_gain": 1.55,             # >1 exaggerates the jaw (cartoon)
    "jaw_spring_hz": 6.5,         # flappy-jaw overshoot spring
    "jaw_spring_damping": 0.42,
    "round_gain": 1.15,
    "spread_gain": 1.0,
    # face extras
    "happy_base": 0.12,
    "brow_gain": 0.9,
    # performance
    "bounce_cm": 2.6,
    "sway_cm": 2.2,
    "groove_floor": 0.55,         # how much he still dances between phrases (0..1)
    # songs with a fart part
    "toot_pop": 1.0,              # size of the butt pop that goes with every toot (0 = none)
    "fart_kick": 1.0,             # size of the recoil each fart gives him: hips, hat hop, ears (0 = none)
    "butt_shake": 1.0,            # size of the side-to-side butt shake while he is bent over (0 = none)
    "fart_orbit_deg": 52.0,       # the camera for songs with a fart part: azimuth towards his right side,
    "fart_dist": 3.75,            #   and distance in m (the same move the X-ray look makes)
    "cloud_size": 2.6,            # size of the gas clouds in the textured look (about 2x the X-ray look's rings)
    "cloud_density": 60.0,        # how thick the gas clouds are
    "cloud_glow": 1.5,            # how much they glow (so they read on the dark backdrop)
    "fart_spine_drag": 1.0,       # how much his torso trails behind the pops (1 = as loose as in other songs)
    "fart_spine_damp": 2.0,       # extra damping of his spine, neck and head springs (1 = as in other songs)
    "fart_spine_stiff": 1.0,      # extra stiffness of the same (1 = as in other songs)
    "bend_deg": 62.0,             # how far his torso tips forward in a deep bend-over
    # jiggle multipliers (1 = default physics; lower stiffness_scale = floppier)
    "stiffness_scale": 1.0,
    "damping_scale": 1.0,
    # stage
    "camera": "Sing_Cam",
    "resolution": (1080, 1080),
    "engine": "eevee",            # "eevee" (fast) or "cycles" (path traced; rendered as an image sequence)
    "eevee_samples": 48,
    "motion_blur": True,          # EEVEE only
    "cycles_samples": 96,         # Cycles: most samples per pixel (adaptive), denoised
    "cycles_noise": 0.04,         # Cycles: adaptive sampling noise threshold (lower = cleaner and slower)
    # where renders go (the command line sets it to the song's output folder); // = next to the .blend
    "output": "//Ape_Synth_Output" + os.sep,
}

# armature-space axes of this rig: +X = character's left, +Y = up, +Z = forward (towards camera)
X_AX, Y_AX, Z_AX = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))

FACE_KEYS = [
    "jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthStretchLeft", "mouthStretchRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthPressLeft", "mouthPressRight", "mouthRollLower",
    "fff_M", "tth_M", "rrr_M", "sss_M", "ssh_M", "tongueOut", "Tongue_TipUp", "Tongue_Back", "cheekPuff",
    "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "browDownLeft", "browDownRight",
    "eyeBlinkLeft", "eyeBlinkRight", "eyeWideLeft", "eyeWideRight", "eyeSquintLeft", "eyeSquintRight",
    "happy_M", "surprise_M", "noseSneerLeft", "noseSneerRight",
]

# the shape keys that move the mouth (silenced in a farts-only song)
MOUTH_KEYS = ["jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthStretchLeft", "mouthStretchRight",
              "mouthPressLeft", "mouthPressRight", "mouthRollLower", "fff_M", "tth_M", "rrr_M", "sss_M", "ssh_M",
              "tongueOut", "Tongue_TipUp", "Tongue_Back"]

# jiggle bones: natural frequency (Hz), damping ratio, gravity factor, max swing (deg), and
# optionally drag (1 = damped against the air, so it trails when its parent moves; 0 = damped
# against the parent, so it rides along; default 1)
JIGGLE = {
    "Spine": (5.0, 0.55, 0.0, 12), "Spine1": (4.6, 0.5, 0.0, 14), "Spine2": (4.2, 0.45, 0.0, 16),
    # head chain: a loose head whips the hat (end of the chain) around, so keep it firmer and
    # give the hat a stiff-but-bouncy spring; the goofiness comes from the hop and the ears
    "Neck": (4.0, 0.45, 0.0, 14), "Head": (3.4, 0.38, 0.0, 16),
    "Hat_Jiggle": (7.5, 0.32, 0.0, 9, 0.0),   # well above the head's ~3.4 Hz bobble: no resonance; rides the head
    "Ear_L": (3.4, 0.16, 0.25, 34), "Ear_R": (3.4, 0.16, 0.25, 34),
    "R_Eye": (4.5, 0.12, 0.0, 16), "L_Eye": (4.5, 0.12, 0.0, 16),
    "LeftShoulder": (4.0, 0.35, 0.0, 18), "RightShoulder": (4.0, 0.35, 0.0, 18),
    "LeftArm": (1.9, 0.22, 0.25, 40), "RightArm": (1.9, 0.22, 0.25, 40),
    "LeftForeArm": (2.1, 0.26, 0.3, 35), "RightForeArm": (2.1, 0.26, 0.3, 35),
    "LeftHand": (2.6, 0.26, 0.3, 40), "RightHand": (2.6, 0.26, 0.3, 40),
}
for _side in ("Left", "Right"):
    for _f in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
        for _i in (1, 2, 3):
            JIGGLE[f"{_side}Hand{_f}{_i}"] = (4.5, 0.25, 0.1, 28)


# --------------------------------------------------------------------------------------------
# small signal helpers
# --------------------------------------------------------------------------------------------
def smooth(a, b, x):
    """smoothstep from a to b (works for a > b too), numpy-friendly"""
    t = np.clip((np.asarray(x, dtype=float) - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def sstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def follow(x, target, tau, dt):
    return x + (target - x) * (1 - math.exp(-dt / tau))


class Spring:
    """second-order follower, as the synth's expression.ts (hz, damping ratio)"""

    def __init__(self, hz, damping, x=0.0):
        self.hz, self.damping, self.x, self.v = hz, damping, x, 0.0

    def step(self, target, dt):
        w = 2 * math.pi * self.hz
        n = max(1, math.ceil(dt / 0.008))
        h = dt / n
        for _ in range(n):
            self.v += (w * w * (target - self.x) - 2 * self.damping * w * self.v) * h
            self.x += self.v * h
        return self.x


def env_follow(x, attack, release, dt):
    """one-pole envelope follower over an array"""
    out = np.zeros_like(x)
    y = 0.0
    for i, v in enumerate(x):
        tau = attack if v > y else release
        y += (v - y) * (1 - math.exp(-dt / tau))
        out[i] = y
    return out


def bump(t, t0, t1, ramp_in, ramp_out):
    """0..1 plateau over [t0, t1] with cosine ramps outside"""
    t = np.asarray(t, dtype=float)
    y = np.zeros_like(t)
    y[(t >= t0) & (t <= t1)] = 1.0
    m = (t > t0 - ramp_in) & (t < t0)
    y[m] = 0.5 - 0.5 * np.cos(np.pi * (t[m] - (t0 - ramp_in)) / ramp_in)
    m = (t > t1) & (t < t1 + ramp_out)
    y[m] = 0.5 + 0.5 * np.cos(np.pi * (t[m] - t1) / ramp_out)
    return y


# --------------------------------------------------------------------------------------------
# 1. track
# --------------------------------------------------------------------------------------------
class Track:
    def __init__(self, path, fps):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.d = d
        self.rate = d["rate"]
        self.cols = d["keys"] + d["scalars"]
        self.F = np.asarray(d["frames"], dtype=float)
        self.t_rows = np.arange(len(self.F)) / self.rate
        self.duration = d["duration"]
        self.bpm = d["bpm"]
        self.t0 = d["t0"]
        self.notes = d["notes"]
        self.rests = d["rests"]
        self.segments = d["segments"]
        self.fps = fps
        self.n_frames = int(math.ceil(self.duration * fps))
        self.t = np.arange(self.n_frames) / fps

    def extend(self, duration):
        """lengthen the timeline (e.g. a fart part that outlasts the voice): the voice rests"""
        if duration <= self.duration:
            return
        rows = int(math.ceil(duration * self.rate)) + 1 - len(self.F)
        if rows > 0:
            self.F = np.concatenate([self.F, np.repeat(self.F[-1:], rows, axis=0)])
            self.t_rows = np.arange(len(self.F)) / self.rate
        self.duration = duration
        self.n_frames = int(math.ceil(duration * self.fps))
        self.t = np.arange(self.n_frames) / self.fps

    def row(self, name):
        return self.F[:, self.cols.index(name)]

    def inst(self, name, t=None):
        return np.interp(self.t if t is None else t, self.t_rows, self.row(name))

    def window(self, name, fn, half=None):
        """min/max of a 200 Hz column over each frame's window [t - half, t + half]"""
        half = (0.5 / self.fps) if half is None else half
        x = self.row(name)
        out = np.empty(self.n_frames)
        for i, t in enumerate(self.t):
            a = int(max(0, math.floor((t - half) * self.rate)))
            b = int(min(len(x), math.ceil((t + half) * self.rate) + 1))
            out[i] = fn(x[a:b]) if b > a else x[min(a, len(x) - 1)]
        return out

    def seg_envelope(self, ipas, t, lead=0.04, lag=0.05):
        """0..1 envelope while any phone in `ipas` sounds (with ramps)"""
        y = np.zeros_like(t)
        for s in self.segments:
            if s["ipa"] in ipas:
                y = np.maximum(y, bump(t, s["t0"], s["t1"], lead, lag))
        return y


def fart_signals(farts, n, fps):
    """Frame-rate signals from a fart part (the info dict fartsynth writes): how loud it is, when
    each one starts, the little bend that goes with every toot, the deep bend-over sections,
    the hip pop each one gives him, and the strain before the big ones."""
    t = np.arange(n) / fps
    dt = 1.0 / fps
    env = np.asarray(farts["env"]["values"], float)
    level = np.clip(np.interp(t, np.arange(len(env)) / farts["env"]["rate"], env, right=0.0), 0.0, 1.5)
    onset, strain, big = np.zeros(n), np.zeros(n), np.zeros(n)
    for e in farts["events"]:
        heavy = e["style"] in ("long", "rip", "blart")
        i = int(round(e["t0"] * fps))
        if 0 <= i < n:
            onset[i] += e.get("loud", 1.0) * (1.6 if heavy else 1.0 if e["style"] == "parp" else 0.35)
        if heavy:
            strain = np.maximum(strain, bump(t, e["t0"] - 0.45, e["t0"] - 0.05, 0.25, 0.08))
            big = np.maximum(big, bump(t, e["t0"], e["t1"], 0.05, 0.2))
    toot = env_follow(np.clip(1.4 * level, 0, 1), 0.12, 0.35, dt)
    deep = np.zeros(n)
    for a, b in farts.get("bend", []):
        deep = np.maximum(deep, bump(t, a, b, 0.45, 0.5))
    # the recoil: one damped bump per fart. It must not ring: a run of toots comes at about the
    # rate his spine, ears and hat wobble at, and a ringing recoil shakes them to their limits.
    sp, kick = Spring(3.0, 1.0), np.zeros(n)
    for i in range(n):
        sp.v += onset[i] * 26.0
        kick[i] = sp.step(0.0, dt)
    return dict(level=level, onset=onset, toot=toot, deep=deep, kick=np.clip(kick, -0.6, 1.2), strain=strain, big=big)


# --------------------------------------------------------------------------------------------
# 2. face
# --------------------------------------------------------------------------------------------
def port_expression(tr, seed):
    """expression.ts (Expression + Gaze) stepped at the track rate, deterministic (seeded)."""
    rng = random.Random(seed)
    dt = 1.0 / tr.rate
    f0, voicing, gate = tr.row("f0"), tr.row("voicing"), tr.row("gate")
    out_rms, mouth_p = tr.row("outRms"), tr.row("mouthP")
    n = len(f0)
    res = {k: np.zeros(n) for k in ("puff", "brow", "lid", "lookUp", "nod", "tilt", "hold", "dev", "gaze_pitch", "gaze_yaw")}
    cheeks, nod_s, tilt_s = Spring(6.5, 0.32), Spring(2.4, 0.42), Spring(3.2, 0.3)
    ref = fast = float("nan")
    held = hold = brow = 0.0
    clock = 0.0
    next_blink = 1.5 + rng.random() * 2
    blink_at, second = -1.0, False
    last_step = -1
    g_pitch = g_yaw = to_p = to_y = 0.0
    g_next = 2.0
    for i in range(n):
        clock += dt
        voiced = voicing[i] > 0.45 and gate[i] > 0.3 and f0[i] > 30 and out_rms[i] > 0.004
        puff = clamp(cheeks.step(float(sstep(1.5, 7.0, mouth_p[i])), dt), -0.35, 1.25)
        dev = wobble = 0.0
        if voiced:
            l = math.log2(f0[i])
            if not math.isfinite(ref) or abs(12 * (l - ref)) > 14:
                ref = fast = l
            ref = follow(ref, l, 5, dt)
            if abs(12 * (l - fast)) > 2.5:
                fast = l
                held = 0.0
            fast = follow(fast, l, 0.35, dt)
            held += dt
            dev = 12 * (l - ref)
            wobble = 12 * (l - fast)
        else:
            held = 0.0
        brow_to = clamp(dev / 6, -0.7, 1) if voiced else 0.0
        brow = follow(brow, brow_to, 0.12 if voiced else 0.45, dt)
        look_up = 0.32 * max(0.0, brow)
        hold_to = 0.92 * sstep(0.9, 1.9, held) * sstep(0.15, 0.55, brow) if voiced else 0.0
        hold = follow(hold, hold_to, 0.35 if hold_to > hold else 0.08, dt)
        if clock >= next_blink and hold < 0.2:
            blink_at = clock
            second = (not second) and rng.random() < 0.18
            next_blink = clock + (0.28 if second else 2 + rng.random() * 4.5)
        b = (clock - blink_at) / 0.17
        blink = math.sin(math.pi * b) ** 0.7 if (blink_at >= 0 and b < 1) else 0.0
        lid = max(blink, hold)
        # beat nods from the melody's tempo (16th-note steps from the first downbeat)
        tt = i * dt
        step = math.floor((tt - tr.t0) * tr.bpm * 4 / 60)
        step = -1 if step < 0 else step % 16
        if step >= 0 and last_step >= 0 and step != last_step:
            wrapped = step < last_step
            if wrapped or step // 4 != last_step // 4:
                nod_s.v -= 1.3 if (wrapped or step // 16 != last_step // 16) else 0.8
        last_step = step
        nod = nod_s.step(0.13 * brow, dt)
        sway = sstep(0.6, 2, held) * 0.07 * math.sin(clock * 1.7)
        tilt = tilt_s.step(sway + 0.05 * clamp(wobble, -1.5, 1.5), dt)
        # gaze saccades (mostly at the camera: he is performing)
        if clock >= g_next:
            centre = rng.random() < 0.55
            to_p = 0 if centre else (rng.random() * 2 - 1) * 0.16
            to_y = 0 if centre else (rng.random() * 2 - 1) * 0.32
            g_next = clock + 1.2 + rng.random() * 3.0
        ease = 1 - math.exp(-dt * 28)
        g_pitch += (to_p - g_pitch) * ease
        g_yaw += (to_y - g_yaw) * ease
        for k, v in (("puff", puff), ("brow", brow), ("lid", lid), ("lookUp", look_up), ("nod", nod),
                     ("tilt", tilt), ("hold", hold), ("dev", dev), ("gaze_pitch", g_pitch), ("gaze_yaw", g_yaw)):
            res[k][i] = v
    # resample to the video frames
    return {k: np.interp(tr.t, tr.t_rows, v) for k, v in res.items()}


def solve_face(tr, cfg):
    t = tr.t
    fps = tr.fps
    dt = 1.0 / fps
    jaw = tr.inst("jaw")
    lip_ap_min = tr.window("lipAp", np.min)
    lip_prot = tr.inst("lipProt")
    lip_w = tr.inst("lipWidth")
    labio = tr.window("labiodental", np.max)
    tt_x = tr.window("ttX", np.max)
    tt_y = tr.inst("ttY")
    curl = tr.inst("ttCurl")
    c_tip = tr.window("contactTip", np.min)
    c_body = tr.window("contactBody", np.min)
    act_raw = np.maximum(tr.inst("gate"), tr.inst("voicing"))
    act = env_follow(act_raw, 0.04, 0.30, dt)                    # mouth activity (closes in rests)
    E = env_follow(np.clip(tr.inst("outRms") / 0.30, 0, 1.3), 0.06, 0.40, dt)   # loudness 0..~1

    ex = port_expression(tr, cfg["seed"])
    W = {k: np.zeros(tr.n_frames) for k in FACE_KEYS}

    # --- jaw: physical jaw opening, exaggerated, through a flappy overshoot spring ---
    jaw_n = np.clip((jaw - 0.15) / 1.35, 0, 1.15)
    fff = smooth(0.15, 0.85, labio)
    jaw_target = cfg["jaw_gain"] * jaw_n * act * (1 - 0.45 * fff)
    s = Spring(cfg["jaw_spring_hz"], cfg["jaw_spring_damping"])
    W["jawOpen"] = np.clip([s.step(v, dt) for v in jaw_target], 0, 1.85)

    # --- lips: closure (m b p), compression, rounding, spread, labiodental ---
    closure = 1 - smooth(0.02, 0.35, lip_ap_min)
    W["mouthClose"] = np.minimum(W["jawOpen"], 1.0) * closure * 0.95 * (1 - fff)
    press = closure * smooth(0.0, -0.22, lip_ap_min)
    W["mouthPressLeft"] = W["mouthPressRight"] = 0.6 * press
    rnd = np.clip((0.55 - lip_w) / 0.5, 0, 1) * (0.35 + 0.65 * smooth(0.15, 1.1, lip_prot))
    # open rounded (o, ɔ, aʊ) vs close rounded (u, w): the synth separates them by the jaw
    # (/o/ jaw 0.66, /u/ 0.22), its lip apertures differ by only ~0.1 cm
    openness = smooth(0.3, 0.75, jaw)
    W["mouthFunnel"] = cfg["round_gain"] * 1.1 * rnd * openness * act
    W["mouthPucker"] = cfg["round_gain"] * 1.1 * rnd * (1 - openness) * act
    spread = smooth(0.6, 0.98, lip_w) * act
    W["mouthStretchLeft"] = W["mouthStretchRight"] = cfg["spread_gain"] * 0.45 * spread * (0.4 + 0.6 * np.minimum(jaw_n, 1))
    W["fff_M"] = fff
    W["mouthRollLower"] = 0.25 * fff

    # --- consonant mouth shapes (the tongue itself is solved at the end, once the jaw is final) ---
    W["tth_M"] = smooth(6.75, 7.15, tt_x) * smooth(7.4, 8.1, tt_y)
    W["rrr_M"] = 0.6 * smooth(0.3, 0.8, curl)
    W["sss_M"] = 0.65 * tr.seg_envelope({"s", "z"}, t)
    W["ssh_M"] = 0.85 * tr.seg_envelope({"ʃ", "ʒ", "tʃ", "dʒ"}, t)
    W["tongueOut"] = 0.6 * smooth(7.4, 7.9, tt_x)

    # --- the synth's own expression model ---
    W["cheekPuff"] = 0.6 * np.clip(ex["puff"], 0, 1)
    brow_up = np.maximum(0, ex["brow"]) * cfg["brow_gain"]
    brow_dn = np.maximum(0, -ex["brow"])
    # goofy brow bounce: kicked on every sung syllable, louder notes kick harder
    bb = Spring(5.0, 0.22)
    onsets = np.zeros(tr.n_frames)
    for n in tr.notes:
        i = int(round(n["t0"] * fps))
        if 0 <= i < tr.n_frames:
            onsets[i] += 0.6 + 0.4 * min(1.0, n["beats"])
    bounce = np.zeros(tr.n_frames)
    for i in range(tr.n_frames):
        bb.v += onsets[i] * 4.0
        bounce[i] = bb.step(0.0, dt)
    bounce = np.clip(bounce, -0.35, 0.6)
    W["browInnerUp"] = np.clip(brow_up + 0.22 * ex["lid"] * np.maximum(0, ex["brow"]) + 0.5 * np.maximum(bounce, 0), 0, 1.2)
    W["browOuterUpLeft"] = W["browOuterUpRight"] = np.clip(0.75 * brow_up + 0.7 * np.maximum(bounce, 0), 0, 1.2)
    W["browDownLeft"] = W["browDownRight"] = np.clip(0.6 * brow_dn + 0.4 * np.maximum(-bounce, 0), 0, 1)
    W["eyeBlinkLeft"] = W["eyeBlinkRight"] = np.clip(ex["lid"], 0, 1)
    W["eyeWideLeft"] = W["eyeWideRight"] = 0.6 * np.maximum(0, ex["brow"]) * (1 - ex["lid"])
    strain = smooth(0.6, 1.0, E) * smooth(2.0, 6.0, ex["dev"])
    W["eyeSquintLeft"] = W["eyeSquintRight"] = 0.45 * strain * (1 - ex["lid"])

    # --- goofy character layers ---
    last = tr.notes[-1]
    singing = bump(t, tr.notes[0]["t0"] - 0.3, last["t1"], 0.4, 0.4)
    finale = bump(t, last["t0"], last["t1"], 0.25, 0.3)
    after = smooth(last["t1"] + 0.2, last["t1"] + 0.9, t)
    W["happy_M"] = np.clip(cfg["happy_base"] * singing + 0.15 * finale + 0.5 * after, 0, 1)
    # dopey finish: tongue out and lazy lids while his head lolls
    W["tongueOut"] = np.maximum(W["tongueOut"], 0.6 * after)
    W["jawOpen"] = np.maximum(W["jawOpen"], 0.6 * after)
    W["eyeBlinkLeft"] = np.maximum(W["eyeBlinkLeft"], 0.35 * after)
    W["eyeBlinkRight"] = np.maximum(W["eyeBlinkRight"], 0.45 * after)
    W["mouthSmileLeft"] = W["mouthSmileRight"] = 0.22 * spread + 0.1 * singing
    oh = [n for n in tr.notes if n["syl"].lower().startswith("oh")]
    if oh:
        W["surprise_M"] = 0.3 * bump(t, oh[-1]["t0"], oh[-1]["t1"], 0.12, 0.2)
    inhale = np.zeros(tr.n_frames)
    for r in tr.rests:
        inhale = np.maximum(inhale, bump(t, r["t0"] + 0.05, r["t1"] - 0.05, 0.12, 0.15))
    W["noseSneerLeft"] = W["noseSneerRight"] = 0.55 * inhale

    # --- his own tongue, driven by the synth's tongue (tongue-only shape keys, see
    # ensure_tongue_keys): the tip reaches the palate whatever the jaw is doing, and never
    # goes through it; the rig's tongueOut is sculpted for an open jaw, so it is capped by it ---
    tg = cfg.get("_tongue")
    if tg:
        tip = smooth(7.3, 9.4, tr.window("ttY", np.max))        # 0 at rest .. 1 on the alveolar ridge
        jaw_now = np.clip(W["jawOpen"], 0.0, 1.6)
        W["Tongue_TipUp"] = np.clip(tip * (tg["lift0"] + tg["drop"] * jaw_now) / tg["rise"], 0.0, 1.6)
        W["Tongue_Back"] = np.clip(1 - smooth(-0.05, 0.45, c_body), 0.0, 1.0) * act   # k, g, ng
    W["tongueOut"] = np.minimum(W["tongueOut"], W["jawOpen"])

    # --- a fart part: he strains before the big ones, his eyes pop when one lands, and he
    # grins while bent over ---
    if cfg.get("_farts"):
        fz = fart_signals(cfg["_farts"], tr.n_frames, fps)
        W["cheekPuff"] = np.clip(W["cheekPuff"] + 0.55 * fz["strain"] * (1 - act), 0, 1)
        W["eyeSquintLeft"] = W["eyeSquintRight"] = np.clip(W["eyeSquintLeft"] + 0.7 * fz["strain"], 0, 1)
        W["browDownLeft"] = W["browDownRight"] = np.clip(W["browDownLeft"] + 0.6 * fz["strain"], 0, 1)
        pop = np.clip(fz["kick"], 0, 1)
        W["eyeWideLeft"] = W["eyeWideRight"] = np.clip(W["eyeWideLeft"] + 0.8 * pop * (1 - W["eyeBlinkLeft"]), 0, 1)
        W["browInnerUp"] = np.clip(W["browInnerUp"] + 0.5 * pop, 0, 1.2)
        W["happy_M"] = np.clip(W["happy_M"] + 0.35 * fz["deep"] + 0.25 * fz["big"], 0, 1)

    signals = {"E": E, "act": act, "inhale": inhale, "finale": finale, "after": after, "singing": singing}
    signals.update(ex)
    return W, signals


# --------------------------------------------------------------------------------------------
# 3. rig: extra bones and weights
# --------------------------------------------------------------------------------------------
def _set_mode(obj, mode):
    vl = bpy.context.view_layer
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in vl.objects:
        if o.select_get():
            o.select_set(False)
    vl.objects.active = obj
    obj.select_set(True)
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode=mode)


def mesh_islands(me):
    """connected-component label per vertex"""
    n = len(me.vertices)
    e = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", e)
    parent = list(range(n))

    def find(i):
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    for a, b in e.reshape(-1, 2).tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(i) for i in range(n)])
    return np.unique(roots, return_inverse=True)[1]


def mouth_parts(mouth_ob):
    """per-vertex part of the mouth mesh: 0 gums / other, 1 tongue, 2 teeth (by mesh island)"""
    me = mouth_ob.data
    kb = me.shape_keys.key_blocks
    n = len(me.vertices)

    def key_co(name):
        a = np.empty(n * 3, np.float32)
        kb[name].data.foreach_get("co", a)
        return a.reshape(-1, 3)

    B = key_co("Basis")
    inv = mesh_islands(me)
    counts = np.bincount(inv)
    part = np.zeros(n, np.int32)
    tongue_id = -1
    if "tongueOut" in kb:
        d = np.linalg.norm(key_co("tongueOut") - B, axis=1)
        if d.max() > 0.5:
            tongue_id = int(inv[int(d.argmax())])
    for i in np.nonzero(counts >= 40)[0]:
        m = inv == i
        if i == tongue_id:
            part[m] = 1
        elif B[m, 0].max() - B[m, 0].min() < 4.0:      # a single tooth is narrow; the gum plates are wide
            part[m] = 2
    return part, inv, B, key_co


def ensure_tongue_keys(cfg, log):
    """Tongue-only shape keys on the mouth mesh, cut out of the rig's own sculpted visemes:
    Tongue_TipUp = (lntd_M - eh_M) on the tongue (tip to the palate, the jaw part removed) and
    Tongue_Back = (gk_M - eh_M) on the tongue (pulled back). The head mesh gets same-named empty
    keys so the one face action resolves on both. Returns the measurements the solver needs."""
    mouth = bpy.data.objects.get(cfg["mouth_mesh"] or "")
    head = bpy.data.objects[cfg["head_mesh"]]
    if mouth is None or mouth.data.shape_keys is None:
        log.append("tongue: no separate mouth mesh; tongue keys skipped")
        return None
    kb = mouth.data.shape_keys.key_blocks
    part, inv, B, key_co = mouth_parts(mouth)
    T = part == 1
    if not T.any() or not all(k in kb for k in ("lntd_M", "gk_M", "eh_M", "jawOpen")):
        log.append("tongue: no separate tongue found in the mouth mesh; tongue keys skipped")
        return None
    deltas = {}
    for name, src in (("Tongue_TipUp", "lntd_M"), ("Tongue_Back", "gk_M")):
        d = np.zeros_like(B)
        d[T] = (key_co(src) - key_co("eh_M"))[T]
        deltas[name] = d
        k = kb.get(name) or mouth.shape_key_add(name=name, from_mix=False)
        k.data.foreach_set("co", (B + d).ravel())
        k.slider_min, k.slider_max, k.value = 0.0, 2.0, 0.0
        hk = head.data.shape_keys.key_blocks
        if name not in hk:
            head.shape_key_add(name=name, from_mix=False).value = 0.0
    mouth.data.update()
    zt = B[T][:, 2]
    tipm = T & (B[:, 2] > np.percentile(zt, 70))
    rise = float(deltas["Tongue_TipUp"][tipm][:, 1].mean())
    drop = float(-(key_co("jawOpen") - B)[tipm][:, 1].mean())
    # the palate above the tip: the biggest part of the mouth mesh that the jaw does not move
    dj = np.linalg.norm(key_co("jawOpen") - B, axis=1)
    lift0 = 0.6
    still = [i for i in np.unique(inv[part == 0]) if (inv == i).sum() >= 40 and dj[inv == i].max() < 0.05]
    if still:
        U = inv == max(still, key=lambda i: (inv == i).sum())
        near = U & (np.abs(B[:, 0]) < 2.5) & (np.abs(B[:, 2] - B[tipm][:, 2].mean()) < 2.0)
        if near.any():
            lift0 = float(np.clip(B[near][:, 1].min() - B[tipm][:, 1].max(), 0.0, 2.0)) + 0.3
    if rise < 0.5:
        log.append("tongue: tip-up shape too small; tongue keys skipped")
        return None
    log.append(f"tongue keys: tip rise {rise:.2f} cm, jaw drop {drop:.2f} cm/unit, palate gap {lift0:.2f} cm")
    return {"rise": rise, "drop": drop, "lift0": lift0}


def ensure_extra_bones(cfg, log):
    """Hat_Jiggle (hat on its own bone so it can hop) and Ear_L / Ear_R (floppy ears)."""
    arm = bpy.data.objects[cfg["armature"]]
    prof = cfg.get("_profile") or {}
    spec = {k: (tuple(v["head"]), tuple(v["tail"])) for k, v in (prof.get("extra_bones") or {}).items()}
    need = [n for n in spec if n not in arm.data.bones]
    if need:
        hide = arm.hide_get()
        arm.hide_set(False)
        _set_mode(arm, 'EDIT')
        eb = arm.data.edit_bones
        head = eb["Head"]
        for name in need:
            b = eb.new(name)
            b.head, b.tail = Vector(spec[name][0]), Vector(spec[name][1])
            b.roll = 0.0
            b.parent = head
            b.use_connect = False
            b.use_deform = True
        _set_mode(arm, 'OBJECT')
        arm.hide_set(hide)
        log.append(f"added bones {need}")
    # hat: move its single 'Head' group onto the hat bone
    hat = bpy.data.objects.get(cfg["hat_mesh"] or "")
    if hat is not None and "Hat_Jiggle" in arm.data.bones and "Hat_Jiggle" not in hat.vertex_groups and "Head" in hat.vertex_groups:
        hat.vertex_groups["Head"].name = "Hat_Jiggle"
        log.append("hat weights -> Hat_Jiggle")
    # ears: lateral part of the head mesh, smooth falloff from the skull
    head_ob = bpy.data.objects[cfg["head_mesh"]]
    ew = prof.get("ear_weights")
    if ew and "Ear_L" in arm.data.bones and "Head" in head_ob.vertex_groups and "Ear_L" not in head_ob.vertex_groups:
        me = head_ob.data
        n = len(me.vertices)
        co = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        g_head = head_ob.vertex_groups["Head"]
        g_l = head_ob.vertex_groups.new(name="Ear_L")
        g_r = head_ob.vertex_groups.new(name="Ear_R")
        w = smooth(*ew["x"], np.abs(co[:, 0])) * smooth(*ew["y_in"], co[:, 1]) * (1 - smooth(*ew["y_out"], co[:, 1]))
        idx_head = g_head.index
        moved = 0
        for v in me.vertices:
            wi = float(w[v.index])
            if wi <= 1e-4:
                continue
            (g_l if co[v.index, 0] > 0 else g_r).add([v.index], wi, 'REPLACE')
            for g in v.groups:
                if g.group == idx_head:
                    g_head.add([v.index], g.weight * (1 - wi), 'REPLACE')
            moved += 1
        log.append(f"ear weights on {moved} head vertices")
    return arm


# --------------------------------------------------------------------------------------------
# 4. FK model, performance and jiggle sim
# --------------------------------------------------------------------------------------------
def rot_xyz(rx=0.0, ry=0.0, rz=0.0):
    """armature-space rotation: roll (Z) * pitch (X) * yaw (Y)"""
    m = Matrix.Identity(3)
    if ry:
        m = Matrix.Rotation(ry, 3, 'Y') @ m
    if rx:
        m = Matrix.Rotation(rx, 3, 'X') @ m
    if rz:
        m = Matrix.Rotation(rz, 3, 'Z') @ m
    return m


def about_head(P, R):
    """rotate pose matrix P by armature-space rotation R around its own head"""
    h = P.translation.copy()
    M = R.to_4x4() @ P
    M.translation = h
    return M


class Rig:
    def __init__(self, arm):
        self.arm = arm
        bones = arm.data.bones
        self.order = []
        def visit(b):
            self.order.append(b.name)
            for c in b.children:
                visit(c)
        for b in bones:
            if b.parent is None:
                visit(b)
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in bones}
        self.length = {b.name: b.length for b in bones}
        self.rel = {}
        for b in bones:
            self.rel[b.name] = (b.parent.matrix_local.inverted() @ b.matrix_local) if b.parent else b.matrix_local.copy()

    def base_basis(self, action_frame=1):
        """the 'Pose' action's local basis per bone (loc, quat) at one frame; identity if unkeyed"""
        basis = {n: Matrix.Identity(4) for n in self.order}
        # always the original rest-of-scene pose, never our own bake (keeps rebuilds idempotent)
        act = bpy.data.actions.get("Pose")
        ad = self.arm.animation_data
        if act is None and ad and ad.action and not ad.action.name.startswith("BAYC_Sing"):
            act = ad.action
        if act is None:
            return basis
        slot = act.slots[0] if len(act.slots) else None
        cb = act.layers[0].strips[0].channelbag(slot) if (act.layers and slot) else None
        if cb is None:
            return basis
        vals = {}
        for fc in cb.fcurves:
            if not fc.data_path.startswith('pose.bones["'):
                continue
            name = fc.data_path.split('"')[1]
            prop = fc.data_path.rsplit('.', 1)[1]
            vals.setdefault(name, {}).setdefault(prop, {})[fc.array_index] = fc.evaluate(action_frame)
        for n, d in vals.items():
            if n not in basis:
                continue
            loc = d.get("location", {})
            q = d.get("rotation_quaternion", {})
            L = Vector((loc.get(0, 0.0), loc.get(1, 0.0), loc.get(2, 0.0)))
            Q = Quaternion((q.get(0, 1.0), q.get(1, 0.0), q.get(2, 0.0), q.get(3, 0.0))).normalized()
            basis[n] = Matrix.Translation(L) @ Q.to_matrix().to_4x4()
        return basis

    def fk(self, basis, P=None):
        P = {} if P is None else P
        for n in self.order:
            p = self.parent[n]
            P[n] = (P[p] @ self.rel[n] @ basis[n]) if p else (self.rel[n] @ basis[n])
        return P


def two_bone_ik(H, F, L1, L2, pole):
    d_vec = F - H
    d = clamp(d_vec.length, abs(L1 - L2) + 1e-3, L1 + L2 - 1e-3)
    u = d_vec.normalized()
    a = (L1 * L1 - L2 * L2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, L1 * L1 - a * a))
    w = (pole - u * pole.dot(u)).normalized()
    return H + u * a + w * h


def swing_to(P, target_dir):
    """rotate P around its head so its +Y axis points along target_dir"""
    cur = (P.to_3x3() @ Y_AX).normalized()
    q = cur.rotation_difference(target_dir.normalized())
    return about_head(P, q.to_matrix())


def performance(tr, sig, cfg):
    """per-frame armature-space deltas: dict frame -> {bone: (rx, ry, rz)}, hips offset (cm)"""
    t = tr.t
    nF = tr.n_frames + int(cfg["tail_seconds"] * tr.fps)
    tt = np.arange(nF) / tr.fps
    pad = lambda x, v=None: np.concatenate([x, np.full(nF - len(x), x[-1] if v is None else v)])
    E = pad(sig["E"], 0.0)
    hold = pad(sig["hold"], 0.0)
    nod, tilt = pad(sig["nod"], 0.0), pad(sig["tilt"], 0.0)
    inhale = pad(sig["inhale"], 0.0)
    g_pitch, g_yaw = pad(sig["gaze_pitch"], 0.0), pad(sig["gaze_yaw"], 0.0)
    look_up = pad(sig["lookUp"], 0.0)
    first, last = tr.notes[0], tr.notes[-1]
    t_end = last["t1"]
    song_on = smooth(0.15, max(0.3, first["t0"] - 0.1), tt) * (1 - smooth(t_end - 0.05, t_end + 0.35, tt))
    groove = song_on * (cfg["groove_floor"] + (1 - cfg["groove_floor"]) * np.clip(E, 0, 1))
    phi = (tt - tr.t0) * tr.bpm / 60.0
    beat_dip = 0.5 + 0.5 * np.cos(2 * np.pi * phi)          # 1 on the beat
    sway = np.sin(np.pi * phi)                                 # 2-beat sway

    # phrase gestures: alternate arms per phrase, both arms on the last phrase (the finale)
    phrases, cur = [], []
    for n in tr.notes:
        if cur and n["t0"] - cur[-1]["t1"] > 1e-3:
            phrases.append(cur)
            cur = []
        cur.append(n)
    if cur:
        phrases.append(cur)
    g_l, g_r = np.zeros(nF), np.zeros(nF)
    for k, ph in enumerate(phrases[:-1]):
        b = bump(tt, ph[0]["t0"] - 0.15, ph[-1]["t1"] - 0.2, 0.35, 0.5)
        if k % 3 == 2:
            g_l = np.maximum(g_l, 0.8 * b)
            g_r = np.maximum(g_r, 0.8 * b)
        elif k % 2 == 0:
            g_r = np.maximum(g_r, b)
        else:
            g_l = np.maximum(g_l, b)
    # finale = the last phrase if it is short (e.g. "Oh yeah!"), else just the final note
    fin_start = max(phrases[-1][0]["t0"], last["t0"] - 1.0) if len(phrases) > 1 else last["t0"]
    fin = bump(tt, fin_start - 0.1, t_end, 0.35, 0.12)
    flop = smooth(t_end + 0.05, t_end + 0.25, tt)        # ragdoll collapse after the last note
    flop_hold = flop * (1 - smooth(t_end + 1.4, t_end + 2.2, tt) * 0.6)

    # a fart part: every toot is a butt pop (the pelvis tips back and the lower spine arches to
    # make up for it, so his chest and head stay put); the sections the song marks are a deep
    # bend-over with a butt shake, arms hanging like an ape's while he is down
    fz = fart_signals(cfg["_farts"], nF, tr.fps) if cfg.get("_farts") else None
    zero = np.zeros(nF)
    pop = cfg["toot_pop"] * fz["toot"] if fz else zero
    deep = fz["deep"] if fz else zero
    kick = cfg["fart_kick"] * fz["kick"] if fz else zero
    bs = cfg["bend_deg"] / 62.0                           # the bend angles below add up to 62 degrees

    out = []
    for i in range(nF):
        G, ph = groove[i], phi[i]
        d = {}
        fl = flop_hold[i]
        B, D, Pp, K = deep[i], deep[i], pop[i], kick[i]
        shake = math.sin(2 * math.pi * ph)
        wag = 0.22 * cfg["butt_shake"] * D * shake        # the butt shake: hips only, the spine turns back
        hip = Vector((cfg["sway_cm"] * G * sway[i] * (1 - 0.7 * D) - 1.5 * fl + 1.5 * cfg["butt_shake"] * D * shake,
                      -(1.2 + cfg["bounce_cm"] * G * beat_dip[i]) - 3.0 * fl - 9.0 * B - 2.0 * Pp + 0.8 * K,
                      -13.0 * B - 4.5 * Pp - 1.5 * K))
        d["Hips"] = (0.50 * bs * B + 0.32 * Pp, 0.06 * G * math.sin(math.pi * ph / 2) + wag, 0.05 * G * sway[i] - 0.04 * fl)
        d["Spine"] = (0.22 * bs * B - 0.20 * Pp, -0.6 * wag, -0.02 * G * sway[i])
        d["Spine1"] = (0.05 * E[i] * song_on[i] + 0.20 * bs * B - 0.10 * Pp, -0.4 * wag, -0.02 * G * math.sin(math.pi * ph - 0.3))
        d["Spine2"] = (-0.10 * hold[i] + 0.07 * fl + 0.16 * bs * B, 0.0, -0.015 * G * math.sin(math.pi * ph - 0.6) + 0.05 * fl)
        d["Neck"] = (0.04 * G * beat_dip[i] - 0.12 * hold[i] + 0.06 * fl - 0.38 * bs * B, 0.0, 0.3 * tilt[i] + 0.14 * fl)
        # after the last note his head lolls onto his right shoulder (+Z) instead of bowing;
        # bent over, he keeps his face up and turns it to the camera on his right
        d["Head"] = (-0.8 * nod[i] + 0.06 * G * (0.5 + 0.5 * math.cos(2 * math.pi * ph - 0.4))
                     - 0.22 * hold[i] - 0.5 * look_up[i] * song_on[i] + 0.1 * fl - 0.50 * bs * B,
                     0.08 * G * math.sin(2 * math.pi * tt[i] / 7.3) - 0.12 * fl - 0.45 * D,
                     0.7 * tilt[i] + 0.06 * G * math.sin(math.pi * ph + 1.2) + 0.36 * fl)
        sh = 0.18 * inhale[i] + 0.04 * G * beat_dip[i] + 0.12 * fin[i]
        d["LeftShoulder"] = (0.0, 0.0, sh)
        d["RightShoulder"] = (0.0, 0.0, -sh)
        for side, gest, sgn in (("Left", g_l[i], 1.0), ("Right", g_r[i], -1.0)):
            amt = gest * (0.55 + 0.45 * min(1.0, E[i])) * (1 - D)
            up = fin[i]
            # "presenting" gesture: upper arm forward, elbow bent, hand up in front of the chest
            d[f"{side}Arm"] = (-(0.42 * amt + 0.55 * up) - 1.05 * bs * B, 0.0, sgn * (0.1 + 0.16 * amt + 1.35 * up + 0.04 * G * beat_dip[i]))
            d[f"{side}ForeArm"] = (-(0.2 + 0.85 * amt + 0.6 * up) - 0.15 * B, 0.0, sgn * 0.25 * up)
            d[f"{side}Hand"] = (-0.2 * amt, 0.0, sgn * 0.15 * amt)
        d["R_Eye"] = d["L_Eye"] = (-g_pitch[i] - 0.6 * look_up[i] * song_on[i], g_yaw[i], 0.0)
        out.append((hip, d))
    return out, nF, {"groove": groove, "fin": fin, "flop": flop, "phi": phi,
                     "t_finale": fin_start, "t_end": t_end, "fz": fz}


def simulate(rig, tr, perf, nF, extra, cfg, log):
    fps = tr.fps
    base = rig.base_basis(1)
    P0 = rig.fk(base)
    feet = {s: P0[f"{s}Foot"].copy() for s in ("Left", "Right")}
    L_up = {s: (P0[f"{s}Leg"].translation - P0[f"{s}UpLeg"].translation).length for s in ("Left", "Right")}
    L_lo = {s: (P0[f"{s}Foot"].translation - P0[f"{s}Leg"].translation).length for s in ("Left", "Right")}
    knee_pole = {"Left": Vector((0.1, 0.0, 1.0)).normalized(), "Right": Vector((-0.1, 0.0, 1.0)).normalized()}
    g_vec = Vector((0.0, -981.0, 0.0))  # cm/s^2, armature space (+Y up)
    rng = random.Random(cfg["seed"] + 1)

    jig = {n: v for n, v in JIGGLE.items() if n in rig.parent}
    state = {}  # bone -> [tail_pos, tail_vel, prev_target, prev_head]
    hop_y, hop_v = 0.0, 0.0
    phi = extra["phi"]
    groove = extra["groove"]
    fart_onset = extra["fz"]["onset"] if extra.get("fz") else None
    note_on = {}
    for n in tr.notes:
        note_on[int(round(n["t0"] * fps))] = n
    beat_frames = set()
    for i in range(1, nF):
        if math.floor(phi[i]) != math.floor(phi[i - 1]) and phi[i] >= -2:
            beat_frames.add(i)
    sub = 8
    h = 1.0 / (fps * sub)
    results = []  # per frame: {bone: basis Matrix}
    for i in range(nF):
        hip_off, deltas = perf[i]
        kicks = {}
        G = groove[i]
        if i in beat_frames and G > 0.05:
            s = 1 if (math.floor(phi[i]) % 2 == 0) else -1
            kicks["Ear_L"] = Vector((0, 55 * s * G, 10 * rng.uniform(-1, 1)))
            kicks["Ear_R"] = Vector((0, -55 * s * G, 10 * rng.uniform(-1, 1)))
            kicks["Hat_Jiggle"] = Vector((rng.uniform(-1, 1) * 22 * G, 0, rng.uniform(-1, 1) * 16 * G))
            kicks["R_Eye"] = Vector((rng.uniform(-1, 1) * 110, 0, rng.uniform(-1, 1) * 60))
            kicks["L_Eye"] = Vector((rng.uniform(-1, 1) * 110, 0, rng.uniform(-1, 1) * 60))
            if math.floor(phi[i]) % 2 == 0:
                hop_v += 52.0 * G
        if i in note_on:
            n = note_on[i]
            acc = 0.5 + 0.5 * min(1.0, n["beats"])
            for hb in ("LeftHand", "RightHand"):
                kicks[hb] = Vector((rng.uniform(-0.4, 0.4), rng.uniform(0.3, 1.0), rng.uniform(-0.5, 0.5))) * 40 * acc
        if fart_onset is not None and fart_onset[i] > 0:       # a fart: the hat jumps, the ears flap
            o = min(1.6, float(fart_onset[i])) * cfg["fart_kick"]
            hop_v += 30.0 * o
            kicks["Ear_L"] = kicks.get("Ear_L", Vector()) + Vector((0, 28 * o, -14 * o))
            kicks["Ear_R"] = kicks.get("Ear_R", Vector()) + Vector((0, 28 * o, -14 * o))
        # hat hop: vertical spring on the hat with a floor (it lands back on the head)
        for _ in range(sub):
            w = 2 * math.pi * 4.0
            hop_v += (-w * w * hop_y - 2 * 0.28 * w * hop_v) * h
            hop_y += hop_v * h
            if hop_y < 0:
                hop_y, hop_v = 0.0, -0.35 * hop_v
        P = {}
        basis_out = {}
        for n in rig.order:
            p = rig.parent[n]
            A = (P[p] @ rig.rel[n] @ base[n]) if p else (rig.rel[n] @ base[n])
            if n == "Hips":
                A = A.copy()
                A.translation = A.translation + hip_off
            if n in deltas:
                rx, ry, rz = deltas[n]
                A = about_head(A, rot_xyz(rx, ry, rz))
            side = "Left" if n.startswith("Left") else "Right" if n.startswith("Right") else None
            if side and n == f"{side}UpLeg":
                K = two_bone_ik(A.translation, feet[side].translation, L_up[side], L_lo[side], knee_pole[side])
                A = swing_to(A, K - A.translation)
            elif side and n == f"{side}Leg":
                A = swing_to(A, feet[side].translation - A.translation)
            elif side and n == f"{side}Foot":
                A = feet[side].to_3x3().to_4x4()
                A.translation = (P[f"{side}Leg"] @ rig.rel[n] @ base[n]).translation
            if n in jig:
                hz, zeta, gf, max_deg = jig[n][:4]
                drag = jig[n][4] if len(jig[n]) > 4 else 1.0
                if fart_onset is not None and n in ("Spine", "Spine1", "Spine2", "Neck", "Head"):
                    # bent over, his spine sways as one long rod at about the beat rate, and
                    # the butt shake would swing his head wildly: damp and stiffen it
                    drag *= cfg["fart_spine_drag"]
                    zeta *= cfg["fart_spine_damp"]
                    hz *= math.sqrt(cfg["fart_spine_stiff"])
                hz *= math.sqrt(cfg["stiffness_scale"])
                zeta *= cfg["damping_scale"]
                L = max(rig.length[n], 1e-3)
                head = A.translation.copy()
                target = A @ Vector((0.0, L, 0.0))
                if n not in state:
                    state[n] = [target.copy(), Vector((0, 0, 0)), target.copy(), head.copy()]
                X, V, T_prev, H_prev = state[n]
                if n in kicks:
                    V = V + kicks[n]
                w = 2 * math.pi * hz
                k, c = w * w, 2 * zeta * w
                max_rad = math.radians(max_deg)
                # damping against the air (drag 1: it trails behind when its parent moves, the
                # follow-through of arms and ears) or against the parent (drag 0: it rides along)
                V_ride = (target - T_prev) * fps * (1.0 - drag)
                for s_ in range(1, sub + 1):
                    a = s_ / sub
                    Tg = T_prev.lerp(target, a)
                    Hd = H_prev.lerp(head, a)
                    acc = (Tg - X) * k - (V - V_ride) * c + g_vec * gf
                    V = V + acc * h
                    X = X + V * h
                    r = X - Hd
                    if r.length < 1e-6:
                        r = Tg - Hd
                    r.normalize()
                    tgt_dir = (Tg - Hd).normalized()
                    ang = tgt_dir.angle(r, 0.0)
                    if ang > max_rad:
                        q = tgt_dir.rotation_difference(r)
                        r = Quaternion(q.axis, max_rad) @ tgt_dir
                        V = V * 0.6
                    radial = V.dot(r)
                    V = V - r * radial
                    X = Hd + r * L
                state[n] = [X, V, target.copy(), head.copy()]
                A = swing_to(A, X - head)
            if n == "Hat_Jiggle" and hop_y > 0:
                up = (A.to_3x3() @ Y_AX).normalized()
                A = A.copy()
                A.translation = A.translation + up * hop_y
            P[n] = A
            parent_m = (P[p] @ rig.rel[n]) if p else rig.rel[n]
            basis_out[n] = parent_m.inverted() @ A
        results.append(basis_out)
    log.append(f"simulated {nF} frames, {len(jig)} jiggle bones, {len(beat_frames)} beats")

    def swing(name):
        a = [math.degrees(2 * math.acos(min(1.0, abs(r[name].to_quaternion().w)))) for r in results]
        return f"{name} {np.median(a):.0f}/{max(a):.0f}"

    watch = [n for n in ("Ear_L", "Ear_R", "Hat_Jiggle", "Head", "LeftHand", "R_Eye") if n in rig.parent]
    log.append("jiggle swing, median/max deg: " + ", ".join(swing(n) for n in watch))
    dead = [n for n in JIGGLE if n not in rig.parent] + [n for n in ("Ear_L", "Ear_R", "Hat_Jiggle") if n in rig.parent and n not in jig]
    if dead:
        log.append(f"WARNING: no jiggle on {dead}")
    return results


# --------------------------------------------------------------------------------------------
# 5. writing animation
# --------------------------------------------------------------------------------------------
def _new_action(name, id_type, slot_name):
    old = bpy.data.actions.get(name)
    if old:
        bpy.data.actions.remove(old)
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    slot = act.slots.new(id_type=id_type, name=slot_name)
    cb = act.layers.new("Layer").strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
    return act, slot, cb


def _write_curve(cb, path, index, values, start_frame, group=None):
    fc = cb.fcurves.new(path, index=index)
    n = len(values)
    fc.keyframe_points.add(n)
    co = np.empty(2 * n, dtype=np.float32)
    co[0::2] = np.arange(start_frame, start_frame + n, dtype=np.float32)
    co[1::2] = np.asarray(values, dtype=np.float32)
    fc.keyframe_points.foreach_set("co", co)
    interp = bpy.types.Keyframe.bl_rna.properties["interpolation"].enum_items["LINEAR"].value
    fc.keyframe_points.foreach_set("interpolation", np.full(n, interp, dtype=np.int32))
    fc.update()
    return fc


def write_face(W, cfg, nF, log):
    head = bpy.data.objects[cfg["head_mesh"]].data.shape_keys
    mouth_ob = bpy.data.objects.get(cfg["mouth_mesh"] or "")
    mouth = mouth_ob.data.shape_keys if mouth_ob is not None else None
    act, slot, cb = _new_action("BAYC_Sing_Face", 'KEY', "BAYC_Face")
    written = 0
    keys = [k for k in (head, mouth) if k is not None]
    for key in keys:                   # keys an earlier build animated but this one does not
        for k in key.key_blocks[1:]:
            k.value = 0.0
    for name, w in W.items():
        if name not in head.key_blocks:
            log.append(f"face key missing on head: {name}")
            continue
        vals = np.concatenate([w, np.full(nF - len(w), 0.0)])
        if name in ("happy_M", "tongueOut", "jawOpen", "eyeBlinkLeft", "eyeBlinkRight"):
            vals[len(w):] = w[-1]   # the dopey end face holds through the tail
        kb_h = head.key_blocks[name]
        kb_h.slider_max = max(kb_h.slider_max, 2.0)
        if mouth is not None and name in mouth.key_blocks:
            mouth.key_blocks[name].slider_max = max(mouth.key_blocks[name].slider_max, 2.0)
        _write_curve(cb, f'key_blocks["{name}"].value', 0, vals, 1)
        written += 1
    for key in keys:
        key.animation_data_create()
        key.animation_data.action = act
        key.animation_data.action_slot = slot
    log.append(f"face action: {written} shape keys x {nF} frames" + (", shared by head + mouth" if mouth is not None else ""))
    return act


def write_body(rig, results, log):
    arm = rig.arm
    act, slot, cb = _new_action("BAYC_Sing_Body", 'OBJECT', "Armature")
    nF = len(results)
    for n in rig.order:
        quats = np.empty((nF, 4))
        locs = np.empty((nF, 3))
        prev = None
        for i, bm in enumerate(results):
            loc, q, _ = bm[n].decompose()
            if prev is not None and q.dot(prev) < 0:
                q = -q
            prev = q
            quats[i] = (q.w, q.x, q.y, q.z)
            locs[i] = loc
        pb = arm.pose.bones[n]
        pb.rotation_mode = 'QUATERNION'
        pb.scale = (1.0, 1.0, 1.0)
        for j in range(4):
            _write_curve(cb, f'pose.bones["{n}"].rotation_quaternion', j, quats[:, j], 1)
        if np.abs(locs).max() > 1e-3:
            for j in range(3):
                _write_curve(cb, f'pose.bones["{n}"].location', j, locs[:, j], 1)
        else:
            pb.location = (0.0, 0.0, 0.0)
    arm.animation_data_create()
    arm.animation_data.action = act
    arm.animation_data.action_slot = slot
    log.append(f"body action: {len(rig.order)} bones x {nF} frames")
    return act


# --------------------------------------------------------------------------------------------
# 6. stage: audio, camera, render settings
# --------------------------------------------------------------------------------------------
def setup_stage(wav_path, nF, cfg, title, log, extra=None):
    sc = bpy.context.scene
    sc.render.fps, sc.render.fps_base = cfg["fps"], 1.0
    sc.frame_start, sc.frame_end = 1, nF
    sc.frame_current = 1
    se = sc.sequence_editor or sc.sequence_editor_create()
    for s in list(se.strips_all):
        if s.name.startswith("BAYC_Song"):
            se.strips.remove(s)
    strip = se.strips.new_sound("BAYC_Song", wav_path, 1, 1)
    sc.sync_mode = 'AUDIO_SYNC'
    log.append(f"sound strip {os.path.basename(wav_path)} at frame 1 ({strip.frame_final_duration} frames)")

    # camera: medium shot, waist up, slow push-in, slight handheld drift
    cam = bpy.data.objects.get(cfg["camera"])
    if cam is None:
        cam = bpy.data.objects.new(cfg["camera"], bpy.data.cameras.new(cfg["camera"]))
        coll = bpy.data.collections.get("Camera") or sc.collection
        coll.objects.link(cam)
    cam.data.lens = 100
    cam.data.sensor_width = 36
    cam.data.type = 'PERSP'
    tgt = bpy.data.objects.get(cfg["camera"] + "_Target")
    if tgt is None:
        tgt = bpy.data.objects.new(cfg["camera"] + "_Target", None)
        (bpy.data.collections.get("Camera") or sc.collection).objects.link(tgt)
    tgt.empty_display_size = 0.1
    tgt.animation_data_clear()
    tgt.location = (0.0, -0.05, 1.6)
    for c in list(cam.constraints):
        cam.constraints.remove(c)
    tc = cam.constraints.new('TRACK_TO')
    tc.target = tgt
    tc.track_axis, tc.up_axis = 'TRACK_NEGATIVE_Z', 'UP_Y'
    cam.animation_data_clear()
    act, slot, cb = _new_action("BAYC_Sing_Camera", 'OBJECT', cfg["camera"])
    t = np.arange(nF) / cfg["fps"]
    t_fin = extra["t_finale"] if extra else t[-1] * 0.8
    # slow push-in through the verses, then a pull-back for the arms-up finale and the flop
    push = smooth(0.0, t_fin, t)
    pull = smooth(t_fin - 0.3, t_fin + 0.9, t)
    rng = np.random.default_rng(cfg["seed"])
    def drift(scale, speed):
        ph = rng.uniform(0, 2 * np.pi, 3)
        return scale * (np.sin(speed * t + ph[0]) * 0.6 + np.sin(1.7 * speed * t + ph[1]) * 0.3 + np.sin(2.9 * speed * t + ph[2]) * 0.1)
    wide = 1.0 if (extra and extra.get("fz")) else 0.0     # a fart part: the whole bend must fit
    xs = 0.15 + drift(0.012, 0.9)
    ys = -2.95 + 0.32 * push - 1.05 * pull * (1 - 0.6 * wide) - 1.0 * wide + drift(0.01, 0.7)
    zs = 1.62 - 0.22 * wide + drift(0.008, 1.1)
    for j, vals in enumerate((xs, ys, zs)):
        _write_curve(cb, "location", j, vals, 1)
    act_t, slot_t, cb_t = _new_action("BAYC_Sing_CamTarget", 'OBJECT', tgt.name)
    _write_curve(cb_t, "location", 2, 1.6 - 0.06 * pull - 0.25 * wide, 1)
    tgt.animation_data_create()
    tgt.animation_data.action = act_t
    tgt.animation_data.action_slot = slot_t
    cam.animation_data_create()
    cam.animation_data.action = act
    cam.animation_data.action_slot = slot
    sc.camera = cam

    r = sc.render
    try:
        r.engine = 'BLENDER_EEVEE'
    except TypeError as e:
        log.append(f"engine: {e}")
    r.resolution_x, r.resolution_y = cfg["resolution"]
    r.resolution_percentage = 100
    try:
        sc.eevee.taa_render_samples = cfg["eevee_samples"]
    except Exception:
        pass
    if hasattr(r, "use_motion_blur"):
        r.use_motion_blur = cfg["motion_blur"]
        if hasattr(r, "motion_blur_shutter"):
            r.motion_blur_shutter = 0.5
    ims = r.image_settings
    try:
        ims.media_type = 'VIDEO'
    except Exception:
        pass
    ims.file_format = 'FFMPEG'
    ff = r.ffmpeg
    ff.format = 'MPEG4'
    ff.codec = 'H264'
    try:
        ff.constant_rate_factor = 'HIGH'
        ff.ffmpeg_preset = 'GOOD'
    except Exception:
        pass
    ff.audio_codec = 'AAC'
    ff.audio_bitrate = 192
    try:
        ff.audio_channels = 'STEREO'
        ff.audio_mixrate = 48000
    except Exception:
        pass
    r.filepath = cfg["output"] + title + "_"
    log.append(f"render: EEVEE {cfg['resolution'][0]}x{cfg['resolution'][1]} @ {cfg['fps']} fps, frames 1-{nF}, MP4/H264 + AAC -> {r.filepath}")


def setup_cycles(cfg, title, log):
    """Path-traced render of the textured look. Cycles frames take seconds, so the output is an
    image sequence that an interrupted render picks up again (existing frames are kept);
    build_song.py encodes it to MP4 with the audio."""
    sc = bpy.context.scene
    r, c = sc.render, sc.cycles
    r.engine = 'CYCLES'
    c.device = 'GPU'
    c.samples = cfg["cycles_samples"]
    c.use_adaptive_sampling = True
    c.adaptive_threshold = cfg["cycles_noise"]
    c.use_denoising = True
    for prop, val in (("adaptive_min_samples", 16), ("denoiser", 'OPENIMAGEDENOISE'), ("denoising_use_gpu", True)):
        try:
            setattr(c, prop, val)
        except Exception as e:
            log.append(f"cycles {prop}: {e}")
    r.use_persistent_data = True
    r.use_motion_blur = False
    r.film_transparent = False                    # the studio's world, not a cut-out
    ims = r.image_settings
    try:
        ims.media_type = 'IMAGE'
    except Exception:
        pass
    ims.file_format = 'PNG'
    ims.color_mode = 'RGB'
    r.use_overwrite = False                       # resume: frames already on disk are not rendered again
    r.use_placeholder = False
    r.filepath = os.path.join(cfg["output"], title + "_cycles_frames", "frame_")
    log.append(f"render: Cycles (GPU, up to {cfg['cycles_samples']} samples, denoised) {cfg['resolution'][0]}x{cfg['resolution'][1]}, "
               f"image sequence -> {r.filepath}####.png")


def encode_frames(sc, audio_path, name, log=print):
    """the rendered image sequence + the song's audio -> <output>/<name>_<first>-<last>.mp4
    (H.264, BT.709, AAC; the audio is padded or cut to the length of the picture)"""
    import shutil
    import subprocess
    r = sc.render
    base = bpy.path.abspath(r.filepath)
    first, last = sc.frame_start, sc.frame_end
    missing = [f for f in range(first, last + 1) if not os.path.exists(f"{base}{f:04d}.png")]
    if missing:
        raise RuntimeError(f"{len(missing)} frames are not rendered yet (first missing: {missing[0]}); "
                           f"render again, it carries on where it stopped")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not on the PATH; the frames are in " + os.path.dirname(base))
    fps = r.fps / r.fps_base
    out = os.path.join(os.path.dirname(os.path.dirname(base)), f"{name}_{first:04d}-{last:04d}.mp4")
    cmd = [ffmpeg, "-y", "-v", "error", "-framerate", f"{fps:g}", "-start_number", str(first), "-i", base + "%04d.png",
           "-i", audio_path, "-map", "0:v", "-map", "1:a",
           "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
           "-c:v", "libx264", "-preset", "slow", "-crf", "16",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-af", "apad", "-t", f"{(last - first + 1) / fps:.4f}",
           "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    log(f"encoded {last - first + 1} frames + {os.path.basename(audio_path)} -> {out}")
    return out


def cycles_gpu(log=print):
    """switch on the GPU for this session (preferences are not saved); returns the device names"""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    names = []
    for kind in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type == kind]
        if gpus:
            for d in prefs.devices:
                d.use = d.type == kind
            names = [d.name for d in gpus]
            break
    log(f"cycles devices: {names or 'none found, CPU'}")
    return names


def puff_sim(farts, hips, p_local, d_local, nF, fps, seed=5):
    """The gas puffs of a fart part: when each one leaves, from where (the exit point p_local and
    direction d_local are in his Hips bone's space; hips: that bone's pose matrices per frame),
    how fast, how long it lives and how big it gets, packed into as few reusable slots as
    possible. Positions are in armature space, cm. Both looks use this, so they show the same puffs."""
    rng = np.random.default_rng(seed)
    puffs = []
    for e in farts["events"]:
        heavy = e["style"] in ("long", "rip", "blart")
        count = max(3, int((e["t1"] - e["t0"]) / 0.22)) if heavy else 2 if e["style"] == "parp" else 1
        for j in range(count):
            tb = e["t0"] + j * (0.22 if heavy else 0.07)
            M = hips[min(nF - 1, max(0, int(round(tb * fps))))]
            d = (M.to_3x3() @ d_local).normalized()
            loud = e.get("loud", 1.0)
            puffs.append(dict(tb=tb, life=1.5 if heavy else 1.2 if e["style"] == "parp" else 0.9,
                              p0=np.array(M @ p_local), d=np.array(d),
                              v0=np.array(d) * (70 + 50 * loud) * rng.uniform(0.8, 1.2) + rng.normal(0, 14, 3),
                              rmax=(7.0 if heavy else 5.0 if e["style"] == "parp" else 3.5) * math.sqrt(loud)))
    slots, free_at = [], []
    for p in sorted(puffs, key=lambda q: q["tb"]):
        k = next((i for i, tfree in enumerate(free_at) if tfree <= p["tb"]), None)
        if k is None:
            k = len(free_at)
            free_at.append(0.0)
            slots.append([])
        free_at[k] = p["tb"] + p["life"] + 1.0 / fps
        slots[k].append(p)
    return puffs, slots


def puff_center(p, age):
    """where a puff is `age` seconds after it left: it slows down in the air and rises"""
    return p["p0"] + p["v0"] * (1 - math.exp(-2.4 * age)) / 2.4 + np.array([0.0, 12.0 * age + 10.0 * age * age, 0.0])


def _cloud_material(cfg):
    """a cartoon stink cloud: a lumpy ball (a sphere whose edge is pushed in and out by noise, so
    it billows like a cumulus), lime green, glowing a little so it reads on the dark backdrop.
    Each cloud thins out by its own `puff_alpha` property and has its own lumps."""
    mat = bpy.data.materials.get("Fart_Cloud_MAT") or bpy.data.materials.new("Fart_Cloud_MAT")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new

    def math_node(op, a=None, b=None):
        m = N("ShaderNodeMath")
        m.operation = op
        for k, v in ((0, a), (1, b)):
            if isinstance(v, (int, float)):
                m.inputs[k].default_value = v
            elif v is not None:
                L(v, m.inputs[k])
        return m

    out, pv = N("ShaderNodeOutputMaterial"), N("ShaderNodeVolumePrincipled")
    tc, info, attr = N("ShaderNodeTexCoord"), N("ShaderNodeObjectInfo"), N("ShaderNodeAttribute")
    attr.attribute_type, attr.attribute_name = 'OBJECT', "puff_alpha"
    dist = N("ShaderNodeVectorMath")
    dist.operation = 'LENGTH'
    L(tc.outputs["Object"], dist.inputs[0])
    noise = N("ShaderNodeTexNoise")
    noise.noise_dimensions = '4D'
    noise.inputs["Scale"].default_value = 1.7
    noise.inputs["Detail"].default_value = 2.5
    noise.inputs["Roughness"].default_value = 0.55
    L(tc.outputs["Object"], noise.inputs["Vector"])
    L(math_node('MULTIPLY', info.outputs["Random"], 37.0).outputs["Value"], noise.inputs["W"])
    # 1 - distance + lumps: above 0.25 is inside the cloud, with a soft edge up to 0.45
    lumps = math_node('MULTIPLY_ADD', noise.outputs["Fac"], 0.6)
    lumps.inputs[2].default_value = 0.7
    shape = math_node('SUBTRACT', lumps.outputs["Value"], dist.outputs["Value"])
    edge = N("ShaderNodeMapRange")
    edge.interpolation_type = 'SMOOTHSTEP'
    for name, val in (("From Min", 0.25), ("From Max", 0.45), ("To Min", 0.0), ("To Max", 1.0)):
        edge.inputs[name].default_value = val
    L(shape.outputs["Value"], edge.inputs["Value"])
    body = math_node('MULTIPLY', edge.outputs["Result"], attr.outputs["Fac"])
    L(math_node('MULTIPLY', body.outputs["Value"], cfg["cloud_density"]).outputs["Value"], pv.inputs["Density"])
    L(math_node('MULTIPLY', body.outputs["Value"], cfg["cloud_glow"]).outputs["Value"], pv.inputs["Emission Strength"])
    pv.inputs["Color"].default_value = (0.55, 0.85, 0.12, 1.0)
    pv.inputs["Emission Color"].default_value = (0.42, 0.9, 0.06, 1.0)
    pv.inputs["Anisotropy"].default_value = 0.3
    L(pv.outputs["Volume"], out.inputs["Volume"])
    return mat


def _clear_fart_stage():
    """undo what fart_stage adds, so a song without a fart part builds on a plain studio"""
    coll = bpy.data.collections.get("Fart_FX")
    if coll:
        for ob in list(coll.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
    tt = bpy.data.objects.get("Stage_Turntable")
    if tt:
        tt.animation_data_clear()
        tt.rotation_euler = (0.0, 0.0, 0.0)


def fart_stage(arm, tr, farts, fz, nF, cfg, log):
    """The textured look of a song with a fart part. The camera makes the move the X-ray look
    makes (more side-on, swinging further behind him while he is bent over); the studio (the
    backdrop and the lights) sits on a turntable that turns with the camera, so the camera always
    faces the backdrop the way the scene was lit for; and every fart leaves a green gas cloud,
    from the same simulation as the X-ray look's rings."""
    import bayc_xray                                   # the exit point and the puffs are shared with it
    sc = bpy.context.scene
    fps = cfg["fps"]
    t = np.arange(nF) / fps
    end = tr.notes[-1]["t1"]
    wide = smooth(end - 2.5, end - 1.5, t)
    deep = np.asarray(fz["deep"], float)[:nF]
    deep = np.array([deep[max(0, i - 6):i + 7].mean() for i in range(nF)])
    dist = cfg["fart_dist"] - 0.25 * deep + 0.15 * wide
    az = np.radians(cfg["fart_orbit_deg"] + 30 * deep - 14 * wide)
    tz = 1.30 - 0.10 * deep + 0.04 * wide
    cam = sc.camera
    act, slot, cb = _new_action("BAYC_Sing_Camera", 'OBJECT', cam.name)
    for j, vals in enumerate((-dist * np.sin(az), -0.05 - dist * np.cos(az), tz + 0.06)):
        _write_curve(cb, "location", j, vals, 1)
    cam.animation_data_create()
    cam.animation_data.action = act
    cam.animation_data.action_slot = slot
    cam.data.lens = 85
    tgt = bpy.data.objects.get(cfg["camera"] + "_Target")
    if tgt:
        act_t, slot_t, cb_t = _new_action("BAYC_Sing_CamTarget", 'OBJECT', tgt.name)
        _write_curve(cb_t, "location", 2, tz, 1)
        tgt.animation_data_create()
        tgt.animation_data.action = act_t
        tgt.animation_data.action_slot = slot_t

    # the studio on a turntable under the camera
    backdrop = ((cfg.get("_profile") or {}).get("meshes") or {}).get("backdrop", ["Background"])
    stage = [o for o in sc.objects if o.type == 'LIGHT' or (o.type == 'MESH' and any(k in o.name for k in backdrop))]
    tt = bpy.data.objects.get("Stage_Turntable")
    if tt is None:
        tt = bpy.data.objects.new("Stage_Turntable", None)
        tt.empty_display_size = 0.4
        (stage[0].users_collection[0] if stage else sc.collection).objects.link(tt)
    tt.animation_data_clear()
    tt.rotation_mode = 'XYZ'
    tt.rotation_euler = (0.0, 0.0, 0.0)
    tt.location = (0.0, -0.05, 0.0)                    # the point the camera circles
    bpy.context.view_layer.update()
    for o in stage:
        if o.parent is not tt:
            o.parent = tt
            o.matrix_parent_inverse = tt.matrix_world.inverted()     # it stays where it is
    act_s, slot_s, cb_s = _new_action("BAYC_Sing_Turntable", 'OBJECT', tt.name)
    _write_curve(cb_s, "rotation_euler", 2, -az, 1)
    tt.animation_data_create()
    tt.animation_data.action = act_s
    tt.animation_data.action_slot = slot_s
    log.append(f"fart stage: camera {np.degrees(az.min()):.0f}-{np.degrees(az.max()):.0f} deg round him at {dist.min():.2f}-{dist.max():.2f} m; "
               f"studio turntable carries {len(stage)} objects")

    # the gas clouds
    coll = bpy.data.collections.get("Fart_FX") or bpy.data.collections.new("Fart_FX")
    if coll.name not in sc.collection.children:
        sc.collection.children.link(coll)
    for ob in list(coll.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    fit = bayc_xray.BodyFit([])
    if not fit.belly:
        log.append("fart stage: no belly found, so no gas clouds")
        return
    p_local, d_local = bayc_xray.fart_exit(fit, arm)
    puffs, slots = puff_sim(farts, bayc_xray.bone_track(arm, "Hips", nF), p_local, d_local, nF, fps)
    import bmesh
    me = bpy.data.meshes.get("Fart_Cloud")
    if me is None:
        me = bpy.data.meshes.new("Fart_Cloud")
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
        bm.to_mesh(me)
        bm.free()
    mat = _cloud_material(cfg)
    me.materials.clear()
    me.materials.append(mat)
    Mw = arm.matrix_world
    unit = Mw.to_scale().x                             # armature cm -> world m
    rng = random.Random(cfg["seed"] + 9)
    for k, sl in enumerate(slots):
        ob = bpy.data.objects.new(f"Fart_Cloud_{k:02d}", me)
        coll.objects.link(ob)
        ob["puff_alpha"] = 0.0
        ob.rotation_euler = (rng.uniform(0, 6.28), rng.uniform(0, 6.28), rng.uniform(0, 6.28))
        loc, scl, alp = np.zeros((nF, 3)), np.full(nF, 1e-4), np.zeros(nF)     # idle: tiny and empty
        last = np.array(Mw @ Vector(sl[0]["p0"].tolist()))
        for i in range(nF):
            p = next((q for q in sl if q["tb"] <= t[i] < q["tb"] + q["life"]), None)
            if p is not None:
                a = t[i] - p["tb"]
                last = np.array(Mw @ Vector(puff_center(p, a).tolist()))
                scl[i] = unit * cfg["cloud_size"] * p["rmax"] * (0.25 + 0.75 * (1 - math.exp(-3.2 * a / p["life"])))
                alp[i] = (1 - a / p["life"]) ** 1.3
            loc[i] = last
        act_c, slot_c, cb_c = _new_action(f"BAYC_Fart_Cloud_{k:02d}", 'OBJECT', ob.name)
        for j in range(3):
            _write_curve(cb_c, "location", j, loc[:, j], 1)
            _write_curve(cb_c, "scale", j, scl, 1)
        _write_curve(cb_c, '["puff_alpha"]', 0, alp, 1)
        ob.animation_data_create()
        ob.animation_data.action = act_c
        ob.animation_data.action_slot = slot_c
    log.append(f"fart stage: {len(puffs)} gas clouds in {len(slots)} objects")


# --------------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------------
def build(track_path, wav_path, title="bayc_song", cfg_over=None, farts=None, fart_fx=True):
    """farts: the info dict fartsynth.build() returns for a song with a fart part (or None);
    wav_path is then the mix of the voice and the farts. fart_fx: also stage the textured look
    for it (camera move, studio turntable, gas clouds); the X-ray look does its own."""
    log = []
    import bayc_rig as rig
    rep = rig.resolve((cfg_over or {}).get("profile", CFG["profile"]), log)
    if not rep["ok"]:
        raise RuntimeError("this character can't sing yet: " + "; ".join(rep["errors"]))
    cfg = dict(CFG)
    if cfg_over:
        cfg.update(cfg_over)
    if cfg_over:
        unknown = [k for k in cfg_over if k not in CFG]
        log.append(f"overrides: {cfg_over}" + (f" (WARNING: unknown keys {unknown})" if unknown else ""))
    tr = Track(track_path, cfg["fps"])
    log.append(f"track: {tr.duration:.2f} s, {len(tr.notes)} notes, {len(tr.segments)} phones, {tr.n_frames} frames")
    cfg["_farts"] = farts
    if farts:
        tr.extend(farts["duration"])
        log.append(f"fart part: {len(farts['events'])} notes, {len(farts.get('bend', []))} bend-over section(s); timeline {tr.duration:.2f} s, {tr.n_frames} frames")
    arm = ensure_extra_bones(cfg, log)
    cfg["_tongue"] = ensure_tongue_keys(cfg, log)
    W, sig = solve_face(tr, cfg)
    if not cfg["vocals"]:
        # a farts-only song: the voice track still sets the timing, but his mouth stays shut
        # while it plays (the dopey face at the very end is kept)
        stop = int(round((tr.notes[-1]["t1"] + 0.3) * cfg["fps"]))
        for k in MOUTH_KEYS:
            if k in W:
                W[k] = np.asarray(W[k], float).copy()
                W[k][:stop] = 0.0
        log.append(f"no vocals: mouth shut for the first {stop} frames")
    if cfg["_tongue"]:
        tu, tb = W["Tongue_TipUp"], W["Tongue_Back"]
        log.append(f"tongue drive: tip up on {100 * float((tu > 0.3).mean()):.0f}% of frames (peak {tu.max():.2f} at frame {int(tu.argmax()) + 1}), "
                   f"pulled back on {100 * float((tb > 0.3).mean()):.0f}% (peak at frame {int(tb.argmax()) + 1})")
    rig_ = Rig(arm)
    perf, nF, extra = performance(tr, sig, cfg)
    extra["E"] = np.concatenate([sig["E"], np.zeros(nF - len(sig["E"]))])
    results = simulate(rig_, tr, perf, nF, extra, cfg, log)
    write_face(W, cfg, nF, log)
    write_body(rig_, results, log)
    rig.ensure_lights(log)
    setup_stage(wav_path, nF, cfg, title, log, extra)
    _clear_fart_stage()
    if farts and fart_fx:
        fart_stage(arm, tr, farts, extra["fz"], nF, cfg, log)
    if cfg["engine"] == "cycles":
        setup_cycles(cfg, title, log)
    bpy.context.scene.frame_set(1)
    return log
