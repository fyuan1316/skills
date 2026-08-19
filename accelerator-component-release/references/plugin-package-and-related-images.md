# Plugin Package And Related Images

Use this reference when a release reaches artifacts-repo registration,
`artifacts-plugin`, AC upload, or related-image packaging failures.

## Registration Rules

- `aml/artifacts` registration is still mandatory even when the component's own
  pipeline produced the chart/image/package.
- Keep two remote refs aligned:
  - `master`: latest registration for the component.
  - `<component>-<version>`: immutable release snapshot for that version.
- For self-built components, `master` and the latest version branch can contain
  the same component metadata.
- Remove stale historical version entries from the active component files on the
  version branch before building or uploading. Do not leave older release
  entries mixed with the current version unless the component format explicitly
  requires a multi-version catalog.
- Keep metadata corrections narrowly scoped. If the maintainer asks for only
  owner/provider changes, do not rewrite display names, descriptions, package
  type, repository, or categories.
- After pushing registration fixes, verify remote content from both refs, for
  example `git show "${ref}:hami/artifacts.yaml"`, and confirm only the target
  version remains.

## Plugin Package Gate

- AC upload requires an installable plugin/package artifact, not just chart and
  image digests.
- First discover whether the component pipeline already produced the formal
  plugin package. If yes, record that package URL and skip `artifacts-plugin`.
- Use `artifacts-plugin` only as the fallback when the component pipeline
  produced chart/image artifacts but no installable plugin package.
- The fallback must run from the artifacts repo release branch
  `<component>-<version>`, with fixed parameter keys. Reject renamed keys or
  unexpected substitutes.
- Confirm `acp_version` compatibility before triggering. If the build template
  rejects an ACP version for the selected product line, narrow the list and
  record why.
- A successful package build proves availability, not correctness. After the
  exact final package is available, run the mandatory single-environment smoke
  defined in `formal-package-smoke.md` before AC upload.
- Do not infer `gate.formal-package-smoke.passed` from package checksums,
  manifest inspection, related-image copy success, retag, or matching source
  commits.

## Related-Image Triage

When `artifacts-plugin` fails while copying related images:

1. Save the BuildRun parameters, final logs, and a redacted failure summary.
2. Compare three sources separately:
   - already published plugin package `manifest.yaml` and `_data/config.yaml`
   - `violet create` log lines such as `found related image`
   - Helm-rendered manifests under the plugin's effective values
3. Do not assume these sets must match. `violet` may scan chart values,
   subcharts, dependencies, or defaults beyond the rendered runtime manifests.
4. Separate package inventory from runtime image addressing. A package may use
   `relatedImages` for discovery and synchronization while runtime manifests
   retain upstream source refs that the platform rewrites through an approved
   image policy. In that model, verify rewrite coverage and actual Pod
   `imageID` values; do not fail only because the Pod spec contains a source
   registry.
5. Inventory package-external runtime images separately. Record the exact ref,
   supported architecture, acquisition/import path, target registry, rewrite
   rule, owner, and runtime verification. Do not silently treat an image as
   delivered merely because a sample or bootstrap template references it.
6. Treat disabled subchart/default-only images and target-cluster-owned images
   as packaging-rule questions, not automatically as component-owned release
   images.
7. For HAMi-style charts, DRA subcharts can introduce DRA driver, webhook, or
   monitor images into the scan even when the main release payload is the HAMi
   chart plus HAMi image. Validate whether they are rendered and supported by
   the delivery plan before packaging them.
8. Target-cluster scheduler images, such as `tkestack/kube-scheduler`, are not
   automatically package-owned just because they appear in a rendered chart.
   Keep cluster dependency, runtime deployment, and package-owned image sets
   separate.
9. If the extra related images point to missing Harbor projects or third-party
   namespaces, do not blindly retry. Choose and record one remedy:
   - exclude non-owned/disabled/default-only images from packaged relatedImages
   - mirror required third-party images to approved registry projects
   - use an approved packtool/violet version that supports the required
     third-party related-image layout
   - change chart/plugin values so package extraction sees the intended image
     set

## Failure Classification

- Stale `artifacts.yaml` entries are registration hygiene issues. Fix them, but
  do not assume they caused a related-image copy failure if `violet create`
  reads the chart artifact directly.
- A successful AC check before `build-plugins` proves metadata compatibility,
  not package build success.
- A package build failure that leaves no plugin package must keep the plugin
  package gate open and block AC upload.
- A package build success without a passing smoke must keep
  `GAP-FORMAL-PACKAGE-SMOKE` open and block AC upload.
- Preserve failed BuildRuns as release evidence. Mark the current candidate and
  explain why older runs are superseded.

## Safety

- Logs may contain registry, S3, or platform credentials. Redact before storing
  excerpts in release evidence.
- Do not delete package objects or rewrite remote branches unless the user has
  approved the exact mutating action.
