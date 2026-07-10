# Next Release Readiness

Use this checklist before starting another accelerator component release. The
goal is to start from source-only input while avoiding the manual rediscovery
that slowed ADP v1.3.0.

## Required Inputs

- source repo path and release branch
- component name and target version
- release type: RC loop, formal release, or audit-only
- expected Edge BuildRun name, cluster, namespace, and build revision rule
- expected package prefix if known
- expected image repositories if known
- blocking hardware matrix and kubeconfig/env binding
- dependency components that must be deployed first
- product docs repo path and English-only or bilingual rule

## Starting Material Directory

For a source-first rehearsal, use:

```text
docs/releases/<component>-<version>-test
```

After all blocking gaps close, promote it to:

```text
docs/releases/<component>-<version>
```

Keep historical run directories intact. Do not rewrite evidence paths after
promotion.

## First Runner Pass

The first pass should prove:

- source checkout fact
- branch and target version fact
- material skeleton location
- RC BuildRun discovery attempt
- whether RC package, checksum, and image digests already exist

If RC discovery finds no matching candidate, the next action should be RC build
trigger. Triggering remains dry-run unless the profile has an approval fact and
`ACCELERATOR_RELEASE_ALLOW_MUTATION=true`.

## Before Formal Tag

Require these facts or explicit waivers:

- RC package URL and checksum recorded
- RC image refs and digests recorded
- package content checked
- target workload actually deployed, not only operator or CSV installed
- function/e2e passed on blocking hardware
- release-grade CVE scan completed after function test
- Critical/High is zero, or residual approval is recorded
- material precheck passed

## Artifacts And AC

For self-built components, `aml/artifacts` can be registration-only, but the
release still needs:

- `master` component directory reflecting the latest version
- `<component>-<version>` branch preserving that release's metadata
- artifacts directory name aligned with the package-minio package prefix

AC upload is the last mutating gap. Confirm the exact BuildRun branch and the
fixed parameter keys before upload:

```text
git-url
git-revision
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

Reject renamed or unknown keys.

## Credentials And Tools

Resolve credentials through:

```text
/Volumes/macOS-2/Users/yuan/Dev/tools/envs/agent-envs/registry.yaml
```

Source only the chosen env file inside the command that needs it. Never print
secret values.

Resolve repeatable external tools through:

```bash
hack/accelerator-release-tool-cache.sh resolve <tool> <version>
```

Do not cache tokens, kubeconfigs, or registry credentials.
