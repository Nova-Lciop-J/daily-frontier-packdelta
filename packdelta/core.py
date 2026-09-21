"""Read bounded gzip/tar input without extraction, execution, or networking."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIB = 1024 * 1024
DEPENDENCY_FIELDS = (
    "dependencies", "optionalDependencies", "peerDependencies", "devDependencies",
)
ENTRY_FIELDS = ("main", "module", "exports", "bin", "browser", "type")
INSTALL_HOOKS = {"preinstall", "install", "postinstall", "prepare"}


class InputError(ValueError):
    """A generic, deliberately value-free diagnostic for untrusted input."""


@dataclass(frozen=True)
class Limits:
    compressed_bytes: int = 16 * MIB
    expanded_bytes: int = 64 * MIB
    file_bytes: int = 8 * MIB
    total_file_bytes: int = 32 * MIB
    members: int = 2000
    manifest_bytes: int = 128 * 1024


@dataclass(frozen=True)
class Entry:
    sha256: str
    size: int
    mode: int


@dataclass
class Snapshot:
    archive_sha256: str
    entries: dict[str, Entry]
    manifest: dict[str, Any]


class BoundedReader:
    def __init__(self, source: gzip.GzipFile, limit: int):
        self.source = source
        self.remaining = limit

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = min(65536, self.remaining + 1)
        data = self.source.read(min(size, self.remaining + 1))
        self.remaining -= len(data)
        if self.remaining < 0:
            raise InputError("Expanded archive exceeds the configured limit.")
        return data


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError("Duplicate JSON keys are not accepted.")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise InputError("Non-finite JSON constants are not accepted.")


def _manifest(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InputError("package.json is not supported valid JSON.") from exc
    if not isinstance(value, dict):
        raise InputError("package.json must contain an object.")
    for key in ("name", "version"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise InputError("package.json needs nonempty name and version strings.")
    for field in ("scripts", *DEPENDENCY_FIELDS):
        mapping = value.get(field, {})
        if not isinstance(mapping, dict) or any(
            not isinstance(v, str) for v in mapping.values()
        ):
            raise InputError("Scripts and dependency entries must be string maps.")
    return value


def _path(member: tarfile.TarInfo) -> str:
    name = member.name
    if len(name) > 512 or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise InputError("Archive member has an unsupported path.")
    if member.isdir():
        name = name.rstrip("/")
    parts = name.split("/")
    if parts[0] != "package" or any(p in ("", ".", "..") for p in parts):
        raise InputError("Archive members must remain inside package/.")
    if len(parts) == 1 and not member.isdir():
        raise InputError("The package root must be a directory.")
    return "/".join(parts)


def load_snapshot(path: Path, limits: Limits | None = None) -> Snapshot:
    limits = limits or Limits()
    entries: dict[str, Entry] = {}
    seen: set[str] = set()
    manifest_data: bytes | None = None
    total = 0
    try:
        # Capture once to bind inventory and SHA to exactly the same compressed bytes.
        with path.open("rb") as source:
            blob = source.read(limits.compressed_bytes + 1)
        if len(blob) > limits.compressed_bytes:
            raise InputError("Compressed archive exceeds the configured limit.")
        with gzip.GzipFile(fileobj=io.BytesIO(blob), mode="rb") as gz:
            reader = BoundedReader(gz, limits.expanded_bytes)
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for count, member in enumerate(archive, 1):
                    if count > limits.members:
                        raise InputError("Archive has too many members.")
                    name = _path(member)
                    if name in seen:
                        raise InputError("Duplicate archive paths are not accepted.")
                    seen.add(name)
                    if member.issparse() or not (member.isfile() or member.isdir()):
                        raise InputError("Links, sparse files and special members are not accepted.")
                    if member.size < 0 or member.size > limits.file_bytes:
                        raise InputError("Archive member exceeds the configured limit.")
                    if member.isdir():
                        if member.size:
                            raise InputError("Directory members must be empty.")
                        continue
                    total += member.size
                    if total > limits.total_file_bytes:
                        raise InputError("Total payload exceeds the configured limit.")
                    if name == "package/package.json" and member.size > limits.manifest_bytes:
                        raise InputError("package.json exceeds the configured limit.")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise InputError("Cannot read archive member.")
                    digest = hashlib.sha256()
                    content = bytearray()
                    consumed = 0
                    with stream:
                        while chunk := stream.read(65536):
                            consumed += len(chunk)
                            digest.update(chunk)
                            if name == "package/package.json":
                                content.extend(chunk)
                    if consumed != member.size:
                        raise InputError("Archive member is truncated.")
                    entries[name] = Entry(digest.hexdigest(), member.size, member.mode & 0o7777)
                    if name == "package/package.json":
                        manifest_data = bytes(content)
            # Validate the gzip footer/CRC and bound trailing compressed streams too.
            while reader.read(65536):
                pass
    except InputError:
        raise
    except (OSError, EOFError, tarfile.TarError, ValueError, OverflowError, RecursionError, zlib.error) as exc:
        raise InputError("Cannot read a supported, complete gzip/tar archive.") from exc
    if manifest_data is None:
        raise InputError("Archive is missing package/package.json.")
    return Snapshot(hashlib.sha256(blob).hexdigest(), entries, _manifest(manifest_data))


def compare(before: Snapshot, after: Snapshot) -> dict[str, Any]:
    old, new = before.entries, after.entries
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    changed = sorted(n for n in old.keys() & new.keys() if old[n] != new[n])
    findings: list[dict[str, str]] = []

    def note(level: str, rule: str, location: str, reason: str) -> None:
        findings.append({"level": level, "rule": rule, "location": location, "reason": reason})

    # Candidate-wide checks intentionally also catch unchanged sensitive filenames.
    for name in sorted(new):
        parts = name.casefold().split("/")
        leaf = parts[-1]
        if (leaf.startswith(".env") or leaf in {".npmrc", ".pypirc", "id_rsa", "id_ed25519"}
                or any(p in {".ssh", ".git", ".aws"} for p in parts)):
            note("high", "sensitive-filename", name,
                 "Potentially sensitive file is shipped; contents are not inspected or printed.")
        if new[name].mode & 0o6000:
            note("high", "special-permission", name, "Setuid or setgid permission bits are present.")
        if name in added or name in changed:
            if leaf.endswith(".map"):
                note("review", "source-map", name, "Source map added or changed; review embedded sources.")
            if "node_modules" in parts:
                note("review", "bundled-dependency", name, "Bundled dependency payload changed.")
            if leaf.endswith((".node", ".wasm", ".so", ".dll", ".exe")):
                note("review", "binary-payload", name, "Binary payload added or changed.")
            old_mode = old[name].mode if name in old else 0
            if new[name].mode & 0o111 & ~old_mode:
                note("review", "executable-bit", name, "New executable permission bits.")
    a, b = before.manifest, after.manifest
    for field in ("scripts", *DEPENDENCY_FIELDS):
        prior, current = a.get(field, {}), b.get(field, {})
        for key in sorted(prior.keys() | current.keys()):
            if prior.get(key) != current.get(key):
                kind = "added" if key not in prior else "removed" if key not in current else "changed"
                level = "high" if field == "scripts" and key in INSTALL_HOOKS and key in current else "review"
                note(level, "script-change" if field == "scripts" else "dependency-change",
                     f"package/package.json:{field}/{key}",
                     f"Entry {kind}; values deliberately omitted. Review exact input privately.")
    for field in ENTRY_FIELDS:
        if a.get(field) != b.get(field) or (field in a) != (field in b):
            note("review", "entry-point-change", f"package/package.json:{field}",
                 "Runtime entry point or module interpretation changed; values omitted.")
    if a.get("license") != b.get("license"):
        note("review", "license-change", "package/package.json:license", "License declaration changed.")
    if a["name"] != b["name"]:
        note("high", "package-name-change", "package/package.json:name", "Package identity changed.")
    payload_changed = bool(added or removed or changed)
    if payload_changed and a["version"] == b["version"]:
        note("review", "same-version-payload-change", "package/package.json:version",
             "Payload changed without a version change.")
    return {
        "schema_version": 1,
        "tool": "packdelta", "tool_version": "0.1.0",
        "before_sha256": before.archive_sha256, "after_sha256": after.archive_sha256,
        "summary": {"added": len(added), "removed": len(removed), "changed": len(changed),
                    "unchanged": len(old.keys() & new.keys()) - len(changed),
                    "candidate_bytes": sum(e.size for e in new.values())},
        "files": {"added": added, "removed": removed, "changed": changed},
        "findings": sorted(findings, key=lambda x: (x["level"], x["rule"], x["location"])),
        "notice": "Review aid only: not a secret scanner, malware verdict, or compatibility proof. "
                  "Reports include archive member names; review before sharing.",
    }
