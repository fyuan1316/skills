---
name: package-artifact-discovery
description: Discover and verify release package artifacts, package-minio URLs, checksum files, md5/sha256, Harbor image refs and digests, and formal package content evidence. Use when Codex needs package URL validation, RC/formal artifact facts, image digest collection, stale package/checksum diagnosis, or action-result facts for release profiles.
---

# Package Artifact Discovery

Use this skill after a BuildRun or package URL exists. It verifies artifacts and produces release facts. It does not trigger builds, deploy packages, or scan CVEs.

## Inputs

Resolve these before acting:

- component package prefix, for example `hami-ascend-device-plugin-operator`
- version or candidate, for example `v1.3.0-rc.24.g37cb9c8f` or `v1.3.0`
- expected channel, usually `stable`
- architecture, for example `arm64`
- package-minio URL or enough fields to derive it
- image refs from BuildRun, bundle metadata, or profile

## Package-MinIO Checks

Expected package forms:

```text
http://package-minio.alauda.cn:9199/packages/<package-prefix>/rc/<package-prefix>.<channel>.<arch>.<candidate>.tgz
http://package-minio.alauda.cn:9199/packages/<package-prefix>/<major.minor>/<package-prefix>.<channel>.<arch>.<version>.tgz
```

Verify:

- package exists and is downloadable
- `.tgz.checksum` exists or absence is explained
- sha256 is computed from downloaded bytes
- md5 is recorded when useful for package-minio/S3 comparison
- package can be unpacked
- package manifest/config names match expected component/version
- `relatedImages` include expected runtime images
- formal package image labels point to the formal tag commit when labels are available

Store evidence under the release run directory, not in the skill directory.

## Image Digest Checks

For each image ref:

- resolve immutable digest with Harbor-compatible tooling, such as `skopeo inspect`, `crane digest`, `docker buildx imagetools inspect`, or Harbor API
- use credentials from `/Volumes/macOS-2/Users/yuan/Dev/tools/envs/env.harbor` only inside the command
- record ref, digest, architecture, and evidence command

Do not mark `image.*.digests.recorded=true` until all expected images have digests.

## Stale Formal Package Handling

If the same-version formal package exists but content points to an old commit or image tag:

1. Save package URL, checksum object content, sha256/md5, and package content proof.
2. Report stale package as a blocker.
3. Do not delete package objects automatically.
4. If the maintainer approves, prefer emptying the `.tgz.checksum` object to force repack.
5. Re-run formal BuildRun.
6. Download and verify the rebuilt package.

This skill may describe the remedy and collect evidence. Direct S3 writes require explicit user approval and a separate mutating action.

## Produced Facts

Produce only facts supported by evidence:

```text
artifact.rc.package.exists
artifact.rc.images.digest.exists
package.rc.checksum.recorded
image.rc.digests.recorded
gate.rc-build-artifacts.passed
artifact.formal.package.exists
artifact.formal.images.digest.exists
security.formal.scan.inputs.ready
```

`gate.rc-build-artifacts.passed` requires package URL, package checksum, and every expected image digest.

## Output Contract

Write action result JSON:

```json
{
  "actionId": "action.formal-build-or-discover",
  "status": "succeeded",
  "summary": {
    "packageUrl": "http://package-minio...tgz",
    "sha256": "...",
    "md5": "...",
    "images": [
      {
        "ref": "build-harbor.alauda.cn/mlops/example:v1.0.0",
        "digest": "sha256:..."
      }
    ],
    "producedFacts": [
      "artifact.formal.package.exists",
      "artifact.formal.images.digest.exists"
    ],
    "evidencePaths": [
      "package-content-check.txt",
      "images-digests.json"
    ]
  }
}
```

The result should pass:

```bash
python3 /Users/yuan/.codex/skills/accelerator-component-release/scripts/validate-action-result.py \
  --strict --profile <profile.yaml> <action-result.json>
```

## Safety

- Never print Harbor, S3, or package credentials.
- Do not treat a URL string in logs as proof; download or `HEAD` it.
- Do not close artifacts repo or AC gaps; this skill only proves package/image artifacts.
