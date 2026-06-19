---
name: hami-dev
description: Drive the HAMi accelerator tech-stack dev/test loop on the devpod (and, for GPU functional tests, on the remote P100). One iteration = edit source → build → unit-test, returning a PASS/FAIL verdict; the model loops by re-invoking after each change. Tier 1 (no hardware, on devpod): `go build` + `go test ./pkg/...` for the Go repos under projects/ai-infra (HAMi, dcgm-exporter, HAMi-WebUI). Tier 3 (real hardware): accelerator-test Ginkgo e2e + HAMi-core CUDA build, run on the Tesla P100 via the jumper. Use when the user asks to "build HAMi", "run HAMi unit tests", "test the HAMi scheduler/device-plugin", "iterate on HAMi-core", "set up the HAMi dev environment", "bootstrap the Go toolchain for HAMi", "run accelerator-test e2e", or describes an edit→build→test loop on any repo under projects/ai-infra. Handles toolchain bootstrap onto the big ephemeral disk automatically (source stays on the small persistent volume).
---

# hami-dev (HAMi 加速器技术栈 开发→测试 闭环)

One iteration of the dev/test loop for the HAMi tech stack living under
`projects/ai-infra/`. Each pass produces a verdict; the model edits code then
re-invokes the driver, loops until green.

## Why this skill exists (the two hard constraints)

The devpod is Linux but **bare** (no go/cmake/docker) and its **persistent
volume has ~1G free**, while the container overlay has >200G but only `/tmp` is
writable and is wiped on pod restart. And HAMi-core (CUDA) + the e2e suite need
a **real GPU**, which the devpod lacks. So the design splits work by *what it
actually needs*:

```
                        runs on            hardware     entry
 Tier 1  unit + build   devpod             none         scripts/run.sh
 Tier 2  static/lint    devpod             none         (go vet / staticcheck)
 Tier 3  e2e + CUDA     P100 via jumper    NVIDIA GPU   scripts/p100.sh + accelerator-test
```

Toolchain + caches go on the big ephemeral disk (`/tmp/hami-toolchain`); source
stays on `/workspaces`. `scripts/bootstrap.sh` is idempotent and cheap to re-run
after a pod restart — `run.sh` calls it automatically when the toolchain is
absent.

## Repos (projects/ai-infra/)

| alias | dir | lang | Tier-1 verified |
|---|---|---|---|
| `hami` | HAMi | Go (scheduler, device-plugin, vGPUmonitor) | ✅ |
| `dcgm-exporter` | dcgm-exporter | Go (DCGM via dlopen) | build ✅ devpod; 13/16 unit pkgs pass devpod; 3 needing `libdcgm.so`/NVML pass on P100 via `run.sh dcgm-exporter gputest` ✅ |
| `hami-webui` | HAMi-WebUI | Go + TS | backend buildable |
| `hami-core` | HAMi-core | C/CUDA (libvgpu.so) | Tier 3 only (CUDA headers) |
| `e2e` | accelerator-test | Go/Ginkgo e2e | Tier 3 only (needs cluster+HW) |

## Tier 1 — one iteration (devpod, no hardware)

```bash
scripts/run.sh hami                      # hack/unit-test.sh → go test ./pkg/...
scripts/run.sh hami build-test           # build all ./cmd/... then unit test
scripts/run.sh hami pkg:./pkg/device/... # scope to one package (fast inner loop)
scripts/run.sh hami build                # compile binaries only
scripts/run.sh hami lint                 # Tier 2 gate: go vet + golangci-lint (repo's make lint)
scripts/run.sh hami lint:./pkg/device/...# scoped lint (fast inner loop)
```

**Tier 2 gate (VERIFIED).** `lint` runs `go vet` + `golangci-lint` v2.8.0 (the
repo's own `.golangci.yaml`: asciicheck/forcetypeassert/godot/misspell/modernize/
staticcheck). golangci-lint auto-installs via `go install` to the big disk on
first use. Gate fails (non-zero) if EITHER tool flags anything — proven to catch
a `misspell` finding and to pass clean.
The driver: bootstrap-if-needed → `source /tmp/hami-toolchain/env.sh` → cd repo
→ build/test → prints `hami-dev: PASS (<repo>/<mode>)` or fails non-zero.

**Loop contract:** model edits source under `projects/ai-infra/<repo>/`, invokes
`run.sh`, reads the verdict, fixes, repeats. First run downloads the module graph
(~4 min, network-bound); it caches on the big disk, so later runs are seconds.

