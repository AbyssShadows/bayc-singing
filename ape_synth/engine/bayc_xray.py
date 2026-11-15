"""bayc_xray.py: the chimera repo's vector-display look, fitted to the BAYC ape's own anatomy.

The ape becomes a thin glowing wireframe on black (the app's palette, src/ui/colors.ts: blue = body
and structure, amber = sound, green / pink / white = tongue / lips / teeth and folds).

His mouth is his own: the mouth mesh is split into its real parts (tongue, teeth, gums) and coloured
the app's way; they are animated by the singing shape keys, the tongue by tongue-only keys driven
from the synth's tongue (bayc_sing.ensure_tongue_keys). No human head anatomy is drawn.

Only the parts he has no geometry for are added, small, thin, and measured from his own neck and
chest so they sit inside him: the larynx with its vocal folds (high in the neck, as in apes), the
throat airway up to the root of his tongue (rings sized by the synth's area function, amber and
brighter when louder), the trachea and bronchi, and lungs that fill during rests. They take their
skin weights from the surrounding body, so they bend with his neck and ride the dance.
A camera-locked HUD shows a stroboscope of the vocal folds, the sung pitch and the sung word.

Run after bayc_sing.build(); reads <song>.geom.json written by `chimera render blender`.
"""
import bpy
import glob
import json
import math
import os
import re
import struct
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

import bayc_sing

PALETTE = {
    "blue": "#4fb6f2", "blueMid": "#3487c4", "blueDim": "#1f5f8c", "frame": "#133954",
    "green": "#5be381", "red": "#ff5d40", "pink": "#ff73cf", "white": "#eef6f8", "amber": "#ffb340",
}

XCFG = {
    "armature": None,             # set from bayc_sing.CFG (the character profile) when the look is applied
    "voice": True,                # False: a farts-only song (no throat glow, no vocal-fold inset, no words)
    "body_wire": 0.055,           # ape wireframe thickness (rig cm)
    "tongue_wire": 0.08,          # his tongue's line thickness (teeth and gums are a fraction)
    "tube": 0.05,                 # anatomy line radius (rig cm)
    "larynx_y": 161.6,            # larynx height (rig cm): high in the neck, as in apes
    "trachea_bottom_y": 148.5,
    "lung": {"x": 5.0, "y": 137.5, "z": -1.5, "rx": 3.3, "ry": 7.2, "rz": 3.9},
    "bloom": 0.45,
    "orbit_deg": 40.0,            # camera azimuth towards his right side
    # songs with a fart part: the digestive system
    "bubble_travel": 1.5,         # seconds a gas bubble takes through the colon to the exit
    "fart_orbit_deg": 52.0,       # camera azimuth (more side-on, so the bend and the puffs show)
    "fart_dist": 3.75,            # camera distance in m (the whole bend must fit)
    "fart_line_scale": 1.35,      # lines are drawn this much thicker, since he is smaller in frame
    "check_frames": 14,           # frames sampled by the inside-the-body check (0 = skip)
    # AVHershey Simplex by Stewart C. Russell (CC0 / WTFPL), the font of chimera's own display
    "font": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "AVHersheySimplexMedium.otf"),
}

# body meshes by name keyword -> (palette colour, emission strength, un-subdivide iterations).
# Everything on the body stays below the bloom threshold: crisp dim lines. The wireframe is the
# model's own topology: Subdivision Surface modifiers are switched off in the X-ray file (they
# multiply the lines by 4-16 and make playback crawl), so no un-subdividing is needed.
APE_STYLE = (
    ("_Head_", ("blue", 0.9, 0)),
    ("_Fur_", ("blueMid", 0.7, 0)),
    ("_Eyes_", ("white", 0.7, 0)),
    ("_Hat_", ("blueMid", 0.8, 0)),
    ("_Clothes_", ("blueDim", 0.9, 0)),
    ("_FlipFlop_", ("blueDim", 0.8, 0)),
)
APE_DEFAULT = ("blueDim", 0.8, 0)
MOUTH_STYLE = (("pink", 0.6), ("green", 2.4), ("white", 1.0))     # gums, tongue, teeth
MOUTH_LINE = (0.3, 1.0, 0.38)                                     # their line weight (x tongue_wire)
LIP_STYLE = ("pink", 0.9)
# bones the added anatomy can follow: the spine chain, and the thighs for what sits in his seat
# (the seat of the shorts moves with the thighs, so the exit must too, or it pokes out when he bends)
SPINE = ("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "LeftUpLeg", "RightUpLeg")


# --------------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------------
def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4))


def sstep(a, b, x):
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def emission_material(name, colour, strength):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em.inputs["Color"].default_value = (*hex_rgb(PALETTE[colour]), 1.0)
    em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    mat.diffuse_color = (*hex_rgb(PALETTE[colour]), 1.0)
    return mat


