# Character profiles

A profile tells the add-on which bones, meshes and shape keys of a character do which job. The
build picks the best match automatically (panel: Character > Auto-detect), or you choose one.

| profile | for | status |
| --- | --- | --- |
| `bayc.json` | 3D Bored Apes rigged with Advanced Skeleton (meshes named `BAYC_<Trait>_<Variant>_GEO`) | tested |
| `jnkyz.json` | 3D Jnkyz (Mixamo-style bones, one body+face mesh with ARKit keys, separate mouth) | tested on Wade |
| `mixamo_arkit.json` | Mixamo bodies (`mixamorig:` bones) with ARKit + Oculus viseme faces | experimental |

## What a profile holds

```json
{
  "id": "my_character",
  "name": "My character",
  "status": "draft",
  "match": {"mesh_name_contains": ["MYCHAR_"], "bones": ["Hips", "Head"]},
  "bone_prefix": "mixamorig:",
  "rename_bones": {"Spine3": "Spine2"},
  "rename_shape_keys": {"viseme_FF": "fff_M"},
  "meshes": {"head": ["_Head_"], "mouth": ["_Mouth_"], "hat": ["_Hat_"], "skin": ["_Body_"],
             "clothes": ["_Clothes_"], "eyes": ["_Eyes_"], "backdrop": ["Background"]},
  "extra_bones": {"Hat_Jiggle": {"head": [0, 191.5, 3], "tail": [0, 201.5, 3]}},
  "ear_weights": {"x": [9.8, 12.6], "y_in": [177.5, 180.5], "y_out": [193.5, 195.5]},
  "xray": {"larynx_y": 161.6}
}
```

- **match**: how auto-detect recognizes the character. Mesh-name keywords score 3 each and bone
  names 1 each. What weighs most is how many of the bones the dance needs exist after the renames.
- **bone_prefix / rename_bones / rename_shape_keys**: renames to the names the engine uses. They
  happen only in the build's copy of your file.
- **meshes**: name keywords for each role. The first match wins. If none matches, the face is the
  mesh with a `jawOpen` shape key and the most keys, and a second such mesh is the mouth.
  `"skin": ["@head"]` means the face mesh is also the whole body (as on a Jnkyz). Without a keyword
  match, the eyes are the mesh skinned only to eye bones, and with `"hat_fallback": "top_head_only"`
  the hat is the highest mesh skinned only to `Head`.
- **derive_shape_keys**: face shapes the rig lacks, mixed from the ones it has, e.g.
  `"fff_M": {"mouthRollLower": 1.6, "mouthUpperUpLeft": 0.3, "mouthUpperUpRight": 0.3}` makes an F
  mouth out of ARKit keys. Made in the build's copy only.
- **extra_bones**: jiggle bones the build adds, parented to `Head` (armature-space coordinates):
  `Hat_Jiggle` for the hat hop, and `Ear_L` / `Ear_R` for floppy ears. Leave it empty if they don't fit.
- **ear_weights**: the region of the head mesh that the ear bones take over.
- **hat_weights**: for a soft hat (a beanie): `{"near": 1.6, "far": 4.5}` puts only the parts of the
  hat more than `near` cm from the head on `Hat_Jiggle` (fully beyond `far`), so the rim stays on.
- **jiggle**: per-bone spring overrides `[Hz, damping, gravity, max degrees, drag]` (see `JIGGLE`
  in `engine/bayc_sing.py`).
- **base_pose**: a resting stance on top of the rest pose, in degrees of armature-space rotation
  `[x, y, z]` per bone, e.g. arms down from an A-pose: `{"LeftArm": [0, 0, -30], "RightArm": [0, 0, 30]}`.
- **tongue_sculpt**: without tongue visemes (`lntd_M gk_M eh_M`), tip-up and pull-back tongue
  shapes are sculpted on the mouth mesh's own tongue; `tip_rise_cm` and `pull_back_cm` size them.
- **cfg**: the character's own engine tuning (keys of `CFG` in `engine/bayc_sing.py`), e.g.
  `{"jaw_gain": 1.35, "hat_hop_beat": 0.0, "bend_deg": 45}`. `--cfg` on the command line still wins.
- **xray**: overrides for the X-ray look's anatomy (see `XCFG` in `engine/bayc_xray.py`), in rig cm:
  the larynx and trachea heights, the lungs, where the neck is measured (`neck_scan`, `neck_r`,
  `cz_clip_lo`), where the esophagus leaves the neck and how far back it runs (`esophagus_y`,
  `esophagus_back_cm`), the exit height (`gut_exit_drop`), and `gut_clamp_cm`, which fits the
  whole gut into a slim body with that much margin. Every X-ray build checks that the organs stay
  inside the skin and prints a warning if they don't.

The camera and the studio lights follow the character's head height automatically (`cam_dz`).

## What the engine needs

- **Bones:** `Hips Spine Spine1 Spine2 Neck Head`, plus `Shoulder Arm ForeArm Hand UpLeg Leg Foot`
  on both sides (`Left…` / `Right…`). These are the Advanced Skeleton and Mixamo names. The
  armature should be Y-up, like a Maya or Mixamo export (rotated 90° on X in Blender).
- **Face shape keys:** `jawOpen mouthClose mouthFunnel mouthPucker` for the lip sync. These help
  more: `fff_M tth_M rrr_M sss_M ssh_M` (visemes; a profile can mix them from ARKit keys),
  `lntd_M gk_M eh_M` (for the tongue; sculpted if missing), and the ARKit brow, eye, smile, cheek
  and nose keys. A plain ARKit face (52 keys + `tongueOut`) is enough.

"Check my character" in the panel lists what's found and what's missing.