## Tier 3 — HAMi-core build + GPU functional test (P100 via jumper) — VERIFIED

`scripts/core.sh` runs the full libvgpu.so pipeline; `run.sh hami-core` delegates
to it. Proven end-to-end 2026-06-04 against the Tesla P100.

```bash
scripts/run.sh hami-core            # transfer -> build -> package -> test (all)
scripts/core.sh build               # just compile libvgpu.so (in-container)
scripts/core.sh package             # crane append .so -> OCI tar
scripts/core.sh test                # ship -> load -> --gpus run -> verify hook
scripts/core.sh gpu-test            # build lib+tests, run ONE test/ binary on real GPU
scripts/core.sh gpu-matrix          # build lib+tests, run the 7-case functional MATRIX
scripts/core.sh matrix              # run the matrix (assumes already built)
scripts/run.sh hami-core functest   # just run one functional test (assumes built)
scripts/p100.sh 'nvidia-smi -L'     # ad-hoc command on the P100
```

**Functional tests (vGPU isolation, VERIFIED).** The repo ships 17 `test/`
programs; `gpu-test`/`gpu-matrix` build all of them (the `.cu` ones via nvcc from
the mounted host CUDA on PATH) and run them under `LD_PRELOAD=libvgpu.so` on the
real P100.

- `functest` (1 case): `FUNCTEST_NAME` (default `test_alloc`) under
  `CUDA_DEVICE_MEMORY_LIMIT` (default 2g). Asserts the NVML virtual total ==
  limit (2147483648, not the physical 16G) AND an over-cap `cuMemAlloc` is
  rejected — `[HAMI-core ERROR ... allocator.c]: Device 0 OOM ... / 2147483648`.