def tube_group(name, radius, material, merge=False):
    """Geometry Nodes: edges -> round tubes (radius and material baked into this object's group).
    merge: first weld points that coincide, so parts collapsed to a point draw nothing."""
    gname = f"XR_Tubes_{name}"
    old = bpy.data.node_groups.get(gname)
    if old:
        bpy.data.node_groups.remove(old)
    ng = bpy.data.node_groups.new(gname, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n = ng.nodes
    gi, go = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    m2c = n.new("GeometryNodeMeshToCurve")
    src = gi.outputs["Geometry"]
    if merge:
        weld = n.new("GeometryNodeMergeByDistance")
        weld.inputs["Distance"].default_value = 0.002
        ng.links.new(src, weld.inputs["Geometry"])
        src = weld.outputs["Geometry"]
    circ = n.new("GeometryNodeCurvePrimitiveCircle")
    circ.inputs["Resolution"].default_value = 5
    circ.inputs["Radius"].default_value = radius
    c2m = n.new("GeometryNodeCurveToMesh")
    setm = n.new("GeometryNodeSetMaterial")
    setm.inputs["Material"].default_value = material
    L = ng.links.new
    L(src, m2c.inputs["Mesh"])
    L(m2c.outputs["Curve"], c2m.inputs["Curve"])
    L(circ.outputs["Curve"], c2m.inputs["Profile Curve"])
    L(c2m.outputs["Mesh"], setm.inputs["Geometry"])
    L(setm.outputs["Geometry"], go.inputs["Geometry"])
    return ng


def write_pc2(path, frames):
    """frames: (F, N, 3) float32 in the object's local space"""
    frames = np.ascontiguousarray(frames, dtype="<f4")
    F, N, _ = frames.shape
    with open(path, "wb") as f:
        f.write(b"POINTCACHE2\0")
        f.write(struct.pack("<iiffi", 1, N, 0.0, 1.0, F))
        f.write(frames.tobytes())


def blend_path(path):
    """'//'-relative to the .blend when possible (same drive, saved file), else absolute"""
    if not bpy.data.filepath:
        return path
    try:
        return bpy.path.relpath(path)
    except ValueError:
        return path


def mesh_co(ob):
    me = ob.data
    a = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def role_mesh(role):
    """the character's mesh for a role (head, mouth, hat, skin, clothes, eyes), from the profile"""
    name = bayc_sing.CFG.get(role + "_mesh")
    return bpy.data.objects.get(name) if name else None


ROLE_STYLE = {"head": ("blue", 0.9, 0), "skin": ("blueMid", 0.7, 0), "eyes": ("white", 0.7, 0),
              "hat": ("blueMid", 0.8, 0), "clothes": ("blueDim", 0.9, 0)}


def find_mesh(keyword):
    return next((o for o in bpy.data.objects if o.type == "MESH" and keyword in o.name and not o.name.startswith("XR_")), None)


class Shape:
    """an edge mesh assembled from polylines; vertices per frame are filled by the builders"""

    def __init__(self):
        self.n = 0
        self.edges = []

    def line(self, count, closed=False):
        i0 = self.n
        self.edges += [(i0 + i, i0 + i + 1) for i in range(count - 1)]
        if closed:
            self.edges.append((i0 + count - 1, i0))
        self.n += count
        return i0

    def link(self, a, b):
        self.edges.append((a, b))


# --------------------------------------------------------------------------------------------
# the inside of the ape, measured from his own meshes (rest pose, armature-space cm:
# +X his left, +Y up, +Z forward)
# --------------------------------------------------------------------------------------------
class BodyFit:
    def __init__(self, log):
        fur = role_mesh("skin")
        head = bpy.data.objects[bayc_sing.CFG["head_mesh"]]
        allc = np.concatenate([mesh_co(fur), mesh_co(head)]) if fur else mesh_co(head)
        ys, cz, rm = [], [], []
        self.neck_top = 165.0
        for y in np.arange(156.0, 168.01, 0.5):
            band = allc[(np.abs(allc[:, 1] - y) < 0.6) & (np.abs(allc[:, 0]) < 9.0)]
            if len(band) < 10:
                continue
            c = 0.5 * (band[:, 2].min() + band[:, 2].max())
            r = np.hypot(band[:, 0], band[:, 2] - c)
            if r.min() < 3.0 or r.max() > 7.5:       # collar / chin geometry: not a clean neck slice
                continue
            ys.append(y)
            cz.append(c)
            rm.append(r.min())
        if len(ys) >= 3:
            self.cz_fit = np.polyfit(ys, cz, 1)
            self.rm_fit = np.polyfit(ys, rm, 1)
            self.neck_lo, self.neck_top = float(min(ys)), float(max(ys))
        else:                                        # this rig's measured values
            self.cz_fit, self.rm_fit = np.array([0.123, -21.9]), np.array([-0.19, 35.4])
            self.neck_lo = 158.0
        # the root of his tongue: where the throat meets the mouth
        mouth = role_mesh("mouth")
        part, _, B, _ = bayc_sing.mouth_parts(mouth) if mouth is not None else (np.zeros(0, int), None, np.zeros((0, 3)), None)
        T = part == 1
        if T.any():
            self.root_z = float(B[T][:, 2].min())
            self.root_y = float(B[T & (B[:, 2] < self.root_z + 1.2)][:, 1].mean())
        else:
            self.root_z, self.root_y = 5.2, 170.9
        log.append(f"fit: neck axis z {self.cz(160):+.2f}..{self.cz(164):+.2f}, inner radius {self.rmin(160):.2f}..{self.rmin(164):.2f} cm "
                   f"(y {self.neck_lo:.0f}-{self.neck_top:.0f}); tongue root at y {self.root_y:.1f} z {self.root_z:.1f}")
        # his belly and backside, for the digestive system: measured on his skin, which is a
        # whole body under the shirt and shorts and a little smaller than they are
        bones = bpy.data.objects[bayc_sing.CFG["armature"]].data.bones
        self.y_leg = bones["LeftUpLeg"].head_local.y if "LeftUpLeg" in bones else 105.0
        self.y_sp = bones["Spine"].head_local.y if "Spine" in bones else 119.3
        self.y_s1 = bones["Spine1"].head_local.y if "Spine1" in bones else 130.1
        self.belly = None
        skin = [mesh_co(fur)] if fur is not None else [mesh_co(o) for o in (role_mesh("clothes"),) if o is not None]
        if skin:
            bc = np.concatenate(skin)
            fr, bk, hw = [], [], []
            for y in np.arange(self.y_leg, self.y_sp + 4.0, 3.0):
                band = bc[(np.abs(bc[:, 1] - y) < 1.2) & (np.abs(bc[:, 0]) < 22.0)]
                core = band[np.abs(band[:, 0]) < 2.5]
                if len(core) < 2:
                    continue
                zc = 0.5 * (core[:, 2].min() + core[:, 2].max())
                side = band[np.abs(band[:, 2] - zc) < 2.5]
                if len(side) and core[:, 2].max() - core[:, 2].min() > 8.0:
                    fr.append(core[:, 2].max())
                    bk.append(core[:, 2].min())
                    hw.append(np.abs(side[:, 0]).max())
            butt = bc[(np.abs(bc[:, 1] - (self.y_leg - 4.5)) < 2.5) & (np.abs(bc[:, 0]) < 3.0)]
            if fr and len(butt):
                self.belly = dict(front=float(min(fr)), back=float(max(bk)), halfw=float(min(hw)), butt_z=float(butt[:, 2].min()))
                log.append("fit: belly {halfw:.1f} cm half-wide, z {back:+.1f}..{front:+.1f}; backside at z {butt_z:+.1f}".format(**self.belly))

    def gut_layout(self):
        """control points (rest pose) of the digestive tract, placed inside the measured belly"""
        b = self.belly
        xc = min(0.56 * b["halfw"], b["halfw"] - 4.6)      # the colon runs up one side and down the other
        zm = 0.5 * (b["front"] + b["back"])
        xs = xc - 2.9                                       # half-width of the small intestine's coils
        yl, ys, y1 = self.y_leg, self.y_sp, self.y_s1
        yt = ys + 1.4                                        # the colon's two top corners
        larynx = XCFG["larynx_y"]
        exit_ = (0.0, yl - 5.0, b["butt_z"] + 2.8)          # well under the skin, also when he bends
        colon = [(-xc, yl + 0.2, zm + 0.7), (-xc - 0.2, yl + 7.0, zm + 0.4), (-xc + 0.3, yt - 0.7, zm + 0.7),
                 (-xc + 2.6, yt + 0.7, zm + 2.1), (0.0, yt - 1.7, zm + 3.7), (xc - 2.6, yt + 0.9, zm + 2.1),
                 (xc - 0.2, yt - 0.3, zm + 0.7), (xc + 0.2, yl + 8.0, zm + 0.3), (xc - 0.6, yl + 1.8, zm - 0.5),
                 (4.2, yl - 1.4, zm - 2.3), (1.2, yl - 1.8, zm - 4.3), (0.0, yl - 3.4, zm - 6.5), exit_]
        colon_r = [1.5, 1.35, 1.3, 1.3, 1.3, 1.3, 1.3, 1.25, 1.2, 1.1, 1.0, 0.9, 0.55]
        stomach = [(1.0, y1 - 1.5, zm - 1.5), (3.6, y1 - 1.2, zm - 0.5), (5.6, y1 - 3.5, zm + 0.7),
                   (5.0, y1 - 5.7, zm + 1.7), (2.8, y1 - 6.7, zm + 2.1), (0.6, y1 - 6.4, zm + 1.9)]
        stomach_r = [0.7, 2.0, 2.6, 2.3, 1.5, 0.75]
        esophagus = [(0.0, larynx - 1.6, self.cz(larynx - 1.6) - 1.7), (0.0, 153.0, self.cz(153.0) - 1.8),
                     (0.2, y1 + 12.0, zm - 3.6), (0.5, y1 + 3.0, zm - 2.6), stomach[0]]
        small = [stomach[-1], (-2.4, y1 - 7.1, zm + 0.3), (-3.2, ys + 1.2, zm - 1.1), (-1.0, ys - 0.9, zm - 0.7)]
        rows = [ys - 2.6, ys - 4.8, ys - 7.0, ys - 9.2]
        for k, yr in enumerate(rows):
            d = 1.0 if k % 2 == 0 else -1.0                  # left to right, then back
            z = zm + 2.0 + (0.5 if k % 2 == 0 else -0.3)
            small += [(-xs * d, yr, z), (-0.34 * xs * d, yr + 0.45, z + 0.3), (0.34 * xs * d, yr - 0.45, z + 0.3), (xs * d, yr, z)]
            if k + 1 < len(rows):
                small.append(((xs + 0.6) * d, 0.5 * (yr + rows[k + 1]), z))
        small += [(-xs - 0.8, rows[-1] - 2.2, zm + 1.4), (-xc + 0.9, yl + 1.2, zm + 0.9)]
        return dict(colon=colon, colon_r=colon_r, stomach=stomach, stomach_r=stomach_r, esophagus=esophagus, small=small)

    def cz(self, y):
        return float(np.polyval(self.cz_fit, np.clip(y, 153.0, self.neck_top + 0.5)))

    def rmin(self, y):
        return float(np.polyval(self.rm_fit, np.clip(y, self.neck_lo, self.neck_top)))

    def throat_path(self, y0, count):
        """centres (y, z) and unit tangents of the airway from just above the larynx, up the neck
        and forward to the root of the tongue, evenly spaced along its length"""
        y1 = self.neck_top + 0.3
        p0 = np.array([y0, self.cz(y0)])
        p1 = np.array([y1, self.cz(y1)])
        p3 = np.array([self.root_y - 0.1, self.root_z - 1.1])
        c = np.array([p3[0] - 0.9, p1[1] + 0.3])
        seg1 = p0 + (p1 - p0) * np.linspace(0, 1, 24)[:, None]
        t = np.linspace(0, 1, 48)[1:, None]
        seg2 = (1 - t) ** 2 * p1 + 2 * (1 - t) * t * c + t ** 2 * p3
        poly = np.vstack([seg1, seg2])
        s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(poly, axis=0), axis=1))])
        u = np.linspace(0, s[-1], count)
        cen = np.stack([np.interp(u, s, poly[:, 0]), np.interp(u, s, poly[:, 1])], 1)
        d = np.gradient(cen, axis=0)
        return cen, d / np.linalg.norm(d, axis=1)[:, None]

    def rmax(self, y):
        """largest ring radius that stays well inside him at this height"""
        return 0.4 * self.rmin(min(y, self.neck_top)) * (1 - 0.42 * float(sstep(self.neck_top + 0.5, self.neck_top + 5.5, y)))


