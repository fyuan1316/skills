# accelerator-test Map

## Repo Role

`accelerator-test` is the executable backend for GPU/NPU e2e:

- HAMi: virtual GPU/NPU via `hami-scheduler`, `hami-device-plugin`, `hami-ascend-device-plugin`.
- PGPU: physical NVIDIA GPU via Alauda `nvidia-device-plugin`.
- pNPU: physical Ascend NPU via `npu-operator`, `ascend-device-plugin`, and `RuntimeClass=ascend`.

## Important Entry Points

| File | Use |
|---|---|
| `Makefile` | Main commands and version/deploy variables |
| `hack/e2e-test.sh` | Ginkgo runner, scope and label filtering |
| `hack/run-full-e2e-with-report.sh` | Full run with guaranteed JUnit artifact behavior |
| `hack/hami-deploy.sh` | HAMi ModulePlugin/ModuleInfo deploy/upgrade |
| `hack/pgpu-deploy.sh` | PGPU deploy/upgrade |
| `hack/pnpu-deploy.sh` | pNPU deploy/upgrade |
| `test/utils/e2e_env.go` | Platform/resource detection, scheduler/runtime/resource names |
| `test/e2e/hami/` | HAMi vGPU/vNPU behavior |
| `test/e2e/compatibility/` | CUDA compatibility matrix |
| `test/e2e/pgpu/` | physical GPU, MIG, time-slicing |
| `test/e2e/pnpu/` | Ascend NPU operator/plugin/runtime behavior |

## Platform Selection

Use explicit `E2E_PLATFORM` for release runs:

- `hami`: excludes `pgpu-only` and `pnpu-only`.
- `pgpu`: excludes `hami-only`, `ascend-only`, and `pnpu-only`.
- `pnpu`: excludes `hami-only`, `pgpu-only`, and HAMi-Ascend `ascend-only`.
- `auto` or empty: cases self-skip based on detected platform.

## Scope Selection

| Scope | Meaning |
|---|---|
| `smoke` | minimal smoke labels |
| `sanity` | smoke plus sanity labels |
| `full` | all applicable specs |
| `focus` | requires `FOCUS_FILES` |

## Key Variables

HAMi:

- `HAMI_AUTO_DEPLOY=true|false`
- `HAMI_DEPLOY_MODE=auto|vgpu|vnpu`
- `HAMI_VERSION`
- `HAMI_WEBUI_VERSION`
- `HAMI_GLOBAL_KUBE_CONF`, `HAMI_BUSINESS_KUBE_CONF`
- `E2E_ACCEL=nvidia|ascend`

PGPU:

- `PGPU_AUTO_DEPLOY=true|false`
- `PGPU_VERSION`
- `PGPU_MIG_STRATEGY=none|single|mixed`
- `PGPU_GLOBAL_KUBE_CONF`, `PGPU_BUSINESS_KUBE_CONF`

pNPU:

- `PNPU_AUTO_DEPLOY=true|false`
- `PNPU_NPU_OPERATOR_VERSION`
- `PNPU_DRIVER_VERSION`
- `PNPU_GLOBAL_KUBE_CONF`, `PNPU_BUSINESS_KUBE_CONF`

Shared:

- `KUBE_CONF`
- `E2E_NAMESPACE`
- `E2E_IMAGE_REGISTRY`
- `E2E_GPU_NODE`
- `E2E_NVIDIA_COUNT_RESOURCE`
- `JUNIT_REPORT`

## Failure Interpretation

- Deploy script fails before Ginkgo: classify as packaging/platform/plugin deployment failure.
- Platform detection fails: inspect installed plugin resources, node allocatable, CRDs, and `E2E_PLATFORM` override.
- Compatibility matrix fails only on old CUDA image: preserve CUDA version/image and GPU driver/runtime evidence.
- Pod Pending: inspect scheduler name, node labels, resource names, allocatable, taints, and events.
- Pod Running but workload fails: inspect device allocation env, mounts, runtime class, `nvidia-smi` or `npu-smi`.
