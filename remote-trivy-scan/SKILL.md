---
name: remote-trivy-scan
description: Run release-grade Trivy image scans on a remote scanner with proxy support, collect JSON/table reports, summarize Critical/High/Medium/Low/Unknown counts, and produce security gate evidence. Use when build-time image scan is unavailable or insufficient, when release CVE gates need independent evidence, or when accelerator release profiles need rc/formal security facts.
---

# Remote Trivy Scan

Use this skill for release-grade image vulnerability evidence. It does not fix CVEs; route fixes to `baseimage-cve-fix` or the owning code skill.

## Gate Position

Run after:

- RC package and image digest discovery
- package content validation
- rollout/deployability validation
- functional/e2e release tests

Do not use an old RC scan as evidence for a newer candidate. Build-time `alauda-image-scan` may be recorded as a signal, but it is not the hard release gate.

## Inputs

Collect:

- image refs and immutable digests
- scan phase: `rc` or `formal`
- remote scanner host
- remote user/auth method
- proxy settings, for example `HTTPS_PROXY=http://192.168.144.12:7890`
- `NO_PROXY` for internal registry/package endpoints
- artifact output directory

Use credentials from `/Volumes/macOS-2/Users/yuan/Dev/tools/envs` only inside commands. Do not write secrets into reports.

## Remote Execution Rules

On the remote host:

- verify `trivy --version`
- write `images.txt`
- write redacted `proxy.env`
- run one JSON and one table report per image
- write `scan-progress.log`
- generate `summary.md`

Recommended report files:

```text
trivy-version.txt
images.txt
proxy.env
scan-progress.log
<image-safe-name>.json
<image-safe-name>.table.txt
summary.md
```

If SSH password automation is needed, prefer a temporary `SSH_ASKPASS` wrapper or a single-match `expect` script. Do not print passwords. For older OpenSSH servers, use `scp -O` when pulling reports.

## Proxy Rules

When proxy is required:

- prefix the remote scan command with `HTTPS_PROXY`, `HTTP_PROXY`, and `NO_PROXY`
- include internal registries in `NO_PROXY`, such as build-harbor and package-minio
- record the proxy values in redacted evidence

## Summary Policy

Security gate passes only when:

- scan completed for every expected image
- Critical count is 0
- High count is 0
- remaining Medium/Low/Unknown are either accepted by policy or left as explicit approval gaps

Produce scan facts separately from approval facts:

```text
security.rc.scan.completed
security.rc.scan.report.recorded
security.rc.critical-high.passed
security.formal.scan.passed
```

Do not produce `gate.cve-release-accepted` or `approval.residual-security.accepted`; those require release owner approval.

## Output Contract

Write action result JSON:

```json
{
  "actionId": "action.rc-cve-image-scan",
  "status": "succeeded",
  "summary": {
    "scanner": "192.168.x.x",
    "phase": "rc",
    "critical": 0,
    "high": 0,
    "medium": 14,
    "low": 18,
    "unknown": 0,
    "producedFacts": [
      "security.rc.scan.completed",
      "security.rc.scan.report.recorded",
      "security.rc.critical-high.passed"
    ],
    "evidencePaths": [
      "summary.md",
      "remote/"
    ]
  }
}
```

If Critical/High is nonzero, set status to failed or warning and produce only scan-completed/report facts. Route to CVE fix.

## Safety

- Do not mutate images or registries.
- Do not scan a tag when the profile requires digest-bound evidence unless the tag digest is recorded.
- Do not hide scanner service failures; report them as a security evidence gap.
