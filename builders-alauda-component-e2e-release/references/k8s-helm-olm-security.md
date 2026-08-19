# Helm, Kubernetes, And OLM Security Checks

Use this reference before packaging, installing, or running e2e for components that ship Helm charts, raw Kubernetes manifests, Cluster Plugin resources, or OLM bundles. In the full release workflow, run these checks through `builders-alauda-security-scan` so image, CVE database, dynamic L5, and manifest security evidence is reported consistently.

Prefer Trivy when it is available because it can scan Kubernetes and Helm configuration for misconfigurations and secrets. Use an equivalent repo-approved scanner only when the repo already standardizes on another tool.

## Inputs To Locate

Identify these files and generated artifacts:

- Helm charts, values files, environment-specific values, and chart dependencies.
- Raw Kubernetes YAML, Kustomize overlays, sample manifests, and e2e Job manifests.
- OLM bundle directories, `ClusterServiceVersion` files, CRDs, webhook manifests, catalog metadata, and bundle Dockerfiles.
- Rendered manifests for the release values that will actually be installed.
- Namespace labels or documented assumptions for Kubernetes Pod Security Admission.
- Existing security scan reports, ignore files, custom Trivy config, and false-positive or residual-risk decisions.

## Trivy Commands

Run the repo's existing scan target when present. Otherwise use commands shaped like these and save the output under an untracked scratch directory unless the repo already has a scan-report location:

```bash
trivy config --scanners misconfig,secret --format table ./charts/<chart>
trivy config --scanners misconfig,secret --format json -o /tmp/<component>-chart-trivy.json ./charts/<chart>
helm template <release-name> ./charts/<chart> -n <namespace> -f <values-file> > /tmp/<component>-rendered.yaml
trivy config --scanners misconfig,secret --format table /tmp/<component>-rendered.yaml
trivy config --scanners misconfig,secret --format json -o /tmp/<component>-rendered-trivy.json /tmp/<component>-rendered.yaml
trivy config --scanners misconfig,secret --format table ./bundle/manifests
trivy fs --scanners vuln,misconfig,secret --format table .
```

When validating a live dev install and cluster access is available, collect runtime evidence:

```bash
trivy k8s -n <namespace> --report summary
trivy k8s -n <namespace> --report all --format json -o /tmp/<component>-k8s-trivy.json
```

Pass Helm value overrides through the scanner when the release uses them, such as `--helm-values`, `--helm-set`, `--helm-set-string`, or `--helm-set-file`. Scan packaged charts only as an additional check; always scan the source chart or rendered manifests when values affect security.

## Required Review Areas

Treat the following as required review areas for every workload manifest and OLM install deployment:

- Pod Security Admission compatibility for the intended namespace level. Prefer `restricted` unless the component has documented reasons for `baseline` or privileged behavior.
- Container and pod `securityContext`: `runAsNonRoot`, non-zero `runAsUser` where compatible, `allowPrivilegeEscalation: false`, `capabilities.drop: ["ALL"]`, explicit added capabilities only when justified, `seccompProfile`, `privileged: false`, and read-only root filesystem decisions.
- Host access: `hostNetwork`, `hostPID`, `hostIPC`, `hostPath`, device mounts, privileged DaemonSets, node selectors, tolerations, and required Linux capabilities.
- Service account token use, projected tokens, image pull secrets, secret mounts, environment variables sourced from secrets, and accidental secret material in manifests.
- RBAC scope: broad verbs such as `*`, broad resources such as `*`, cluster-wide permissions, update or delete on sensitive resources, impersonation, token reviews, subject access reviews, and bind or escalate verbs.
- Network exposure: Services, Ingress, Routes, webhooks, ports, TLS settings, and NetworkPolicy expectations when the component is network-facing.
- Resource controls: CPU and memory requests or limits, probes, disruption budgets, replica settings, leader election, and HA-sensitive settings.
- OLM specifics: `ClusterServiceVersion.spec.install.spec.deployments`, `permissions`, `clusterPermissions`, owned or required CRDs, conversion webhooks, admission webhooks, `relatedImages`, install modes, and catalog or bundle image references.

## Fix Guidance

Apply fixes in the source that owns the generated manifest:

- Update Helm `values.yaml`, schema, and templates instead of editing rendered YAML when a chart owns the field.
- Update OLM bundle source, operator SDK config, CSV templates, or generator input instead of editing generated bundle output when the repo has a generator.
- Keep required privileged behavior documented next to the manifest or in release notes, with residual-risk approval if the release gate requires it.
- Keep image references aligned with the rebuilt CVE-fixed images.
- Avoid adding scanner ignore rules unless the referenced security documents or reviewer decision explicitly approve the exception.

## Evidence To Record

Record these items in the final report, PR/MR, or release notes:

- Trivy or scanner version, command, scan time, input path, and output path.
- Helm values and rendered manifest path used for the release check.
- OLM bundle or CSV path and image references checked.
- PSA target level and pass, fail, or residual-risk status.
- Non-root, privilege, capability, seccomp, host access, secret, and RBAC findings fixed.
- Remaining findings with false-positive, known-issue, not-applicable, or residual-risk decisions and links to the referenced security documents.
