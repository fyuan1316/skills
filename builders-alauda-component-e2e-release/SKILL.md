---
name: builders-alauda-component-e2e-release
description: |
  Orchestrate end-to-end Alauda component release validation. Use when Codex
  needs to update or sync component code, add or reuse smoke, compatibility,
  performance, and HA e2e tests, add buildkitd-backed image build and artifact
  packaging support, call
  `builders-alauda-security-scan` for image, CVE database, L5, Helm,
  Kubernetes, and OLM scans, fix required CVEs or manifest security issues,
  rebuild and push remediated images through the configured buildkitd server
  before e2e, package/upload with `builders-violet`, install Cluster Plugins
  or OLM operators on a dev ACP cluster, run e2e, update release docs and
  ERRATA evidence, and create or update a PR/MR. For individual sub-steps,
  call the specific builder skill.
allowed-tools: Bash, Read, Edit, Write
---

# Alauda Component E2E Release

Use this skill for full component release validation, from repo changes through dev-cluster e2e. Keep the target component repository as the source of truth and reuse existing project build scripts, image names, and packaging conventions where possible.

Release validation must include project e2e assets and a buildkitd-backed path for building images and packaging/uploading ACP artifacts. If the target project does not have them, add them during the workflow before building, uploading, installing, and running e2e.

Before releasing, design e2e coverage from the component's actual behavior. Inspect whether it provides Kubernetes APIs, CRDs, controllers, admission webhooks, charts, HTTP APIs, CLIs, background jobs, UI/plugin configuration, storage integrations, or hardware integration points. Reuse existing smoke tests when they cover these surfaces; otherwise add the smallest meaningful tests for the installed component. Use `references/pre-release-e2e-test-design.md` for capability inspection, compatibility tests, performance checks, HA documentation, and compatibility matrix output.

Before committing a release candidate or declaring it releasable, also complete the security, product documentation, CVE database, and ERRATA readiness gates in `references/release-readiness-gates.md`. Treat that referenced readiness document as the authority for CVE fix thresholds, residual-risk decisions, evidence requirements, CVE database handling, and ERRATA. These gates come from the ACP 4.0 L5 plugin release flow and Alauda security handling standards.

Before e2e or release validation, call `builders-alauda-security-scan` to complete required image, CVE database, L5 dynamic, Helm, Kubernetes, and OLM security scans. First check `references/release-readiness-gates.md`, then check the scan evidence, security tickets, CVE notes, or vulnerability documents produced or consumed by `builders-alauda-security-scan`. Use those documents to decide which findings are required fixes, false positives, known issues, or approved residual risks. Build the image CVE scan set from the component type: for Cluster Plugins, scan every image listed in the release `values.yaml` files; for OLM operators or Helm operators, scan the operator image, bundle image, and all related runtime images needed when using the component. Inspect every Dockerfile or image dependency input used by component images, chart or bundle images, helper images, and the e2e runner image. Also inspect Helm charts, rendered Kubernetes manifests, and OLM bundle or CSV manifests for security issues including Kubernetes Pod Security Admission compatibility, non-root containers, privilege escalation, Linux capabilities, seccomp, host namespace usage, hostPath, privileged containers, and overbroad RBAC. Update base images, pinned package versions, package manager upgrade steps, lockfiles, chart values, templates, RBAC, or OLM manifests using the repo's existing conventions. Rebuild and push affected images before packaging, installing, and running e2e so the test evidence belongs to the remediated images.

## Required Inputs

Before editing, ask the user for an environment markdown file based on `references/environment-template.md`. Verify access before continuing:

