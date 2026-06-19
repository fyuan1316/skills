#!/usr/bin/env bash
# hami-dev Tier-3 for dcgm-exporter — the unit-test packages that need real
# DCGM/NVML can't run on the GPU-less devpod (they fail with `libdcgm.so not
# found` / NVML-not-initialized there). Compile-on-devpod, run-on-P100, same
# split as core.sh:
#   nvmlprovider   -> ubuntu:22.04 + --gpus       (needs NVML only)
#   transformation -> dcgm-exporter image + --gpus (needs libdcgm)
#   cmd            -> dcgm-exporter image + --gpus (needs libdcgm)
#
# `go test -c` works on devpod because go-dcgm/go-nvml dlopen their libs at
# runtime (nothing to link). The binaries link devpod's glibc (>=2.34), so the
# run base must be >= ubuntu:22.04 (ubuntu:20.04 fails: GLIBC_2.34 missing). The
# dcgm-exporter image is 22.04-based, so it satisfies this too.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
P100="$SKILL_DIR/p100.sh"
AI_INFRA="${AI_INFRA:-/workspaces/yuanfang-base-ubuntu/projects/ai-infra}"
TOOLROOT="${TOOLROOT:-/tmp/hami-toolchain}"
JUMPER_KEY="${JUMPER_KEY:-$HOME/.ssh/fy-qq-jumper.pem}"
JUMPER="${JUMPER:-fangyuan@192.168.144.101}"; JUMPER_PORT="${JUMPER_PORT:-52022}"
P100_SSH="${P100_SSH:-root@192.168.138.15}"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10"

# dcgm-exporter image (carries libdcgm); default = what the cluster runs.
DCGM_IMAGE="${DCGM_IMAGE:-152-231-registry.alauda.cn:60070/mlops/dcgm-exporter:v4.2.3-4.1.3-fabb1dd8}"
NVML_BASE="${NVML_BASE:-docker-mirrors.alauda.cn/library/ubuntu:22.04}"
OUT=/tmp/dcgm-tests
REMOTE=/root/dcgm-tests

log() { echo "dcgm: $*" >&2; }
_put() { ssh -i "$JUMPER_KEY" -p "$JUMPER_PORT" $SSH_OPTS "$JUMPER" "ssh $SSH_OPTS $P100_SSH 'cat > $1'"; }

# shellcheck disable=SC1091
. "$TOOLROOT/env.sh"

log "compile DCGM/NVML test binaries on devpod (go test -c)"
rm -rf "$OUT" && mkdir -p "$OUT"
cd "$AI_INFRA/dcgm-exporter"
GOPROXY="${GOPROXY:-https://goproxy.cn,direct}" go test -c -o "$OUT/nvmlprovider.test"   ./internal/pkg/nvmlprovider
GOPROXY="${GOPROXY:-https://goproxy.cn,direct}" go test -c -o "$OUT/transformation.test" ./internal/pkg/transformation
GOPROXY="${GOPROXY:-https://goproxy.cn,direct}" go test -c -o "$OUT/cmd.test"            ./pkg/cmd

log "ship test binaries -> P100:$REMOTE"
tar czf - -C "$OUT" . | _put "$REMOTE.tgz"
"$P100" "rm -rf $REMOTE && mkdir -p $REMOTE && tar xzf $REMOTE.tgz -C $REMOTE && rm -f $REMOTE.tgz && echo ship-ok"

log "run on P100 GPU (nvml->ubuntu, dcgm->dcgm-exporter image)"
out="$("$P100" "REMOTE=$REMOTE NVML_BASE=$NVML_BASE DCGM_IMAGE=$DCGM_IMAGE bash -s" <<'REMOTE_EOF'
run() { # base  binary  — verdict by the test binary's EXIT CODE (0 = pass);
        # tail-grepping "PASS" is unreliable since goroutines log after it.
  local base="$1" bin="$2"
  if timeout 180 nerdctl run --rm --net host --gpus all -v "$REMOTE:/t" \
        --entrypoint "/t/$bin" "$base" -test.v >"/tmp/$bin.log" 2>&1; then
    echo "  $bin -> PASS"
  else
    echo "  $bin -> FAIL (exit $?); last lines:"; tail -3 "/tmp/$bin.log" | sed 's/^/    /'
  fi
}
run "$NVML_BASE"  nvmlprovider.test
run "$DCGM_IMAGE" transformation.test
run "$DCGM_IMAGE" cmd.test
REMOTE_EOF
)"
echo "$out"
if [ "$(echo "$out" | grep -c '> PASS')" = 3 ]; then
  log "DCGM Tier-3 PASS (3/3 hardware test packages green on P100)"
else
  log "DCGM Tier-3 has failures"; exit 1
fi
