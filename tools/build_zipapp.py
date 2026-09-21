"""Build a deterministic, dependency-free Python zipapp from the source tree."""

from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
out = root / "dist" / "packdelta.pyz"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
    items = [("__main__.py", b"from packdelta.cli import main\nraise SystemExit(main())\n")]
    items += [
        (p.relative_to(root).as_posix(), p.read_bytes())
        for p in sorted((root / "packdelta").glob("*.py"))
    ]
    for name, data in items:
        info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, data)
print("Built dist/packdelta.pyz")
