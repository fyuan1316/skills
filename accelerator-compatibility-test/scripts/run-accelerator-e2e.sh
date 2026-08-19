#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage: run-accelerator-e2e.sh --kube-conf PATH [options]

Options:
  --root PATH                    accelerator-test repo root
  --kube-conf PATH               target cluster kubeconfig
  --global-kube-conf PATH        global kubeconfig for deploy scripts
  --business-kube-conf PATH      business kubeconfig for deploy scripts
  --platform auto|hami|pgpu|pnpu platform under test (default: auto)
  --scope smoke|sanity|full|focus test scope (default: full)
  --focus-files LIST             comma-separated *_test.go files for focus scope
  --namespace NAME               e2e namespace (default: gpu-test)
  --image-registry REGISTRY      CUDA/probe image proxy registry
  --accel nvidia|ascend          accelerator family override
  --no-deploy                    skip product deployment/upgrade
  --artifact-dir PATH            output artifact directory
  --hami-version VERSION         HAMi version to deploy
  --hami-webui-version VERSION   HAMi WebUI version to deploy
  --hami-deploy-mode MODE        auto|vgpu|vnpu (default: auto)
  --pgpu-version VERSION         PGPU version to deploy
  --pnpu-operator-version VER    pNPU operator version to deploy
  --pnpu-driver-version VER      pNPU driver version to deploy
USAGE
}

ROOT="${ACCELERATOR_TEST_ROOT:-/Volumes/macOS-2/Users/yuan/Dev/alauda/ai-infra/accelerator-test}"
KUBE_CONF="${KUBE_CONF:-}"
GLOBAL_KUBE_CONF=""
BUSINESS_KUBE_CONF=""
PLATFORM="auto"
SCOPE="full"
FOCUS_FILES_VALUE=""
NAMESPACE="${E2E_NAMESPACE:-gpu-test}"
IMAGE_REGISTRY="${E2E_IMAGE_REGISTRY:-}"
ACCEL="${E2E_ACCEL:-}"
DEPLOY="true"
ARTIFACT_DIR=""
HAMI_VERSION_VALUE=""
HAMI_WEBUI_VERSION_VALUE=""
HAMI_DEPLOY_MODE_VALUE="auto"
PGPU_VERSION_VALUE=""
PNPU_OPERATOR_VERSION_VALUE=""
PNPU_DRIVER_VERSION_VALUE=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --kube-conf) KUBE_CONF="$2"; shift 2 ;;
    --global-kube-conf) GLOBAL_KUBE_CONF="$2"; shift 2 ;;
    --business-kube-conf) BUSINESS_KUBE_CONF="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --scope) SCOPE="$2"; shift 2 ;;
    --focus-files) FOCUS_FILES_VALUE="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --image-registry) IMAGE_REGISTRY="$2"; shift 2 ;;
    --accel) ACCEL="$2"; shift 2 ;;
    --no-deploy) DEPLOY="false"; shift ;;
    --artifact-dir) ARTIFACT_DIR="$2"; shift 2 ;;
    --hami-version) HAMI_VERSION_VALUE="$2"; shift 2 ;;
    --hami-webui-version) HAMI_WEBUI_VERSION_VALUE="$2"; shift 2 ;;
    --hami-deploy-mode) HAMI_DEPLOY_MODE_VALUE="$2"; shift 2 ;;
    --pgpu-version) PGPU_VERSION_VALUE="$2"; shift 2 ;;
    --pnpu-operator-version) PNPU_OPERATOR_VERSION_VALUE="$2"; shift 2 ;;
    --pnpu-driver-version) PNPU_DRIVER_VERSION_VALUE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$PLATFORM" in auto|hami|pgpu|pnpu) ;; *) echo "invalid --platform: $PLATFORM" >&2; exit 2 ;; esac
case "$SCOPE" in smoke|sanity|full|focus) ;; *) echo "invalid --scope: $SCOPE" >&2; exit 2 ;; esac
if [ "$SCOPE" = "focus" ] && [ -z "$FOCUS_FILES_VALUE" ]; then
  echo "--focus-files is required when --scope focus" >&2
  exit 2
fi
if [ -z "$KUBE_CONF" ]; then
  echo "--kube-conf is required" >&2
  exit 2
