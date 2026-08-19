# Artifact Publishing With Buildkitd

Use this reference when the target repo does not already provide a local path to build images, package chart or bundle artifacts, and upload them to ACP.

## Detection

Search the repo before editing:

```bash
rg -n "buildctl|BUILDKITD|violet|helm package|operator-sdk generate bundle|bundle.Dockerfile|artifact_names|artifacts.yaml" .build Makefile scripts charts artifacts
```

If a local build or packaging path is already present, inspect it and update only missing values. Do not add GitLab CI, Katanomi Build, Tekton Pipeline, `BuildRun`, `PipelineRun`, or `TaskRun` definitions to produce release validation artifacts.

## Required Repo Shape

The release workflow needs explicit, reproducible outputs:

- Image refs for every rebuilt component, helper, operator, bundle, and e2e runner image.
- Chart or bundle artifact refs that embed or reference those image refs.
- `artifacts/<artifact-name>/metadata.yaml`, `versions.yaml`, and `artifacts.yaml` when the repo uses Alauda artifact metadata.
- A local packaging command that can run after image build and before ACP upload.

Record image tags and digests in the release notes or result report. The installed package and e2e job must use these same refs.

## Buildkitd Image Build Pattern

Use the buildkitd endpoint from the user environment file:

```bash
buildctl --addr "$BUILDKITD_ADDR" debug workers

buildctl --addr "$BUILDKITD_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=. \
  --local dockerfile=. \
  --opt filename=Dockerfile \
  --opt platform=linux/amd64,linux/arm64 \
  --output "type=image,name=${IMAGE_REF},push=true"
```

Adapt `context`, `dockerfile`, `filename`, `platform`, build args, and labels to the repo's existing image target. Keep the repo's established image names unless the change genuinely adds a new image.

## Chart Artifact Pattern

For Helm chart artifacts, update the chart values with the built image refs, then package and push locally:

```bash
helm dependency update charts/<name>
helm package charts/<name> --version "$ARTIFACT_VERSION" --app-version "$ARTIFACT_VERSION" --destination .build/out
helm push ".build/out/<name>-${ARTIFACT_VERSION}.tgz" "oci://${REGISTRY}/${CHART_REPOSITORY}"
```

If the repo stores Alauda artifact metadata under `artifacts/`, update `versions.yaml` and `artifacts.yaml` with the same artifact version and chart or bundle ref.

## OLM Bundle Pattern

For OLM operators, generate the bundle locally, then build and push the bundle image through buildkitd:

```bash
make bundle IMG="$OPERATOR_IMAGE_REF" VERSION="$BUNDLE_VERSION" CHANNELS=stable

buildctl --addr "$BUILDKITD_ADDR" build \
  --frontend dockerfile.v0 \
  --local context="$OPERATOR_DIR" \
  --local dockerfile="$OPERATOR_DIR" \
  --opt filename=bundle.Dockerfile \
  --opt platform=linux/amd64,linux/arm64 \
  --output "type=image,name=${BUNDLE_IMAGE_REF},push=true"
```

Patch CSV `relatedImages` before the bundle image build so the final bundle records the operator image and dependent runtime images.

## ACP Packaging And Upload

Use `builders-violet` or the repo's local violet wrapper after the chart or bundle ref exists:

```bash
export ARTIFACT="${CHART_OR_BUNDLE_REF}"
export DOCKER_USER="${REGISTRY_USERNAME}"
export DOCKER_PASSWORD="${REGISTRY_PASSWORD}"

violet create "$PACKAGE_NAME" \
  --artifact "$ARTIFACT" \
  --platforms=linux/amd64,linux/arm64 \
  --username="$DOCKER_USER" \
  --password="$DOCKER_PASSWORD"

violet package "$PACKAGE_NAME" \
  --username="$DOCKER_USER" \
  --password="$DOCKER_PASSWORD" \
  --debug

violet push "${PACKAGE_NAME}.tgz" \
  --platform-address "$PLATFORM_ADDRESS" \
  --platform-username "$PLATFORM_USERNAME" \
  --platform-password "$PLATFORM_PASSWORD" \
  --debug
```

The upload must happen after security scans and e2e image rebuilds use the final image refs. Do not upload a package built from stale pre-remediation image tags.

## Notes

- Keep buildkitd and registry credentials out of repo files.
- Use CI only as a post-MR review check. Do not read CI artifact paths, image tags, or generated package versions as release validation evidence.
- If a repo still has legacy `.build/build.yaml` pipeline files, update only the repository metadata needed for review; execute the release validation build with the buildkitd commands above.
