"""Create entirely synthetic npm-shaped artifacts. No package code is executed."""
from pathlib import Path
import gzip
import io
import json
import tarfile

root = Path(__file__).resolve().parents[1]
out = root / "dist" / "demo"
out.mkdir(parents=True, exist_ok=True)
for name, version, script, extra in [
    ("before.tgz", "1.0.0", {}, {}),
    ("after.tgz", "1.1.0", {"postinstall": "node setup.js"},
     {"index.js.map": b'{"version":3,"sources":["example.ts"],"mappings":""}'}),
]:
    manifest = {"name": "packdelta-example", "version": version, "license": "MIT",
                "main": "index.js", "scripts": script}
    files = {"package.json": json.dumps(manifest).encode(), "index.js": b"module.exports = 42;\n", **extra}
    if script:
        files["setup.js"] = b"console.log('Synthetic example; not executed by PackDelta');\n"
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for relative, data in sorted(files.items()):
            info = tarfile.TarInfo("package/" + relative)
            info.size = len(data); info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    (out / name).write_bytes(gzip.compress(raw.getvalue(), mtime=0))
print("Created dist/demo/before.tgz and dist/demo/after.tgz")
