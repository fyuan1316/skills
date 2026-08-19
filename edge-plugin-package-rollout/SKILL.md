---
name: edge-plugin-package-rollout
description: Roll out an Alauda plugin/operator package produced by an Edge/Katanomi BuildRun into a target ACP environment, especially OLM + Helm-operator installs such as npu-operator on kubeos. Use when Edge already built the plugin package or bundle and the user wants to sync or verify it on dev kubeos/microos/global, update CatalogSource/Subscription, preserve current Helm values and running images, and validate CSV, Helm release, pods, and CR status.
---

# Edge Plugin Package Rollout

Use this as the orchestration layer between Edge pipeline output and ACP runtime validation.

It is intentionally separate from:

- `edge-ci-build`: old low-level BuildRun trigger. Prefer `hyperflux-pipeline-ops` for branch-aware RC builds.
- `sync-bundle`: only syncs a known artifact into a platform catalog.
- `bundle-iterate`: old code-to-cluster loop for air-gapped kubeos2/devpod/npuserver flows.

## When To Use

- Edge has already built a plugin/operator package and the user wants to deploy or verify it on `dev kubeos`.
- The target is OLM-backed and may have an operator-managed Helm release, for example:
  - `Subscription` / `CSV` install the package manager.
  - a CR such as `NPUOperatorCtl` drives a Helm release such as `cluster` in namespace `npu-operator`.
- The user cares about preserving live Helm values, runtime images, CRs, and cluster-specific settings.

Do not use this for generic artifact upload only; use `sync-bundle` when the input is simply “upload this bundle image to dev kubeos”.

## Inputs

Resolve these before mutation:

| Input | Example | Source |
|---|---|---|
| Edge BuildRun | `npu-operator-wzhdm` | user / Edge UI / `hyperflux-pipeline-ops` |
| Expected package version | `v26.6.0-alauda.1` | release branch / BuildRun output |
| Target env + cluster | `dev kubeos` | `agent-envs/registry.yaml` or `envs/dev-*/clusters/*.env` |
| OLM package | `npu-operator` | current Subscription / PackageManifest |
| Install namespace | `npu-operator` | current Subscription / CSV |
| Helm release, if any | `cluster` | `helm list -A` / operator CR |

Read credentials from `/Volumes/macOS-2/Users/yuan/Dev/tools/envs`; never print token or password values.

## BuildRun Artifact Discovery

If the user gives only a BuildRun name, first harvest non-secret artifact clues:

```bash
python3 <skill-dir>/scripts/edge-buildrun-artifacts.py \
  --buildrun npu-operator-wzhdm \
  --namespace aml-dev \
  --cluster business-build
```

The script checks the native BuildRun, Tekton PipelineRun, and TaskRuns for values containing package, bundle, tgz, image, artifact, digest, or version-looking strings.

Interpretation:

- `*.tgz` / package URL: the package may already be a violet package; download or locate it, then `violet push` to the platform.
- `build-harbor...*-bundle:<tag>` or chart/bundle image: use `sync-bundle` / `sync-bundle-envs`.
- no artifact clue: inspect Edge task logs or the build definition before guessing a registry path.

## Target State Snapshot

Before changing anything, capture the live target state. For kubeos-style contexts:

```bash
helm get values <release> -n <ns> --kube-context <context> -o yaml
kubectl --context <context> -n <ns> get deploy,ds,pod -o wide
kubectl --context <context> -n <ns> get npuclusterpolicy -o yaml
kubectl --context <context> get subscription,csv,installplan,catalogsource -A | rg -i '<package>|<version>|platform|catalog'
helm get manifest <release> -n <ns> --kube-context <context> | rg -n 'image:|imagePullSecrets|runtimeClass|webhook|cert-manager|kind: (Deployment|DaemonSet|Certificate|Issuer|MutatingWebhookConfiguration)|name:'
```

Save conclusions in the response, not secret values. The point is to avoid a blind Helm upgrade that replaces live values or runtime images.

## Rollout Decision

Use this order:

1. If the target platform catalog already exposes the expected package version, do not resync. Move to OLM upgrade verification.
2. If Edge produced a bundle/chart artifact image, run `sync-bundle-envs <artifact> dev kubeos` or the specific target.
3. If Edge produced a prebuilt `.tgz` package, push that package with `violet push --force` against the target platform. Do not run `violet create` again unless the artifact is not already packaged.
4. If only image tags are visible and no package/bundle artifact exists, stop and report the missing packaging output.

## OLM + Helm Operator Upgrade Verification

For OLM-backed installs, verify through OLM first:

```bash
kubectl --context <context> -n <sub-ns> get subscription <package> -o yaml
kubectl --context <context> -n <sub-ns> get csv
kubectl --context <context> -n <sub-ns> get installplan
kubectl --context <context> -n cpaas-system get catalogsource platform -o yaml
kubectl --context <context> get packagemanifest <package> -o yaml 2>/dev/null || true
```

Expected success signals:

- Subscription `installedCSV` / `currentCSV` is the expected new version.
- CSV phase is `Succeeded`.
- manager Deployment is ready.
- The operator-managed Helm release still exists and did not lose live values.
- Runtime Deployments/DaemonSets are ready.
- product CR status is healthy, for example `NPUOperatorCtl` / `NPUClusterPolicy`.

If Subscription does not move:

- Check whether the platform catalog actually contains the new version.
- Check channel and semver ordering.
- Check `installPlanApproval`; if manual, show the pending InstallPlan before approving.
- In dev-only validation, deleting/recreating Subscription or stale CSV is acceptable only after stating the impact.

## Safety

- Treat `violet push`, Subscription changes, InstallPlan approval, Helm upgrade, and CSV deletion as live mutations.
- Prefer OLM/package upgrade over raw `helm upgrade` for OLM-managed products.
- Never overwrite live Helm values unless the requested change explicitly requires it.
- Never print Edge, platform, Harbor, or kubeconfig credentials.
- If an existing release is OLM + Helm operator managed, do not bypass the owner chain without calling that out.

## Output Contract

Report:

- BuildRun and discovered package/bundle artifact.
- Target platform, cluster, namespace, Subscription, current CSV, desired CSV.
- Whether catalog sync was needed or skipped.
- Preserved live state summary: Helm values source, running images, important CRs.
- Final status: CSV, Helm release, pods, and CR health.
- Any remaining blocker with the exact layer: Edge artifact, catalog sync, OLM resolution, Helm operator, runtime pods.
