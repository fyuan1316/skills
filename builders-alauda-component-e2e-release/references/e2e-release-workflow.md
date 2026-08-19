# E2E Release Workflow

Use this reference after prerequisites are verified.

## Repository Inspection

Identify:

- Component type: Cluster Plugin, OLM operator, OLM-managed Helm operator, or plain chart.
- Component feature surfaces: CRDs, controllers, webhooks, HTTP/gRPC APIs, CLIs, UI/plugin config, storage, hardware, or middleware integration.
- Chart, bundle, and image build targets in `.build/`, Makefiles, scripts, or build metadata.
- Artifact metadata under `artifacts/<name>/`.
- Existing e2e tests, component Dockerfiles, e2e runner Dockerfiles, helper image Dockerfiles, image lockfiles or package manifests, and Kubernetes Job manifests.
- Helm charts, values files, rendered manifests, OLM bundle manifests, CSVs, RBAC, webhooks, PodDisruptionBudgets, NetworkPolicies, and namespace or PSA assumptions.
- Dependency and compatibility evidence in docs, chart values, CRDs, RBAC, controller dependencies, and sample manifests.
- CVE evidence from existing scan reports, security tickets, dependency reports, or repo-supported scan commands.
- Product documentation repo URL or local directory for the current component when the work is release-oriented.
- Existing PR or MR branch strategy.

Do not add new build or e2e structure until the current repo pattern is understood. After inspection, missing buildkitd image build support, missing local ACP artifact packaging/upload support, and missing e2e assets are release blockers that must be added before validation continues.

Use `pre-release-e2e-test-design.md` to decide which smoke, compatibility, performance, and HA checks are appropriate for the component. Keep generated tests minimal but behavior-based: test the installed component through Kubernetes or API surfaces instead of only checking that pods exist.

Use `release-readiness-gates.md` in parallel with e2e planning when the work is release-oriented. Read that referenced document before classifying CVEs, choosing Dockerfile changes, accepting false positives, or carrying residual risk. Use `builders-alauda-security-scan` to run or collect the required scan evidence. Security fixes and residual security decisions should be handled early. Required CVE fixes must land in Dockerfiles, base image references, package pinning, package manager updates, or lockfiles before the images are built for e2e. Product documentation, frozen-package CVE database updates, and ERRATA are checked again after e2e passes and the package is no longer changing.

Use `builders-alauda-security-scan` before packaging or installing when the component ships images, Helm charts, raw Kubernetes manifests, Cluster Plugin resources, or OLM bundles. Manifest security findings are release blockers when they violate required PSA expectations, run containers as root without approval, grant unnecessary privileges, use host access without a documented need, expose secrets, or grant overbroad RBAC.

If the product documentation location is not explicit or discoverable, ask the user for the repo or local directory before running the full release workflow. The component repo can still be inspected, but formal release validation must not assume product docs live there.

## Required Missing Pieces

When the target repo lacks release validation scaffolding, add the smallest structure that fits the existing project:

- Buildkitd-backed image build scripts or Make targets when no equivalent local build path exists.
- Local ACP artifact packaging and upload support, usually through `violet` or the repo's local violet wrapper, when no equivalent artifact publishing path exists.
- End-to-end test scripts that exercise the installed component through its user-facing or Kubernetes-facing behavior.
- Minimal compatibility tests for documented or discovered dependencies.
- API performance tests when the component exposes HTTP/gRPC endpoints.
- HA configuration checks or release documentation for replicas, leader election, PDBs, and stateful dependencies.
- An e2e runner image, including the Dockerfile or buildkitd build script needed to build and push it.
- Sample Kubernetes e2e run jobs that use the built runner image and can be applied to the dev workload cluster.

Keep names, locations, build params, image registries, and artifact metadata aligned with the repo's existing `.build/`, chart, operator, and artifact conventions. Do not rely on CI or pipeline output to select release validation image tags or artifacts.

## CVE Remediation Before E2E

