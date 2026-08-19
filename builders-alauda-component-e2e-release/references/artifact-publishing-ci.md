# Artifact Publishing CI

Use this reference when the target repo does not already call `ci-templates/build-check-push-artifacts-to-ac.yaml`.

## Detection

Search the repo before editing:

```bash
rg -n "build-check-push-artifacts-to-ac|artifact_names|acp_version|alauda_ai_versions" .build artifacts
```

If the task is already present, inspect the parameters and only update missing values. If it is absent, add push-to-AC artifact publishing CI as part of the release work.

## Required Repo Shape

The reusable task expects artifact directories like:

```text
artifacts/
  <artifact-name>/
    metadata.yaml
    versions.yaml
    artifacts.yaml
```

`artifact_names` must match directories under `artifact_path`. The task writes the CI artifact version into `versions.yaml`, regenerates `artifacts.yaml`, reviews metadata with Codex, builds packages for tag builds, and pushes them to AC.

## Task Reference Pattern

Use this task reference:

```yaml
taskRef:
  resolver: katanomi.dev.gitsource
  params:
    - name: url
      value: https://gitlab-ce.alauda.cn/aml/ci-templates
    - name: revision
      value: refs/heads/main
    - name: pathInRepo
      value: build-check-push-artifacts-to-ac.yaml
```

## Single Artifact Example

Adapt the `mlflow-plugin` pattern for one chart or plugin:

```yaml
- name: ac-push-mlflow
  timeout: 300m
  retries: 0
  runAfter:
    - build-chart-mlflow
  workspaces:
    - name: source
      workspace: source
  params:
    - name: artifact_names
      value: "mlflow"
    - name: git_branch
      value: "$(build.git.revision.raw)"
    - name: acp_version
      value: "$(params.acp_version)"
    - name: alauda_ai_versions
      value: "$(params.alauda_ai_versions)"
    - name: permissive_artifacts
      value: "$(params.ac_artifact_check_permissive_artifacts)"
    - name: artifact_path
      value: artifacts
    - name: artifact_version
      value: "$(build.git.version.docker)"
    - name: artifact_build_archs
      value: "$(params.artifact_build_archs)"
    - name: artifact_build_parallelism
      value: "$(params.artifact_build_parallelism)"
    - name: packtool_version
      value: "$(params.packtool_version)"
    - name: violet_version
      value: "$(params.violet_version)"
    - name: ac_env
      value: "$(params.ac_env)"
    - name: ac_auto_commit
      value: "$(params.ac_auto_commit)"
    - name: ac_reuse_version_meta
      value: "$(params.ac_reuse_version_meta)"
  taskRef:
    resolver: katanomi.dev.gitsource
    params:
      - name: url
        value: https://gitlab-ce.alauda.cn/aml/ci-templates
      - name: revision
        value: refs/heads/main
      - name: pathInRepo
        value: build-check-push-artifacts-to-ac.yaml
```

## Multiple Artifact Pattern

Adapt the `kubeflow-plugin` pattern when one repo publishes multiple artifact directories. Prefer one task call per artifact when the artifacts need different `acp_version` values.

Use:

- `artifact_names`: one artifact directory name, such as `kfbase` or `kubeflow-trainer`.
- `artifact_version`: the same version used by chart/image build tasks.
- `runAfter`: the chart or package task that produces the referenced artifact.
- `acp_version`: a shared param or artifact-specific param when compatibility differs.

## Common Parameters

Add these pipeline params if they are missing:

```yaml
- name: artifact_build_archs
  default: amd64,arm64,ALL
- name: artifact_build_parallelism
  default: "3"
- name: packtool_version
  default: v3.0.1
- name: violet_version
  default: v4.0.0
- name: acp_version
  default: "v4.0,v4.1,v4.2,v4.3"
- name: alauda_ai_versions
  default: "v2.3"
- name: ac_artifact_check_permissive_artifacts
  default: ""
- name: ac_env
  default: all
- name: ac_auto_commit
  default: "true"
- name: ac_reuse_version_meta
  default: "false"
```

## Notes

- The reusable task runs artifact update, review, build, and push only for git tag builds.
- `direct_upload_ac` defaults to `true`; do not set it unless a repo explicitly needs S3 upload behavior.
- The edge cluster must provide the `build-harbor.kauto`, `ac-upload`, `codex-api-key`, and Codex config ConfigMap expected by the task.
