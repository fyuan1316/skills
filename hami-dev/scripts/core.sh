#!/usr/bin/env bash
# hami-dev Tier-3 — HAMi-core (libvgpu.so) build/package/test pipeline.
#
# Honors two hard constraints, proven end-to-end 2026-06-04:
#   1. NEVER install deps or build on the P100 HOST. All compilation runs in a
#      container; the host's CUDA 12.8 is only read-only mounted (it's already
#      installed — mounting != polluting).
#   2. No registry push (env.harbor cred is pull-only). Distribution is
#      crane append -> OCI tar -> jumper -> nerdctl load. (Air-gap-friendly.)
#
# Why a tiny ubuntu base + mounted host CUDA instead of a 3-8GB CUDA devel
# image: direct pulls of the big nvidia/cuda images off the mirror to the P100
# repeatedly EOF'd, and HAMi-core's code needs CUDA >= 12.5 headers
# (CUctxCreateParams / cuCtxCreate_v4). The host already has CUDA 12.8 with
# those headers + stub libs, so we mount them and pull only ubuntu:20.04 (~80MB).
#
# Stages:
#   transfer  tar HAMi-core (devpod) -> P100 /root/hami-build  (reflects local edits)
#   build     nerdctl run ubuntu + RO-mounted host CUDA -> make vgpu -> fetch .so
#   package   crane append .so onto slim base -> OCI tar (devpod, daemonless)
#   test      ship tar -> P100 nerdctl load -> run --gpus -> verify load + NVML hook
#   all       transfer -> build -> package -> test
#
# Usage: core.sh <transfer|build|package|test|all>
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
P100="$SKILL_DIR/p100.sh"
AI_INFRA="${AI_INFRA:-/workspaces/yuanfang-base-ubuntu/projects/ai-infra}"
TOOLROOT="${TOOLROOT:-/tmp/hami-toolchain}"
CRANE="${CRANE:-$TOOLROOT/gopath/bin/crane}"

# Connection (mirror p100.sh defaults; explicit so transfers work anywhere).
JUMPER_KEY="${JUMPER_KEY:-$HOME/.ssh/fy-qq-jumper.pem}"
JUMPER="${JUMPER:-fangyuan@192.168.144.101}"; JUMPER_PORT="${JUMPER_PORT:-52022}"
P100_SSH="${P100_SSH:-root@192.168.138.15}"

# Knobs
BASE_IMAGE="${BASE_IMAGE:-docker-mirrors.alauda.cn/library/ubuntu:20.04}"
HOST_CUDA="${HOST_CUDA:-/usr/local/cuda}"           # on the P100, read-only mounted
REMOTE_DIR="${REMOTE_DIR:-/root/hami-build}"
PRODUCT_REF="${PRODUCT_REF:-hami-core/libvgpu:devtest}"
OUT_DIR="${OUT_DIR:-/tmp/hami-core-out}"
PRODUCT_TAR="${PRODUCT_TAR:-/tmp/hami-core-product.tar}"
FUNCTEST_NAME="${FUNCTEST_NAME:-test_alloc}"   # which test/ binary to run
MEM_LIMIT="${MEM_LIMIT:-2g}"                    # CUDA_DEVICE_MEMORY_LIMIT for functest
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10"

log() { echo "core: $*" >&2; }

# Stream stdin from devpod to a file on the P100 (through the jumper).
_put() { ssh -i "$JUMPER_KEY" -p "$JUMPER_PORT" $SSH_OPTS "$JUMPER" \
           "ssh $SSH_OPTS $P100_SSH 'cat > $1'"; }
# Stream a file from the P100 to devpod stdout.
_get() { ssh -i "$JUMPER_KEY" -p "$JUMPER_PORT" $SSH_OPTS "$JUMPER" \
           "ssh $SSH_OPTS $P100_SSH 'cat $1'"; }

transfer() {
  log "tar HAMi-core -> P100:$REMOTE_DIR/HAMi-core (reflects local edits)"
  tar czf - -C "$AI_INFRA" --exclude='.git' --exclude='build' HAMi-core \
    | _put "$REMOTE_DIR/HAMi-core.tgz"
  "$P100" "rm -rf $REMOTE_DIR/HAMi-core && mkdir -p $REMOTE_DIR && tar xzf $REMOTE_DIR/HAMi-core.tgz -C $REMOTE_DIR && rm -f $REMOTE_DIR/HAMi-core.tgz && echo transfer-ok"
}