- `buildctl` can reach the configured buildkitd server.
- Registry credentials can push to the image repository and Kubernetes can pull the e2e image.
- Current CVE or vulnerability scan evidence is available, or a repo-supported image scan command can be run before e2e.
- Trivy or an equivalent repo-approved scanner is available for Helm, Kubernetes manifest, OLM bundle, and image scan evidence.
- `kubectl` can access both the dev workload cluster and the corresponding global cluster.
- `PLATFORM_ADDRESS`, `PLATFORM_USERNAME`, and `PLATFORM_PASSWORD` are available for `violet`.
- Git remote access is available if the user wants commit, push, PR, or MR creation.
- Product documentation repo URL or local directory for the current component is known when the work is release-oriented.

For a formal release, release-candidate commit, or full end-to-end release run, also identify the target component version, whether the release is a `.0`, `.x`, security, or non-security release, the previous released version used for bug/CVE comparison, the intended AC product or bundle ID when available, and the product documentation repo or local directory that stores docs for the current component.

If any prerequisite is missing, stop and report the missing item. Do not guess credentials, cluster names, or product documentation locations. If the product documentation location cannot be discovered from the user request or local workspace, ask the user which repo or local directory stores the product documentation before running the full release workflow.

## Workflow

1. Inspect the target repo layout, component type, feature surfaces, build scripts, `.build/` helpers, artifact metadata, image targets, chart or operator package targets, dependency declarations, docs, and existing e2e tests.
2. If the user requested an upstream sync or component upgrade, use `builders-alauda-component-upgrade` first. Preserve Alauda-specific overlays, image names, and packaging behavior.
3. Design or update e2e coverage before release: smoke tests, minimal compatibility tests for Kubernetes and required components, API breaking-change checks where an API exists, API performance checks where endpoints exist, and HA configuration validation or documentation.
4. Run the pre-release security gate early: read `references/release-readiness-gates.md`, then inspect known security tickets, scan reports, dependency and image vulnerability outputs, release type, vulnerability database freeze date, and residual issue approvals. Fix required security issues before freezing the release candidate.
5. Use `builders-alauda-security-scan` to run or collect all required security scan evidence before e2e: `image-security-scanner` image audit, CVE, secret, and virus scans for the component-type-specific image set; DB-driven CVE database scan when product/version metadata exists and covers the same image set; L5 dynamic ACP/Ares scans when an installed environment exists; and Helm, Kubernetes, OLM, PSA, non-root, secret, and RBAC scans.
6. Check Helm charts, rendered Kubernetes manifests, and OLM bundle or CSV manifests for security issues before e2e through `builders-alauda-security-scan`. Fix required PSA, non-root, privilege, capability, seccomp, host access, secret, and RBAC findings in chart values, templates, manifests, or OLM metadata before packaging.
7. Fix required image CVEs before e2e by updating Dockerfiles or image dependency inputs for all images that will be shipped or tested. Use the referenced readiness gates and `builders-alauda-security-scan` output to classify required fixes before editing. Prefer patched base images and pinned dependency updates that match the repo's conventions. Record the CVE IDs or scanner findings addressed and any residual-risk or false-positive decisions.
8. If local ACP artifact packaging and upload support is missing, add it as part of the release work. Use `references/artifact-publishing-buildkitd.md` for the buildkitd image build and local `violet` packaging pattern.
9. If e2e coverage is missing, add the minimal project-appropriate e2e assets before release validation: end-to-end test scripts, an e2e runner image, sample Kubernetes e2e run jobs, and any buildkitd build script needed to produce the runner image.
10. If e2e tests exist but cannot run from an image or Kubernetes Job, adapt them so the workflow can build an e2e image and run a sample e2e Job in the dev cluster.
11. Build and push all affected component, helper, chart or bundle, and e2e runner images with the configured buildkitd and registry credentials. Follow the repo's existing image names and Dockerfile paths instead of inventing new names. Do not run e2e against stale images after Dockerfile or dependency changes.
12. Upload the test artifact with `scripts/violet-sync.sh`. Set platform credentials from the user's environment file and pass the built chart or bundle reference.
13. Install on the dev platform:
   - For Cluster Plugins, create or update `ModuleInfo` on the global cluster, not the workload cluster. Use `builders-install-cluster-plugin`.
   - For OLM operators, use `builders-olm-operator-lifecycle` and install through CatalogSource, Subscription, InstallPlan, CSV, and OperatorGroup as appropriate.
