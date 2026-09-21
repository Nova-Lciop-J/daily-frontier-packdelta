"""CLI that never echoes raw file contents or exception values."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from . import __version__
from .core import InputError, compare, load_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review two local npm .tgz files without running package code.")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--fail-on", choices=("review", "high", "change", "never"), default="review")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        report = compare(load_snapshot(args.before), load_snapshot(args.after))
    except InputError as exc:
        print("packdelta: " + str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print("PackDelta 0.1.0 | offline artifact review")
        print("before SHA256: " + report["before_sha256"])
        print("after  SHA256: " + report["after_sha256"])
        s = report["summary"]
        print(f"Files: +{s['added']} -{s['removed']} ~{s['changed']} unchanged={s['unchanged']}")
        for finding in report["findings"]:
            location = json.dumps(finding["location"], ensure_ascii=True)
            print(f"[{finding['level']}] {finding['rule']} {location}")
            print("  " + finding["reason"])
        if not report["findings"]:
            print("No configured review signals. This is not a security clearance.")
        print(report["notice"])
    levels = {f["level"] for f in report["findings"]}
    if args.fail_on == "never":
        return 0
    if args.fail_on == "change":
        return int(any(report["summary"][k] for k in ("added", "removed", "changed")))
    return int(bool(levels & ({"high"} if args.fail_on == "high" else {"high", "review"})))