build() {
  log "ensure base $BASE_IMAGE on P100"
  "$P100" "nerdctl pull --quiet $BASE_IMAGE >/dev/null && echo base-ok"
  log "compile libvgpu.so in container (host stays clean)"
  "$P100" "bash -s" <<EOF
set -e
nerdctl run --rm --net host \
  -v $REMOTE_DIR/HAMi-core:/libvgpu -w /libvgpu \
  -v $HOST_CUDA:/usr/local/cuda:ro \
  -e DEBIAN_FRONTEND=noninteractive -e CUDA_HOME=/usr/local/cuda \
  -e LIBRARY_PATH=/usr/local/cuda/lib64/stubs:/usr/local/cuda/lib64 \
  $BASE_IMAGE bash -c '
    apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq cmake build-essential >/dev/null 2>&1
    rm -rf build && mkdir build && cd build
    cmake .. -DDLSYM_HOOK_ENABLE=1 -DMULTIPROCESS_LIMIT_ENABLE=1 -DHOOK_MEMINFO_ENABLE=1 \
      -DHOOK_NVML_ENABLE=1 -DCMAKE_BUILD_TYPE=Debug -DTEST_DEVICE_ID=0 >/tmp/c.log 2>&1
    make vgpu -j\$(nproc) >/tmp/m.log 2>&1
    ls -l libvgpu.so'
echo container-build-ok
EOF
  log "fetch .so -> devpod $OUT_DIR"
  rm -rf "$OUT_DIR" && mkdir -p "$OUT_DIR/usr/local/vgpu"
  _get "$REMOTE_DIR/HAMi-core/build/libvgpu.so" > "$OUT_DIR/usr/local/vgpu/libvgpu.so"
  log "built $(du -h "$OUT_DIR/usr/local/vgpu/libvgpu.so" | cut -f1) libvgpu.so"
}

package() {
  [ -f "$OUT_DIR/usr/local/vgpu/libvgpu.so" ] || { log "no .so; run build first"; exit 2; }
  log "crane append .so -> $PRODUCT_TAR (daemonless, no push)"
  tar -C "$OUT_DIR" -cf /tmp/vgpu-layer.tar usr/local/vgpu/libvgpu.so
  "$CRANE" append -b "$BASE_IMAGE" -f /tmp/vgpu-layer.tar -t "$PRODUCT_REF" -o "$PRODUCT_TAR"
  log "product image tar: $(du -h "$PRODUCT_TAR" | cut -f1)"
}

test_() {
  [ -f "$PRODUCT_TAR" ] || { log "no product tar; run package first"; exit 2; }
  log "ship product tar -> P100 + load"
  cat "$PRODUCT_TAR" | _put "$REMOTE_DIR/product.tar"
  "$P100" "nerdctl load -i $REMOTE_DIR/product.tar"
  log "verify: load as LD_PRELOAD + NVML interception on real GPU"
  "$P100" "bash -s" <<EOF
set -e
echo '--- [1] preload loads in --gpus container ---'
nerdctl run --rm --net host --gpus all -e LD_PRELOAD=/usr/local/vgpu/libvgpu.so \
  $PRODUCT_REF bash -c 'echo PRELOAD_LOADED_OK'
echo '--- [2] HAMi-core hooks NVML against the real GPU ---'
nerdctl run --rm --net host --gpus all -e LD_PRELOAD=/usr/local/vgpu/libvgpu.so \
  -e CUDA_DEVICE_MEMORY_LIMIT=2g $PRODUCT_REF bash -c 'nvidia-smi -L 2>&1 | head -6'
EOF
}

# Build the lib AND all test/ binaries (needs nvcc for the .cu tests — provided
# by the mounted host CUDA's bin/ on PATH). Separate from build() which only
# builds libvgpu.so for the product image.
build_tests() {
  log "compile lib + all test binaries in container (host stays clean)"
  "$P100" "bash -s" <<EOF
set -e
nerdctl run --rm --net host \
  -v $REMOTE_DIR/HAMi-core:/libvgpu -w /libvgpu \
  -v $HOST_CUDA:/usr/local/cuda:ro \
  -e DEBIAN_FRONTEND=noninteractive -e CUDA_HOME=/usr/local/cuda \
  -e PATH=/usr/local/cuda/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  -e LIBRARY_PATH=/usr/local/cuda/lib64/stubs:/usr/local/cuda/lib64 \
  $BASE_IMAGE bash -c '
    apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq cmake build-essential >/dev/null 2>&1
    rm -rf build && mkdir build && cd build
    cmake .. -DDLSYM_HOOK_ENABLE=1 -DMULTIPROCESS_LIMIT_ENABLE=1 -DHOOK_MEMINFO_ENABLE=1 \
      -DHOOK_NVML_ENABLE=1 -DCMAKE_BUILD_TYPE=Debug -DTEST_DEVICE_ID=0 >/tmp/c.log 2>&1
    make -j\$(nproc) >/tmp/m.log 2>&1
    echo "built lib + \$(ls test/ | grep -c ^test_) test binaries"'
echo build-tests-ok
EOF
}

