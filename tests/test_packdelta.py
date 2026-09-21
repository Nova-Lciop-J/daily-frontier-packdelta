from __future__ import annotations
import contextlib
import gzip
import hashlib
import io
import json
import random
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from packdelta.cli import main
from packdelta.core import InputError, Limits, compare, load_snapshot

ROOT = Path(__file__).resolve().parents[1]


def blob(files=None, manifest=None, members=None, mtime=0):
    manifest = manifest if manifest is not None else {"name": "example-package", "version": "1.0.0"}
    source = {"package/package.json": json.dumps(manifest).encode(), **(files or {})}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in source.items():
            item = tarfile.TarInfo(name); item.size = len(data); item.mode = 0o644
            archive.addfile(item, io.BytesIO(data))
        for item, data in members or []:
            archive.addfile(item, io.BytesIO(data) if data else None)
    return gzip.compress(output.getvalue(), mtime=mtime)


class PackDeltaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seq = 0

    def write(self, data):
        self.seq += 1
        path = self.root / f"sample-{self.seq}.tgz"
        path.write_bytes(data)
        return path

    def snap(self, files=None, manifest=None, **kwargs):
        return load_snapshot(self.write(blob(files, manifest, **kwargs)))

    def rules(self, report):
        return {f["rule"] for f in report["findings"]}

    def test_identical(self):
        a = self.snap(); r = compare(a, a)
        self.assertEqual(r["files"], {"added": [], "removed": [], "changed": []})
        self.assertEqual(r["findings"], [])

    def test_add_remove_change(self):
        a = self.snap({"package/a.txt": b"a", "package/c.txt": b"x"})
        b = self.snap({"package/b.txt": b"b", "package/c.txt": b"y"})
        r = compare(a, b)
        self.assertEqual(r["files"]["added"], ["package/b.txt"])
        self.assertEqual(r["files"]["removed"], ["package/a.txt"])
        self.assertEqual(r["files"]["changed"], ["package/c.txt"])

    def test_compressed_hash_is_bound(self):
        data = blob(); s = load_snapshot(self.write(data))
        self.assertEqual(s.archive_sha256, hashlib.sha256(data).hexdigest())

    def test_compression_metadata_not_payload(self):
        a = self.snap(mtime=1); b = self.snap(mtime=2)
        self.assertNotEqual(a.archive_sha256, b.archive_sha256)
        self.assertEqual(compare(a, b)["summary"]["changed"], 0)

    def test_script_values_omitted(self):
        marker = "DO_NOT_PRINT_SYNTHETIC_SCRIPT"
        b = self.snap(manifest={"name": "example-package", "version": "1.1.0",
                               "scripts": {"postinstall": marker}})
        r = compare(self.snap(), b)
        self.assertIn("script-change", self.rules(r))
        self.assertNotIn(marker, json.dumps(r))
        self.assertEqual(r["findings"][0]["level"], "high")

    def test_removed_hook_is_review(self):
        a = self.snap(manifest={"name": "example-package", "version": "1.0.0",
                               "scripts": {"postinstall": "echo example"}})
        b = self.snap(manifest={"name": "example-package", "version": "1.1.0"})
        self.assertEqual(compare(a, b)["findings"][0]["level"], "review")

    def test_dependency_change(self):
        b = self.snap(manifest={"name": "example-package", "version": "1.1.0",
                               "dependencies": {"example-dependency": "^1.0.0"}})
        r = compare(self.snap(), b)
        self.assertIn("dependency-change", self.rules(r))
        self.assertNotIn("^1.0.0", json.dumps(r))

    def test_runtime_entry_change(self):
        b = self.snap(manifest={"name": "example-package", "version": "1.1.0", "exports": "./b.js"})
        self.assertIn("entry-point-change", self.rules(compare(self.snap(), b)))

    def test_license_change(self):
        b = self.snap(manifest={"name": "example-package", "version": "1.1.0", "license": "MIT"})
        self.assertIn("license-change", self.rules(compare(self.snap(), b)))

    def test_identity_change(self):
        b = self.snap(manifest={"name": "another-example", "version": "1.1.0"})
        self.assertIn("package-name-change", self.rules(compare(self.snap(), b)))

    def test_same_version_change(self):
        self.assertIn("same-version-payload-change", self.rules(compare(self.snap(), self.snap({"package/a": b"a"}))))

    def test_sensitive_unchanged(self):
        a = self.snap({"package/.env.example": b"MODE=example\n"})
        self.assertIn("sensitive-filename", self.rules(compare(a, a)))

    def test_source_map_and_binary_and_bundle(self):
        b = self.snap({"package/a.js.map": b"{}", "package/a.node": b"example",
                       "package/node_modules/example/a": b"example"})
        self.assertTrue({"source-map", "binary-payload", "bundled-dependency"} <= self.rules(compare(self.snap(), b)))

    def test_executable_mode(self):
        item = tarfile.TarInfo("package/run.sh"); item.mode = 0o755; item.size = 4
        b = self.snap(members=[(item, b"test")])
        self.assertIn("executable-bit", self.rules(compare(self.snap(), b)))

    def test_special_permission(self):
        item = tarfile.TarInfo("package/run.sh"); item.mode = 0o4755; item.size = 4
        b = self.snap(members=[(item, b"test")])
        self.assertIn("special-permission", self.rules(compare(self.snap(), b)))

    def test_unchanged_special_permission_still_flagged(self):
        item = tarfile.TarInfo("package/run.sh"); item.mode = 0o4755; item.size = 4
        a = self.snap(members=[(item, b"test")])
        self.assertIn("special-permission", self.rules(compare(a, a)))

    def test_explicit_null_entry_is_a_change(self):
        b = self.snap(manifest={"name": "example-package", "version": "1.1.0", "exports": None})
        self.assertIn("entry-point-change", self.rules(compare(self.snap(), b)))

    def test_traversal_absolute_backslash_and_control(self):
        for name in ("../outside", "/package/a", "package/../outside", "package//a", "package/./a",
                     "package/dir\\a", "package/bad\x1bname", "other/a"):
            with self.subTest(name=repr(name)), self.assertRaises(InputError):
                self.snap({name: b"example"})
        self.assertEqual(len(list(self.root.glob('*'))), 8)

    def test_long_name(self):
        with self.assertRaises(InputError):
            self.snap({"package/" + "a" * 513: b"x"})

    def test_duplicate_member(self):
        item = tarfile.TarInfo("package/package.json"); item.size = 2
        with self.assertRaises(InputError):
            self.snap(members=[(item, b"{}")])

    def test_links_and_special_types(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE):
            item = tarfile.TarInfo("package/special"); item.type = kind; item.linkname = "example"
            with self.subTest(kind=kind), self.assertRaises(InputError):
                self.snap(members=[(item, b"")])

    def test_directory_is_allowed(self):
        item = tarfile.TarInfo("package/docs/"); item.type = tarfile.DIRTYPE
        b = self.snap(members=[(item, b"")])
        self.assertEqual(len(b.entries), 1)

    def test_missing_manifest(self):
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w") as archive:
            item = tarfile.TarInfo("package/readme"); archive.addfile(item)
        with self.assertRaises(InputError):
            load_snapshot(self.write(gzip.compress(out.getvalue())))

    def test_invalid_manifest_types(self):
        manifests = [[], {"name": "x"}, {"name": "x", "version": 1},
                     {"name": "x", "version": "1", "scripts": []},
                     {"name": "x", "version": "1", "dependencies": {"a": 1}}]
        for m in manifests:
            with self.subTest(m=m), self.assertRaises(InputError):
                self.snap(manifest=m)

    def test_duplicate_json(self):
        with self.assertRaises(InputError):
            self.snap({"package/package.json": b'{"name":"a","name":"b","version":"1"}'})

    def test_nonfinite_json(self):
        with self.assertRaises(InputError):
            self.snap({"package/package.json": b'{"name":"a","version":"1","x":NaN}'})

    def test_invalid_unicode(self):
        with self.assertRaises(InputError):
            self.snap({"package/package.json": b'\xff'})

    def test_corrupt_and_empty_and_truncated_inputs(self):
        for data in (b"", b"not gzip", blob()[:20], blob()[:-8], b"\x1f\x8b" + b"bad" * 20):
            with self.subTest(size=len(data)), self.assertRaises(InputError):
                load_snapshot(self.write(data))

    def test_bad_crc(self):
        data = bytearray(blob()); data[-8] ^= 1
        with self.assertRaises(InputError):
            load_snapshot(self.write(data))

    def test_all_size_limits(self):
        cases = [Limits(compressed_bytes=1), Limits(expanded_bytes=1024), Limits(file_bytes=1),
                 Limits(total_file_bytes=1), Limits(manifest_bytes=1), Limits(members=0)]
        for limits in cases:
            with self.subTest(limits=limits), self.assertRaises(InputError):
                load_snapshot(self.write(blob()), limits)

    def test_gzip_bomb_is_bounded(self):
        data = gzip.compress(b"\0" * 100000)
        with self.assertRaises(InputError):
            load_snapshot(self.write(data), Limits(expanded_bytes=4096))

    def test_deterministic_report(self):
        a = self.snap(); b = self.snap({"package/z": b"z", "package/a": b"a"})
        self.assertEqual(json.dumps(compare(a, b)), json.dumps(compare(a, b)))

    def test_random_plain_payloads(self):
        rng = random.Random(17)
        for _ in range(50):
            data = rng.randbytes(rng.randrange(0, 1024))
            a = self.snap({"package/data.bin": data})
            self.assertEqual(a.entries["package/data.bin"].sha256, hashlib.sha256(data).hexdigest())

    def test_cli_findings_and_never_exit_codes(self):
        a = self.write(blob()); b = self.write(blob({"package/new.map": b"{}"}))
        for mode, code in [("review", 1), ("high", 0), ("change", 1), ("never", 0)]:
            with self.subTest(mode=mode), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(a), str(b), "--fail-on", mode]), code)

    def test_cli_json_is_parseable(self):
        a = self.write(blob()); output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main([str(a), str(a), "--format", "json"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["schema_version"], 1)

    def test_cli_error_is_value_free_even_with_never(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            result = main([str(self.root / "private-example-input"), "also-missing", "--fail-on", "never"])
        self.assertEqual(result, 2)
        self.assertNotIn("private-example-input", output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue())

    def test_cli_escapes_untrusted_keys(self):
        b = self.write(blob(manifest={"name": "example-package", "version": "2.0.0",
                                     "scripts": {"test\x1b[31m": "example"}}))
        a = self.write(blob()); output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main([str(a), str(b)])
        self.assertNotIn("\x1b", output.getvalue())
        self.assertIn("\\u001b", output.getvalue())

    def test_real_cli_process(self):
        a = self.write(blob()); b = self.write(blob({"package/a.map": b"{}"}))
        proc = subprocess.run([sys.executable, "-m", "packdelta", str(a), str(b), "--format", "json"],
                              cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("source-map", self.rules(json.loads(proc.stdout)))
        self.assertEqual(proc.stderr, "")

    def test_zipapp_reproducible_and_portable(self):
        run = lambda: subprocess.run([sys.executable, "tools/build_zipapp.py"], cwd=ROOT,
                                     capture_output=True, text=True, check=True, timeout=20)
        run(); first = (ROOT / "dist/packdelta.pyz").read_bytes()
        run(); self.assertEqual(first, (ROOT / "dist/packdelta.pyz").read_bytes())
        portable = self.root / "packdelta.pyz"; portable.write_bytes(first)
        a = self.write(blob())
        proc = subprocess.run([sys.executable, str(portable), str(a), str(a), "--format", "json"],
                              cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["summary"]["changed"], 0)


if __name__ == "__main__":
    unittest.main()
