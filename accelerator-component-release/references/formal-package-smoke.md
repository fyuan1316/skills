# Formal Package Smoke

Use this reference after the final installable plugin/package artifact exists
and before AC upload or any claim that the formal package is correct.

## Gate Semantics

- `artifact.formal.package.exists=true` proves only that package bytes exist.
- `plugin.package.available=true` proves only that an installable URL is
  available.
- `gate.formal-package-smoke.passed=true` proves that the exact final package
  can be installed and can run a minimal accelerator workload in one
  representative environment.
- Retag, source-commit equality, image-digest equality, reproducible build
  evidence, package-content inspection, and a successful packaging BuildRun do
  not waive the formal package smoke.
- If the smoke cannot run because the environment is unavailable, keep
  `GAP-FORMAL-PACKAGE-SMOKE` open. Do not close it with a waiver.

## Required Action And Facts

Use a blocking action and gap with this contract:

```yaml
- id: action.formal-package-smoke
  requires:
    - artifact.formal.package.exists
    - artifact.formal.images.digest.exists
    - plugin.package.available
  produces:
    - artifact.formal.package.smoke.executed
    - artifact.formal.package.smoke.runtime-digests.verified
    - gate.formal-package-smoke.passed
  closes:
    - GAP-FORMAL-PACKAGE-SMOKE
```

AC upload must require `gate.formal-package-smoke.passed` explicitly. Package
availability or formal image scans are not substitutes.

## Environment Selection

- Use one non-production environment from the blocking compatibility matrix.
- Select an environment that exercises the real install surface and the
  highest-risk runtime path. Record the kubeconfig/env binding, Kubernetes
  version, architecture, accelerator model, driver delivery mode, and runtime.
- Use the architecture-specific package that matches the environment, or the
  `ALL` package when that is the actual delivery path.
- Do not deploy to production to satisfy this gate.

## Minimum Smoke Contract

1. Download the exact final package URL and verify its recorded checksum.
2. Install or upgrade through the real delivery path: final plugin package,
   OLM bundle, or packaged Chart. Do not substitute a source checkout, RC
   package, or direct Helm chart when AC will deliver a plugin package.
3. Verify the installed version, CSV/ModuleConfig/Helm release, workloads, and
   related-image references point to the formal artifacts.
4. Wait for the operator, scheduler, device plugin, runtime hook, webhook, and
   other component-owned workloads that apply to become ready.
5. Run one minimal accelerator workload using the released resource path and
   verify the device is usable, for example `nvidia-smi`, the Ascend equivalent,
   or the component's focused smoke case.
6. Record the running Pods' immutable `imageID` values and verify every
   release-owned runtime image matches the formal digest evidence.
7. Confirm package-owned related images pull successfully and target-cluster
   dependencies are not incorrectly packaged as release-owned images.
8. Delete the smoke workload and verify accelerator resource cleanup. Uninstall
   the package when the environment workflow requires cleanup evidence.

Store the package checksum, environment facts, install output, object status,
workload result, JUnit or equivalent result, Pod image IDs, and cleanup result
under the release run directory.

## Scope Relative To RC Testing

- The RC blocking hardware matrix proves broad function and compatibility.
- Digest-preserving promotion allows that broad RC evidence to carry forward
  for the atomic runtime images.
- The formal package smoke proves the final delivery wrapper and install path.
- If formal runtime image digests differ from the tested RC digests, the smoke
  still remains mandatory but does not by itself establish full RC-matrix
  equivalence. Record and resolve that separate binary-equivalence risk.

## Failure Handling

- Treat install, readiness, image pull, related-image, workload, image-digest,
  or cleanup failures as a blocking formal-package defect.
- Preserve failed smoke evidence and build a new formal package after the fix.
- Re-run the smoke against the new final package bytes; never reuse a pass from
  an older checksum, tag, or package URL.