fi
if [ ! -f "$KUBE_CONF" ]; then
  echo "kubeconfig not found: $KUBE_CONF" >&2
  exit 2
fi
if [ ! -d "$ROOT" ] || [ ! -f "$ROOT/Makefile" ]; then
  echo "accelerator-test root not found or invalid: $ROOT" >&2
  exit 2
fi

if [ -z "$GLOBAL_KUBE_CONF" ]; then GLOBAL_KUBE_CONF="$KUBE_CONF"; fi
if [ -z "$BUSINESS_KUBE_CONF" ]; then BUSINESS_KUBE_CONF="$KUBE_CONF"; fi

RUN_ID="$(date +%Y%m%d-%H%M%S)-${PLATFORM}-${SCOPE}"
if [ -z "$ARTIFACT_DIR" ]; then
  ARTIFACT_DIR="$ROOT/test/e2e/.artifacts/skill-runs/$RUN_ID"
fi
mkdir -p "$ARTIFACT_DIR"

LOG_FILE="$ARTIFACT_DIR/run.log"
COMMAND_FILE="$ARTIFACT_DIR/command.env"
SUMMARY_FILE="$ARTIFACT_DIR/summary.env"
JUNIT_REPORT="$ARTIFACT_DIR/junit.xml"
PREFLIGHT_FILE="$ARTIFACT_DIR/preflight.log"

GINKGO_HELPER="$ROOT/hack/ensure-ginkgo.sh"
if [ ! -f "$GINKGO_HELPER" ]; then
  GINKGO_HELPER="$SCRIPT_DIR/ensure-ginkgo.sh"
fi
# shellcheck disable=SC1090
source "$GINKGO_HELPER"
export GOPROXY="${E2E_GOPROXY:-https://build-nexus.alauda.cn/repository/golang/,https://proxy.golang.org,direct}"
export GOSUMDB="${E2E_GOSUMDB:-off}"
preflight_failed() {
  cat "$PREFLIGHT_FILE" >&2
  {
    printf 'exit_code=2\n'
    printf 'artifact_dir=%q\n' "$ARTIFACT_DIR"
    printf 'tool_preflight=failed\n'
    printf 'preflight_log=%q\n' "$PREFLIGHT_FILE"
  } > "$SUMMARY_FILE"
  exit 2
}

: > "$PREFLIGHT_FILE"
if ! GO_BIN="$(ensure_go 2>>"$PREFLIGHT_FILE")"; then
  preflight_failed
fi
export GO_BIN
PATH="$(dirname "$GO_BIN"):$PATH"
export PATH
GO_VERSION="$(go_cli_version "$GO_BIN")"
if ! GINKGO_BIN="$(ensure_ginkgo "$ROOT" 2>>"$PREFLIGHT_FILE")"; then
  preflight_failed
fi
cat "$PREFLIGHT_FILE" >&2
GINKGO_VERSION="$(ginkgo_cli_version "$GINKGO_BIN")"
export GINKGO_BIN

HAMI_AUTO_DEPLOY_VALUE="$DEPLOY"
PGPU_AUTO_DEPLOY_VALUE="$DEPLOY"
PNPU_AUTO_DEPLOY_VALUE="$DEPLOY"

{
  printf 'ROOT=%q\n' "$ROOT"
  printf 'KUBE_CONF=%q\n' "$KUBE_CONF"
  printf 'PLATFORM=%q\n' "$PLATFORM"
  printf 'SCOPE=%q\n' "$SCOPE"
  printf 'NAMESPACE=%q\n' "$NAMESPACE"
  printf 'DEPLOY=%q\n' "$DEPLOY"
  printf 'ARTIFACT_DIR=%q\n' "$ARTIFACT_DIR"
  printf 'GO_BIN=%q\n' "$GO_BIN"
  printf 'GO_VERSION=%q\n' "$GO_VERSION"
  printf 'GINKGO_BIN=%q\n' "$GINKGO_BIN"
  printf 'GINKGO_VERSION=%q\n' "$GINKGO_VERSION"
} > "$COMMAND_FILE"