Complete this phase before packaging, installing, or running e2e:

1. Read `release-readiness-gates.md` to determine the severity thresholds, release-type rules, residual-risk evidence, false-positive requirements, frozen-package scan requirements, CVE database handling, and ERRATA impact.
2. Use `builders-alauda-security-scan` to collect the current scanner findings for the required component image set. For Cluster Plugins, scan every image listed in the release `values.yaml` files. For OLM operators or Helm operators, scan the operator image, bundle image, and all related runtime images needed when using the component. Also scan helper images and the e2e runner image when they are built or shipped as part of the release validation workflow.
3. Check the user-provided referenced documents from the environment file, including scan report paths, security tickets, CVE notes, previous-release image references, and any vulnerability tracking links. Do not decide that a CVE is not applicable without support from these documents or an explicit review decision.
4. Map each required CVE fix to the exact Dockerfile, base image tag or digest, package manifest, lockfile, or build argument that controls the vulnerable package.
5. Update Dockerfiles and image dependency inputs using the repo's existing style. Prefer patched base images, explicit package version bumps, refreshed lockfiles, or package manager upgrade steps that are acceptable for reproducible buildkitd builds.
6. Avoid broad unpinned package upgrades unless the repo already uses that pattern or the security owner accepts the risk. Preserve multi-arch behavior and existing image labels, users, entrypoints, and build args.
7. Run the smallest relevant unit, lint, or build checks for Dockerfile changes when available.
8. Record addressed CVE IDs, remaining scanner findings, false positives, residual-risk approvals, and the referenced documents used for each decision.

Do not start e2e with stale pre-remediation image tags. If a Dockerfile, lockfile, base image, or image build argument changes after e2e, rebuild and rerun e2e or clearly mark the old e2e evidence invalid.

## Helm, Kubernetes, And OLM Security Before E2E

Complete this phase through `builders-alauda-security-scan` before packaging and installing:

1. Render Helm charts with the release values that will be uploaded or installed, including platform-specific overrides and image references from the current build.
2. Scan source charts, rendered manifests, raw Kubernetes YAML, and OLM bundle or CSV manifests with the scanner flow from `builders-alauda-security-scan`.
3. Fix required PSA and workload hardening findings in values, templates, manifests, or OLM deployment specs. Cover `runAsNonRoot`, non-zero `runAsUser` where appropriate, `allowPrivilegeEscalation`, Linux capabilities, `seccompProfile`, privileged mode, host namespaces, hostPath, service account token mounting, probes, resources, and writable root filesystem decisions.
4. Review OLM `ClusterServiceVersion` install deployments, `permissions`, `clusterPermissions`, webhook manifests, CRD conversion webhooks, related images, and catalog or bundle metadata.
5. Review RBAC for broad verbs or resources and reduce privileges unless the component behavior requires them.
6. Record scanner output paths, manual review decisions, false positives, residual-risk approvals, and the exact rendered manifest or bundle version used for the release test.

If Helm values, templates, OLM manifests, or raw Kubernetes manifests change after e2e, re-render, rescan, repackage, reinstall, and rerun e2e or clearly mark previous evidence invalid.

## Build

Use the user-provided buildkitd and registry after CVE remediation is complete. Follow the repo's image names and Dockerfile paths. For each affected image:

1. Build for the platforms required by the repo or environment file.
2. Push to the configured registry.
3. Scan the rebuilt image or collect scanner output from the configured security scan workflow.
4. Record the immutable image reference or tag and the scan reference used for the release gate.

For chart or bundle artifacts, use the repo's existing local packaging commands or add a minimal local wrapper. Do not trigger CI or read pipeline output to discover the artifact reference.

## Upload With Bundled Violet Sync

Use `scripts/violet-sync.sh` from this skill when testing locally:

