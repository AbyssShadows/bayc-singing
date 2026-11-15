"""Build the installable add-on zip: python tools/make_zip.py  ->  dist/ape_synth-<version>.zip

Blender installs it with Edit > Preferences > Add-ons > (v menu) > Install from Disk.
"""
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ape_synth")
with open(os.path.join(SRC, "blender_manifest.toml"), encoding="utf-8") as fh:
    version = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M).group(1)
os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
out = os.path.join(ROOT, "dist", f"ape_synth-{version}.zip")
n = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for base, dirs, files in os.walk(SRC):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not d.startswith("."))
        for f in sorted(files):
            if f.endswith(".pyc") or f.startswith("."):
                continue
            path = os.path.join(base, f)
            z.write(path, os.path.relpath(path, SRC))
            n += 1
print(f"{out}: {n} files, {os.path.getsize(out) / 1e6:.1f} MB")