14. Run the e2e job with the rebuilt e2e image and remediated component images. Collect pod status, logs, relevant application status, install status, compatibility evidence, performance results, HA configuration evidence, image references used by the run, and `builders-alauda-security-scan` evidence.
15. Fix failures and repeat manifest security remediation or CVE remediation when needed, then rebuild, call `builders-alauda-security-scan` again for changed scan inputs, upload, install, and e2e until tests pass or a real blocker remains.
16. After tests pass, document the tested compatibility matrix in the repo or release notes when the workflow creates or updates release documentation.
17. Complete the product-documentation gate in the user-confirmed documentation repo or local directory, not by assuming docs live in the component repo: release notes, user/API/operations/deployment/upgrade/DR docs as applicable, product feature list, security statement, lifecycle or support notes, and upgrade matrix.
18. Complete the post-package security and ERRATA gate before formal release: use `builders-alauda-security-scan` to scan the frozen package or final image set when applicable, update the CVE database source when required, compare with the previous release for fixed CVEs, prepare Bugfix ERRATA when bugs were fixed, prepare Security ERRATA when CVEs or security redline issues were fixed, and record AC ERRATA links or an explicit "not applicable" reason.
19. Ask whether to commit and push if the user has not already decided. If approved, create a focused branch, commit, push, and create or update the PR or MR.

## References

- `references/environment-template.md`: markdown file the user should fill before execution.
- `references/artifact-publishing-buildkitd.md`: buildkitd image build and local ACP artifact packaging/upload pattern.
- `references/pre-release-e2e-test-design.md`: capability inspection, stronger e2e coverage, compatibility matrix, performance checks, and HA documentation.
- `references/release-readiness-gates.md`: authoritative security fix thresholds, residual-risk decisions, product document updates, CVE database, and ERRATA checks required before commit or release.
- `references/k8s-helm-olm-security.md`: Trivy-based Helm, Kubernetes manifest, OLM bundle, PSA, non-root, RBAC, and runtime cluster security checks.
- `references/e2e-release-workflow.md`: detailed build, upload, install, e2e, and retry workflow.
- `builders-alauda-security-scan`: required skill for image-security-scanner, DB CVE scan, L5 dynamic scan, and manifest security scan execution and evidence.
- `scripts/violet-sync.sh`: bundled package upload helper copied from the workspace root.

## Rules

- Never store secrets in repo files, skill files, commits, or logs.
- Prefer existing repo build conventions and local helper scripts over new abstractions, but run component image builds through the configured buildkitd server.
- Treat explicit buildkitd-pushed image refs and locally packaged artifact refs as authoritative for release validation.
- Do not trigger GitLab CI, Katanomi Builds, Tekton Pipelines, `BuildRun`, `PipelineRun`, or `TaskRun` objects to control builds or discover image and artifact outputs.
- For Cluster Plugins, use `ModulePlugin`, `ModuleConfig`, and `ModuleInfo` on the global cluster as the primary install surface.
- Keep scratch files outside tracked paths unless the workflow intentionally adds a new repo file.
- Do not invent compatibility support. If a requirement is not documented or tested, mark it as unknown, not required by current evidence, or not tested.
- Do not commit or declare a release ready when required Critical/High security fixes are unresolved, required residual-risk approvals are missing, required product documents are not updated, or required ERRATA/CVE database evidence is missing.
- Report the final component version, CVE fixes applied to Dockerfiles or image dependency inputs, Helm/Kubernetes/OLM security fixes, rebuilt image references and scan evidence, manifest security scan evidence, uploaded artifact reference, install status, e2e result using the rebuilt images, security gate result, product documentation updates, ERRATA/CVE database status, compatibility matrix location, HA findings, performance result location, and PR or MR URL when available.