class SkinSource:
    """spine-chain bone weights of the body surface, to hand to the anatomy inside it"""

    def __init__(self):
        cos, ws = [], []
        for ob in (role_mesh("skin"), bpy.data.objects[bayc_sing.CFG["head_mesh"]], role_mesh("clothes")):
            if ob is None:
                continue
            me = ob.data
            n = len(me.vertices)
            W = np.zeros((n, len(SPINE)), np.float32)
            gi = {ob.vertex_groups[b].index: j for j, b in enumerate(SPINE) if b in ob.vertex_groups}
            for v in me.vertices:
                for g in v.groups:
                    j = gi.get(g.group)
                    if j is not None:
                        W[v.index, j] = g.weight
            keep = W.sum(1) > 0.5                     # skip arm- and leg-driven skin
            cos.append(mesh_co(ob)[keep])
            ws.append(W[keep])
        self.co = np.concatenate(cos)
        self.W = np.concatenate(ws)
        self.tree = KDTree(len(self.co))
        for i, p in enumerate(self.co):
            self.tree.insert(Vector(p.tolist()), i)
        self.tree.balance()

    def weights(self, pts, k=12):
        out = np.zeros((len(pts), len(SPINE)))
        for i, p in enumerate(pts):
            acc = np.zeros(len(SPINE))
            for _, idx, dist in self.tree.find_n(Vector(p.tolist()), k):
                acc += self.W[idx] / (dist * dist + 0.5)
            out[i] = acc / max(acc.sum(), 1e-9)
        return out


# --------------------------------------------------------------------------------------------
# the added anatomy
# --------------------------------------------------------------------------------------------
def fold_state(G, fps=30):
    """per frame: how far the vibrating folds are open (0..1, stroboscopic like the app: a slow
    sweep through the two-cycle glottal-area scope) and how far they are drawn apart (0 singing,
    1 breathing)"""
    peak = np.array([max(f.get("gScope") or [0.0]) for f in G])
    ref = max(1e-6, float(np.percentile(peak[peak > 0], 90))) if (peak > 0).any() else 1.0
    k = 1 - math.exp(-(1 / fps) / 0.07)
    ph, abd, vib, ab = 0.0, 1.0, [], []
    for f in G:
        ph = (ph + (1 / fps) / 1.8) % 1.0
        sc = f.get("gScope") or [0.0]
        voiced = f.get("voicing", 0) > 0.2
        abd += ((0.0 if voiced else 1.0) - abd) * k
        v = min(1.0, sc[int(ph * len(sc)) % len(sc)] / ref) if voiced else 0.0
        vib.append(v * (1 - abd))
        ab.append(abd)
    return np.array(vib), np.array(ab)


def build_structures(geom, fit, cfg, nF, fps, track_path, log):
    G = [f for f in geom["frames"] if f]
    out = {}

    def add(name, colour, strength, S, frames, radius=None):
        arr = np.asarray(frames, np.float32)
        if arr.ndim == 2:
            arr = arr[None]
        elif len(arr) < nF:
            arr = np.concatenate([arr, np.repeat(arr[-1:], nF - len(arr), axis=0)])
        assert arr.shape[1] == S.n, (name, arr.shape, S.n)
        out[name] = dict(colour=colour, strength=strength, edges=S.edges, frames=arr, radius=radius or cfg["tube"])

    yl = cfg["larynx_y"]
    czl = fit.cz(yl)

    # throat airway: rings from the larynx to the root of his tongue, sized by the synth's
    # pharynx area function (cm^2), clamped to what fits inside his neck
    NR, R = 10, 8
    cen, tan = fit.throat_path(yl + 0.75, NR)
    nrm = np.stack([-tan[:, 1], tan[:, 0]], 1)
    rmax = np.array([fit.rmax(y) for y in cen[:, 0]])
    th = np.linspace(0, 2 * np.pi, R, endpoint=False)
    S = Shape()
    starts = [S.line(R, closed=True) for _ in range(NR)]
    for j in range(0, R, 2):
        for a, b in zip(starts[:-1], starts[1:]):
            S.link(a + j, b + j)
    frames = []
    for f in G:
        g = np.asarray(f["grid"], float)
        split = int(f.get("split", -1))
        area = g[:split, 4] if split > 2 else g[g[:, 5] <= 1.5, 4]
        if len(area) < 2:
            area = g[:, 4]
        a = np.interp(np.linspace(0, 1, NR), np.linspace(0, 1, len(area)), area)
        r = np.clip(1.15 * np.sqrt(np.maximum(a, 0.0) / np.pi), 0.28, rmax)
        rows = []
        for k in range(NR):
            sn = r[k] * np.sin(th)
            rows.append(np.stack([r[k] * np.cos(th), cen[k, 0] + sn * nrm[k, 0], cen[k, 1] + sn * nrm[k, 1]], 1))
        frames.append(np.concatenate(rows))
    add("XR_throat", "amber", 1.0, S, frames)

    # larynx: a ring and the two vocal folds, joined at the front, apart at the back when he breathes
    vib, abd = fold_state(G, fps)
    P = 7
    s = np.linspace(0, 1, P)
    S = Shape()
    S.line(12, closed=True)
    for _ in range(2):
        S.line(P + 2, closed=True)
    th12 = np.linspace(0, 2 * np.pi, 12, endpoint=False)
    ring = np.stack([1.45 * np.cos(th12), np.full(12, yl - 0.15), czl + 1.3 * np.sin(th12)], 1)
    zf, zb = czl + 1.1, czl - 1.0
    frames = []
    for i in range(len(G)):
        rows = [ring]
        for side in (1.0, -1.0):
            xm = side * (0.04 + 0.5 * vib[i] * np.sin(np.pi * s) + 0.95 * abd[i] * s ** 1.2)
            medial = np.stack([xm, np.full(P, yl), zf + (zb - zf) * s], 1)
            lateral = np.array([[side * 1.12, yl, zb + 0.05], [side * 1.0, yl, czl + 0.35]])
            rows += [medial, lateral]
        frames.append(np.concatenate(rows))
    add("XR_folds", "white", 3.4, S, frames)

    # trachea rings and the two bronchi (static)
    lung = cfg["lung"]
    ys = np.arange(yl - 1.0, cfg["trachea_bottom_y"] - 1e-6, -1.2)
    R2 = 8
    th8 = np.linspace(0, 2 * np.pi, R2, endpoint=False)
    S = Shape()
    starts = [S.line(R2, closed=True) for _ in ys]
    for j in range(0, R2, 2):
        for a, b in zip(starts[:-1], starts[1:]):
            S.link(a + j, b + j)
    rows = [np.stack([1.0 * np.cos(th8), np.full(R2, y), fit.cz(y) + 1.0 * np.sin(th8)], 1) for y in ys]
    yb, zc = float(ys[-1]), fit.cz(float(ys[-1]))
    for side in (1.0, -1.0):
        S.line(4)
        rows.append(np.array([[0.0, yb, zc], [side * 1.2, yb - 1.4, zc + 0.1], [side * 2.2, yb - 2.9, zc + 0.3],
                              [side * (lung["x"] - 0.45 * lung["rx"]), lung["y"] + 0.42 * lung["ry"], lung["z"]]]))
    add("XR_trachea", "blueMid", 1.8, S, np.concatenate(rows))

    # lungs: fill during rests, empty while he sings
    with open(track_path, encoding="utf-8") as fh:
        d = json.load(fh)
    cols = d["keys"] + d["scalars"]
    F = np.asarray(d["frames"], float)
    gate = np.interp(np.arange(nF) / fps, np.arange(len(F)) / d["rate"], F[:, cols.index("gate")], right=0.0)
    lat, lon = 6, 8
    S = Shape()
    for _ in range(2):
        rings = [S.line(lon, closed=True) for _ in range(lat)]
        for j in range(lon):
            for a, b in zip(rings[:-1], rings[1:]):
                S.link(a + j, b + j)
    thl = np.linspace(0, 2 * np.pi, lon, endpoint=False)
    frames, v = [], 0.6
    for i in range(nF):
        if gate[i] > 0.3:
            v -= 0.11 / fps * gate[i]
        else:
            v += (1.0 - v) * (1 - math.exp(-(1 / fps) / 0.35))
        v = min(1.0, max(0.12, v))
        sc = 0.88 + 0.2 * v
        rows = []
        for side in (1.0, -1.0):
            for k in range(lat):
                phi = -0.5 * np.pi + np.pi * (k + 0.5) / lat
                rr = np.cos(phi) * sc
                rows.append(np.stack([side * lung["x"] + lung["rx"] * rr * np.cos(thl),
                                      np.full(lon, lung["y"] + lung["ry"] * np.sin(phi) * sc),
                                      lung["z"] + lung["rz"] * rr * np.sin(thl)], 1))
        frames.append(np.concatenate(rows))
    add("XR_lungs", "blueMid", 2.0, S, frames, radius=0.8 * cfg["tube"])
    log.append(f"anatomy: larynx at y {yl:.1f} (z {czl:+.2f}), throat rings r <= {rmax.max():.2f} cm, "
               f"trachea to y {yb:.1f}, lungs {2 * lung['rx']:.1f} x {2 * lung['ry']:.1f} cm")
    return out


# --------------------------------------------------------------------------------------------
# the digestive system (songs with a fart part)
# --------------------------------------------------------------------------------------------
def catmull(points, spacing):
    """evenly spaced points, unit tangents and arc lengths along a Catmull-Rom spline"""
    P = np.asarray(points, float)
    P = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for u in np.linspace(0, 1, 24, endpoint=False):
            out.append(0.5 * (2 * p1 + (p2 - p0) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (3 * p1 - p0 - 3 * p2 + p3) * u ** 3))
    out.append(P[-2])
    poly = np.asarray(out)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(poly, axis=0), axis=1))])
    u = np.linspace(0, s[-1], max(2, int(round(s[-1] / spacing)) + 1))
    cen = np.stack([np.interp(u, s, poly[:, k]) for k in range(3)], 1)
    tan = np.gradient(cen, axis=0)
    return cen, tan / np.linalg.norm(tan, axis=1)[:, None], u


