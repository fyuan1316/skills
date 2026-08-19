# Release Observation Schema

Use this schema while collecting HAMi, NFD, HAMi Ascend device-plugin and InferNex release samples. It is an observation format, not yet the evaluator input contract.

```yaml
project: infernex-bridge
release:
  targetVersion: v26.6.0
  releaseType: formal
  sourceBranch: release-26.6.0-alauda
  sourceCommit: e0052c8
  candidateVersion: v26.6.0-alauda.4
  formalTag: v26.6.0
  formalTagCommit: 6c641e4
packaging:
  type: olm-bundle
  pluginPackageRequired: true
  artifactsRepoMode: registration-only
hardware:
  types: [ascend-npu]
  environments: [global-910]
stages:
  - id: source-audit
    status: complete
    actions: []
    gapsBefore: []
    gapsAfter: []
  - id: rc-build
    status: complete
    actions: []
    gapsBefore: []
    gapsAfter: []
actions:
  - id: action.rc-build
    ownerSkill: edge-buildrun-ops
    status: succeeded
    requires: []
    produces: [build.rc.exists, build.rc.images.digest.exists]
    evidence: []
    retryOf: null
    externalBlock: null
gaps:
  - id: GAP-RC-PACKAGE
    type: ARTIFACT
    severity: P0
    statusBefore: open
    statusAfter: open
    nextActionObserved: action.rc-package
    closureEvidence: null
decisions:
  - id: decision.rc-build.approved
    value: true
    approver: TODO
    expiresAt: TODO
notes:
  - TODO: record why the maintainer selected the next action.
```

Collection rules:

- preserve original project-specific terminology in `notes`;
- record failed and retried actions, not only successful actions;
- record evidence paths and candidate identity for every produced fact;
- never mark a gap closed without a verification evidence path;
- distinguish “not applicable”, “not run”, “blocked” and “passed”.
