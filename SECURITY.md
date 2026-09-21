# Security and limitations

PackDelta never executes package scripts, installs a package, extracts an archive,
opens a network connection, or requests a credential. Input is untrusted.
It rejects path traversal, links, special members, duplicates, missing manifests,
invalid gzip/tar and malformed manifest fields. Compressed input is capped at
16 MiB, expanded input at 64 MiB, individual payloads at 8 MiB, total payloads at
32 MiB, members at 2,000 and the manifest at 128 KiB. PAX/GNU metadata counts
toward the expanded-byte cap. These are bounded defaults, not a sandbox guarantee.

Use an up-to-date Python runtime and operating-system resource limits for
hostile inputs. This initial release does not prove parser correctness or
adversarial CPU-time safety. It does not recursively inspect nested archives,
scan secret values, detect malware, validate signatures/provenance, resolve
transitive dependencies, or establish semantic compatibility. A high finding is
a reason to review, not a proven vulnerability. No findings is not a safety verdict.

Values of scripts, dependency specifications and local input paths are omitted
from reports. Archive member names and manifest key names ARE included and can
be sensitive. Reports are NOT automatically safe to publish. Do not put secrets
in member names. Review reports before sharing; terminal output escapes names.

No public security contact is configured until a target repository is designated.
Do not post secrets or private reproductions in public issues. Use the eventual
repository's private vulnerability reporting facility if available.