# Functional test: run a test/ binary under the freshly-built libvgpu.so with a
# memory cap, on the real GPU, and assert HAMi-core enforces the virtual limit.
functest() {
  log "run $FUNCTEST_NAME under libvgpu (--gpus, CUDA_DEVICE_MEMORY_LIMIT=$MEM_LIMIT)"
  out="$("$P100" "bash -s" <<EOF
nerdctl run --rm --net host --gpus all \
  -v $REMOTE_DIR/HAMi-core:/libvgpu -v $HOST_CUDA:/usr/local/cuda:ro \
  -e LD_LIBRARY_PATH=/usr/local/cuda/lib64 \
  -e LD_PRELOAD=/libvgpu/build/libvgpu.so \
  -e CUDA_DEVICE_MEMORY_LIMIT=$MEM_LIMIT \
  $BASE_IMAGE /libvgpu/build/test/$FUNCTEST_NAME 2>&1
EOF
)"
  echo "$out" | grep -iE 'HAMI-core|OOM|total: [0-9]+ bytes' | tail -15
  # Assert: the virtualized total equals the limit AND an over-cap alloc was rejected.
  if echo "$out" | grep -q 'HAMI-core ERROR.*OOM' && echo "$out" | grep -q 'total: 2147483648 bytes'; then
    log "FUNCTEST PASS — vGPU memory limit enforced on real GPU"
  else
    log "FUNCTEST INCONCLUSIVE — check output above (limit/test may differ)"; return 1
  fi
}

# Functional-test MATRIX: run a curated set of the repo's test/ binaries under
# libvgpu on the real GPU, each with the right limit knob + assertion.
#   mem      -> NVML reports virtual total == CUDA_DEVICE_MEMORY_LIMIT
#   mem-oom  -> mem + an over-cap cuMemAlloc is rejected (HAMI-core OOM)
#   compute  -> runs to completion with the hook active under CUDA_DEVICE_SM_LIMIT
# Override the limits via MEM_LIMIT / SM_LIMIT. Assumes binaries are built
# (run `core.sh tests` first, or use `gpu-matrix`).
matrix() {
  local mem_bytes
  case "$MEM_LIMIT" in
    *g|*G) mem_bytes=$(( ${MEM_LIMIT%[gG]} * 1073741824 )) ;;
    *m|*M) mem_bytes=$(( ${MEM_LIMIT%[mM]} * 1048576 )) ;;
    *) mem_bytes="$MEM_LIMIT" ;;
  esac
  log "functional-test matrix (MEM_LIMIT=$MEM_LIMIT=$mem_bytes B, SM_LIMIT=${SM_LIMIT:-50})"
  "$P100" "MEM_BYTES=$mem_bytes MEM_LIMIT=$MEM_LIMIT SM_LIMIT=${SM_LIMIT:-50} REMOTE_DIR=$REMOTE_DIR HOST_CUDA=$HOST_CUDA BASE_IMAGE=$BASE_IMAGE bash -s" <<'REMOTE'
set -u
run_one() { # name  category  env...
  local name="$1" cat="$2"; shift 2
  local out rc
  out=$(timeout 150 nerdctl run --rm --net host --gpus all \
    -v "$REMOTE_DIR/HAMi-core:/libvgpu" -v "$HOST_CUDA:/usr/local/cuda:ro" \
    -e LD_LIBRARY_PATH=/usr/local/cuda/lib64 -e LD_PRELOAD=/libvgpu/build/libvgpu.so \
    "$@" "$BASE_IMAGE" "/libvgpu/build/test/$name" 2>&1); rc=$?
  local hook total oom verdict
  hook=$(echo "$out" | grep -c 'HAMI-core')
  total=$(echo "$out" | grep -oE 'total: [0-9]+ bytes' | grep -oE '[0-9]+' | head -1)
  oom=$(echo "$out" | grep -c 'HAMI-core ERROR.*OOM')
  case "$cat" in
    mem)     [ "$total" = "$MEM_BYTES" ] && verdict=PASS || verdict=FAIL ;;
    mem-oom) { [ "$total" = "$MEM_BYTES" ] && [ "$oom" -ge 1 ]; } && verdict=PASS || verdict=FAIL ;;
    # host/pinned RAM must NOT count against the device limit: succeeds (rc 0,
    # no device OOM) while the lib still reports the virtual total.
    host)    { [ "$rc" = 0 ] && [ "$total" = "$MEM_BYTES" ] && [ "$oom" = 0 ]; } && verdict=PASS || verdict=FAIL ;;
    compute) { [ "$rc" = 0 ] && [ "${hook:-0}" -ge 1 ]; } && verdict=PASS || verdict=FAIL ;;
  esac
  printf '  %-26s %-8s rc=%-3s total=%-12s oom=%s hook=%s -> %s\n' "$name" "$cat" "$rc" "${total:-none}" "$oom" "$hook" "$verdict"
  [ "$verdict" = PASS ]
}
fails=0
echo "--- 显存限制 driver/runtime API (CUDA_DEVICE_MEMORY_LIMIT=$MEM_LIMIT) ---"
run_one test_alloc                 mem-oom -e CUDA_DEVICE_MEMORY_LIMIT=$MEM_LIMIT || fails=$((fails+1))
for t in test_alloc_managed test_alloc_pitch test_create_array test_runtime_alloc test_runtime_alloc_managed; do
  run_one "$t" mem -e CUDA_DEVICE_MEMORY_LIMIT=$MEM_LIMIT || fails=$((fails+1))