class Tube:
    """a tube drawn as rings (and rails) along a path"""

    def __init__(self, points, spacing, radius, sides=8, rails=4):
        self.cen, self.tan, self.s = catmull(points, spacing)
        n = len(self.cen)
        self.r = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(radius)), radius) if np.ndim(radius) else np.full(n, float(radius))
        n1, ref = np.zeros((n, 3)), np.array([0.0, 0.0, 1.0])
        for i in range(n):                                   # carry the normal along: no twist
            v = ref - ref.dot(self.tan[i]) * self.tan[i]
            if np.linalg.norm(v) < 1e-6:
                v = np.cross(self.tan[i], [1.0, 0.0, 0.0])
            ref = n1[i] = v / np.linalg.norm(v)
        self.n1, self.n2 = n1, np.cross(self.tan, n1)
        self.sides, self.rails = sides, rails
        th = np.linspace(0, 2 * np.pi, sides, endpoint=False)
        self.c, self.sn = np.cos(th), np.sin(th)

    def add_to(self, S):
        starts = [S.line(self.sides, closed=True) for _ in range(len(self.cen))]
        if self.rails:
            for j in range(0, self.sides, max(1, self.sides // self.rails)):
                for a, b in zip(starts[:-1], starts[1:]):
                    S.link(a + j, b + j)

    def verts(self, scale=None):
        r = self.r if scale is None else self.r * scale
        ring = r[:, None, None] * (self.c[None, :, None] * self.n1[:, None, :] + self.sn[None, :, None] * self.n2[:, None, :])
        return (self.cen[:, None, :] + ring).reshape(-1, 3)


def bone_track(arm, name, nF):
    """pose matrices (armature space) of a root bone over the baked body action"""
    loc, quat = np.zeros((nF, 3)), np.tile([1.0, 0.0, 0.0, 0.0], (nF, 1))
    ad = arm.animation_data
    if ad and ad.action and ad.action.layers:
        cb = ad.action.layers[0].strips[0].channelbag(ad.action_slot)
        for fc in (cb.fcurves if cb else ()):
            if fc.data_path == f'pose.bones["{name}"].location':
                loc[:, fc.array_index] = [fc.evaluate(f) for f in range(1, nF + 1)]
            elif fc.data_path == f'pose.bones["{name}"].rotation_quaternion':
                quat[:, fc.array_index] = [fc.evaluate(f) for f in range(1, nF + 1)]
    rest = arm.data.bones[name].matrix_local
    return [rest @ (Matrix.Translation(loc[i].tolist()) @ Quaternion(quat[i].tolist()).normalized().to_matrix().to_4x4()) for i in range(nF)]


def fart_exit(fit, arm):
    """where the gas leaves him and which way (down and back), in his Hips bone's space: just
    past the end of the colon"""
    L = fit.gut_layout()
    colon = Tube(L["colon"], 1.3, L["colon_r"], sides=8, rails=4)
    rest_inv = arm.data.bones["Hips"].matrix_local.inverted()
    p_local = rest_inv @ (Vector(colon.cen[-1].tolist()) + Vector(colon.tan[-1].tolist()) * 1.8)
    d_local = rest_inv.to_3x3() @ Vector((0.0, -0.2, -1.0)).normalized()
    return p_local, d_local


def build_gut(fit, farts, cfg, nF, fps, arm, log):
    """Esophagus, stomach, small intestine and colon as thin tubes inside his belly. Every fart is
    a gas bubble that travels down the colon and reaches the exit as it sounds; the colon swells
    where a bubble is, the exit valve flutters, and a puff leaves behind him."""
    L = fit.gut_layout()
    t = np.arange(nF) / fps
    r = cfg["tube"]
    colon = Tube(L["colon"], 1.3, L["colon_r"], sides=8, rails=4)
    colon.r = colon.r * (1 + 0.12 * np.sin(2 * np.pi * colon.s / 2.6))        # its bulges
    small = Tube(L["small"], 1.5, 0.7, sides=6, rails=2)
    stomach = Tube(L["stomach"], 1.2, L["stomach_r"], sides=10, rails=5)
    eso = Tube(L["esophagus"], 2.2, 0.5, sides=6, rails=2)
    sN = colon.s / colon.s[-1]
    T = cfg["bubble_travel"]
    ta, amp = [], []
    for e in farts["events"]:
        if e["style"] in ("long", "rip", "blart"):                            # a long one is a stream of bubbles
            for j in range(int((e["t1"] - e["t0"]) / 0.2) + 1):
                ta.append(e["t0"] + 0.2 * j)
                amp.append(1.0)
        else:
            ta.append(e["t0"])
            amp.append({"toot": 0.6, "parp": 0.85}.get(e["style"], 0.5) * e.get("loud", 1.0))
    ta, amp = np.asarray(ta), np.asarray(amp)
    sig = 1.7 / colon.s[-1]
    level = np.clip(bayc_sing.fart_signals(farts, nF, fps)["level"], 0, 1)
    S_gut, S_gas, S_exit = Shape(), Shape(), Shape()
    for tube in (eso, stomach, small, colon):
        tube.add_to(S_gut)
    for _ in colon.cen:
        S_gas.line(colon.sides, closed=True)
    S_exit.line(12, closed=True)
    S_exit.line(12, closed=True)
    th12 = np.linspace(0, 2 * np.pi, 12, endpoint=False)
    ec, e1, e2 = colon.cen[-1], colon.n1[-1], colon.n2[-1]
    circ = np.cos(th12)[:, None] * e1[None, :] + np.sin(th12)[:, None] * e2[None, :]
    gut_f, gas_f, exit_f = [], [], []
    for i in range(nF):
        pos = 1 - (ta - t[i]) / T                                              # 0 at the start of the colon, 1 at the exit
        on = (pos >= -0.05) & (pos <= 1.0)
        if on.any():
            dz = (sN[:, None] - pos[on][None, :]) / sig
            A = np.clip((amp[on][None, :] * np.exp(-0.5 * dz * dz)).sum(1), 0, 1.4)
            cap = np.clip((amp[on][None, :] * np.sqrt(np.clip(1 - dz * dz / 4.0, 0, 1))).max(1), 0, 1.2)
        else:
            A = cap = np.zeros(len(sN))
        gut_f.append(np.concatenate([
            eso.verts(),
            stomach.verts(1 + 0.05 * np.sin(2 * np.pi * t[i] / 1.3 + 0.6 * np.arange(len(stomach.cen)))),
            small.verts(1 + 0.10 * np.sin(2 * np.pi * (small.s / 7.0 - t[i] / 1.6))),
            colon.verts(1 + 0.45 * A)]))
        gas_f.append(colon.verts(0.72 * cap * (1 + 0.45 * A)))                # a bubble: rings that swell and vanish
        ap = 0.15 + 0.6 * level[i] * (0.6 + 0.4 * abs(math.sin(2 * np.pi * 3.1 * t[i])))
        exit_f.append(np.concatenate([ec + 0.95 * circ, ec + ap * circ]))

    # puffs: they leave from his backside and drift off behind him (world space, not skinned);
    # the simulation is shared with the textured look's gas clouds
    p_local, d_local = fart_exit(fit, arm)
    puffs, slots = bayc_sing.puff_sim(farts, bone_track(arm, "Hips", nF), p_local, d_local, nF, fps)
    PR = 10
    thp = np.linspace(0, 2 * np.pi, PR, endpoint=False)
    S_puff = Shape()
    for _ in slots:
        S_puff.line(PR, closed=True)
        S_puff.line(PR, closed=True)
    hidden = np.tile(np.array([0.0, -400.0, 0.0]), (2 * PR, 1))
    puff_f = np.empty((nF, len(slots) * 2 * PR, 3), np.float32)
    for i in range(nF):
        rows = []
        for sl in slots:
            p = next((q for q in sl if q["tb"] <= t[i] < q["tb"] + q["life"]), None)
            if p is None:
                rows.append(hidden)
                continue
            a = t[i] - p["tb"]
            c = bayc_sing.puff_center(p, a)
            rad =p["rmax"] * (1 - math.exp(-4 * a / p["life"])) * min(1.0, (p["life"] - a) / (0.25 * p["life"]))
            d = p["d"]
            u = np.cross(d, [0.0, 1.0, 0.0])
            u = u / (np.linalg.norm(u) + 1e-9)
            w = np.cross(d, u)
            rows.append(c + rad * (np.cos(thp)[:, None] * u + np.sin(thp)[:, None] * w))    # a smoke ring, facing the way it flies
            rows.append(c + rad * (np.cos(thp)[:, None] * u + np.sin(thp)[:, None] * d))    # and one across it
        puff_f[i] = np.concatenate(rows) if rows else np.zeros((0, 3))
    out = {
        "XR_gut": dict(colour="pink", strength=1.25, edges=S_gut.edges, frames=np.asarray(gut_f, np.float32), radius=r),
        "XR_gas": dict(colour="green", strength=2.6, edges=S_gas.edges, frames=np.asarray(gas_f, np.float32), radius=1.15 * r, merge=True),
        "XR_exit": dict(colour="green", strength=1.0, edges=S_exit.edges, frames=np.asarray(exit_f, np.float32), radius=1.15 * r, glow=level),
    }
    if len(slots):
        out["XR_puffs"] = dict(colour="green", strength=1.5, edges=S_puff.edges, frames=puff_f, radius=1.15 * r, merge=True, skin=False)
    log.append(f"gut: esophagus {eso.s[-1]:.0f} cm, stomach, small intestine {small.s[-1]:.0f} cm, colon {colon.s[-1]:.0f} cm; "
               f"{len(ta)} gas bubbles, {len(puffs)} puffs in {len(slots)} slots; exit at y {ec[1]:.1f} z {ec[2]:+.1f}")
    return out


def make_object(name, spec, coll, cache_dir, ref_obj, arm, skin):
    fr = spec["frames"]
    me = bpy.data.meshes.new(name)
    me.from_pydata(fr[0].tolist(), spec["edges"], [])
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob.matrix_world = ref_obj.matrix_world.copy()
    if len(fr) > 1:
        path = os.path.join(cache_dir, name + ".pc2")
        write_pc2(path, fr)
        mc = ob.modifiers.new("XR_cache", "MESH_CACHE")
        mc.cache_format = "PC2"
        mc.filepath = blend_path(path)
        mc.frame_start = 1.0
        mc.play_mode = "SCENE"
        mc.time_mode = "FRAME"
    if spec.get("skin", True):                    # rides his body; otherwise it stays put in the world
        W = skin.weights(fr[0])
        for j, bone in enumerate(SPINE):
            idx = np.nonzero(W[:, j] > 1e-4)[0]
            if len(idx):
                vg = ob.vertex_groups.new(name=bone)
                for i in idx.tolist():
                    vg.add([i], float(W[i, j]), "REPLACE")
        am = ob.modifiers.new("XR_rig", "ARMATURE")
        am.object = arm
    mat = emission_material(f"XR_{name}", spec["colour"], spec["strength"])
    gn = ob.modifiers.new("XR_tubes", "NODES")
    gn.node_group = tube_group(name, spec["radius"], mat, merge=spec.get("merge", False))
    me.materials.append(mat)
    return ob, mat


# --------------------------------------------------------------------------------------------
# the ape himself
# --------------------------------------------------------------------------------------------
def _poly_first_vertex(me):
    ls = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)
    return ls, lv


def mouth_lining(me, front):
    """Faces of the head mesh that line the inside of his mouth: flood from the opening at the
    back of the mouth (a boundary loop on the midline) across faces that look into the cavity,
    which stops at the crest of the lips."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    parent = {}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e in bm.edges:
        if e.is_boundary:
            a, b = e.verts[0].index, e.verts[1].index
            parent.setdefault(a, a)
            parent.setdefault(b, b)
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    loops = {}
    for i in parent:
        loops.setdefault(find(i), []).append(i)
    best, best_c = None, None
    for idx in loops.values():
        c = sum((bm.verts[i].co for i in idx), Vector()) / len(idx)
        if abs(c.x) < 1.0 and (best_c is None or c.z > best_c.z):   # midline loops: neck hole, mouth back
            best, best_c = idx, c
    faces = []
    if best is not None:
        A, Bp = best_c, Vector(front)
        axis = Bp - A
        L2 = max(axis.length_squared, 1e-9)

        def inward(f):
            p = f.calc_center_median()
            q = A + axis * min(1.0, max(0.0, (p - A).dot(axis) / L2))
            d = q - p
            return d.length > 1e-6 and f.normal.dot(d.normalized()) > 0.1

        stack = [f for i in best for f in bm.verts[i].link_faces if inward(f)]
        seen = set(stack)
        while stack:
            f = stack.pop()
            for e in f.edges:
                for g in e.link_faces:
                    if g not in seen and inward(g):
                        seen.add(g)
                        stack.append(g)
        faces = [f.index for f in seen]
    bm.free()
    return faces


def style_ape(arm, log, wire=None):
    wire = XCFG["body_wire"] if wire is None else wire
    mouth_name, head_name = bayc_sing.CFG["mouth_mesh"], bayc_sing.CFG["head_mesh"]
    for ob in bpy.data.objects:
        if ob.type != "MESH" or ob.name.startswith("XR_"):
            continue
        if not any(m.type == "ARMATURE" and m.object == arm for m in ob.modifiers):
            continue
        for m in list(ob.modifiers):
            if m.name.startswith("XR_"):
                ob.modifiers.remove(m)
            elif m.type == "SUBSURF":             # kept on the mesh, just not used by this look
                m.show_viewport = False
                m.show_render = False
        me = ob.data
        role = next((r for r in ROLE_STYLE if bayc_sing.CFG.get(r + "_mesh") == ob.name), None)
        colour, strength, unsub = ROLE_STYLE[role] if role else next((st for key, st in APE_STYLE if key in ob.name), APE_DEFAULT)
        if ob.name == mouth_name:
            # his own tongue, teeth and gums, each in the app's colour
            part = bayc_sing.mouth_parts(ob)[0]
            ls, lv = _poly_first_vertex(me)
            me.materials.clear()
            for c, s in MOUTH_STYLE:
                me.materials.append(emission_material(f"XR_mouth_{c}", c, s))
            me.polygons.foreach_set("material_index", part[lv[ls]].astype(np.int32))
            unsub = 0
            # line weight per part: the tongue bold, teeth and gums hairlines (so it shows through)
            vg = ob.vertex_groups.get("XR_thick") or ob.vertex_groups.new(name="XR_thick")
            for p_id, wgt in ((0, MOUTH_LINE[0]), (1, MOUTH_LINE[1]), (2, MOUTH_LINE[2])):
                vg.add(np.nonzero(part == p_id)[0].tolist(), wgt, "REPLACE")
            n_t, n_th = int((part == 1).sum()), int((part == 2).sum())
            log.append(f"mouth: his own tongue ({n_t} verts, green), teeth ({n_th} verts, white), gums (pink)")
        else:
            mat = emission_material(f"XR_ape_{colour}_{strength}", colour, strength)
            if me.materials:
                for i in range(len(me.materials)):
                    me.materials[i] = mat
            else:
                me.materials.append(mat)
            if ob.name == head_name and mouth_name and mouth_name in bpy.data.objects:
                # the lining of his mouth, up to the crest of the lips, in the app's lip pink
                mouth_ob = bpy.data.objects[mouth_name]
                mc = mesh_co(mouth_ob)
                teeth_front = mc[mc[:, 2] > mc[:, 2].max() - 1.5]
                lining = mouth_lining(me, (0.0, float(teeth_front[:, 1].mean()), float(mc[:, 2].max()) + 1.2))
                if len(lining) >= 20:
                    me.materials.append(emission_material("XR_lips", *LIP_STYLE))
                    mi = np.zeros(len(me.polygons), np.int32)
                    mi[lining] = len(me.materials) - 1
                    me.polygons.foreach_set("material_index", mi)
                    log.append(f"lips: {len(lining)} faces of mouth lining in pink")
                else:
                    log.append("lips: no mouth lining found in the head mesh; left blue")
        if unsub:
            dm = ob.modifiers.new("XR_unsubdiv", "DECIMATE")   # topological only: no flicker
            dm.decimate_type = "UNSUBDIV"
            dm.iterations = unsub
        wf = ob.modifiers.new("XR_wire", "WIREFRAME")
        wf.thickness = wire
        wf.use_replace = True
        wf.use_even_offset = True
        wf.use_boundary = True
        if ob.name == mouth_name:
            wf.thickness = XCFG["tongue_wire"] * wire / XCFG["body_wire"]
            wf.vertex_group = "XR_thick"
            wf.thickness_vertex_group = 0.0       # thickness = base x weight
        me.update()
    backdrop = ((bayc_sing.CFG.get("_profile") or {}).get("meshes") or {}).get("backdrop", ["Background"])
    for ob in bpy.data.objects:
        if ob.type == "MESH" and any(k in ob.name for k in backdrop):
            ob.hide_render = True
            ob.hide_viewport = True
    log.append("ape: thin emission wireframe in the app palette; background hidden")


def setup_look(scene, log):
    w = scene.world or bpy.data.worlds.new("XR_World")
    scene.world = w
    w.use_nodes = True
    bgn = next((n for n in w.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bgn:
        bgn.inputs["Color"].default_value = (0, 0, 0, 1)
        bgn.inputs["Strength"].default_value = 0.0
    vs = scene.view_settings
    try:
        vs.view_transform = "Standard"
    except TypeError as e:
        log.append(f"view transform: {e}")
    vs.look = "None"
    vs.exposure = 0.0
    vs.gamma = 1.0
    scene.render.film_transparent = False        # black, in the viewport too
    try:
        scene.eevee.taa_render_samples = 16
    except Exception:
        pass
    if hasattr(scene.render, "use_motion_blur"):
        scene.render.use_motion_blur = False     # crisp vector lines
    try:
        tree = bpy.data.node_groups.get("XR_Compositor") or bpy.data.node_groups.new("XR_Compositor", "CompositorNodeTree")
        tree.nodes.clear()
        if not any(getattr(s, "in_out", "") == "OUTPUT" for s in tree.interface.items_tree):
            tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl = tree.nodes.new("CompositorNodeRLayers")
        gl = tree.nodes.new("CompositorNodeGlare")
        out = tree.nodes.new("NodeGroupOutput")
        for sock, val, prop, legacy in (("Type", "Bloom", "glare_type", "BLOOM"), ("Quality", "Medium", "quality", "MEDIUM")):
            s = gl.inputs.get(sock)
            try:
                if s is not None:
                    s.default_value = val
                else:
                    setattr(gl, prop, legacy)
            except Exception as e:
                log.append(f"glare {sock}: {e}")
        for sock, val in (("Strength", XCFG["bloom"]), ("Size", 0.45), ("Threshold", 1.0), ("Saturation", 1.0)):
            s = gl.inputs.get(sock)
            if s is not None:
                try:
                    s.default_value = val
                except Exception:
                    pass
        tree.links.new(rl.outputs["Image"], gl.inputs["Image"])
        tree.links.new(gl.outputs["Image"], out.inputs[0])
        scene.compositing_node_group = tree
        scene.render.use_compositing = True
    except Exception as e:
        log.append(f"bloom setup failed: {e!r}")


def _curve(cb, path, index, values):
    n = len(values)
    fc = cb.fcurves.new(path, index=index)
    fc.keyframe_points.add(n)
    co = np.empty(2 * n, np.float32)
    co[0::2] = np.arange(1, n + 1)
    co[1::2] = values
    fc.keyframe_points.foreach_set("co", co)
    fc.update()


def _fresh_action(name, id_type, slot_name):
    act = bpy.data.actions.get(name)
    if act:
        bpy.data.actions.remove(act)
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    slot = act.slots.new(id_type=id_type, name=slot_name)
    return act, slot, act.layers.new("Layer").strips.new(type="KEYFRAME").channelbag(slot, ensure=True)


def animate_glow(mat, level, action_name, lo, hi):
    """a material's emission strength follows a 0..1 level, frame by frame (rise fast, fall slower)"""
    sm, y = np.zeros(len(level)), 0.0
    for i, v in enumerate(level):
        y += (v - y) * (0.6 if v > y else 0.15)
        sm[i] = y
    em = next(n for n in mat.node_tree.nodes if n.type == "EMISSION")
    nt = mat.node_tree
    act, slot, cb = _fresh_action(action_name, "NODETREE", mat.name)
    _curve(cb, f'nodes["{em.name}"].inputs[1].default_value', 0, lo + (hi - lo) * np.clip(sm, 0, 1.2))
    nt.animation_data_create()
    nt.animation_data.action = act
    nt.animation_data.action_slot = slot


def animate_sound_glow(mat, geom, nF):
    """amber = sound: the throat's glow follows the voice's output level"""
    lvl = np.array([f.get("outRms", 0.0) for f in geom["frames"] if f], float)
    lvl = np.concatenate([lvl, np.zeros(max(0, nF - len(lvl)))])[:nF]
    animate_glow(mat, lvl / 0.35, "XR_SoundGlow", 0.55, 3.75)


def orbit_camera(scene, nF, fps, track_path, cfg, fz=None):
    """three-quarter view from his right, side-on while pushed in on the verse (mouth and throat
    in profile), back towards his face and wider for the hooks and the finale. With a fart part
    (fz: its frame-rate signals) the whole figure stays in frame, more side-on, and the camera
    swings further behind him while he is bent over."""
    cam = scene.camera
    with open(track_path, encoding="utf-8") as fh:
        notes = json.load(fh)["notes"]
    t = np.arange(nF) / fps
    end, first = notes[-1]["t1"], notes[0]["t0"]
    close = sstep(first, first + 4.0, t) * (1 - sstep(end * 0.45, end * 0.55, t))
    wide = sstep(end - 2.5, end - 1.5, t)
    if fz is None:
        dist = 2.95 - 0.75 * close + 0.55 * wide
        az = np.radians(cfg["orbit_deg"] + 24 * close - 10 * wide)
        tz = 1.62 + 0.08 * close - 0.12 * wide
    else:
        deep = np.asarray(fz["deep"], float)[:nF]
        deep = np.array([deep[max(0, i - 6):i + 7].mean() for i in range(nF)])     # ease the move
        dist = cfg["fart_dist"] - 0.25 * deep + 0.15 * wide
        az = np.radians(cfg["fart_orbit_deg"] + 30 * deep - 14 * wide)
        tz = 1.30 - 0.10 * deep + 0.04 * wide
    act, slot, cb = _fresh_action("BAYC_Sing_Camera", "OBJECT", cam.name)
    for j, vals in enumerate((-dist * np.sin(az), -0.05 - dist * np.cos(az), tz + 0.06)):
        _curve(cb, "location", j, vals)
    cam.animation_data_create()
    cam.animation_data.action = act
    cam.animation_data.action_slot = slot
    tgt = bpy.data.objects.get(cam.name + "_Target")
    if tgt:
        tgt.animation_data_clear()
        act_t, slot_t, cbt = _fresh_action("BAYC_Sing_CamTarget", "OBJECT", tgt.name)
        _curve(cbt, "location", 2, tz)
        tgt.location = (0.0, -0.05, float(tz[0]))
        tgt.animation_data_create()
        tgt.animation_data.action = act_t
        tgt.animation_data.action_slot = slot_t
    cam.data.lens = 85
    cam.data.show_passepartout = True
    cam.data.passepartout_alpha = 1.0             # black outside the frame in the viewport


# --------------------------------------------------------------------------------------------
# HUD (camera-locked): vocal-fold stroboscope, pitch, sung word
# --------------------------------------------------------------------------------------------
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _hud_text(name, body, size, colour, strength, loc, cam, coll, font):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    if font:
        cu.font = font
    cu.align_x = "CENTER"
    ob = bpy.data.objects.new(name, cu)
    coll.objects.link(ob)
    ob.parent = cam
    ob.location = loc
    cu.materials.append(emission_material(f"XR_hud_{colour}_{strength}", colour, strength))
    return ob


def _visible_between(ob, f0, f1):
    for fr, hidden in ((1, True), (f0, False), (f1 + 1, True)):
        ob.hide_render = hidden
        ob.hide_viewport = hidden
        ob.keyframe_insert("hide_render", frame=fr)
        ob.keyframe_insert("hide_viewport", frame=fr)


def _hud_mesh(name, colour, strength, radius, S, frames, coll, cache_dir, cam):
    fr = np.asarray(frames, np.float32)
    if fr.ndim == 2:
        fr = fr[None]
    me = bpy.data.meshes.new(name)
    me.from_pydata(fr[0].tolist(), S.edges, [])
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob.parent = cam
    if len(fr) > 1:
        path = os.path.join(cache_dir, name + ".pc2")
        write_pc2(path, fr)
        mc = ob.modifiers.new("XR_cache", "MESH_CACHE")
        mc.cache_format = "PC2"
        mc.filepath = blend_path(path)
        mc.frame_start = 1.0
        mc.play_mode = "SCENE"
        mc.time_mode = "FRAME"
    mat = emission_material(f"XR_{name}", colour, strength)
    gn = ob.modifiers.new("XR_tubes", "NODES")
    gn.node_group = tube_group(name, radius, mat)
    me.materials.append(mat)
    return ob


class Hud:
    """the camera-locked display plane, 1 m in front of the lens"""

    def __init__(self, scene, cache_dir):
        self.cam = scene.camera
        self.coll = bpy.data.collections.get("XRay_HUD") or bpy.data.collections.new("XRay_HUD")
        if self.coll.name not in scene.collection.children:
            scene.collection.children.link(self.coll)
        for ob in list(self.coll.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        self.font = bpy.data.fonts.load(XCFG["font"], check_existing=True) if os.path.exists(XCFG["font"]) else None
        self.D = -1.0
        self.half = 0.5 * self.cam.data.sensor_width / self.cam.data.lens     # visible half-size at 1 m
        self.cache_dir = cache_dir

    def text(self, name, body, size, colour, strength, x, y):
        return _hud_text(name, body, size, colour, strength, (x, y, self.D), self.cam, self.coll, self.font)

    def mesh(self, name, colour, strength, radius, S, frames):
        return _hud_mesh(name, colour, strength, radius, S, frames, self.coll, self.cache_dir, self.cam)


def sound_panel_data(x, nF, fps, win_s, n_pts=72, n_bins=40, fs=48000):
    """per video frame: an oscilloscope trace (triggered on a peak, so it holds still) and a
    spectrum on a log frequency axis (60 Hz - 6 kHz, 50 dB range, peak-hold with decay)"""
    W = int(win_s * fs)
    look = W // 3
    xp = np.concatenate([x, np.zeros(max(0, int(nF / fps * fs) - len(x)) + W + look + 4096)])   # the video outlasts the audio
    ref = np.percentile(np.abs(x[np.abs(x) > 1e-4]), 99.5) if (np.abs(x) > 1e-4).any() else 1.0
    idx = np.linspace(0, W - 1, n_pts).astype(int)
    nfft = 2048
    hann = np.hanning(nfft)
    freqs = np.fft.rfftfreq(nfft, 1 / fs)
    edges = np.geomspace(60.0, 6000.0, n_bins + 1)
    pick = [np.nonzero((freqs >= a) & (freqs < b))[0] for a, b in zip(edges[:-1], edges[1:])]
    pick = [p if len(p) else np.array([int(round(0.5 * (a + b) / (fs / nfft)))]) for p, a, b in zip(pick, edges[:-1], edges[1:])]
    scope, spec = np.zeros((nF, n_pts)), np.zeros((nF, n_bins))
    for i in range(nF):
        c = int(i / fps * fs)
        k = c + int(np.argmax(xp[c:c + look]))
        scope[i] = xp[k:k + W][idx]
        b0 = max(0, c - nfft // 2)
        P = np.abs(np.fft.rfft(xp[b0:b0 + nfft] * hann)) ** 2
        spec[i] = [P[p].max() for p in pick]
    db = 10 * np.log10(spec + 1e-12)
    top = np.percentile(db, 99.8)
    sp = np.clip((db - (top - 50.0)) / 50.0, 0, 1)
    for i in range(1, nF):
        sp[i] = np.maximum(sp[i], sp[i - 1] - 0.07)
    return np.clip(scope / ref, -1.15, 1.15), sp


def hud_sound(H, name, x, nF, fps, win_s, colour, label, px, py, w, h):
    """a panel for one sound source: its waveform on top, its spectrum below"""
    scope, spec = sound_panel_data(x, nF, fps, win_s)
    ns, nb = scope.shape[1], spec.shape[1]
    S = Shape()
    S.line(ns)
    S.line(nb)
    xs = px + w * 0.92 * (np.linspace(0, 1, ns) - 0.5)
    xb = px + w * 0.92 * (np.linspace(0, 1, nb) - 0.5)
    frames = np.empty((nF, ns + nb, 3), np.float32)
    frames[:, :ns, 0], frames[:, ns:, 0], frames[:, :, 2] = xs, xb, H.D
    frames[:, :ns, 1] = py + 0.25 * h + 0.19 * h * scope
    frames[:, ns:, 1] = py - 0.45 * h + 0.40 * h * spec
    H.mesh(f"XR_hud_{name}_wave", colour, 1.8, 0.00042, S, frames)
    S2 = Shape()
    S2.line(4, closed=True)
    S2.line(2)
    box = [[px - w / 2, py - h / 2, H.D], [px + w / 2, py - h / 2, H.D], [px + w / 2, py + h / 2, H.D], [px - w / 2, py + h / 2, H.D],
           [px - w / 2, py + 0.02 * h, H.D], [px + w / 2, py + 0.02 * h, H.D]]
    H.mesh(f"XR_hud_{name}_box", "blueDim", 1.3, 0.0003, S2, np.asarray(box))
    H.text(f"XR_hud_{name}_label", label, 0.04 * H.half, colour, 1.3, px, py - 0.5 * h - 0.055 * H.half)


def hud_sphincter(H, farts, nF, fps, cx, cy, R):
    """the other sound source, drawn like the vocal-fold inset: a valve that opens while it sounds"""
    level = np.clip(bayc_sing.fart_signals(farts, nF, fps)["level"], 0, 1)
    t = np.arange(nF) / fps
    openv = level * (0.6 + 0.4 * np.abs(np.sin(2 * np.pi * 3.1 * t)))
    NA, NP = 24, 8
    th = np.linspace(0, 2 * np.pi, NA, endpoint=False)
    tp = (np.arange(NP) + 0.5) * 2 * np.pi / NP
    S = Shape()
    S.line(NA, closed=True)
    for _ in range(NP):
        S.line(2)
    frames = np.empty((nF, NA + 2 * NP, 3), np.float32)
    frames[:, :, 2] = H.D
    for i in range(nF):
        ra = R * (0.07 + 0.5 * openv[i]) * (1 + 0.10 * np.cos(NP * th))
        frames[i, :NA, 0], frames[i, :NA, 1] = cx + ra * np.cos(th), cy + ra * np.sin(th)
        r0 = R * (0.07 + 0.5 * openv[i]) * 1.3
        frames[i, NA::2, 0], frames[i, NA::2, 1] = cx + r0 * np.cos(tp), cy + r0 * np.sin(tp)
        frames[i, NA + 1::2, 0], frames[i, NA + 1::2, 1] = cx + 0.88 * R * np.cos(tp), cy + 0.88 * R * np.sin(tp)
    H.mesh("XR_hud_valve", "green", 1.8, 0.00045, S, frames)
    tc = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    S2 = Shape()
    S2.line(48, closed=True)
    pts = [np.stack([cx + 1.12 * R * np.cos(tc), cy + 1.12 * R * np.sin(tc), np.full(48, H.D)], 1)]
    for k in range(4):
        a = k * np.pi / 2
        S2.line(2)
        pts.append(np.array([[cx + 1.17 * R * np.cos(a), cy + 1.17 * R * np.sin(a), H.D], [cx + 1.3 * R * np.cos(a), cy + 1.3 * R * np.sin(a), H.D]]))
    H.mesh("XR_hud_valve_ring", "blueMid", 1.3, 0.00035, S2, np.concatenate(pts))
    H.text("XR_hud_valve_label", "SPHINCTER", 0.04 * H.half, "blue", 1.3, cx, cy - 1.62 * R)
    fr = lambda s: int(round(s * fps)) + 1
    evs = farts["events"]
    for i, e in enumerate(evs):
        m = int(round(e["midi"]))
        ob = H.text(f"XR_hud_fart_{i:03d}", f"{e['hz']:.0f} HZ  {NOTE_NAMES[m % 12]}{m // 12 - 1}", 0.05 * H.half, "green", 1.3, cx, cy + 1.5 * R)
        last = fr(e["t1"])
        if i + 1 < len(evs):
            last = min(last, fr(evs[i + 1]["t0"]) - 1)
        _visible_between(ob, fr(e["t0"]), max(fr(e["t0"]), last))


def hud(scene, geom, track_path, nF, fps, cache_dir, log, farts=None, voice_wav=None, voice=True):
    H = Hud(scene, cache_dir)
    cam, coll, font, D, half = H.cam, H.coll, H.font, H.D, H.half
    if farts:
        # two instruments, one each side: the gas on his left of frame, the voice on the right
        import fartsynth
        cx, cy, R = 0.76 * half, -0.70 * half, 0.12 * half
        word_at, word_size = (0.0, -0.86 * half), 0.11 * half
        hud_sphincter(H, farts, nF, fps, -0.76 * half, -0.70 * half, 0.12 * half)
        hud_sound(H, "gas", fartsynth.read_wav(farts["wav"])[0], nF, fps, 0.045, "green", "GAS", -0.77 * half, 0.80 * half, 0.40 * half, 0.25 * half)
        if voice_wav:
            hud_sound(H, "voice", fartsynth.read_wav(voice_wav)[0], nF, fps, 0.030, "amber", "VOICE", 0.77 * half, 0.80 * half, 0.40 * half, 0.25 * half)
    else:
        cx, cy, R = -0.78 * half, -0.72 * half, 0.13 * half
        word_at, word_size = (0.12 * half, -0.8 * half), 0.12 * half
    if not voice:                               # farts only: no vocal-fold inset, pitches or words
        log.append("hud: sphincter inset and gas panel (no vocals)")
        return

    # stroboscope: top view of the folds (front up), thin lines
    vib, abd = fold_state([f for f in geom["frames"] if f], fps)
    pad = max(0, nF - len(vib))
    vib, abd = np.concatenate([vib, np.zeros(pad)])[:nF], np.concatenate([abd, np.ones(pad)])[:nF]
    P = 9
    s = np.linspace(0, 1, P)
    S = Shape()
    for _ in range(2):
        S.line(2 * P, closed=True)
    Lf = 1.5 * R
    ys = cy + Lf / 2 - Lf * s
    xl = R * (0.10 + 0.66 * np.sin(0.5 * np.pi * s ** 0.7))
    frames = []
    for i in range(nF):
        xm = R * (0.012 + 0.42 * vib[i] * np.sin(np.pi * s) + 0.6 * abd[i] * s ** 1.2)
        xm = np.minimum(xm, xl - 0.03 * R)
        rows = []
        for side in (-1.0, 1.0):
            rows.append(np.stack([cx + side * xm, ys, np.full(P, D)], 1))
            rows.append(np.stack([cx + side * xl[::-1], ys[::-1], np.full(P, D)], 1))
        frames.append(np.concatenate(rows))
    _hud_mesh("XR_hud_folds", "white", 1.7, 0.00045, S, frames, coll, cache_dir, cam)
    th = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    S2 = Shape()
    S2.line(48, closed=True)
    pts = [np.stack([cx + 1.12 * R * np.cos(th), cy + 1.12 * R * np.sin(th), np.full(48, D)], 1)]
    for k in range(4):
        a = k * np.pi / 2
        S2.line(2)
        pts.append(np.array([[cx + 1.17 * R * np.cos(a), cy + 1.17 * R * np.sin(a), D], [cx + 1.3 * R * np.cos(a), cy + 1.3 * R * np.sin(a), D]]))
    _hud_mesh("XR_hud_ring", "blueMid", 1.3, 0.00035, S2, np.concatenate(pts), coll, cache_dir, cam)
    _hud_text("XR_hud_label", "VOCAL FOLDS", 0.04 * half, "blue", 1.3, (cx, cy - 1.62 * R, D), cam, coll, font)

    with open(track_path, encoding="utf-8") as fh:
        d = json.load(fh)
    notes = d["notes"]
    fr = lambda t: int(round(t * fps)) + 1
    for i, n in enumerate(notes):
        m = int(round(n["midi"]))
        hz = 440.0 * 2 ** ((n["midi"] - 69) / 12)
        ob = _hud_text(f"XR_hud_f0_{i:03d}", f"{hz:.0f} HZ  {NOTE_NAMES[m % 12]}{m // 12 - 1}", 0.05 * half,
                       "white", 1.2, (cx, cy + 1.5 * R, D), cam, coll, font)
        last = fr(n["t1"])
        if i + 1 < len(notes):
            last = min(last, fr(notes[i + 1]["t0"]) - 1)      # never two readouts at once
        _visible_between(ob, fr(n["t0"]), max(fr(n["t0"]), last))
    # rejoin the planner's syllables into the lyric's words
    letters = lambda x: re.sub(r"[^a-z]", "", x.lower())
    words, k = [], 0
    for w in re.findall(r"[A-Za-z']+", d.get("lyrics", "")):
        if k >= len(notes):
            break
        t0, t1, acc = notes[k]["t0"], notes[k]["t1"], letters(notes[k]["syl"])
        k += 1
        while k < len(notes) and len(acc) < len(letters(w)) and (notes[k]["syl"] == "~" or letters(w).startswith(acc + letters(notes[k]["syl"]))):
            acc += letters(notes[k]["syl"])
            t1 = notes[k]["t1"]
            k += 1
        words.append((w.upper(), t0, t1))
    for i, (w, t0, t1) in enumerate(words):
        ob = _hud_text(f"XR_hud_word_{i:03d}", w, word_size, "amber", 1.9, (word_at[0], word_at[1], D), cam, coll, font)
        last = fr(t1 + 0.12)
        if i + 1 < len(words):
            last = min(last, fr(words[i + 1][1]) - 1)         # a word leaves when the next arrives
        _visible_between(ob, fr(t0), max(fr(t0), last))
    log.append(f"hud: fold stroboscope, {len(notes)} pitch readouts, {len(words)} lyric words"
               + (f"; sphincter inset, {len(farts['events'])} fart readouts, sound panels for gas and voice" if farts else ""))


# --------------------------------------------------------------------------------------------
# check: is the added anatomy inside him, in motion?
# --------------------------------------------------------------------------------------------
def _sphere_dirs(n=40):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return [Vector(v) for v in np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1).tolist()]


def inside_check(scene, names, count, log):
    """Is every point of the added anatomy enclosed by his skin, in motion? A point counts as
    inside when rays cast from it in (nearly) every direction hit his skin (the body and the head;
    his clothes do not count, they are outside it); the depth is the distance to the nearest skin."""
    body = [o for o in (role_mesh("skin"), bpy.data.objects[bayc_sing.CFG["head_mesh"]]) if o]
    if len(body) < 2:                                # no separate skin: the clothes are the surface
        body = [o for o in (bpy.data.objects[bayc_sing.CFG["head_mesh"]], role_mesh("clothes")) if o]
    anat = [bpy.data.objects[n] for n in names]
    off = [m for o in body + anat for m in o.modifiers if m.name in ("XR_wire", "XR_unsubdiv", "XR_tubes") and m.show_viewport]
    for m in off:
        m.show_viewport = False
    dirs = _sphere_dirs()
    worst = {n: (1e9, 0, 0, 0) for n in names}       # min depth cm, frame, outside, total
    try:
        for fnum in np.linspace(scene.frame_start, scene.frame_end, count).round().astype(int).tolist():
            scene.frame_set(fnum)
            dg = bpy.context.evaluated_depsgraph_get()
            verts, polys, base = [], [], 0
            for o in body:
                ev = o.evaluated_get(dg)
                me = ev.to_mesh()
                co = np.empty(len(me.vertices) * 3, np.float32)
                me.vertices.foreach_get("co", co)
                co = co.reshape(-1, 3).astype(np.float64)
                mw = np.array(ev.matrix_world)
                verts.append(co @ mw[:3, :3].T + mw[:3, 3])
                polys += [tuple(i + base for i in p.vertices) for p in me.polygons]
                base += len(co)
                ev.to_mesh_clear()
            bvh = BVHTree.FromPolygons([Vector(v) for v in np.concatenate(verts).tolist()], polys)
            for o in anat:
                ev = o.evaluated_get(dg)
                me = ev.to_mesh()
                mw = ev.matrix_world
                depth, outside = [], 0
                for v in me.vertices:
                    p = mw @ v.co
                    hits = [h[3] for h in (bvh.ray_cast(p, d, 3.0) for d in dirs) if h[0] is not None]
                    near = bvh.find_nearest(p)[3] * 100.0       # cm to the nearest surface
                    if len(hits) >= 0.9 * len(dirs):
                        depth.append(near)
                    else:
                        depth.append(-near)
                        outside += 1
                ev.to_mesh_clear()
                w = worst[o.name]
                worst[o.name] = (min(w[0], min(depth)), fnum if min(depth) < w[0] else w[1], w[2] + outside, w[3] + len(depth))
    finally:
        for m in off:
            m.show_viewport = True
        scene.frame_set(scene.frame_start)
    for n, (dmin, fnum, outside, total) in worst.items():
        log.append(f"inside check {n}: {total - outside}/{total} points inside over {count} frames, shallowest {dmin:.2f} cm under the skin (frame {fnum})")
    return worst


# --------------------------------------------------------------------------------------------
def apply(geom_path, track_path, cache_dir, cfg_over=None, farts=None, voice_wav=None):
    """farts: the info dict fartsynth.build() returns (a song with a fart part), voice_wav: the
    voice on its own; with them the digestive system and the two sound panels are added."""
    XCFG["armature"] = bayc_sing.CFG["armature"]
    XCFG.update((bayc_sing.CFG.get("_profile") or {}).get("xray") or {})
    if cfg_over:
        XCFG.update(cfg_over)
    cfg = dict(XCFG)
    if farts:                                   # he is smaller in frame: draw the lines a little thicker
        cfg["tube"] = XCFG["tube"] * XCFG["fart_line_scale"]
    log = []
    scene = bpy.context.scene
    nF = scene.frame_end - scene.frame_start + 1
    fps = scene.render.fps
    with open(geom_path, encoding="utf-8") as fh:
        geom = json.load(fh)
    if not cfg["voice"]:
        # a farts-only song: the voice track only set the timing; nothing sounds in his throat
        for f in geom["frames"]:
            if f:
                f["outRms"], f["voicing"], f["gScope"] = 0.0, 0.0, [0.0] * len(f.get("gScope") or [0.0])
        voice_wav = None
    os.makedirs(cache_dir, exist_ok=True)
    for old in glob.glob(os.path.join(cache_dir, "XR_*.pc2")):
        os.remove(old)
    arm = bpy.data.objects[cfg["armature"]]
    ref = bpy.data.objects[bayc_sing.CFG["head_mesh"]]
    coll = bpy.data.collections.get("XRay_Anatomy") or bpy.data.collections.new("XRay_Anatomy")
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    for ob in list(coll.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    fit = BodyFit(log)
    skin = SkinSource()
    specs = build_structures(geom, fit, cfg, nF, fps, track_path, log)
    fz = None
    if farts:
        fz = bayc_sing.fart_signals(farts, nF, fps)
        if fit.belly:
            specs.update(build_gut(fit, farts, cfg, nF, fps, arm, log))
        else:
            log.append("gut: no belly found under the clothes; digestive system skipped")
    for name, spec in specs.items():
        ob, mat = make_object(name, spec, coll, cache_dir, ref, arm, skin)
        if name == "XR_throat":
            animate_sound_glow(mat, geom, nF)
        elif "glow" in spec:                    # the exit lights up while it sounds
            animate_glow(mat, spec["glow"], f"XR_Glow_{name}", 0.5, 4.0)
    style_ape(arm, log, wire=XCFG["body_wire"] * (XCFG["fart_line_scale"] if farts else 1.0))
    setup_look(scene, log)
    orbit_camera(scene, nF, fps, track_path, cfg, fz)
    hud(scene, geom, track_path, nF, fps, cache_dir, log, farts, voice_wav, voice=cfg["voice"])
    if cfg["check_frames"]:
        inside_check(scene, [n for n, s in specs.items() if s.get("skin", True)], cfg["check_frames"], log)
    return log
