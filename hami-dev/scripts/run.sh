#!/usr/bin/env bash
# hami-dev iteration driver — one edit -> build -> unit-test pass over a HAMi
# tech-stack repo. Skill-triggered: the model edits source, then invokes this
# for a verdict, then loops.
#
# Tier 1 (this script, on devpod, NO hardware): build + `go test ./pkg/...`.
# Tier 2 (build/static): compile all binaries + lint.
# Tier 3 (e2e, on P100 / a real cluster): accelerator-test Ginkgo — see
#   scripts/p100.sh and the SKILL.md "GPU / e2e" section. Intentionally not
#   wired here so a green Tier-1 run never implies untested hardware paths.
#
# Usage:
#   run.sh <repo> [mode]
#     repo : hami | dcgm-exporter | hami-webui   (Go repos; Tier 1 verified for hami)
#     mode : test (default) | build | build-test | pkg:<import-path>
#
# Examples:
#   run.sh hami                       # go test ./pkg/... -short
#   run.sh hami build-test            # build all cmds, then unit test
#   run.sh hami pkg:./pkg/device/...  # scope to one package (fast inner loop)
set -euo pipefail

REPO="${1:?usage: run.sh <hami|dcgm-exporter|hami-webui> [mode]}"
MODE="${2:-test}"

AI_INFRA="${AI_INFRA:-/workspaces/yuanfang-base-ubuntu/projects/ai-infra}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLROOT="${TOOLROOT:-/tmp/hami-toolchain}"

# --- L0: ensure toolchain (idempotent; re-bootstraps after a pod restart) ---
if [ ! -x "$TOOLROOT/go/bin/go" ]; then
  echo "hami-dev: toolchain absent, bootstrapping ..." >&2
  TOOLROOT="$TOOLROOT" bash "$SKILL_DIR/bootstrap.sh" >&2
fi
# shellcheck disable=SC1091
. "$TOOLROOT/env.sh"

# Resolve repo alias -> actual dir name (dirs are mixed-case: HAMi, HAMi-core ...)
case "$(echo "$REPO" | tr '[:upper:]' '[:lower:]')" in
  hami)            REPO=HAMi ;;
  hami-core|core)  REPO=HAMi-core ;;
  hami-webui|webui) REPO=HAMi-WebUI ;;
  dcgm|dcgm-exporter) REPO=dcgm-exporter ;;
  accelerator-test|e2e) REPO=accelerator-test ;;
esac
# fix-label: correct the OCI image.source label in a repo's .build/build.yaml
# via the GitLab API (creates a feat branch + MR, no merge). Repo-specific.
if [ "$MODE" = "fix-label" ]; then
  exec bash "$SKILL_DIR/label.sh" "$REPO"
fi

# HAMi-core (C/CUDA) is Tier 3: build/test happen in a container on the P100
# (host stays clean), distributed via crane tar. Delegate to core.sh.
if [ "$REPO" = "HAMi-core" ]; then
  case "$MODE" in test|"") MODE=all ;; esac   # default to the full pipeline
  exec bash "$SKILL_DIR/core.sh" "$MODE"
fi

# accelerator-test (Ginkgo k8s e2e) is Tier 3: runs FROM devpod against the
# cluster (devpod reaches the API + has Go). Cluster already has HAMi deployed,
# so no deploy step. MODE = e2e type: smoke (default) | sanity | full.
if [ "$REPO" = "accelerator-test" ]; then
  etype="$MODE"; case "$etype" in test|"") etype=smoke ;; esac
  if [ ! -x "$TOOLROOT/gopath/bin/ginkgo" ]; then
    gv=$(grep -E 'onsi/ginkgo' "$AI_INFRA/accelerator-test/go.mod" | grep -oE 'v2\.[0-9.]+' | head -1)
    echo "hami-dev: installing ginkgo @$gv ..." >&2
    GOBIN="$TOOLROOT/gopath/bin" GOPROXY="${GOPROXY:-https://goproxy.cn,direct}" \
      go install "github.com/onsi/ginkgo/v2/ginkgo@$gv" >&2
  fi
  cd "$AI_INFRA/accelerator-test"
  exec make "e2e-test-$etype" \
    E2E_PLATFORM="${E2E_PLATFORM:-hami}" \
    KUBE_CONF="${KUBE_CONF:-${WORKSPACE:-/workspaces/yuanfang-base-ubuntu}/envs/kubeconfig/g1-c1-x86.yaml}" \
    E2E_IMAGE_REGISTRY="${E2E_IMAGE_REGISTRY:-docker-mirrors.alauda.cn}" \
    E2E_GOPROXY="${E2E_GOPROXY:-https://goproxy.cn,direct}" \
    GINKGO_BIN="$TOOLROOT/gopath/bin/ginkgo"
fi

# dcgm-exporter Tier-3: the 3 unit-test pkgs needing real DCGM/NVML run on the
# P100 (compile@devpod -> run in GPU container). Devpod handles build/test/lint.
if [ "$REPO" = "dcgm-exporter" ] && [ "$MODE" = "gputest" ]; then
  exec bash "$SKILL_DIR/dcgm.sh"
fi

repo_dir="$AI_INFRA/$REPO"
[ -d "$repo_dir" ] || { echo "hami-dev: no such repo dir: $repo_dir" >&2; exit 2; }
cd "$repo_dir"
echo "hami-dev: repo=$REPO mode=$MODE dir=$repo_dir go=$(go version | awk '{print $3}')" >&2

do_build() {
  if [ -d cmd ]; then
    echo "hami-dev: building ./cmd/... -> $TOOLROOT/out/$REPO" >&2
    go build -o "$TOOLROOT/out/$REPO/" ./cmd/... 2>&1
  else
    go build ./... 2>&1
  fi
}

do_test() {
  # Prefer the repo's own unit-test entry (sets up fake kubeconfig etc.),
  # fall back to a direct `go test ./pkg/...`.
  if [ -f hack/unit-test.sh ] && [ "${MODE}" = "test" ]; then
    echo "hami-dev: running hack/unit-test.sh" >&2
    bash hack/unit-test.sh 2>&1
  else
    go test ./pkg/... -short -count=1 2>&1
  fi
}

# Tier 2 pre-commit gate: `go vet` (cheap, built-in) + golangci-lint (the repo's
# own `make lint`). Scope to a path with `lint:<import-path>` for a fast inner
# loop. Non-zero exit on any finding so the skill loop / CI can gate on it.
do_lint() {
  local scope="${1:-./...}" rc=0
  echo "hami-dev: go vet $scope" >&2
  go vet "$scope" 2>&1 || rc=1
  if [ ! -x "$TOOLROOT/gopath/bin/golangci-lint" ]; then
    echo "hami-dev: installing golangci-lint v2.8.0 ..." >&2
    GOBIN="$TOOLROOT/gopath/bin" GOPROXY="${GOPROXY:-https://goproxy.cn,direct}" \
      go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.8.0 >&2
  fi
  echo "hami-dev: golangci-lint run $scope" >&2
  golangci-lint run "$scope" 2>&1 || rc=1
  return $rc   # gate fails if EITHER go vet or golangci-lint flags anything
}

case "$MODE" in
  build)       do_build ;;
  test)        do_test ;;
  build-test)  do_build && do_test ;;
  lint)        do_lint ;;
  lint:*)      do_lint "${MODE#lint:}" ;;
  pkg:*)       go test "${MODE#pkg:}" -short -count=1 2>&1 ;;
  *)           echo "hami-dev: unknown mode: $MODE" >&2; exit 2 ;;
esac

echo "hami-dev: PASS ($REPO / $MODE)" >&2