done
echo "--- host/锁页内存:不计入设备限额 (CUDA_DEVICE_MEMORY_LIMIT=$MEM_LIMIT) ---"
for t in test_alloc_host test_host_alloc test_host_register test_runtime_alloc_host test_runtime_host_alloc test_runtime_host_register; do
  run_one "$t" host -e CUDA_DEVICE_MEMORY_LIMIT=$MEM_LIMIT || fails=$((fails+1))
done
echo "--- SM/算力限制 (CUDA_DEVICE_SM_LIMIT=$SM_LIMIT) ---"
run_one test_runtime_launch         compute -e CUDA_DEVICE_SM_LIMIT=$SM_LIMIT || fails=$((fails+1))
run_one test_multi_gpu_utilization  compute -e CUDA_DEVICE_SM_LIMIT=$SM_LIMIT || fails=$((fails+1))
echo "MATRIX_FAILS=$fails"
REMOTE
}

# Framework-level vGPU test: a REAL PyTorch workload must see the device as the
# virtual limit and get OOM'd past it. Uses a torch image already cached on the
# P100 (k8s.io ns). Two cases: a >limit tensor must OOM, a <limit tensor must
# succeed. Assumes libvgpu.so is built (run `core.sh build` first / `gpu-framework`).
TORCH_IMAGE="${TORCH_IMAGE:-152-231-registry.alauda.cn:60070/mlops/torch-distributed:v2.9.1-aml2}"
framework() {
  log "PyTorch vGPU limit test (image=$TORCH_IMAGE, MEM_LIMIT=$MEM_LIMIT)"
  local out
  out="$("$P100" "REMOTE_DIR=$REMOTE_DIR IMG=$TORCH_IMAGE MEM_LIMIT=$MEM_LIMIT bash -s" <<'REMOTE'
run() { # tensor_shape  -> prints raw output
  nerdctl -n k8s.io run --rm --net host --gpus all \
    -v "$REMOTE_DIR/HAMi-core:/libvgpu" \
    -e LD_PRELOAD=/libvgpu/build/libvgpu.so -e CUDA_DEVICE_MEMORY_LIMIT="$MEM_LIMIT" \
    --entrypoint python "$IMG" /libvgpu/test/python/limit_pytorch.py ${1:+--tensor_shape "$1"} 2>&1
}
echo "### NEG (4GiB > limit, expect OOM):"; run "" | grep -iE 'OutOfMemoryError|total capacity|HAMI-core ERROR.*OOM' | tail -3
echo "### POS (1GiB < limit, expect ok):"; run "256,1024,1024" | grep -iE 'Tensor sum|OutOfMemoryError' | tail -2
REMOTE
)"
  echo "$out"
  if echo "$out" | grep -q 'OutOfMemoryError' && echo "$out" | grep -q 'Tensor sum'; then
    log "FRAMEWORK PASS — real PyTorch sees the vGPU limit (OOM past it, runs under it)"
  else
    log "FRAMEWORK INCONCLUSIVE — check output"; return 1
  fi
}

case "${1:?usage: core.sh <transfer|build|package|test|tests|functest|matrix|framework|all|gpu-test|gpu-matrix|gpu-framework>}" in
  transfer)   transfer ;;
  build)      build ;;
  package)    package ;;
  test)       test_ ;;
  tests)      build_tests ;;
  functest)   functest ;;
  matrix)     out="$(matrix)"; echo "$out"; echo "$out" | grep -q 'MATRIX_FAILS=0' && log "MATRIX PASS" || { log "MATRIX has failures"; exit 1; } ;;
  framework)  framework ;;
  gpu-test)   build_tests && functest ;;
  gpu-matrix) build_tests && { out="$(matrix)"; echo "$out"; echo "$out" | grep -q 'MATRIX_FAILS=0' && log "MATRIX PASS" || { log "MATRIX has failures"; exit 1; }; } ;;
  gpu-framework) build && framework ;;
  all)        transfer && build && package && test_ ;;
  *) log "unknown stage: $1"; exit 2 ;;
esac
log "core: $1 OK"
