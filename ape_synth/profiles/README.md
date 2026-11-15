# Character profiles

A profile tells the add-on which bones, meshes and shape keys of a character do which job. The
build picks the best match automatically (panel: Character > Auto-detect), or you choose one.

| profile | for | status |
| --- | --- | --- |
| `bayc.json` | 3D Bored Apes rigged with Advanced Skeleton (meshes named `BAYC_<Trait>_<Variant>_GEO`) | tested |
| `jnkyz.json` | Jnkyz characters with the same rig and face shapes | draft: send a model to finish it |
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
- **extra_bones**: jiggle bones the build adds, parented to `Head` (armature-space coordinates):
  `Hat_Jiggle` for the hat hop, and `Ear_L` / `Ear_R` for floppy ears. Leave it empty if they don't fit.
- **ear_weights**: the region of the head mesh that the ear bones take over.
- **xray**: overrides for the X-ray look's anatomy (see `XCFG` in `engine/bayc_xray.py`).

## What the engine needs

- **Bones:** `Hips Spine Spine1 Spine2 Neck Head`, plus `Shoulder Arm ForeArm Hand UpLeg Leg Foot`
  on both sides (`Left…` / `Right…`). These are the Advanced Skeleton and Mixamo names. The
  armature should be Y-up, like a Maya or Mixamo export (rotated 90° on X in Blender).
- **Face shape keys:** `jawOpen mouthClose mouthFunnel mouthPucker` for the lip sync. These help
  more: `fff_M tth_M rrr_M sss_M ssh_M` (visemes), `lntd_M gk_M eh_M` (for the tongue), and the
  ARKit brow, eye, smile, cheek and nose keys.

"Check my character" in the panel lists what's found and what's missing.