- `matrix` (14 cases, all PASS) — three assertion categories:
  - **device memory** (6): `test_alloc` (driver, +OOM), `test_alloc_managed`,
    `test_alloc_pitch`, `test_create_array`, `test_runtime_alloc`,
    `test_runtime_alloc_managed` — assert virtual total == `MEM_LIMIT`.
  - **host/pinned memory** (6): `test_alloc_host`, `test_host_alloc`,
    `test_host_register`, `test_runtime_alloc_host`, `test_runtime_host_alloc`,
    `test_runtime_host_register` — assert host RAM is NOT counted against the
    device limit (rc 0, no device OOM, lib still reports virtual total).
  - **SM/compute** (2): `test_runtime_launch`, `test_multi_gpu_utilization`
    under `CUDA_DEVICE_SM_LIMIT` — assert run completes with the hook active.
  Tune via `MEM_LIMIT` / `SM_LIMIT`. (`test_mem_create` VMM path doesn't surface
  a usage total, so it's built but excluded from the asserted set.)
- `framework` / `gpu-framework` (VERIFIED) — the crown-jewel test: a REAL
  PyTorch workload under `LD_PRELOAD=libvgpu.so` + `CUDA_DEVICE_MEMORY_LIMIT`.
  Uses a torch image already cached on the P100 (`TORCH_IMAGE`, default
  `…/mlops/torch-distributed:v2.9.1-aml2`, run via `nerdctl -n k8s.io`). Asserts
  both directions: a 4 GiB tensor is OOM'd (`torch.OutOfMemoryError ... total
  capacity of 2.00 GiB` — PyTorch sees the virtual limit, not the physical 16G)
  and a 1 GiB tensor succeeds (`Tensor sum: …`). This is the product value
  end-to-end: a real ML framework constrained by HAMi-core's vGPU limit.

Pipeline and the two hard rules it honors:
1. **Never build or install on the P100 host.** Compilation runs in an
   `ubuntu:20.04` container with the host's already-installed CUDA 12.8
   read-only mounted (`-v /usr/local/cuda:...:ro`) — mounting ≠ polluting. We
   use a tiny ubuntu base (not a 3–8GB `nvidia/cuda` devel image) because direct
   pulls of the big images off the mirror to the P100 repeatedly EOF'd, and the
   host CUDA 12.8 already has the headers HAMi-core needs (CUDA ≥ 12.5:
   `CUctxCreateParams` / `cuCtxCreate_v4`) plus stub libs for `-lcuda -lnvidia-ml`.
2. **No registry push** (env.harbor is pull-only). Packaging is **crane**
   `append` (daemonless, on devpod) → OCI tar → jumper → `nerdctl load`. Same
   path works for air-gapped GPU boxes. (If a push-capable harbor robot becomes
   available, `crane push` the product to `build-harbor.alauda.cn/test/...`
   instead of shipping the tar.)

```
devpod                                   P100 (host stays clean)
 tar HAMi-core ───jumper──────────────►  /root/hami-build/HAMi-core
                                         nerdctl run ubuntu + RO host CUDA → make vgpu → libvgpu.so
 libvgpu.so ◄──jumper─────────────────── (fetch)
 crane append → 27MB product OCI tar ───jumper──► nerdctl load
                                         nerdctl run --gpus all -e LD_PRELOAD=…  → NVML hook fires
```

Verified output: `PRELOAD_LOADED_OK` + `[HAMI-core Msg(...)]` hook logs printed
alongside the real `Tesla P100-PCIE-16GB` from `nvidia-smi` — i.e. the hijack lib
loads and instruments the process against the physical GPU.

### accelerator-test — Ginkgo k8s e2e (VERIFIED)

Runs **from devpod** against the P100's cluster (devpod reaches the API + has Go;
the cluster `g1-c1-x86` already runs hami-scheduler + hami-device-plugin, so no
deploy step). Kubeconfig: `envs/kubeconfig/g1-c1-x86.yaml` (single source).

```bash
scripts/run.sh e2e            # = e2e-test-smoke, E2E_PLATFORM=hami
scripts/run.sh e2e sanity     # smoke || sanity
scripts/run.sh e2e full       # everything applicable
```
The driver installs ginkgo (pinned to the repo's go.mod) on first use, then runs
`make e2e-test-<type>` with `KUBE_CONF=envs/kubeconfig/g1-c1-x86.yaml`,
`E2E_PLATFORM=hami`, `E2E_IMAGE_REGISTRY=docker-mirrors.alauda.cn` (internal
mirror so nodes can pull the CUDA test image), `E2E_GOPROXY=goproxy.cn`. The
suite auto-detects platform (hami/pgpu/pnpu) and skips inapplicable cases.
Verified: smoke → `1 Passed | 0 Failed | 12 Skipped, Test Suite Passed` (the
hami vGPU memory-isolation spec scheduled + ran on the real cluster). Override
`KUBE_CONF` / `E2E_PLATFORM` / `E2E_IMAGE_REGISTRY` as needed.

### dcgm-exporter hardware unit tests (VERIFIED)

3 of dcgm-exporter's 16 unit-test packages need real DCGM/NVML and fail on the
GPU-less devpod. `scripts/dcgm.sh` (via `run.sh dcgm-exporter gputest`) compiles
them on devpod (`go test -c` — go-dcgm/go-nvml dlopen at runtime, nothing to
link) and runs them on the P100: `nvmlprovider` in `ubuntu:22.04` + `--gpus`
(NVML only), `transformation` + `cmd` in the dcgm-exporter image + `--gpus`
(carries `libdcgm`). Verdict by the test binary's exit code. Verified 3/3 PASS.
Note the compiled binaries link devpod glibc (≥2.34) so the run base must be
≥ ubuntu:22.04 (ubuntu:20.04 fails: `GLIBC_2.34 not found`).

## fix-label — correct a repo's OCI build-image source label

`run.sh <repo> fix-label` (→ `scripts/label.sh <repo>`) fixes the
`org.opencontainers.image.source` in that repo's `.build/build.yaml` to
`aml/ai-infra/<repo>` (several repos copy-pasted the labels block and left the
wrong repo). Pure GitLab API (token from `envs/env.gitlab`): creates
`feat/aml-dev-fix-oci-image-source` off the repo's trunk (HAMi→release-2.8, else
master), commits the one-line fix, opens an MR, and **stops — never merges**.
Per-repo (the correct value IS the repo). No-ops if already correct; aborts if
the labels block is missing entirely (that repo needs the block ADDED, a
different change). Uses yuanfang's Developer token from
`/workspaces/home/secrets/gitlab.token` (NOT `envs/env.gitlab`, which is the
alaudabot **admin** token — authored work must show as the real author) and sets
the commit author explicitly. GitLab 14.x files API needs `encoding=base64`.
Verified on HAMi → MR !51 (clean 1-line, author=yuanfang, can_be_merged).

## Scope / non-goals

- Does **not** commit or push. Feature work belongs on `feat/*` branches off the
  repo's trunk (see memory feedback-branch-workflow); the model creates those
  only when the user asks.
- Tier 1 green never implies Tier 3 passed — hardware paths are explicitly
  separate so a unit-test PASS can't be mistaken for a GPU-validated change.