echo "artifact_dir=$ARTIFACT_DIR"
echo "platform=$PLATFORM scope=$SCOPE deploy=$DEPLOY"
echo "go_bin=$GO_BIN go_version=$GO_VERSION"
echo "ginkgo_bin=$GINKGO_BIN ginkgo_version=$GINKGO_VERSION"

set +e
(
  cd "$ROOT"
  export KUBE_CONF
  export JUNIT_REPORT
  export E2E_NAMESPACE="$NAMESPACE"
  export E2E_PLATFORM="$PLATFORM"
  export HAMI_AUTO_DEPLOY="$HAMI_AUTO_DEPLOY_VALUE"
  export PGPU_AUTO_DEPLOY="$PGPU_AUTO_DEPLOY_VALUE"
  export PNPU_AUTO_DEPLOY="$PNPU_AUTO_DEPLOY_VALUE"
  export HAMI_GLOBAL_KUBE_CONF="$GLOBAL_KUBE_CONF"
  export HAMI_BUSINESS_KUBE_CONF="$BUSINESS_KUBE_CONF"
  export PGPU_GLOBAL_KUBE_CONF="$GLOBAL_KUBE_CONF"
  export PGPU_BUSINESS_KUBE_CONF="$BUSINESS_KUBE_CONF"
  export PNPU_GLOBAL_KUBE_CONF="$GLOBAL_KUBE_CONF"
  export PNPU_BUSINESS_KUBE_CONF="$BUSINESS_KUBE_CONF"
  export HAMI_DEPLOY_MODE="$HAMI_DEPLOY_MODE_VALUE"
  [ -z "$IMAGE_REGISTRY" ] || export E2E_IMAGE_REGISTRY="$IMAGE_REGISTRY"
  [ -z "$ACCEL" ] || export E2E_ACCEL="$ACCEL"
  [ -z "$FOCUS_FILES_VALUE" ] || export FOCUS_FILES="$FOCUS_FILES_VALUE"
  [ -z "$HAMI_VERSION_VALUE" ] || export HAMI_VERSION="$HAMI_VERSION_VALUE"
  [ -z "$HAMI_WEBUI_VERSION_VALUE" ] || export HAMI_WEBUI_VERSION="$HAMI_WEBUI_VERSION_VALUE"
  [ -z "$PGPU_VERSION_VALUE" ] || export PGPU_VERSION="$PGPU_VERSION_VALUE"
  [ -z "$PNPU_OPERATOR_VERSION_VALUE" ] || export PNPU_NPU_OPERATOR_VERSION="$PNPU_OPERATOR_VERSION_VALUE"
  [ -z "$PNPU_DRIVER_VERSION_VALUE" ] || export PNPU_DRIVER_VERSION="$PNPU_DRIVER_VERSION_VALUE"
  make e2e-test E2E_TYPE="$SCOPE" E2E_PLATFORM="$PLATFORM" KUBE_CONF="$KUBE_CONF"
) 2>&1 | tee "$LOG_FILE"
STATUS=${PIPESTATUS[0]}
set -e

if [ -f "$JUNIT_REPORT" ]; then
  echo "junit_report=$JUNIT_REPORT"
fi
LATEST_JUNIT="$ROOT/test/e2e/.artifacts/latest/junit.xml"
if [ -f "$LATEST_JUNIT" ] && [ "$LATEST_JUNIT" != "$JUNIT_REPORT" ]; then
  cp "$LATEST_JUNIT" "$ARTIFACT_DIR/junit.latest.xml"
fi

{
  printf 'exit_code=%s\n' "$STATUS"
  printf 'artifact_dir=%q\n' "$ARTIFACT_DIR"
  printf 'log_file=%q\n' "$LOG_FILE"
  printf 'junit_report=%q\n' "$JUNIT_REPORT"
  printf 'tool_preflight=passed\n'
  printf 'go_bin=%q\n' "$GO_BIN"
  printf 'go_version=%q\n' "$GO_VERSION"
  printf 'ginkgo_bin=%q\n' "$GINKGO_BIN"
  printf 'ginkgo_version=%q\n' "$GINKGO_VERSION"
  printf 'preflight_log=%q\n' "$PREFLIGHT_FILE"
} > "$SUMMARY_FILE"

echo "exit_code=$STATUS"
exit "$STATUS"
