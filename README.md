# PackDelta

**Review what actually changed in two npm package tarballs — without running them.**

PackDelta is an offline CLI for package maintainers and release reviewers. It
compares shipped payloads, not only repository diffs, and highlights changed
install scripts, dependencies, entry points, source maps and executable bits.
It also flags potentially sensitive filenames anywhere in the candidate,
including files unchanged since the baseline. Findings request review; they
are not malware verdicts or proof that a release is safe.

## Why this instead of another diff?

`npm diff` produces useful file patches; `npm pack --dry-run` previews included
files; diffoscope performs broad, deep artifact comparisons. PackDelta has a
narrower purpose: a dependency-free, offline, bounded two-tarball release-review
summary with machine-readable output and CI exit codes. It omits script values
and dependency specifications instead of printing them. It is not a replacement
for those tools or a secret scanner, and it does not claim to be the first
artifact comparison tool.

npm's September 18, 2026 stage-only token announcement increases the usefulness
of reviewing staged payloads. PackDelta needs no token and does not implement
or claim verified integration with the npm staging API.

## Install and run — no network or API key

Run from this project directory using Python 3.13.15. Linux/Python 3.13.15 is the
initial verification environment; other Python versions and operating systems
are not yet claimed as verified. Python must already be installed. There are
**no runtime or test dependencies**, so no pip or registry access is needed.

```sh
python3 -m venv --without-pip .venv
.venv/bin/python tools/build_zipapp.py
.venv/bin/python examples/make_demo.py
.venv/bin/python dist/packdelta.pyz dist/demo/before.tgz dist/demo/after.tgz --fail-on never
.venv/bin/python -m unittest discover -s tests -v
```

The example creates synthetic tarballs and actually analyzes their contents.
Expect two added files, one changed file, an unchanged entry file, a high-priority
`postinstall` change and a source-map review signal. The synthetic script is
never executed. `--fail-on never` is used above only so an intentional finding
does not interrupt a first demonstration. Production review defaults to failing
on review/high signals.

The built `dist/packdelta.pyz` can be copied to another directory and run with
Python; it contains no third-party dependencies. The builder uses deterministic
ZIP member order, timestamps, permissions and stored bytes.

## Your own artifacts

```sh
python3 dist/packdelta.pyz before.tgz after.tgz --format json > report.json
```

The default exit code is **0** for no configured review signals, **1** when
signals need review, and **2** for input/usage errors. `--fail-on high` fails only
on high signals; `--fail-on change` fails on any file/content/mode difference;
`--fail-on never` suppresses findings-based failure but NEVER input errors.
Findings are still emitted in all modes. These controls belong to this review
tool and do not waive your release process's security checks.

Create artifacts separately with `npm pack --ignore-scripts --offline` in a
trusted local package directory. PackDelta itself never invokes npm. This
avoids lifecycle scripts; it does NOT build missing assets. Build trusted source
in a separate unprivileged environment first. Do not pack an untrusted project
in an environment containing credentials. Staged publishing itself has NOT been
verified here; no npm login, network service or registry publishing is required.

## Output and limitations

JSON schema version 1 contains input SHA-256 hashes, file counts, added/removed/
changed paths and findings. Hashes bind the report to the actual compressed
inputs. Gzip metadata differences can change archive hashes without changing the
file inventory. Reordering files and tar timestamps do not count as payload
changes. Removal of a script/dependency is reported as review, not high risk.

Only npm-shaped gzip/tar archives under `package/` are accepted. Read
[SECURITY.md](SECURITY.md) for hard limits, parser restrictions and threat-model
limits. Reports contain archive member/key names and require privacy review
before sharing. No content scanning, transitively resolved dependency audit,
malware detection, digital signature validation, or semantic compatibility
analysis is performed. For a first release, create a deliberate baseline;
PackDelta requires two valid artifacts rather than pretending a missing one is
safe. The CLI has no user interface or browser component.

## Development and maintenance

Run the unittest command above and rebuild after every source edit. Optional
static tools are configured in `pyproject.toml`; absence is not a passing result.
No claims of independently verified CI, current vulnerability scanning, speed,
compatibility beyond the listed environment, or public release are made.

See [README.zh-CN.md](README.zh-CN.md), [CHANGELOG.md](CHANGELOG.md),
[MAINTENANCE.md](MAINTENANCE.md) and [THIRD_PARTY.md](THIRD_PARTY.md).
License: MIT; publication into an existing repository needs license compatibility
review first.

## Primary references

- npm pack: https://docs.npmjs.com/cli/v11/commands/npm-pack/
- npm diff: https://docs.npmjs.com/cli/v11/commands/npm-diff/
- Stage-only token announcement, 2026-09-18: https://github.blog/changelog/2026-09-18-stage-only-npm-tokens-for-safer-automation/
- diffoscope: https://diffoscope.org/

References checked on 2026-09-21; announcement date is not a claim of a new event
today. No third-party implementation or data was copied into this project.
