"""Character profiles: which bones, meshes and shape keys of a character do which job.

A profile is a JSON file in ../profiles/. resolve() picks one (or takes the one asked for), and in
the build's own copy of the file renames bones and shape keys to the names the engine uses (for
example strips a "mixamorig:" prefix), finds the meshes for each role, and writes the result into
bayc_sing.CFG. report() does the same without changing anything (the panel's "Check" button).
"""
import glob
import json
import math
import os

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(ROOT, "profiles")

# the dance, the physics and the leg IK need these (Advanced Skeleton / Mixamo names)
REQUIRED_BONES = ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head"] + [
    f"{s}{b}" for s in ("Left", "Right") for b in ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot")]
# without these four there is no lip sync; the rest of FACE_KEYS only add expression
FACE_CORE = ["jawOpen", "mouthClose", "mouthFunnel", "mouthPucker"]
ROLES = ("head", "mouth", "hat", "skin", "clothes", "eyes")


def load_profiles():
    out = {}
    for path in sorted(glob.glob(os.path.join(PROFILE_DIR, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            p = json.load(fh)
        out[p["id"]] = p
    return out


def _armature():
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    if not arms:
        return None
    def deforms(a):
        return sum(1 for o in bpy.context.scene.objects if o.type == 'MESH'
                   and any(m.type == 'ARMATURE' and m.object == a for m in o.modifiers))
    return max(arms, key=lambda a: (deforms(a), len(a.data.bones)))


def _meshes(arm):
    """the character's meshes: deformed by (or parented to) the armature"""
    out = []
    for o in bpy.context.scene.objects:
        if o.type != 'MESH' or o.name.startswith(("XR_", "Fart_")):
            continue
        if arm and (o.parent == arm or any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)):
            out.append(o)
    return out


def _canon(name, prof):
    pre = prof.get("bone_prefix") or ""
    if pre and name.startswith(pre):
        name = name[len(pre):]
    return (prof.get("rename_bones") or {}).get(name, name)


def _keys(ob):
    sk = ob.data.shape_keys
    return [k.name for k in sk.key_blocks] if sk else []


def _score(prof, arm, meshes):
    m = prof.get("match", {})
    names = [o.name for o in meshes]
    s = sum(3 for kw in m.get("mesh_name_contains", []) if any(kw in n for n in names))
    if arm:
        bones = set(arm.data.bones.keys())
        s += sum(1 for b in m.get("bones", []) if b in bones)
        # what counts most: how many of the bones the dance needs exist after this profile's renames
        canon = {_canon(b, prof) for b in bones}
        s += 2 * sum(1 for b in REQUIRED_BONES if b in canon)
    return s


def pick_profile(pid, arm, meshes):
    profs = load_profiles()
    if pid and pid != "auto":
        if pid not in profs:
            raise RuntimeError(f"no character profile '{pid}' (have: {', '.join(profs)})")
        return profs[pid]
    best = max(profs.values(), key=lambda p: (_score(p, arm, meshes), p["id"] == "bayc"))
    return best


def _find(role, prof, meshes, taken):
    for kw in (prof.get("meshes") or {}).get(role, []):
        for o in meshes:
            if kw in o.name and o.name not in taken:
                return o
    return None


def _resolve_meshes(prof, meshes, rename):
    """role -> mesh; `rename` maps a shape key name to the engine's (applied or not)"""
    canon = lambda ob: [rename.get(k, k) for k in _keys(ob)]
    found, taken = {}, set()
    for role in ("head", "mouth"):
        o = _find(role, prof, meshes, taken)
        if o is not None and "jawOpen" in canon(o):
            found[role] = o
            taken.add(o.name)
    # generic: the face is the mesh with a jawOpen key and the most keys; a second one is the mouth
    talkers = sorted((o for o in meshes if "jawOpen" in canon(o) and o.name not in taken),
                     key=lambda o: -len(_keys(o)))
    if "head" not in found and talkers:
        found["head"] = talkers.pop(0)
        taken.add(found["head"].name)
    if "mouth" not in found and talkers:
        found["mouth"] = talkers.pop(0)
        taken.add(found["mouth"].name)
    for role in ("hat", "skin", "clothes", "eyes"):
        o = _find(role, prof, meshes, taken)
        if o is not None:
            found[role] = o
            taken.add(o.name)
    return found


def analyse(profile="auto"):
    """what resolve() would find and do, without changing anything"""
    arm = _armature()
    meshes = _meshes(arm)
    rep = {"ok": False, "errors": [], "warnings": [], "renamed_bones": 0, "renamed_keys": 0}
    if arm is None:
        rep["errors"].append("no armature in the scene")
        return rep, None, None, {}
    prof = pick_profile(profile, arm, meshes)
    rep["profile"], rep["profile_name"], rep["profile_status"] = prof["id"], prof["name"], prof.get("status", "")
    rep["armature"] = arm.name
    bones = {b.name: _canon(b.name, prof) for b in arm.data.bones}
    rep["renamed_bones"] = sum(1 for a, b in bones.items() if a != b)
    have = set(bones.values())
    rep["missing_bones"] = [b for b in REQUIRED_BONES if b not in have]
    if rep["missing_bones"]:
        rep["errors"].append("the armature lacks bones the dance needs: " + ", ".join(rep["missing_bones"])
                             + " (Advanced Skeleton or Mixamo names; a profile can rename them)")
    rename = prof.get("rename_shape_keys") or {}
    found = _resolve_meshes(prof, meshes, rename)
    for role in ROLES:
        rep[role] = found[role].name if role in found else None
    if "head" not in found:
        rep["errors"].append("no face mesh: none of his meshes has a 'jawOpen' shape key")
    else:
        keys = set(rename.get(k, k) for o in (found.get("head"), found.get("mouth")) if o for k in _keys(o))
        rep["renamed_keys"] = sum(1 for o in found.values() for k in _keys(o) if k in rename)
        import bayc_sing
        rep["missing_face"] = [k for k in bayc_sing.FACE_KEYS if k not in keys and not k.startswith("Tongue_")]
        core = [k for k in FACE_CORE if k not in keys]
        if core:
            rep["errors"].append("the face lacks the lip-sync shape keys " + ", ".join(core))
        elif rep["missing_face"]:
            rep["warnings"].append(f"{len(rep['missing_face'])} expression keys missing (he still sings): "
                                   + ", ".join(rep["missing_face"][:8]) + ("..." if len(rep["missing_face"]) > 8 else ""))
    if "mouth" not in found:
        rep["warnings"].append("no separate mouth mesh: no tongue articulation, and the X-ray look shows no tongue/teeth")
    if "hat" not in found:
        rep["warnings"].append("no hat found: no hat hop (fine if he has none)")
    if "skin" not in found:
        rep["warnings"].append("no body/fur mesh found: the X-ray look fits its anatomy to the clothes instead")
    if not any(o.type == 'LIGHT' for o in bpy.context.scene.objects):
        rep["warnings"].append("no lights in the scene: the build adds a three-light studio")
    rep["ok"] = not rep["errors"]
    return rep, arm, prof, found


def resolve(profile="auto", log=None):
    """pick the profile, rename (in this file: the build's copy), set bayc_sing.CFG; -> report"""
    import bayc_sing
    rep, arm, prof, _ = analyse(profile)
    log = log if log is not None else []
    if not rep["ok"]:
        return rep
    n_b = 0
    for b in arm.data.bones:
        new = _canon(b.name, prof)
        if new != b.name:
            b.name = new                      # Blender renames the vertex groups and the animation paths with it
            n_b += 1
    rename = prof.get("rename_shape_keys") or {}
    n_k = 0
    if rename:
        for o in _meshes(arm):
            sk = o.data.shape_keys
            for k in (sk.key_blocks if sk else []):
                if k.name in rename and rename[k.name] not in sk.key_blocks:
                    k.name = rename[k.name]
                    n_k += 1
    found = _resolve_meshes(prof, _meshes(arm), {})
    bayc_sing.CFG.update({
        "armature": arm.name, "_profile": prof,
        **{f"{role}_mesh": (found[role].name if role in found else None) for role in ROLES},
    })
    log.append(f"character: profile '{prof['id']}' ({prof.get('status', '')}); armature {arm.name}; "
               + ", ".join(f"{r} {found[r].name}" for r in ROLES if r in found)
               + (f"; renamed {n_b} bones" if n_b else "") + (f", {n_k} shape keys" if n_k else ""))
    for w in rep["warnings"]:
        log.append("note: " + w)
    return rep


def report_lines(rep):
    """a few short lines for the panel and the command line"""
    lines = []
    if rep.get("profile"):
        lines.append(f"Profile: {rep['profile_name']} [{rep['profile_status']}]")
    for role in ("armature",) + ROLES:
        if role in rep:
            lines.append(f"{role.capitalize()}: {rep[role] or '-'}")
    if rep.get("renamed_bones") or rep.get("renamed_keys"):
        lines.append(f"Will rename {rep['renamed_bones']} bones, {rep['renamed_keys']} shape keys (in the build's copy only)")
    lines += ["ERROR: " + e for e in rep["errors"]] + ["Note: " + w for w in rep["warnings"]]
    lines.append("Ready to sing." if rep["ok"] else "Not ready: see the errors above.")
    return lines


def ensure_lights(log):
    """a scene without lights gets a soft three-light studio aimed at his chest (and a world)"""
    sc = bpy.context.scene
    if sc.world is None:
        w = bpy.data.worlds.new("BAYC_World")
        w.use_nodes = True
        bg = next((n for n in w.node_tree.nodes if n.type == "BACKGROUND"), None)
        if bg:
            bg.inputs["Color"].default_value = (0.05, 0.05, 0.05, 1.0)
            bg.inputs["Strength"].default_value = 1.5
        sc.world = w
        log.append("added a dark grey world")
    if any(o.type == 'LIGHT' for o in sc.objects):
        return
    coll = bpy.data.collections.get("Lights") or bpy.data.collections.new("Lights")
    if coll.name not in sc.collection.children:
        sc.collection.children.link(coll)
    aim = Vector((0.0, 0.0, 1.3))
    for name, energy, loc in (("Key", 160.0, (0.95, -1.22, 3.1)), ("Rim", 130.0, (-0.37, 0.85, 2.73)),
                              ("Back", 60.0, (-1.1, 0.98, 1.41))):
        L = bpy.data.lights.new(name, 'SPOT')
        L.energy = energy
        L.spot_size = math.radians(55)
        L.spot_blend = 0.6
        L.shadow_soft_size = 0.35
        ob = bpy.data.objects.new(name, L)
        ob.location = loc
        ob.rotation_mode = 'QUATERNION'
        ob.rotation_quaternion = (aim - Vector(loc)).to_track_quat('-Z', 'Y')
        ob.rotation_mode = 'XYZ'
        coll.objects.link(ob)
    log.append("added a three-light studio (Key, Rim, Back)")
