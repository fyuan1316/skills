---
name: edge-buildrun-ops
description: Query, trigger, monitor, and collect evidence from Alauda Edge/Katanomi BuildRuns for release workflows. Use when Codex needs branch-aware RC/formal BuildRun discovery or trigger, BuildRun status/log/parameter inspection, build output evidence, artifacts-upload-ac execution evidence, or action-result facts for accelerator component release profiles.
---

# Edge BuildRun Ops

Use this skill for the Edge/Katanomi build layer only. It stops at BuildRun/PipelineRun evidence and does not deploy packages into ACP, scan images, or edit release materials.

## Scope

Handle:

- list and inspect `Build` / `BuildRun`
- discover matching RC/formal BuildRun by build name, branch/tag, candidate version, package URL, or image tag
- trigger branch-aware BuildRun when explicitly approved
- watch status and collect logs/params
- verify generated PipelineRun `git-url`, `git-revision`, `git-commit`
- write action-result JSON for the release orchestrator

Delegate package download/checksum/image digest interpretation to `package-artifact-discovery`.

## Environment

Use `/Volumes/macOS-2/Users/yuan/Dev/tools/envs/agent-envs/resolve-env.py edge` or `env.edge`.

Never print token values. Use this pattern inside one command:

```bash
set -a
source /Volumes/macOS-2/Users/yuan/Dev/tools/envs/env.edge
set +a
```

Default target:

```text
platform: https://edge.alauda.cn
cluster: business-build
namespace: aml-dev
workspace: aml
```

## Read-Only Discovery

For discovery, prefer read-only API calls:

```text
GET /kubernetes/<cluster>/apis/builds.katanomi.dev/v1alpha1/namespaces/<namespace>/builds
GET /kubernetes/<cluster>/apis/builds.katanomi.dev/v1alpha1/namespaces/<namespace>/buildruns?limit=500
GET /kubernetes/<cluster>/apis/builds.katanomi.dev/v1alpha1/namespaces/<namespace>/buildruns/<name>
```

Collect:

- BuildRun name
- build name
- `spec.git.revision`
- `spec.params`
- status phase/conditions
- PipelineRun name
- generated PipelineRun params
- relevant logs
- package URL or image refs if visible

For release profile facts, discovery succeeds only when the BuildRun matches the requested candidate/tag and exposes enough evidence for downstream artifact discovery.

## Trigger Rules

Triggering a BuildRun is a mutating action. Require:

- explicit user approval for this BuildRun
- profile decision fact, for example `decision.rc-build-trigger.approved=true`
- `ACCELERATOR_RELEASE_ALLOW_MUTATION=true`

For branch-aware release builds, use the console/hyperflux shape that sets the BuildRun branch, not a fake parameter:

```bash
python3 /Volumes/macOS-2/Users/yuan/Dev/tools/alauda-ai-builders/hyperflux/skills/hyperflux-pipeline-ops/scripts/trigger_buildrun.py \
  --build-name <build-name> \
  --cluster business-build \
  --namespace aml-dev \
  --branch <branch> \
  --param key=value
```

Use `--branch <component>-<version>` for artifacts upload branches. The resulting BuildRun must have:

```text
spec.git.revision=refs/heads/<branch>
```

Do not rely on a hand-passed `git-revision` param to select the build YAML; Katanomi needs the branch before loading the build definition.

## AC Upload Pipeline

For AC upload BuildRun `artifacts-upload-ac`, this skill may trigger and monitor only after the release orchestrator confirms the AC gate. Validate fixed parameter keys before mutation:

```text
upload_artifacts
acp_version
ac_env
upload_versions
auto_commit
reuse_version_meta
upload_no_pack
overwrite_s3
image
```

Reject unknown keys, missing keys, or renamed keys. After trigger, record generated `git-url`, `git-revision`, and `git-commit`.

## Output Contract

Write an action result JSON in the run directory:

```json
{
  "actionId": "action.rc-build-or-discover",
  "status": "succeeded",
  "summary": {
    "buildRun": "example-build-abcde",
    "phase": "Succeeded",
    "matchedRevision": "refs/heads/release-1.3",
    "producedFacts": [
      "build.rc.discovery.attempted",
      "build.rc.exists"
    ],
    "evidencePaths": [
      "buildrun.json",
      "pipelinerun-summary.json",
      "logs.txt"
    ]
  }
}
```

Use only facts supported by evidence. Do not produce `artifact.*.package.exists` or `image.*.digests.recorded` unless package and digest data were actually discovered or verified.

## Safety

- Do not mutate Edge unless the user approved this exact BuildRun.
- Do not print secrets.
- Do not infer success from UI link alone; record API status or logs.
- Do not close release gaps directly; return facts/evidence for the orchestrator to close them.