```bash
export PLATFORM_ADDRESS="<platform-url>"
export PLATFORM_USERNAME="<user>"
export PLATFORM_PASSWORD="<password>"
export CLUSTERS="${CLUSTERS:-global}"
export SKIP_PACKAGE_IMAGES="${SKIP_PACKAGE_IMAGES:-true}"
export PACKAGE_PLATFORMS="${PACKAGE_PLATFORMS:-dual}"

path/to/skill/scripts/violet-sync.sh "<chart-or-bundle-artifact>"
```

The script downloads `violet` when needed, rewrites `build-harbor.alauda.cn/...` to the internal registry used by the environment, creates a package, and pushes it to the ACP platform.

## Install

### Cluster Plugin

Use the global cluster:

1. Inspect `ModulePlugin <name>` and matching `ModuleConfig`.
2. If the uploaded version appears as a `ModuleConfig`, patch the existing `ModuleInfo.spec.version`.
3. If a test-only upload does not create `ModuleConfig`, create a test `ModuleConfig` only when the workflow requires it and copy the existing config shape carefully.
4. Wait for `ModuleInfo.status.phase=Running`, `status.version=<version>`, and all `status.appReleases[*].ready=true`.

Do not create `ModuleInfo` directly on the workload cluster.

### OLM Operator

Use `builders-olm-operator-lifecycle`:

1. Confirm the CatalogSource image or bundle source.
2. Confirm OperatorGroup, Subscription, and InstallPlan.
3. Wait for CSV `Succeeded`.
4. Verify operator deployment health and CRD availability.

## E2E

Use a Kubernetes Job with the rebuilt e2e image. If no test scripts, runner image, or sample Job manifest exists, add them before running validation. The job should:

- Run in a dedicated test namespace.
- Use the image tag produced by the current build after Dockerfile and CVE fixes.
- Mount or reference any required kubeconfig, tokens, registry pull secrets, and test data.
- Emit test logs to stdout.
- Print compatibility, performance, and HA evidence in a form that can be copied into release notes or a PR/MR.

After running:

```bash
kubectl --context "$DEV_CONTEXT" get job -n "$TEST_NAMESPACE"
kubectl --context "$DEV_CONTEXT" get pods -n "$TEST_NAMESPACE" -o wide
kubectl --context "$DEV_CONTEXT" logs -n "$TEST_NAMESPACE" job/<job-name> --all-containers=true
```

If the job fails, inspect:

- Image pull errors and missing pull secrets.
- Component pods, AppReleases, ModuleInfo, CSVs, and operator logs.
- RBAC errors from the test service account.
- Network policies and service names.

Fix the repo, Dockerfiles, image dependency inputs, Helm charts, Kubernetes manifests, OLM manifests, or test environment as appropriate, then repeat `builders-alauda-security-scan`, CVE remediation, build, upload, install, and e2e.

## Commit, Push, PR, or MR

Ask the user before committing and pushing unless the original request already explicitly asked for it.

When approved:

1. Re-run the release readiness checklist when the commit is for a release candidate or release branch.
2. Create a focused branch from the target branch.
3. Commit only related repo changes.
4. Push the branch.
5. Create or update the PR/MR.
6. Create or update the PR/MR using the user's configured Git hosting credentials. Review pipelines may run after the MR exists, but they are not the source of the release validation artifacts.

Final reporting should include:

- Commit SHA and branch.
- PR or MR URL.
- Built image references.
- `builders-alauda-security-scan` evidence: image-security-scanner outputs, DB CVE scan status when applicable, dynamic L5 scan status when applicable, and manifest scan references.
- CVE fixes applied to Dockerfiles or image dependency inputs, plus scan references for rebuilt images.
- Helm, Kubernetes, and OLM manifest security scan references, PSA/non-root status, RBAC findings, and residual-risk decisions.
- Uploaded artifact reference.
- Installed component version and status.
- E2E job status and log summary.
- Security gate result and scan references.
- Product documentation repo or directory, updates, and gaps.
- Frozen package CVE database and ERRATA status.
- Compatibility matrix location or table.
- Performance result location or "not applicable".
- HA configuration findings and gaps.
